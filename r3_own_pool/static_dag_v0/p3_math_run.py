"""P3 Math500 six-arm runner: one frozen stratified panel, deployable-only detection.

Nodes: analyze -> solve -> verify. No gold at runtime. Correctness is decided
offline by the frozen sympy scorer (p3_xdomain/math_scorer.py). Runtime
failure signals are validity/format/consistency only (documented weaker than
code's unit tests). Execution staged by model; resumable keyed ledger; refuses
to start while the GPU is busy.

Per-arm cell bookkeeping: each arm consumes only its own protocol cells
(no cross-arm reuse of fallback outputs). Identical prompts still dedupe
through the keyed cache.

Arms: always_medium / always_large / query_router / node_type_router /
static_dag / dynamic_real.
"""
import argparse
import fcntl
import hashlib
import json
import re
import sys
import time

from . import core
from . import run as engine

sys.path.insert(0, str(core.ROOT / 'static_dag_v0' / 'p3_xdomain'))
from math_scorer import equivalent, parseable, _unwrap_boxed  # noqa: E402

P3 = core.ROOT / 'static_dag_v0' / 'p3_xdomain'
OUT = P3 / 'math_run'
QUERY_GUARD = 154.0  # frozen median char length of the 100-task panel questions
BUDGET_MULT = 1.2
BUDGET_FLOOR = 200

MONO_P = ('Solve the math problem step by step. Put ONLY the final answer on the '
          'last line inside \\boxed{{...}}.\nPROBLEM:\n{q}')
ANALYZE_P = ('Analyze the math problem. Return ONLY JSON '
             '{{"unknowns":["..."],"conditions":["..."],"plan":["step 1",...]}}.\n'
             'PROBLEM:\n{q}')
SOLVE_P = ('Solve the math problem using the analysis. Put ONLY the final answer on '
           'the last line inside \\boxed{{...}}.\nPROBLEM:\n{q}\nANALYSIS:\n{analysis}')
VERIFY_P = ('Check this solution to the math problem. Return ONLY JSON '
            '{{"verdict":"yes"}} if it is correct, otherwise '
            '{{"verdict":"no","value":"<corrected final answer in plain LaTeX>"}}.\n'
            'PROBLEM:\n{q}\nSOLUTION:\n{solution}')


def load_tasks():
    detail = json.loads((P3 / 'P3_MATH_TASKS_100_DETAIL.json').read_text())
    tasks = [dict(task_id=t['task_id'], question=t['question'], gold=t['gold']) for t in detail]
    assert len(tasks) == 100
    return tasks


def extract_answer(text):
    a = _unwrap_boxed(text or '')
    if a.strip():
        return a.strip()
    lines = [l.strip() for l in (text or '').splitlines() if l.strip()]
    return lines[-1] if lines else ''


def parse_jsonish(text):
    t = (text or '').strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t)
    try:
        return json.loads(t)
    except Exception:
        return None


def tok(r):
    return (r.get('usage') or {}).get('total_tokens', 0)


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    engine.OUT = OUT
    tasks = load_tasks()
    if (OUT / 'ALL_DONE').exists():
        raise FileExistsError('math run complete')
    resp = OUT / 'RESPONSES.jsonl'
    cache = {}
    if resp.exists():
        for line in resp.open():
            r = json.loads(line)
            cache[r['key']] = r

    def key_of(model, node, task, prompt):
        return f'{task["task_id"]}:{node}:{model}:{hashlib.sha256(prompt.encode()).hexdigest()[:12]}'

    state = {t['task_id']: dict(task_id=t['task_id'], question=t['question'], gold=t['gold'],
                                cells={}, arms={}, tokens={}, budget=None,
                                budget_violation=False) for t in tasks}
    by_id = {t['task_id']: t for t in tasks}

    def collect(model, jobs):
        """jobs: list of (node, task_id, prompt) -> {index: response}."""
        have = {}
        for i, (node, tid, prompt) in enumerate(jobs):
            t = by_id[tid]
            key = key_of(model, node, t, prompt)
            if key in cache:
                have[i] = cache[key]
                continue
            r = engine.call_model(model, prompt)
            row = dict(key=key, model=model, prompt=prompt, task_id=tid, node=node, **r)
            with resp.open('a') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
                f.flush()
            cache[key] = row
            have[i] = row
        return have

    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        try:
            def ensure(model):
                nonlocal proc, log
                if proc is not None:
                    engine.stop_model(proc, log)
                    proc = log = None
                proc, log, _ = engine.start_model(model)

            # ---- Phase 1 (large): mono_large + analyze (main) ----
            ensure('large')
            jobs = [(node, t['task_id'], prompt) for node, t, prompt in
                    ([( 'mono', t, MONO_P.format(q=t['question'])) for t in tasks] +
                     [('analyze', t, ANALYZE_P.format(q=t['question'])) for t in tasks])]
            res = collect('large', jobs)
            for i, (node, tid, prompt) in enumerate(jobs):
                state[tid]['cells'][f'{node}_large' if node == 'mono' else 'analyze_main'] = res[i]
            print(json.dumps(dict(phase='large_done')))

            # ---- Phase 2 (medium): mono_medium + analyze fallback + solves ----
            ensure('medium')
            jobs = [('mono', t['task_id'], MONO_P.format(q=t['question'])) for t in tasks]
            for st in state.values():
                if parse_jsonish(st['cells']['analyze_main'].get('answer')) is None:
                    jobs.append(('analyze', st['task_id'], ANALYZE_P.format(q=st['question'])))
            res = collect('medium', jobs)
            for i, (node, tid, prompt) in enumerate(jobs):
                if node == 'mono':
                    state[tid]['cells']['mono_medium'] = res[i]
                else:
                    state[tid]['cells']['analyze_fb'] = res[i]
            # per-arm analysis text
            for st in state.values():
                main = parse_jsonish(st['cells']['analyze_main'].get('answer'))
                if main is not None:
                    st['ana_main_text'] = st['cells']['analyze_main'].get('answer') or ''
                    st['ana_main_ok'] = True
                else:
                    st['ana_main_text'] = st['cells']['analyze_main'].get('answer') or ''
                    st['ana_main_ok'] = False
                fb = parse_jsonish((st['cells'].get('analyze_fb') or {}).get('answer'))
                if main is None and fb is not None:
                    st['ana_fb_text'] = st['cells']['analyze_fb'].get('answer') or ''
                    st['ana_fb_ok'] = True
                else:
                    st['ana_fb_text'] = st['ana_main_text']
                    st['ana_fb_ok'] = st['ana_main_ok']
            # solve cells: ntr uses main analysis; static/dynamic use fb-updated analysis
            jobs = []
            jobmap = []
            for st in state.values():
                jobs.append(('solve', st['task_id'], SOLVE_P.format(q=st['question'], analysis=st['ana_main_text'])))
                jobmap.append((st['task_id'], 'solve_ntr'))
                jobs.append(('solve', st['task_id'], SOLVE_P.format(q=st['question'], analysis=st['ana_fb_text'])))
                jobmap.append((st['task_id'], 'solve_sd'))
            res = collect('medium', jobs)
            for i, (tid, role) in enumerate(jobmap):
                state[tid]['cells'][role] = res[i]
                ans = extract_answer(res[i].get('answer'))
                state[tid]['cells'][role + '_ans'] = ans
                state[tid]['cells'][role + '_ok'] = bool(ans) and parseable(ans)
            print(json.dumps(dict(phase='medium_done')))

            # mono arm scoring (offline)
            for st in state.values():
                am = extract_answer(st['cells']['mono_medium'].get('answer'))
                al = extract_answer(st['cells']['mono_large'].get('answer'))
                st['arms']['always_medium'] = bool(am) and equivalent(am, st['gold'])
                st['arms']['always_large'] = bool(al) and equivalent(al, st['gold'])
                st['arms']['query_router'] = st['arms']['always_large'] if len(st['question']) > QUERY_GUARD else st['arms']['always_medium']
                st['tokens']['mono'] = tok(st['cells']['mono_medium']) + tok(st['cells']['mono_large'])

            # ---- Phase 3 (coder): static solve fallback + verify cells ----
            ensure('coder')
            jobs = []
            jobmap = []
            for st in state.values():
                if not st['cells']['solve_sd_ok']:
                    jobs.append(('solve', st['task_id'], SOLVE_P.format(q=st['question'], analysis=st['ana_fb_text'])))
                    jobmap.append((st['task_id'], 'solve_sd_fb'))
                jobs.append(('verify', st['task_id'], VERIFY_P.format(q=st['question'], solution=st['cells']['solve_ntr_ans'])))
                jobmap.append((st['task_id'], 'verify_ntr'))
                jobs.append(('verify', st['task_id'], VERIFY_P.format(q=st['question'], solution=st['cells']['solve_sd_ans'])))
                jobmap.append((st['task_id'], 'verify_sd'))
            res = collect('coder', jobs)
            for i, (tid, role) in enumerate(jobmap):
                state[tid]['cells'][role] = res[i]
            for st in state.values():
                if 'solve_sd_fb' in st['cells']:
                    ans = extract_answer(st['cells']['solve_sd_fb'].get('answer'))
                    if ans and parseable(ans):
                        st['cells']['solve_sd_ans'] = ans
                        st['cells']['solve_sd_ok'] = True
            print(json.dumps(dict(phase='coder_done')))

            # ---- Phase 4 (medium): verify fallback for static ----
            need_vf = [st for st in state.values()
                       if parse_jsonish(st['cells']['verify_sd'].get('answer')) is None]
            if need_vf:
                ensure('medium')
                jobs = [('verify', st['task_id'], VERIFY_P.format(q=st['question'], solution=st['cells']['solve_sd_ans'])) for st in need_vf]
                res = collect('medium', jobs)
                for i, st in enumerate(need_vf):
                    st['cells']['verify_sd_fb'] = res[i]
            print(json.dumps(dict(phase='verify_fb_done', n=len(need_vf))))

            def final_from(solve_ans, verdict):
                if verdict and verdict.get('verdict') == 'no' and verdict.get('value'):
                    return str(verdict['value'])
                return solve_ans

            # ---- Phase 5 (large): dynamic escalation (solve/verify, budget-gated) ----
            dyn_need = []
            for st in state.values():
                v_sd = parse_jsonish(st['cells']['verify_sd'].get('answer'))
                if not st['cells']['solve_sd_ok'] or v_sd is None:
                    dyn_need.append(st)
            esc_solve = [st for st in dyn_need if not st['cells']['solve_sd_ok']]
            esc_verify = [st for st in dyn_need if st['cells']['solve_sd_ok']]
            if esc_solve or esc_verify:
                ensure('large')
                jobs = []
                jobmap = []
                for st in esc_solve:
                    jobs.append(('solve', st['task_id'], SOLVE_P.format(q=st['question'], analysis=st['ana_fb_text'])))
                    jobmap.append((st['task_id'], 'solve_dyn_esc'))
                for st in esc_verify:
                    jobs.append(('verify', st['task_id'], VERIFY_P.format(q=st['question'], solution=st['cells']['solve_sd_ans'])))
                    jobmap.append((st['task_id'], 'verify_dyn_esc'))
                res = collect('large', jobs)
                for i, (tid, role) in enumerate(jobmap):
                    state[tid]['cells'][role] = res[i]
                for st in esc_solve:
                    ans = extract_answer(st['cells']['solve_dyn_esc'].get('answer'))
                    if ans and parseable(ans):
                        st['cells']['solve_dyn_ans'] = ans
                        st['cells']['solve_dyn_ok'] = True
                    else:
                        st['cells']['solve_dyn_ans'] = st['cells']['solve_sd_ans']
                        st['cells']['solve_dyn_ok'] = st['cells']['solve_sd_ok']
                for st in esc_verify:
                    v = parse_jsonish(st['cells']['verify_dyn_esc'].get('answer'))
                    if v is not None:
                        st['cells']['verify_dyn_ok'] = True
                        st['cells']['verdict_dyn'] = v
                print(json.dumps(dict(phase='escalate_done', n=len(jobs))))

            # ---- final scoring per arm ----
            for st in state.values():
                # node_type_router: no recovery
                v_ntr = parse_jsonish(st['cells']['verify_ntr'].get('answer'))
                fin_ntr = final_from(st['cells']['solve_ntr_ans'], v_ntr)
                st['arms']['node_type_router'] = bool(fin_ntr) and equivalent(fin_ntr, st['gold'])
                st['tokens']['ntr'] = (tok(st['cells']['analyze_main']) + tok(st['cells']['solve_ntr'])
                                       + tok(st['cells']['verify_ntr']))
                # static: fb-updated analysis -> solve -> solve fb -> verify -> verify fb
                v_sd = parse_jsonish(st['cells']['verify_sd'].get('answer'))
                if v_sd is None:
                    v_sd = parse_jsonish((st['cells'].get('verify_sd_fb') or {}).get('answer'))
                fin_sd = final_from(st['cells']['solve_sd_ans'], v_sd)
                st['arms']['static_dag'] = bool(fin_sd) and equivalent(fin_sd, st['gold'])
                st['tokens']['static'] = (tok(st['cells']['analyze_main'])
                                          + (tok(st['cells']['analyze_fb']) if 'analyze_fb' in st['cells'] else 0)
                                          + tok(st['cells']['solve_sd'])
                                          + (tok(st['cells']['solve_sd_fb']) if 'solve_sd_fb' in st['cells'] else 0)
                                          + tok(st['cells']['verify_sd'])
                                          + (tok(st['cells']['verify_sd_fb']) if 'verify_sd_fb' in st['cells'] else 0))
                st['budget'] = max(BUDGET_FLOOR, BUDGET_MULT * st['tokens']['static'])
                # dynamic: fb analysis -> solve (escalate large) -> verify (escalate large)
                solve_dyn_ans = st['cells'].get('solve_dyn_ans', st['cells']['solve_sd_ans'])
                v_dyn = st['cells'].get('verdict_dyn')
                if v_dyn is None:
                    v_dyn = parse_jsonish(st['cells']['verify_sd'].get('answer'))
                fin_dyn = final_from(solve_dyn_ans, v_dyn)
                st['arms']['dynamic_real'] = bool(fin_dyn) and equivalent(fin_dyn, st['gold'])
                dt = st['tokens']['static']
                for role in ('solve_dyn_esc', 'verify_dyn_esc'):
                    if role in st['cells']:
                        dt += tok(st['cells'][role])
                st['tokens']['dynamic'] = dt
                st['budget_violation'] = dt > st['budget']
        finally:
            if proc is not None:
                engine.stop_model(proc, log)

    rows = [dict(task_id=st['task_id'], arms=st['arms'], tokens=st['tokens'],
                 budget=st['budget'], budget_violation=st['budget_violation']) for st in state.values()]
    core.write(OUT / 'RESULTS.json', dict(created_unix=time.time(), n_tasks=len(rows), rows=rows,
                                          implementation_note=('dynamic solve/verify escalation is large-only '
                                                               '(no coder-first memory switch on analyze); all failure '
                                                               'detection deployable, no gold at runtime')))
    core.write(OUT / 'ALL_DONE', dict(unix_time=time.time(), n_tasks=len(rows)))
    acc = {arm: float(sum(1 for r in rows if r['arms'][arm]) / len(rows)) for arm in
           ['always_medium', 'always_large', 'query_router', 'node_type_router', 'static_dag', 'dynamic_real']}
    print(json.dumps(acc, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
