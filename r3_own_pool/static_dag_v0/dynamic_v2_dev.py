"""Dynamic v2 dev iteration: Static vs Dynamic v1 vs Dynamic v2 on a frozen dev task set
(the 33 scale_up tasks remaining after the live-48 freeze; disjoint from all prior sets).

Only the dynamic scheduling rules differ; model pool, prompts, DAG (extraction->reasoning),
initial assignment, budget rule and generation config are identical to the live experiment.

Dynamic v2 rules (frozen before the dev run; iteration allowed only within these families):
R1 positive-evidence lock: the frozen second-best fallback is kept unless it has actually
   failed (F>=1) in this run — failure memory may not override a no-failure-evidence choice.
R2 hysteresis margin: a switch additionally requires score(alt) > score(cur) + delta.
R3 affected-descendant gating: reasoning is refreshed on recovered extraction output only if
   the recovered fact set materially differs from the failed attempt's; otherwise the Static
   assignment is kept.
R4 capability-profile rerouting: score = U_RANK(type, m) - gamma * F(m) (capability profile
   plus failure penalty; lambda/mu = 0 because per-node token/latency gaps across the pool
   are ~equal for these node types; frozen gamma = 1.0, delta = 0.1).
v1 = the live experiment's dynamic policy (fallback large / extraction medium after first
primary failure), frozen unchanged. Static = frozen-utility second best, downstream fixed.
"""
import fcntl
import hashlib
import json
import os
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .live_static_dynamic import OUT as LIVE, Caller, FALLBACK, close, reasoning_out, sha

OUT = BASE / 'dynamic_v2_dev'
POOL = ['medium', 'large', 'coder']
GAMMA = 1.0
DELTA = 0.1
HEADROOM = 1.2
U_RANK = {'extraction': {'large': 1.0, 'coder': 0.5, 'medium': 0.0},
          'reasoning': {'medium': 1.0, 'coder': 0.75, 'large': 0.0}}
ARMS = ['static', 'dynv1', 'dynv2']

def freeze_dev():
    used = set()
    for e in ['recovery_matrix_v2_pool_final.json', 'scale_up/decompose_at_scale/RESULTS.json',
              'recovery_matrix_v2/dev_replan_pilot/dev_failure_set.json']:
        d = json.loads((BASE / e).read_text())
        rows = d['rows'] if isinstance(d, dict) and 'rows' in d else (d.get('nodes') if isinstance(d, dict) else d)
        for r in rows: used.add(r.get('task_uid') or r['node_id'].split(':')[0])
    live = json.loads((LIVE / 'LIVE_POLICY.json').read_text())
    for t in live['tasks']: used.add(t['uid'])
    tasks = [t for t in json.loads((BASE / 'scale_up/TQ_TASKS.json').read_text()) if t['uid'] not in used]
    tasks.sort(key=lambda t: sha('dev2:' + t['uid']))
    policy = dict(n_tasks=len(tasks), selection='all remaining unused scale_up tasks after live-48 freeze; no headroom/failure screening',
                  rules=dict(R1_positive_evidence_lock='frozen fallback kept unless F>=1', R2_delta=DELTA,
                             R3_gating='reasoning refreshed only on materially changed facts', R4_gamma=GAMMA,
                             scoring='U_RANK - gamma*F'),
                  arms=ARMS, tasks=tasks)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'DEV2_POLICY.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2))
    return policy

def append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())

def run():
    if not (OUT / 'DEV2_POLICY.json').exists():
        freeze_dev()
    pol = json.loads((OUT / 'DEV2_POLICY.json').read_text())
    tasks = pol['tasks']
    if (OUT / 'DEV2_DONE.json').exists(): raise FileExistsError('dev v2 run complete')
    engine.OUT = OUT
    caller = Caller.__new__(Caller)
    caller.proc = caller.log = caller.current = None
    caller.cache = {}
    if (OUT / 'RESPONSES.jsonl').exists():
        for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l); caller.cache[r['key']] = r
    caller.lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
    fcntl.flock(caller.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    t0 = time.time()
    try:
        # Pass A (shared): extraction planned=large
        for t in tasks:
            k = 'A:' + t['uid']
            if k not in caller.cache:
                caller.call(k, 'large', v.eprompt(dict(question=t['question'], context=t['context'])))
        factsA = {}
        for t in tasks:
            try: factsA[t['uid']] = (v.parse_facts(caller.cache['A:' + t['uid']]['response']['answer']), False)
            except Exception: factsA[t['uid']] = ({'facts': []}, True)
        # Pass B (shared): reasoning planned=medium
        for t in tasks:
            k = 'B:' + t['uid']
            if k not in caller.cache:
                caller.call(k, 'medium', v.sprompt(dict(question=t['question']), {'facts': factsA[t['uid']][0]['facts']}))
        state = {a: {t['uid']: dict(facts=factsA[t['uid']][0], keys=[('A:' + t['uid'], 'large'), ('B:' + t['uid'], 'medium')], used=0.0)
                     for t in tasks} for a in ARMS}
        # memory of fallback-model failures per arm (updated in task order as outcomes arrive)
        Fmem = {a: {'extraction': {'coder': 0, 'medium': 0}, 'reasoning': {'coder': 0, 'large': 0}} for a in ARMS}
        for arm in ARMS:
            n_ext_fail = 0
            # freeze static realized cost right after the static arm (needed as the budget
            # base for later arms' pass E; computing it here avoids a zero-budget bug)
            if arm != 'static':
                for tt in tasks:
                    state['static'][tt['uid']]['used'] = sum(
                        float((caller.cache[k]['response'].get('usage') or {}).get('total_tokens') or 0)
                        for k, _ in state['static'][tt['uid']]['keys'] if k in caller.cache)
            for t in tasks:
                uid = t['uid']
                failedA = factsA[uid][1]
                if failedA:
                    n_ext_fail += 1
                    # Pass C: extraction fallback
                    if arm == 'static': fb = 'coder'
                    elif arm == 'dynv1': fb = 'medium'
                    else:  # dynv2: R1+R2 hysteresis (default frozen coder; switch only on evidence)
                        fb = 'coder' if Fmem[arm]['extraction']['coder'] == 0 else 'medium'
                    kC = f'C:{arm}:{uid}'
                    if kC not in caller.cache:
                        caller.call(kC, fb, v.eprompt(dict(question=t['question'], context=t['context'])))
                    try: fC = (v.parse_facts(caller.cache[kC]['response']['answer']), True)
                    except Exception: fC = ({'facts': []}, True)
                    Fmem[arm]['extraction'][fb] += int(not (fC[0]['facts'] and any(True for _ in fC[0]['facts'])))
                    if fC[0]['facts']: Fmem[arm]['extraction'][fb] = Fmem[arm]['extraction'][fb]  # success: no penalty increment
                    state[arm][uid]['facts'] = fC[0]
                    state[arm][uid]['keys'].append((kC, fb))
                    # Pass D: reasoning refresh — v1/static always; v2 only on materially changed facts (R3)
                    old_vals = sorted(f['value'] for f in factsA[uid][0]['facts'])
                    new_vals = sorted(f['value'] for f in fC[0]['facts'])
                    materially_changed = old_vals != new_vals
                    if arm != 'dynv2' or materially_changed:
                        kD = f'D:{arm}:{uid}'
                        if kD not in caller.cache:
                            caller.call(kD, 'medium', v.sprompt(dict(question=t['question']), {'facts': fC[0]['facts']}))
                        state[arm][uid]['keys'].append((kD, 'medium'))
                        state[arm][uid]['facts'] = fC[0]
                    else:
                        state[arm][uid]['keys'].append((kD, 'medium'))  # reuse B result; recorded for provenance
            # Pass E: reasoning fallback for failed reasoning nodes
            for t in tasks:
                uid = t['uid']; st = state[arm][uid]
                val, _ = reasoning_out(caller.cache, st['keys'][-1][0], st['facts'])
                st['ok'] = close(val, t['answer'])
                if st['ok']: continue
                if arm == 'static':
                    fb = 'coder'
                elif arm == 'dynv1':
                    fb = 'large'
                else:  # dynv2: R1+R2+R4 — frozen fallback coder locked unless it has failed; switch by score+delta
                    fc = Fmem[arm]['reasoning']['coder']
                    s_coder = U_RANK['reasoning']['coder'] - GAMMA * fc
                    s_large = U_RANK['reasoning']['large'] - GAMMA * Fmem[arm]['reasoning']['large']
                    fb = 'large' if (fc >= 1 and s_large > s_coder + DELTA) else 'coder'
                kE = f'E:{arm}:{uid}'
                budget = state['static'][uid]['used'] * HEADROOM
                rem = budget - sum(float((caller.cache[k]['response'].get('usage') or {}).get('total_tokens') or 0)
                                   for k, _ in st['keys'] if k in caller.cache)
                if arm != 'static' and rem < 200:
                    st['escalation_skipped'] = 'budget'; continue
                st['keys'].append((kE, fb))
                if kE not in caller.cache:
                    caller.call(kE, fb, v.sprompt(dict(question=t['question']), {'facts': st['facts']['facts']}))
                val, _ = reasoning_out(caller.cache, kE, st['facts'])
                st['ok'] = close(val, t['answer'])
                if not st['ok'] and arm == 'dynv2': Fmem[arm]['reasoning'][fb] += 1
        # costs
        for arm in ARMS:
            for t in tasks:
                uid = t['uid']
                state[arm][uid]['used'] = sum(float((caller.cache[k]['response'].get('usage') or {}).get('total_tokens') or 0)
                                              for k, _ in state[arm][uid]['keys'] if k in caller.cache)
        budgets = {t['uid']: state['static'][t['uid']]['used'] * HEADROOM for t in tasks}
        raw = dict(wall_seconds=time.time() - t0,
                   arms={a: {u: {k: v for k, v in st.items() if k != 'facts'} for u, st in state[a].items()} for a in ARMS},
                   budgets=budgets,
                   facts={t['uid']: {a: [f['value'] for f in state[a][t['uid']]['facts']['facts']] for a in ARMS} for t in tasks},
                   extraction_initial_parse_failed={t['uid']: factsA[t['uid']][1] for t in tasks},
                   Fmem={a: {ty: dict(mm) for ty, mm in Fmem[a].items()} for a in ARMS})
        core.write(OUT / 'RAW_TAIL.json', raw)
        core.write(OUT / 'DEV2_DONE.json', dict(unix_time=time.time(), wall_seconds=time.time() - t0, calls=len(caller.cache)))
    finally:
        caller.close()

if __name__ == '__main__':
    run()
