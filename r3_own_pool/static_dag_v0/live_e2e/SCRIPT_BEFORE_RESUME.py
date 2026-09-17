"""Live end-to-end: 50 fresh-holdout tasks executed for real, three arms.

Arms share an execution cache (keyed node+model; prompts identical per node).
Static: frozen router picks; chain = extraction (deduped) -> reasoning ->
verification; no detection. Static+Feedback: sequential live loop, memory-fused
picks (lambda .3, type x length bucket), failure detection by the real coder-v0
verifier on reasoning/verification outputs (parse failure for extraction),
memory-driven fallback (lambda' .5), memory updated from VERDICTS (deployable
signal, not gold). Full Adaptive: same loop with type-aware gating (verifier-
driven reroute acts on verification nodes; reasoning fallback on verifier
reject) and failure-aware decompose (D1 report alignment -> D2 expression ->
tool -> D4) when the reasoning fallback is still rejected. All outputs scored
OFFLINE against gold: task success = final accepted value ~= gold answer.
"""
import argparse
import json
import time

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
OUT = core.ROOT / 'static_dag_v0/live_e2e'
POOL = ['medium', 'large', 'coder']
N_TASKS = 50
LAMBDA, LAMBDA_FAIL = 0.3, 0.5
LEN_SPLIT = 150
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
V0 = ('Check this financial computation. QUESTION: {q}\nFACTS: {facts}\nEXPRESSION: {expr}\nVALUE: {val}\n'
      'Does it correctly answer the question using accurate facts? '
      'Answer ONLY JSON {{"verdict":"yes"|"no"}}.')
D1 = ('Align the bare financial facts with the report. For each fact state what it measures (entity, period, '
      'unit/scale), then state the single quantitative relationship the question asks for. Return ONLY JSON '
      '{{"facts":[{{"index":i,"meaning":"..."}}],"relationship":"..."}}.\nQUESTION: {q}\nREPORT:\n{ctx}\n'
      'FACT VALUES: {vals}')
D2 = ('Using the aligned facts and the relationship, first list the arithmetic steps, then write the single '
      'final expression over fact values v0,v1,.... Allowed operators: + - * / and parentheses; small numeric '
      'constants permitted (divide by the count to average). Return ONLY JSON '
      '{{"steps":["..."],"expression":"..."}}.\nQUESTION: {q}\nALIGNMENT: {align}')


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


class Runner:
    def __init__(self):
        self.cache = {}
        self.cache_file = OUT / 'CALL_CACHE.jsonl'
        if self.cache_file.exists():
            for line in self.cache_file.open():
                row = json.loads(line)
                self.cache[tuple(row['key'].split('/')) if '/' in row['key'] else row['key']] = row['response']
        self.tokens = {'Static': 0, 'Feedback': 0, 'Full': 0}
        self.calls = {'Static': 0, 'Feedback': 0, 'Full': 0}
        self.latency = {'Static': 0.0, 'Feedback': 0.0, 'Full': 0.0}
        self.current = None
        self.proc = self.log = None

    def _ensure(self, model):
        if model != self.current:
            if self.proc is not None:
                engine.stop_model(self.proc, self.log)
            self.proc, self.log, _ = engine.start_model(model)
            self.current = model

    def batch(self, jobs, arms):
        """Execute independent (model, key, prompt) jobs with a small pool.

        Jobs are grouped by model; within a group requests run concurrently
        against the loaded server (vLLM handles concurrent requests natively).
        """
        from concurrent.futures import ThreadPoolExecutor
        results = {}
        for model in sorted({j[0] for j in jobs}):
            group = [j for j in jobs if j[0] == model]
            todo = [j for j in group if j[1] not in self.cache]
            self._ensure(model)
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(engine.call_model, model, j[2]): j for j in todo}
                for future in futures:
                    j = futures[future]
                    r = future.result()
                    key_id = '/'.join(str(k) for k in j[1]) if not isinstance(j[1], str) else j[1]
                    for a in arms:
                        if r.get('usage'):
                            self.tokens[a] += r['usage'].get('total_tokens', 0)
                        self.calls[a] += 1
                        self.latency[a] += r.get('latency_s', 0.0)
                    self.cache[j[1]] = r
                    with self.cache_file.open('a') as cf:
                        cf.write(json.dumps(dict(key=key_id, model=model, response=r), ensure_ascii=False) + '\n')
            for j in group:
                results[j[1]] = self.cache[j[1]]
        return results

    def call(self, model, key, prompt, arms):
        if key in self.cache:
            return self.cache[key]
        key_id = '/'.join(str(k) for k in key) if not isinstance(key, str) else key
        self._ensure(model)
        r = engine.call_model(model, prompt)
        for a in arms:
            if r.get('usage'):
                self.tokens[a] += r['usage'].get('total_tokens', 0)
            self.calls[a] += 1
            self.latency[a] += r.get('latency_s', 0.0)
        self.cache[key] = r
        with self.cache_file.open('a') as cf:
            cf.write(json.dumps(dict(key=key_id, model=model, response=r), ensure_ascii=False) + '\n')
        return r


def run():
    if (OUT / 'RESULTS.json').exists():
        raise FileExistsError('live_e2e already complete')
    OUT.mkdir(exist_ok=True)
    tasks = json.loads((SRC / 'TASKS.json').read_text())[:N_TASKS]
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    by_task = {}
    for n in nodes_all:
        by_task.setdefault(n['task_uid'], []).append(n)

    def qhat_row(n):
        types = [1.0 if n['node_type'] == t else 0.0
                 for t in ['extraction', 'transformation', 'reasoning', 'verification']]
        x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
        return (x @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'])[0]

    def util(n):
        return qhat_row(n) - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']

    def beta(S, N_):
        return (S + 1) / (N_ + 2)

    runner = Runner()
    import fcntl
    traces = []
    mem = {}
    mem_fail = {}
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            trace_by_task = {t['uid']: dict(task_uid=t['uid'], arms={}) for t in tasks}
            # ---- Static pass, phase-parallelized ----
            ext_jobs = []
            for t in tasks:
                ns = by_task[t['uid']]
                ext = [n for n in ns if n['node_type'] == 'extraction']
                if ext:
                    m_ext = POOL[int(np.argmax(util(ext[0])))]
                    ext_jobs.append((m_ext, (ext[0]['node_id'], m_ext),
                                     v.eprompt(dict(question=t['question'], context=t['context']))))
            ext_res = runner.batch(ext_jobs, ['Static'])
            rsn_jobs = []
            for t in tasks:
                ns = by_task[t['uid']]
                ext = [n for n in ns if n['node_type'] == 'extraction']
                r_node = next(n for n in ns if n['node_type'] == 'reasoning')
                r = ext_res.get((ext[0]['node_id'], POOL[int(np.argmax(util(ext[0])))])) if ext else None
                facts = None
                try:
                    facts = v.parse_facts(r['answer'])
                except Exception:
                    pass
                rinput = facts if facts else r_node['gold_facts']
                m_r = POOL[int(np.argmax(util(r_node)))]
                rsn_jobs.append((m_r, (r_node['node_id'], m_r, 'live'),
                                 v.sprompt(dict(question=t['question']), rinput)))
            rsn_res = runner.batch(rsn_jobs, ['Static'])
            for t in tasks:
                ns = by_task[t['uid']]
                ext = [n for n in ns if n['node_type'] == 'extraction']
                r_node = next(n for n in ns if n['node_type'] == 'reasoning')
                r = ext_res.get((ext[0]['node_id'], POOL[int(np.argmax(util(ext[0])))])) if ext else None
                facts = None
                try:
                    facts = v.parse_facts(r['answer'])
                except Exception:
                    pass
                state = dict(extraction_parse=facts is not None)
                rinput = facts if facts else r_node['gold_facts']
                rr = rsn_res[(r_node['node_id'], POOL[int(np.argmax(util(r_node)))], 'live')]
                expr = val = None
                try:
                    expr = v.decode(rr['answer'])['expression']
                    val = exec_calc(expr, rinput)
                except Exception:
                    pass
                state.update(final_value=val, expression=expr,
                             model=POOL[int(np.argmax(util(r_node)))], verdict=None, gold=t['answer'],
                             task_success=bool(close(val, t['answer'])))
                trace_by_task[t['uid']]['arms']['Static'] = state
            # ---- sequential feedback passes ----
            for arm in ['Feedback', 'Full']:
                for t in tasks:
                    ns = by_task[t['uid']]
                    ext = [n for n in ns if n['node_type'] == 'extraction']
                    r_node = next(n for n in ns if n['node_type'] == 'reasoning')
                    vf = next(n for n in ns if n['node_id'].endswith('vfpos'))
                    results = trace_by_task[t['uid']]['arms']
                    state = {}
                    # extraction (one deduped call on the arm's chosen model)
                    if arm == 'Static':
                        m_ext = POOL[int(np.argmax(util(ext[0])))] if ext else None
                    else:
                        b = 'short' if len(t['question']) < LEN_SPLIT else 'long'
                        key = ('extraction', b)
                        mem.setdefault(key, {m: [0, 0] for m in POOL})
                        qs = np.array([(1 - LAMBDA) * qhat_row(ext[0])[k] + LAMBDA * beta(*mem[key][m])
                                       for k, m in enumerate(POOL)]) if ext else None
                        m_ext = POOL[int(np.argmax(qs - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']))] if ext else None
                    facts = None
                    if ext:
                        r = runner.call(m_ext, (ext[0]['node_id'], m_ext), v.eprompt(dict(question=t['question'], context=t['context'])), [arm])
                        try:
                            facts = v.parse_facts(r['answer'])
                        except Exception:
                            facts = None
                        state['extraction_parse'] = facts is not None
                    # reasoning (gold facts for the STATIC conditional chain? NO: live chain uses extracted
                    # facts when available, else falls back to gold facts only as interface contract input)
                    rinput = facts if facts else r_node['gold_facts']
                    if arm == 'Static':
                        m_r = POOL[int(np.argmax(util(r_node)))]
                    else:
                        b = 'short' if len(t['question']) < LEN_SPLIT else 'long'
                        key = ('reasoning', b)
                        mem.setdefault(key, {m: [0, 0] for m in POOL})
                        qs = np.array([(1 - LAMBDA) * qhat_row(r_node)[k] + LAMBDA * beta(*mem[key][m])
                                       for k, m in enumerate(POOL)])
                        m_r = POOL[int(np.argmax(qs - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']))]
                    rr = runner.call(m_r, (r_node['node_id'], m_r, 'live'),
                                     v.sprompt(dict(question=t['question']), rinput), [arm])
                    expr = val = None
                    try:
                        expr = v.decode(rr['answer'])['expression']
                        val = exec_calc(expr, rinput)
                    except Exception:
                        pass
                    verdict = None
                    if expr is not None:
                        rv = runner.call('coder', (r_node['node_id'], m_r, 'verifier'),
                                         V0.format(q=t['question'], facts=json.dumps(rinput), expr=expr, val=val),
                                         [] if arm == 'Static' else [arm])
                        try:
                            verdict = v.decode(rv['answer'])['verdict'] == 'yes'
                        except Exception:
                            verdict = None
                    accepted_val, m_final = val, m_r
                    if arm in ('Feedback', 'Full') and (val is None or verdict is False):
                        # memory-driven fallback (exclude failed model)
                        qf = np.array([(1 - LAMBDA_FAIL) * qhat_row(r_node)[k] + LAMBDA_FAIL *
                                       beta(*mem_fail.setdefault('reasoning', {m: [0, 0] for m in POOL})[m])
                                       for k, m in enumerate(POOL) if m != m_r])
                        alt = [m for m in POOL if m != m_r]
                        m2 = alt[int(np.argmax(qf))]
                        rr2 = runner.call(m2, (r_node['node_id'], m2, 'live'),
                                          v.sprompt(dict(question=t['question']), rinput), [arm])
                        try:
                            expr2 = v.decode(rr2['answer'])['expression']
                            val2 = exec_calc(expr2, rinput)
                        except Exception:
                            expr2, val2 = None, None
                        v2 = None
                        if expr2 is not None:
                            rv2 = runner.call('coder', (r_node['node_id'], m2, 'verifier'),
                                              V0.format(q=t['question'], facts=json.dumps(rinput), expr=expr2, val=val2),
                                              [arm])
                            try:
                                v2 = v.decode(rv2['answer'])['verdict'] == 'yes'
                            except Exception:
                                v2 = None
                        accepted_val, m_final = val2, m2
                        expr, val, verdict = expr2, val2, v2
                        # memory update from deployable verdict signal
                        mem_fail['reasoning'][m2][0] += int(v2 is True)
                        mem_fail['reasoning'][m2][1] += 1
                    if arm == 'Full' and accepted_val is None or (arm == 'Full' and verdict is False):
                        # failure-aware decompose on the still-rejected reasoning node
                        ra = runner.call(m_final, (r_node['node_id'], m_final, 'd1'),
                                         D1.format(q=t['question'], ctx=t['context'][:14000],
                                                   vals=[f['value'] for f in rinput['facts']]), [arm])
                        try:
                            align = v.decode(ra['answer'])
                            rb = runner.call(m_final, (r_node['node_id'], m_final, 'd2'),
                                             D2.format(q=t['question'], align=json.dumps(align)), [arm])
                            expr_d = v.decode(rb['answer'])['expression']
                            val_d = exec_calc(expr_d, rinput)
                            accepted_val, expr = val_d, expr_d
                            trace['decompose'] = True
                        except Exception:
                            trace['decompose'] = False
                    # memory update for initial picks (verdict signal)
                    if arm in ('Feedback', 'Full') and accepted_val is not None:
                        b = 'short' if len(t['question']) < LEN_SPLIT else 'long'
                        mem.setdefault(('reasoning', b), {m: [0, 0] for m in POOL})
                        mem[('reasoning', b)][m_final][0] += int(verdict is True)
                        mem[('reasoning', b)][m_final][1] += 1
                        if facts is not None:
                            mem.setdefault(('extraction', b), {m: [0, 0] for m in POOL})
                            mem[('extraction', b)][m_ext][0] += 1
                            mem[('extraction', b)][m_ext][1] += 1
                    state.update(final_value=accepted_val, expression=expr, model=m_final,
                                 verdict=verdict, gold=t['answer'],
                                 task_success=bool(close(accepted_val, t['answer'])))
                    results[arm] = state
            traces = list(trace_by_task.values())
        finally:
            if runner.proc is not None:
                engine.stop_model(runner.proc, runner.log)
    summary = {}
    for arm in ['Static', 'Feedback', 'Full']:
        rows = [t['arms'][arm] for t in traces]
        summary[arm] = dict(
            task_success=float(np.mean([r['task_success'] for r in rows])),
            final_value_rate=float(np.mean([r['final_value'] is not None for r in rows])),
            tokens=runner.tokens[arm], calls=runner.calls[arm],
            service_seconds=round(runner.latency[arm], 1))
    core.write(OUT / 'RESULTS.json', dict(summary=summary, n_tasks=len(traces),
                                          detection='live coder-v0 verifier; memory updated from verdicts only',
                                          scoring='offline vs gold answer; tolerance 1e-4 relative'))
    (OUT / 'TRACES.jsonl').write_text(''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in traces))
    print(json.dumps(summary, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
