"""P3 MBPP six-arm runner: one frozen panel, deployable-only failure detection.

Arms share a node-level call cache (keyed by sha256(prompt) + model). Scoring
is deterministic: generated code + the task's embedded unit tests run in a
sandboxed subprocess; correct iff all asserts pass. No gold anywhere at
runtime (the release contains no reference solutions at all).

Arms: always_medium / always_large / query_router / node_type_router /
static_dag / dynamic_real. Execution is staged by model (few vLLM reloads),
resumable via keyed ledger; refuses to start while the GPU is busy.
"""
import argparse
import fcntl
import hashlib
import json
import re
import subprocess
import sys
import time

from . import core
from . import run as engine

P3 = core.ROOT / 'static_dag_v0' / 'p3_xdomain'
OUT = P3 / 'mbpp_run'
QUERY_GUARD = 225.0  # frozen median char length (query+tests) of the 100-task panel
BUDGET_MULT = 1.2
BUDGET_FLOOR = 200

EXPERT = 'You are an expert Python programmer, and here is your task:\n'
MONO_P = (EXPERT + '{q}\n\nYour code should pass these tests:\n{tests}\n\n'
          'Write only the python code (function + any imports). Do not explain.')
PLAN_P = ('Analyze the coding task and design the solution. Return ONLY JSON '
          '{{"signature":"function signature","algorithm":"step plan","edge_cases":["..."]}}.\n'
          'TASK: {q}\nTESTS:\n{tests}')
IMPL_P = ('Implement the function per the plan. Write only the python code '
          '(function + any imports). Do not explain.\nTASK: {q}\nTESTS:\n{tests}\nPLAN: {plan}')
REPAIR_P = ('The submitted code failed. Fix it. Write only the python code '
            '(function + any imports). Do not explain.\nTASK: {q}\nTESTS:\n{tests}\n'
            'SUBMITTED CODE:\n{code}\nFAILURE REPORT:\n{err}')


def load_tasks():
    detail = json.loads((P3 / 'P3_CODE_TASKS_100_DETAIL.json').read_text())
    tasks = [dict(task_id=t['task_id'], query=t['query'], tests=t['tests']) for t in detail]
    assert len(tasks) == 100
    return tasks


def extract_code(text):
    t = (text or '').strip()
    m = re.search(r'```(?:python)?\s*\n(.*?)```', t, re.S)
    if m:
        return m.group(1).strip()
    return t


def run_tests(code, tests, timeout=20):
    prog = code + '\n\n' + '\n'.join(tests) + '\n'
    try:
        p = subprocess.run([sys.executable, '-I', '-c', prog], capture_output=True,
                           timeout=timeout, cwd='/tmp',
                           env={'PATH': '/usr/bin:/bin', 'HOME': '/tmp'})
        if p.returncode == 0:
            return True, ''
        err = (p.stderr.decode(errors='ignore') or p.stdout.decode(errors='ignore'))[-1200:]
        return False, err.strip() or 'non-zero exit'
    except subprocess.TimeoutExpired:
        return False, 'timeout'
    except Exception as e:
        return False, type(e).__name__ + ': ' + str(e)


def parse_plan(text):
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
        raise FileExistsError('mbpp run complete')

    resp = OUT / 'RESPONSES.jsonl'
    cache = {}
    if resp.exists():
        for line in resp.open():
            r = json.loads(line)
            cache[r['key']] = r

    def key_of(model, node, task, prompt):
        return f'{task["task_id"]}:{node}:{model}:{hashlib.sha256(prompt.encode()).hexdigest()[:12]}'

    state = {t['task_id']: dict(task_id=t['task_id'], query=t['query'], tests=t['tests'],
                                cells={}, arms={}, tokens={}, budget=None,
                                budget_violation=False, repairs=0) for t in tasks}

    def collect(model, jobs):
        """jobs: list of (node, task, prompt). Returns {job_index: response}."""
        have = {}
        for i, (node, t, prompt) in enumerate(jobs):
            key = key_of(model, node, t, prompt)
            if key in cache:
                have[i] = cache[key]
                continue
            r = engine.call_model(model, prompt)
            row = dict(key=key, model=model, prompt=prompt,
                       task_id=t['task_id'], node=node, **r)
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

            # Phase 1 (medium): mono + plan for all tasks
            ensure('medium')
            mono_jobs = [(t['task_id'], 'mono', MONO_P.format(q=t['query'], tests='\n'.join(t['tests']))) for t in tasks]
            plan_jobs = [(t['task_id'], 'plan', PLAN_P.format(q=t['query'], tests='\n'.join(t['tests']))) for t in tasks]
            mono_res = collect('medium', [(s, next(t for t in tasks if t['task_id'] == s), p) for s, node, p in mono_jobs])
            plan_res = collect('medium', [(s, next(t for t in tasks if t['task_id'] == s), p) for s, node, p in plan_jobs])
            for i, (tid, node, p) in enumerate(mono_jobs):
                state[tid]['cells']['mono_medium'] = mono_res[i]
            for i, (tid, node, p) in enumerate(plan_jobs):
                state[tid]['cells']['plan_medium'] = plan_res[i]
            print(json.dumps(dict(phase='medium_done')))

            # Phase 2 (large): mono + plan fallback where plan unparsed
            ensure('large')
            jobs = [(t['task_id'], 'mono', MONO_P.format(q=t['query'], tests='\n'.join(t['tests']))) for t in tasks]
            need_plan = [t for t in tasks
                         if parse_plan(state[t['task_id']]['cells']['plan_medium'].get('answer')) is None]
            jobs += [(t['task_id'], 'plan', PLAN_P.format(q=t['query'], tests='\n'.join(t['tests']))) for t in need_plan]
            res = collect('large', [(s, next(t for t in tasks if t['task_id'] == s), p) for s, node, p in jobs])
            for i, (tid, node, p) in enumerate(jobs):
                if node == 'mono':
                    state[tid]['cells']['mono_large'] = res[i]
                else:
                    state[tid]['cells']['plan_large'] = res[i]
            print(json.dumps(dict(phase='large_done', plan_fallbacks=len(need_plan))))

            # resolve per-task plan texts
            for st in state.values():
                p_med = st['cells']['plan_medium']
                plan = parse_plan(p_med.get('answer'))
                if plan is not None:
                    st['plan_text'] = json.dumps(plan, ensure_ascii=False)
                    st['plan_ok'] = True
                elif 'plan_large' in st['cells']:
                    plan = parse_plan(st['cells']['plan_large'].get('answer'))
                    st['plan_text'] = json.dumps(plan, ensure_ascii=False) if plan else (st['cells']['plan_large'].get('answer') or '')
                    st['plan_ok'] = plan is not None
                else:
                    st['plan_text'] = p_med.get('answer') or ''
                    st['plan_ok'] = False

            # mono arm results (offline tests)
            for st in state.values():
                cm = extract_code(st['cells']['mono_medium']['answer'])
                cl = extract_code(st['cells']['mono_large']['answer'])
                okm, _ = run_tests(cm, st['tests'])
                okl, _ = run_tests(cl, st['tests'])
                st['arms']['always_medium'] = okm
                st['arms']['always_large'] = okl
                st['arms']['query_router'] = okl if (len(st['query']) + len('\n'.join(st['tests']))) > QUERY_GUARD else okm
                st['tokens']['mono'] = tok(st['cells']['mono_medium']) + tok(st['cells']['mono_large'])
                st['impl_text'] = st['plan_text']
            print(json.dumps(dict(phase='mono_scored')))

            # Phase 3 (coder): implements for ntr/static/dynamic (dedup by prompt hash)
            ensure('coder')
            jobs = []
            jobmap = []
            for st in state.values():
                for arm in ('ntr', 'static', 'dynamic'):
                    jobs.append((st['task_id'], 'implement', IMPL_P.format(q=st['query'], tests='\n'.join(st['tests']), plan=st['impl_text'])))
                    jobmap.append((st['task_id'], arm))
            res = collect('coder', [(s, next(t for t in tasks if t['task_id'] == s), p) for s, node, p in jobs])
            impl = {}
            for i, (tid, arm) in enumerate(jobmap):
                key = key_of('coder', 'implement', next(t for t in tasks if t['task_id'] == tid), jobs[i][2])
                impl[(tid, arm)] = res[i]
                state[tid]['cells'][f'impl_{arm}'] = res[i]
            # execute
            for st in state.values():
                for arm in ('ntr', 'static', 'dynamic'):
                    code = extract_code(impl[(st['task_id'], arm)]['answer'])
                    ok, err = run_tests(code, st['tests'])
                    st['cells'][f'code_{arm}'] = code
                    st['cells'][f'ok_{arm}'] = ok
                    st['cells'][f'err_{arm}'] = err
                st['arms']['node_type_router'] = st['cells']['ok_ntr']
                st['tokens']['ntr'] = tok(st['cells']['plan_medium']) + tok(st['cells']['impl_ntr'])
                st['tokens']['static'] = tok(st['cells']['plan_medium']) + (tok(st['cells']['plan_large']) if 'plan_large' in st['cells'] else 0) + tok(st['cells']['impl_static'])
                st['tokens']['dynamic'] = st['tokens']['static'] - (tok(st['cells']['impl_static']) - tok(st['cells']['impl_dynamic']))
            print(json.dumps(dict(phase='coder_done')))

            # Phase 4 (medium): static fallback implement for failed static
            failed_static = [st for st in state.values() if not st['cells']['ok_static']]
            if failed_static:
                ensure('medium')
                jobs = [(st['task_id'], 'implement', IMPL_P.format(q=st['query'], tests='\n'.join(st['tests']), plan=st['impl_text'])) for st in failed_static]
                res = collect('medium', [(s, next(t for t in tasks if t['task_id'] == s), p) for s, node, p in jobs])
                for i, st in enumerate(failed_static):
                    st['cells']['impl_static_fb'] = res[i]
                    ok, err = run_tests(extract_code(res[i]['answer']), st['tests'])
                    st['cells']['ok_static'] = ok
                    st['cells']['err_static'] = err
                    st['tokens']['static'] += tok(res[i])
                print(json.dumps(dict(phase='static_fb_done', n=len(failed_static))))
            for st in state.values():
                st['arms']['static_dag'] = st['cells']['ok_static']
                st['budget'] = max(BUDGET_FLOOR, BUDGET_MULT * st['tokens']['static'])

            # Phase 5 (coder): dynamic repair rounds (bounded by budget)
            active = [st for st in state.values() if not st['cells']['ok_dynamic']]
            for rnd in range(2):
                active = [st for st in active if st['tokens']['dynamic'] < st['budget'] and not st['cells']['ok_dynamic']]
                if not active:
                    break
                ensure('coder')
                jobs = [(st['task_id'], 'repair', REPAIR_P.format(q=st['query'], tests='\n'.join(st['tests']), code=st['cells']['code_dynamic'], err=st['cells']['err_dynamic'])) for st in active]
                res = collect('coder', [(s, next(t for t in tasks if t['task_id'] == s), p) for s, node, p in jobs])
                for i, st in enumerate(active):
                    st['tokens']['dynamic'] += tok(res[i])
                    st['repairs'] += 1
                    code = extract_code(res[i]['answer'])
                    ok, err = run_tests(code, st['tests'])
                    st['cells']['code_dynamic'] = code
                    st['cells']['ok_dynamic'] = ok
                    st['cells']['err_dynamic'] = err
                print(json.dumps(dict(phase=f'repair_{rnd+1}_done', n=len(active))))

            # Phase 6 (large): dynamic escalation implement
            escalate = [st for st in state.values() if not st['cells']['ok_dynamic'] and st['tokens']['dynamic'] < st['budget']]
            if escalate:
                ensure('large')
                jobs = [(st['task_id'], 'implement', IMPL_P.format(q=st['query'], tests='\n'.join(st['tests']), plan=st['impl_text'])) for st in escalate]
                res = collect('large', [(s, next(t for t in tasks if t['task_id'] == s), p) for s, node, p in jobs])
                for i, st in enumerate(escalate):
                    st['tokens']['dynamic'] += tok(res[i])
                    ok, err = run_tests(extract_code(res[i]['answer']), st['tests'])
                    st['cells']['ok_dynamic'] = ok
                print(json.dumps(dict(phase='escalate_done', n=len(escalate))))
            for st in state.values():
                st['arms']['dynamic_real'] = st['cells']['ok_dynamic']
                st['budget_violation'] = st['tokens']['dynamic'] > st['budget']
        finally:
            if proc is not None:
                engine.stop_model(proc, log)

    rows = [dict(task_id=st['task_id'], arms=st['arms'], tokens=st['tokens'],
                 budget=st['budget'], budget_violation=st['budget_violation'],
                 repairs=st['repairs'], plan_ok=st['plan_ok']) for st in state.values()]
    core.write(OUT / 'RESULTS.json', dict(created_unix=time.time(), n_tasks=len(rows), rows=rows))
    core.write(OUT / 'ALL_DONE', dict(unix_time=time.time(), n_tasks=len(rows)))
    acc = {arm: float(sum(1 for r in rows if r['arms'][arm]) / len(rows)) for arm in
           ['always_medium', 'always_large', 'query_router', 'node_type_router', 'static_dag', 'dynamic_real']}
    print(json.dumps(acc, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
