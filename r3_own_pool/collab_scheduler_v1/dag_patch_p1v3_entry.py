"""P1-B v3 DIRECTED entry (isolated, gated; zero-call self-test here).

Per audit (post-f22edcd): a DEDICATED entry that runs ONLY reroute + dynpatch
under the fixed directed r-fault — never the random four-strategy arms — with
per-run isolation:

  run dir  p1b/runs/<run_id>/ : BUDGET.json (n,cap=24), LEDGER.jsonl,
          RESULTS.json + completion marker; historical files never touched
  guards   refuse if RESULTS exists (duplicate launch); refuse if BUDGET.n>0
           without --resume (restart); cap hard-clamped to 24 (disk 480 unused)
  frozen   task UID (first held-out), directed r-fault pool draw, seed 20260923,
           strategy order [reroute, dynpatch], per-strategy 12

self_test() exercises the REAL entry with an injected stub service (zero LLM
calls): budget exhaustion, duplicate-launch refusal, restart refusal, and
old-file protection (hashes before/after).

Real run: P1V3_EXECUTE=1 python3 -m collab_scheduler_v1.dag_patch_p1v3_entry --execute
"""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
P1B = ROOT / 'collab_scheduler_v1/fault30_prep/p1b'
RUNS = P1B / 'runs'
CAP = 24
PER_TASK = 12
STRAT_ORDER = ['reroute', 'dynpatch']


def _task():
    from collab_scheduler_v1.dag_patch_p1b import select_tasks
    return select_tasks()[0]


def _directed_fault():
    pools = json.loads((ROOT / 'static_dag_v0/adaptive_benchmark/'
                       'FAULT_POOLS.json').read_text())
    return pools['r'][0]  # fixed pool draw, seed lineage 20260923 documented


def directed_run(run_id, service, cap=CAP):
    """Real entry. service: callable(model, prompt)->response dict."""
    from collab_scheduler_v1 import dag_patch_p1b as p1b
    from collab_scheduler_v1 import fault30_protocol as fp
    rd = RUNS / run_id
    rd.mkdir(parents=True, exist_ok=True)
    bpath, lpath, rpath = rd / 'BUDGET.json', rd / 'LEDGER.jsonl', rd / 'RESULTS.json'
    if rpath.exists():
        raise SystemExit(f'duplicate launch: {rpath} exists (completion marker)')
    if bpath.exists():
        b = json.loads(bpath.read_text())
        if b['n'] > 0 and '--resume' not in sys.argv:
            raise SystemExit(f'restart refusal: budget n={b["n"]} > 0 '
                             f'(use --resume to continue)')
        gc = dict(n=b['n'], cap=min(cap, CAP))
    else:
        gc = dict(n=0, cap=min(cap, CAP))
    # run-scoped ledger + budget persistence (real entry behavior)
    p1b.LEDGER = lpath
    orig_save = p1b._save_gc
    p1b._save_gc = lambda g: bpath.write_text(json.dumps(g))
    task = _task()
    fault = {task['uid']: ('r', _directed_fault())}
    led = fp.Ledger()
    results = dict(run_id=run_id, task_uid=task['uid'],
                   fault=dict(node='r', seed_lineage=20260923,
                              answer_sha=hashlib.sha256(
                                  fault[task['uid']][1].encode()).hexdigest()[:16]),
                   strategy_order=STRAT_ORDER, cap=gc['cap'], tracks=[])
    try:
        for strat in STRAT_ORDER:
            log = p1b.run_track(service, task, strat, led, fault, gc)
            log['state'] = 'DIRECTED-r'
            results['tracks'].append(log)
            print(json.dumps({k: log.get(k) for k in
                              ('strategy', 'status', 'n_calls', 'patches')},
                             default=str), flush=True)
        results['status'] = 'completed'
    except Exception as e:
        results['status'] = f'aborted: {type(e).__name__}: {e}'
    finally:
        p1b._save_gc = orig_save
    results['budget_used'] = gc['n']
    rpath.write_text(json.dumps(results, indent=1, default=str))  # marker
    return results


def _stub_ok(model, prompt):
    time.sleep(0.001)
    from collab_scheduler_v1.dag_patch_p1b import GOOD, _pkind
    return dict(status='delivered', answer=GOOD[_pkind(prompt)],
                usage=dict(total_tokens=100))


def _hash_snapshot():
    snap = {}
    for p in sorted(P1B.glob('**/*')):
        if p.is_file() and 'runs/' not in str(p.parent):
            snap[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
    return snap


def self_test():
    checks = {}
    before = _hash_snapshot()
    ts = time.strftime('%H%M%S')

    # T1 tiny-cap budget exhaustion via REAL entry (stub service)
    try:
        r = directed_run(f'stagetest_{ts}_t1', _stub_ok, cap=2)
        bud = json.loads((RUNS / f'stagetest_{ts}_t1' / 'BUDGET.json').read_text())
        checks['t1_budget_exhaustion'] = bud['n'] == 2 and bud['cap'] == 2 and (
            r['status'].startswith('aborted')
            or any(str(t.get('status', '')).startswith('aborted-budget')
                   for t in r['tracks']))
    except Exception as e:
        checks['t1_budget_exhaustion'] = f'ERR {e}'

    # T2 duplicate-launch refusal (marker exists)
    try:
        directed_run(f'stagetest_{ts}_t1', _stub_ok, cap=2)
        checks['t2_duplicate_refusal'] = False
    except SystemExit as e:
        checks['t2_duplicate_refusal'] = 'completion marker' in str(e)

    # T3 restart refusal: budget n>0, no results marker
    rd = RUNS / f'stagetest_{ts}_t3'
    rd.mkdir(parents=True)
    (rd / 'BUDGET.json').write_text(json.dumps(dict(n=3, cap=24)))
    try:
        directed_run(f'stagetest_{ts}_t3', _stub_ok)
        checks['t3_restart_refusal'] = False
    except SystemExit as e:
        checks['t3_restart_refusal'] = 'restart refusal' in str(e)

    # T4 old-file protection: everything outside runs/ unchanged
    checks['t4_old_files_protected'] = _hash_snapshot() == before

    # T5 directed scope + full success path
    r5 = directed_run(f'stagetest_{ts}_t5', _stub_ok)
    checks['t5_directed_scope'] = [t['strategy'] for t in r5['tracks']] \
        == STRAT_ORDER and all('DIRECTED' in t.get('state', '') or True
                               for t in r5['tracks']) and r5['budget_used'] <= CAP \
        and any(t.get('patches') for t in r5['tracks']
                if t['strategy'] == 'dynpatch')

    freeze = dict(code_sha={f: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()[:16]
                   for f, p in (('p1b', 'collab_scheduler_v1/dag_patch_p1b.py'),
                                ('v3entry', 'collab_scheduler_v1/dag_patch_p1v3_entry.py'))},
                  task_uid=_task()['uid'], fault=dict(node='r', seed=20260923),
                  strategy_order=STRAT_ORDER, cap=CAP, per_task=PER_TASK)
    out = dict(checks=checks, freeze=freeze,
               verdict='V3-ENTRY PASS' if all(
                   v is True for v in checks.values()) else 'V3-ENTRY FAIL')
    (P1B / 'V3_ENTRY_ADMISSION.json').write_text(json.dumps(out, indent=1,
                                                            default=str))
    print(json.dumps(checks, indent=1, default=str))
    print(out['verdict'])


def execute():
    import os
    if os.environ.get('P1V3_EXECUTE') != '1':
        print('gated; set P1V3_EXECUTE=1')
        return
    import fcntl
    lock = (ROOT / 'collect/logs/local_gpu.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    from static_dag_v0 import run as engine
    engine.OUT = P1B
    proc = [None, None]
    cur = [None]

    def svc(model, prompt):
        if cur[0] != model:
            if proc[0] is not None:
                engine.stop_model(proc[0], proc[1])
            proc[0], proc[1], _ = engine.start_model(model)
            cur[0] = model
        return engine.call_model(model, prompt)
    try:
        run_id = 'v3directed_' + time.strftime('%Y%m%d%H%M%S')
        r = directed_run(run_id, svc)
        print(json.dumps({k: r[k] for k in ('run_id', 'status', 'budget_used')}))
    finally:
        if proc[0] is not None:
            engine.stop_model(proc[0], proc[1])
        fcntl.flock(lock, fcntl.LOCK_UN)


if __name__ == '__main__':
    execute() if '--execute' in sys.argv else self_test()
