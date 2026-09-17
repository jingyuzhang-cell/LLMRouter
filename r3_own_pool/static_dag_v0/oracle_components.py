"""Error Bottleneck Analysis under Oracle Components (5.5.3).

Policy replay over the 50 live tasks: the Full-Adaptive control flow is kept
(exact model sequences reconstructed via deterministic memory replay), and one
component is replaced by an oracle at a time.

- Oracle Verification: the LLM verdict is replaced by ground truth. Tasks the
  live verifier wrongly accepted (first answer wrong, no fallback executed)
  get their memory-fallback reasoning executed FOR REAL on the same extracted
  facts (new calls, billed); the live decompose rescue result is kept if the
  fallback also fails.
- Oracle Extraction: reasoning inputs become gold facts; outcome = the frozen
  node table's Q for the same final model (zero calls). Decompose rescues are
  kept where they fired live.
- Oracle Both: gold facts + truth-triggered recovery over the table (zero calls).

Disclosed approximation: under policy replay the trigger events remain those
of the live run; replacing a component changes outcomes, not the control flow
that produced them.
"""
import argparse
import json

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

LIVE = core.ROOT / 'static_dag_v0/live_e2e'
SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
OUT = LIVE / 'oracle_components'
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
LAMBDA, LAMBDA_FAIL = 0.3, 0.5
LEN_SPLIT = 150
POOL = ['medium', 'large', 'coder']


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def run():
    import os
    if os.environ.get('RERUN'):
        (OUT / 'RESULTS.json').unlink(missing_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    traces = [json.loads(l) for l in (LIVE / 'TRACES.jsonl').open()]
    tasks = json.loads((SRC / 'TASKS.json').read_text())[:50]
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    table = dict(np.load(SRC / 'SCORED_MATRIX_EXEC.npz', allow_pickle=False))
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    by_task = {}
    for n in nodes_all:
        by_task.setdefault(n['task_uid'], []).append(n)
    node_idx = {n['node_id']: i for i, n in enumerate(nodes_all)}
    cache = {}
    for f in (LIVE / 'CALL_CACHE.jsonl',):
        for line in f.open():
            row = json.loads(line)
            k = tuple(row['key'].split('/')) if '/' in row['key'] else row['key']
            cache[k] = row['response']

    def qhat(n):
        types = [1.0 if n['node_type'] == t else 0.0
                 for t in ['extraction', 'transformation', 'reasoning', 'verification']]
        x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
        return (x @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'])[0]

    # ---- deterministic memory replay to recover the Full arm's model sequence
    mem, mem_fail = {}, {}

    def pick_model(n, t, b):
        key = (t, b)
        mem.setdefault(key, {m: [0, 0] for m in POOL})
        qs = np.array([(1 - LAMBDA) * qhat(n)[k] + LAMBDA * ((mem[key][m][0] + 1) / (mem[key][m][1] + 2))
                       for k, m in enumerate(POOL)])
        return POOL[int(np.argmax(qs - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']))]

    seq = {}
    for tr in traces:
        t = next(x for x in tasks if x['uid'] == tr['task_uid'])
        ns = by_task[t['uid']]
        ext = next((n for n in ns if n['node_type'] == 'extraction'), None)
        r_node = next(n for n in ns if n['node_type'] == 'reasoning')
        b = 'short' if len(t['question']) < LEN_SPLIT else 'long'
        m_ext = pick_model(ext, 'extraction', b) if ext else None
        m_r = pick_model(r_node, 'reasoning', b)
        state = tr['arms']['Full']
        m_final = state.get('model', m_r)
        fallback_model = m_final if m_final != m_r else None
        # facts consumed by the routed arms
        facts = None
        if ext:
            r_ext = cache.get((ext['node_id'], m_ext))
            if r_ext is None:
                for k, resp in cache.items():
                    if k[0] == ext['node_id']:
                        r_ext = resp
                        break
            if r_ext is not None:
                try:
                    facts = v.parse_facts(r_ext['answer'])
                except Exception:
                    facts = None
        facts = facts if facts else r_node['gold_facts']
        seq[t['uid']] = dict(m_ext=m_ext, m_r=m_r, m_fb=fallback_model, facts=facts,
                             gold=t['answer'], r_node=r_node, ext=ext,
                             decompose_rescued=bool(state.get('decompose')) and state['task_success'],
                             live_success=state['task_success'])
        # memory update exactly as executed (verdict signal)
        vd = state.get('verdict')
        rk = ('reasoning', b)
        mem.setdefault(rk, {m: [0, 0] for m in POOL})
        if vd is not None:
            mem[rk][m_final][0] += int(vd is True)
            mem[rk][m_final][1] += 1
        elif fallback_model is not None:
            mem_fail.setdefault('reasoning', {m: [0, 0] for m in POOL})
            mem_fail['reasoning'][m_final][0] += int(state['task_success'])
            mem_fail['reasoning'][m_final][1] += 1

    def first_outcome(uid):
        """Correctness of the FIRST reasoning pick on the live facts (cache)."""
        s = seq[uid]
        r = cache.get((s['r_node']['node_id'], s['m_r'], 'live'))
        if r is None:
            return None
        try:
            val = exec_calc(v.decode(r['answer'])['expression'], s['facts'])
        except Exception:
            return False
        return close(val, s['gold'])

    def fallback_outcome(uid, allow_real):
        s = seq[uid]
        if s['m_fb'] is None:
            return None
        key = (s['r_node']['node_id'], s['m_fb'], 'live')
        r = cache.get(key)
        if r is None:
            if not allow_real:
                return 'MISSING'
            import fcntl
            with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                proc = log = None
                try:
                    proc, log, _ = engine.start_model(s['m_fb'])
                    rr = engine.call_model(s['m_fb'], v.sprompt(dict(question=next(
                        x['question'] for x in tasks if x['uid'] == uid)), s['facts']))
                finally:
                    if proc is not None:
                        engine.stop_model(proc, log)
            cache[key] = rr
            with (LIVE / 'CALL_CACHE.jsonl').open('a') as cf:
                cf.write(json.dumps(dict(key='/'.join(key), model=s['m_fb'], response=rr),
                                    ensure_ascii=False) + '\n')
            r = rr
        try:
            val = exec_calc(v.decode(r['answer'])['expression'], s['facts'])
        except Exception:
            return False
        return close(val, s['gold'])

    def table_q(uid, model):
        s = seq[uid]
        return float(table['Q'][node_idx[s['r_node']['node_id']], POOL.index(model)])

    # ---------- arm computations ----------
    uids = [t['uid'] for t in tasks]
    full_live = float(np.mean([seq[u]['live_success'] for u in uids]))

    # Oracle Verification (truth verdicts; real fallback calls where missing)
    ov = []
    for u in uids:
        s = seq[u]
        first = first_outcome(u)
        if first is None:
            first = s['live_success']  # first pick never isolated in cache; final == first here
        if first:
            ov.append(True)
            continue
        fb = fallback_outcome(u, allow_real=True)
        if fb is True:
            ov.append(True)
            print('fb rescued', u[:8])
        elif fb is False or fb is None:
            ov.append(bool(s['decompose_rescued']))
        else:
            raise RuntimeError('missing fallback cell despite real calls')
    oracle_ver = float(np.mean(ov))

    # Oracle Extraction (gold facts; outcome from frozen table at the same final model)
    oe = []
    for u in uids:
        s = seq[u]
        m_final = s['m_fb'] or s['m_r']
        ok = table_q(u, m_final) > 0
        if not ok and s['decompose_rescued']:
            ok = True
        oe.append(ok)
    oracle_ext = float(np.mean(oe))

    # Oracle Both (gold facts + truth triggers over the table)
    ob = []
    for u in uids:
        s = seq[u]
        if table_q(u, s['m_r']) > 0:
            ob.append(True)
            continue
        fb = s['m_fb']
        ok = fb is not None and table_q(u, fb) > 0
        if not ok and s['decompose_rescued']:
            ok = True
        ob.append(ok)
    oracle_both = float(np.mean(ob))

    result = dict(
        table=dict(FullAdaptive_live=full_live, OracleVerification=oracle_ver,
                   OracleExtraction=oracle_ext, OracleBoth=oracle_both),
        semantics='policy replay: live control flow kept; one component substituted per arm',
        oracle_verification_note='fallback executed for real on tasks the live verifier wrongly accepted; '
                                 'decompose rescue kept where it fired',
        oracle_extraction_note='outcome read from the frozen conditional table (gold facts) at the same final '
                               'model; decompose rescues kept',
        positioning='diagnosis only - explains why live success is 34%; not a headline result')
    core.write(OUT / 'RESULTS.json', result)
    print(json.dumps(result['table'], indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
