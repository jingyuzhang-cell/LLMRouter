"""Live Static DAG vs Live Dynamic DAG — the final core experiment.

Frozen BEFORE any live call (LIVE_POLICY.json). 48 unused TAT-QA tasks (scale_up pool,
disjoint from pool_final / decompose_at_scale / dev_replan_pilot / tatqa_benchmark / live_e2e),
chosen by sha256("live:"+uid) order — NOT screened by oracle headroom or failure status.

Shared by both arms: DAG = extraction -> reasoning (2-node chain); FrozenNodeRouter initial
assignment (extraction=large, reasoning=medium); frozen prompts (v.eprompt / v.sprompt);
model pool (medium/large/coder); generation (temperature 0, top_p 1, max_tokens 512);
per-task token budget = 1.2 x Static arm realized tokens; real recovered outputs propagate
to reasoning in BOTH arms (live propagation).

Static: node failure -> one local fallback to the frozen-utility second best
(extraction large->coder; reasoning medium->coder); downstream model assignment and plan
unchanged.

Dynamic: failure-state feedback with two frozen adaptation rules —
(a) extraction fallback switches to medium once a primary extraction failure has been
    observed (memory: primary large-failure events in task order; beta_mem(0,n)>=0.5 while
    n=0, else medium);
(b) reasoning failure escalates to the stronger untried model large (selective dynamic
    update: reasoning is the only affected descendant of either node), budget-gated —
    skipped and recorded when B_rem cannot cover the call.
Topology unchanged; no new recovery actions; decisions are computed before their calls
(all from pass A/B outcomes and Static realized costs), so calls batch by model.
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

OUT = BASE / 'live_static_dynamic'
POOL = ['medium', 'large', 'coder']
HEADROOM = 1.2
N_TASKS = 48
FROZEN_COMMIT = '8417776'
FALLBACK = {'extraction': {'static': {'large': 'coder'}, 'dynamic': {'large': 'coder', '_switch_after_first_failure': 'medium'}},
            'reasoning': {'static': {'medium': 'coder'}, 'dynamic': {'medium': 'large'}}}
EXCLUDE = ['recovery_matrix_v2_pool_final.json', 'scale_up/decompose_at_scale/RESULTS.json',
           'recovery_matrix_v2/dev_replan_pilot/dev_failure_set.json']

def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))

def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()

def freeze():
    used = set()
    for e in EXCLUDE:
        d = json.loads((BASE / e).read_text())
        rows = d['rows'] if isinstance(d, dict) and 'rows' in d else (d.get('nodes') if isinstance(d, dict) else d)
        for r in rows:
            used.add(r.get('task_uid') or r['node_id'].split(':')[0])
    tasks = [t for t in json.loads((BASE / 'scale_up/TQ_TASKS.json').read_text()) if t['uid'] not in used]
    tasks.sort(key=lambda t: sha('live:' + t['uid']))
    sel = tasks[:N_TASKS]
    assert len(sel) == N_TASKS, len(sel)
    policy = dict(
        frozen_commit=FROZEN_COMMIT, n_tasks=len(sel),
        selection='sha256("live:"+uid) ascending; unused scale_up tasks; no headroom/failure screening',
        dag='extraction(large) -> reasoning(medium); success = expression on consumed facts == gold (close, 1e-4 rel)',
        static_policy='node failure -> one local fallback (extraction large->coder; reasoning medium->coder); downstream plan unchanged; recovered outputs propagate',
        dynamic_policy=('extraction fallback switches large->medium after the first primary extraction failure (memory in task order); '
                        'reasoning failure escalates to large (stronger untried model), budget-gated; real outputs propagate; '
                        'selective: reasoning is the only affected descendant; topology unchanged'),
        budget='per-task = 1.2 x Static arm realized tokens; B_rem recomputed after every call; exhausted budget -> escalation skipped and recorded',
        headroom='post-hoc: failed reasoning instances re-called with untried models on the same input',
        generation='temperature 0, top_p 1, max_tokens 512 via run.call_model',
        tasks=sel)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'LIVE_POLICY.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2))
    return policy

def append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())

class Caller:
    def __init__(self):
        self.proc = self.log = None; self.current = None
        self.cache = {}
        if (OUT / 'RESPONSES.jsonl').exists():
            for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
                r = json.loads(l); self.cache[r['key']] = r
        self.lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def call(self, key, model, prompt):
        if key in self.cache:
            r = self.cache[key]
            if r['response'].get('status') != 'delivered': raise RuntimeError('cached infra failure: ' + key)
            return r
        if model != self.current:
            if self.proc is not None: engine.stop_model(self.proc, self.log); self.proc = self.log = None
            self.proc, self.log, _ = engine.start_model(model); self.current = model
        append(OUT / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
        resp = engine.call_model(model, prompt)
        rec = dict(key=key, model=model, response=resp); append(OUT / 'RESPONSES.jsonl', rec)
        self.cache[key] = rec
        if resp.get('status') != 'delivered': raise RuntimeError('Infrastructure failure: ' + key)
        return rec
    def close(self):
        if self.proc is not None: engine.stop_model(self.proc, self.log); self.proc = None
        try: fcntl.flock(self.lock, fcntl.LOCK_UN)
        except Exception: pass
        self.lock.close()

def reasoning_out(cache, key, facts):
    r = cache.get(key)
    if not r: return None, None
    try:
        expr = v.decode(r['response']['answer'])['expression']
        return exec_calc(expr, facts), expr
    except Exception:
        return None, None

def cost_of(cache, key):
    r = cache.get(key)
    return float((r['response'].get('usage') or {}).get('total_tokens') or 0) if r else 0.0

def run():
    if not (OUT / 'LIVE_POLICY.json').exists():
        freeze()
    pol = json.loads((OUT / 'LIVE_POLICY.json').read_text())
    tasks = pol['tasks']
    if (OUT / 'LIVE_DONE.json').exists(): raise FileExistsError('live run complete')
    engine.OUT = OUT
    caller = Caller()
    t0 = time.time()
    try:
        # ---- Pass A (shared): initial extraction, planned=large ----
        for t in tasks:
            k = 'A:' + t['uid']
            if k not in caller.cache:
                caller.call(k, 'large', v.eprompt(dict(question=t['question'], context=t['context'])))
        factsA = {}
        for t in tasks:
            try: factsA[t['uid']] = (v.parse_facts(caller.cache['A:' + t['uid']]['response']['answer']), False)
            except Exception: factsA[t['uid']] = ({'facts': []}, True)
        # ---- Pass B (shared): initial reasoning, planned=medium, on pass-A facts ----
        for t in tasks:
            k = 'B:' + t['uid']
            if k not in caller.cache:
                caller.call(k, 'medium', v.sprompt(dict(question=t['question']), {'facts': factsA[t['uid']][0]['facts']}))
        # ---- Per-arm passes ----
        state = {'static': {}, 'dynamic': {}}
        n_ext_fail_seen = 0
        for t in tasks:
            uid = t['uid']
            state['static'][uid] = dict(facts=factsA[uid][0], keys=[('A:' + uid, 'large'), ('B:' + uid, 'medium')])
            state['dynamic'][uid] = dict(facts=factsA[uid][0], keys=[('A:' + uid, 'large'), ('B:' + uid, 'medium')])
        for arm in ['static', 'dynamic']:
            n_ext_fail_seen = 0
            for t in tasks:
                uid = t['uid']
                failedA = factsA[uid][1]
                # Pass C: extraction fallback (dynamic switches to medium after first primary failure)
                if failedA:
                    fb_model = 'coder' if (arm == 'static' or n_ext_fail_seen == 0) else 'medium'
                    kC = f'C:{arm}:{uid}'
                    if kC not in caller.cache:
                        caller.call(kC, fb_model, v.eprompt(dict(question=t['question'], context=t['context'])))
                    try: fC = (v.parse_facts(caller.cache[kC]['response']['answer']), True)
                    except Exception: fC = ({'facts': []}, True)
                    state[arm][uid]['facts'] = fC[0]
                    state[arm][uid]['keys'].append((kC, fb_model))
                    n_ext_fail_seen += 1
                    # Pass D: reasoning refresh with the recovered (real) output — planned model kept
                    kD = f'D:{arm}:{uid}'
                    if kD not in caller.cache:
                        caller.call(kD, 'medium', v.sprompt(dict(question=t['question']), {'facts': fC[0]['facts']}))
                    state[arm][uid]['keys'].append((kD, 'medium'))
            # ---- costs for executed keys (before this arm's pass E) ----
            for tt in tasks:
                state[arm][tt['uid']]['used'] = sum(cost_of(caller.cache, k) for k, _ in state[arm][tt['uid']]['keys'])
            # Pass E: reasoning failure escalation (node-level, on the latest consumed facts)
            for t in tasks:
                uid = t['uid']; st = state[arm][uid]
                val, _ = reasoning_out(caller.cache, st['keys'][-1][0], st['facts'])
                st['ok'] = close(val, t['answer'])
                if st['ok']: continue
                fb_model = FALLBACK['reasoning'][arm]['medium']  # static: coder; dynamic: large
                kE = f'E:{arm}:{uid}'
                # budget base = Static arm FINAL realized cost (incl. its own fallback), per policy
                static_realized = sum(cost_of(caller.cache, k) for k, _ in state['static'][uid]['keys'])
                budget = static_realized * HEADROOM
                rem = budget - sum(cost_of(caller.cache, k) for k, _ in st['keys'])
                if arm == 'dynamic' and rem < 200:
                    st['escalation_skipped'] = 'budget'
                    continue
                st['keys'].append((kE, fb_model))
                if kE not in caller.cache:
                    caller.call(kE, fb_model, v.sprompt(dict(question=t['question']), {'facts': st['facts']['facts']}))
                val, _ = reasoning_out(caller.cache, kE, st['facts'])
                st['ok'] = close(val, t['answer'])
        # ---- costs, budgets ----
        for arm in ['static', 'dynamic']:
            for t in tasks:
                uid = t['uid']
                state[arm][uid]['used'] = sum(cost_of(caller.cache, k) for k, _ in state[arm][uid]['keys'])
        skipped = []
        for t in tasks:
            uid = t['uid']; dst = state['dynamic'][uid]
            dst['budget'] = state['static'][uid]['used'] * HEADROOM
            dst['over_budget'] = dst['used'] > dst['budget'] + 1e-9
            if dst.get('escalation_skipped'): skipped.append(dict(uid=uid, reason='budget', used=dst['used'], budget=dst['budget']))
        head = posthoc_headroom(caller, tasks, state)
        raw = dict(wall_seconds=time.time() - t0,
                   static={u: {k: v for k, v in st.items() if k != 'facts'} for u, st in state['static'].items()},
                   dynamic={u: {k: v for k, v in st.items() if k != 'facts'} for u, st in state['dynamic'].items()},
                   skipped=skipped, headroom=head,
                   facts={t['uid']: {'static': [f['value'] for f in state['static'][t['uid']]['facts']['facts']],
                                     'dynamic': [f['value'] for f in state['dynamic'][t['uid']]['facts']['facts']],
                                     'initial': [f['value'] for f in factsA[t['uid']][0]['facts']]} for t in tasks},
                   extraction_initial_parse_failed={t['uid']: factsA[t['uid']][1] for t in tasks})
        core.write(OUT / 'RAW_TAIL.json', raw)
        core.write(OUT / 'LIVE_DONE.json', dict(unix_time=time.time(), wall_seconds=time.time() - t0, calls=len(caller.cache)))
    finally:
        caller.close()

def posthoc_headroom(caller, tasks, state):
    head = []; seen = set()
    for arm in ['static', 'dynamic']:
        for t in tasks:
            uid = t['uid']; st = state[arm][uid]
            if st['ok']: continue
            fhash = sha(json.dumps([f['value'] for f in st['facts']['facts']]))[:8]
            if (uid, fhash) in seen: continue
            seen.add((uid, fhash))
            tried = {m for _, m in st['keys']}
            for m in POOL:
                if m in tried: continue
                kH = f'H:{uid}:{fhash}:{m}'
                if kH not in caller.cache:
                    caller.call(kH, m, v.sprompt(dict(question=t['question']), {'facts': st['facts']['facts']}))
                val, _ = reasoning_out(caller.cache, kH, st['facts'])
                head.append(dict(arm=arm, uid=uid, facts_hash=fhash, model=m, ok=close(val, t['answer'])))
    return head

if __name__ == '__main__':
    run()
