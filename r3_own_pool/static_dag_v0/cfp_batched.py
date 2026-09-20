"""Batched executor for the controlled fault propagation experiment.

CFP's policy is memoryless across (task, fault, arm) units and every call's key/model/
prompt is determined by earlier stages, so the remaining calls batch into five model
groups (large -> coder -> medium -> coder -> large) costing 5 loads instead of ~150.
Unit semantics are IDENTICAL to controlled_fault_propagation.run(); the budget gate for
dynamic escalations is evaluated with run()'s exact formula offline, so finalize adds
zero new calls.

Stages:
 1 large : A extractions (missing) + dynamic T3 re-extractions (capability re-route)
 2 coder : static T3 re-extractions (frozen fallback)
 3 medium: T3 planned extraction (the fault source) + all r1 calls
 4 coder : static r2 fallbacks + dynamic T3 r2 (both coder) where r1 failed
 5 large : dynamic r2 escalations for C0/T1/T2 where r1 failed, budget-gated
"""
import copy
import fcntl
import json
import os
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .controlled_fault_propagation import OUT, MIN_TOKENS, HEADROOM, close, freeze, reasoning_out, cost_of
from .recovery_matrix_v2_devset import BASE
from .live_static_dynamic import OUT as LIVE
DEV2 = BASE / 'dynamic_v2_dev'

def append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())

def load_cache():
    cache = {}
    for src in [LIVE / 'RESPONSES.jsonl', DEV2 / 'RESPONSES.jsonl', OUT / 'RESPONSES.jsonl']:
        if src.exists():
            for l in src.read_text().splitlines():
                r = json.loads(l); cache[r['key']] = r
    return cache

def run():
    if not (OUT / 'CFP_POLICY.json').exists():
        freeze()
    pol = json.loads((OUT / 'CFP_POLICY.json').read_text())
    tasks = pol['tasks']
    if (OUT / 'CFP_DONE.json').exists(): raise FileExistsError('CFP already complete')
    engine.OUT = OUT
    cache = load_cache()
    lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    proc = logm = None; current = None
    t0 = time.time()
    try:
        def call(key, model, prompt):
            if key in cache:
                r = cache[key]
                if r['response'].get('status') != 'delivered': raise RuntimeError('cached infra failure: ' + key)
                return r
            nonlocal proc, logm, current
            if model != current:
                if proc is not None: engine.stop_model(proc, logm); proc = logm = None
                proc, logm, _ = engine.start_model(model); current = model
            append(OUT / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
            resp = engine.call_model(model, prompt)
            rec = dict(key=key, model=model, response=resp); append(OUT / 'RESPONSES.jsonl', rec)
            cache[key] = rec
            if resp.get('status') != 'delivered': raise RuntimeError('Infrastructure failure: ' + key)
            return rec
        def parse(key):
            r = cache.get(key)
            if not r: return None
            try: return v.parse_facts(r['response']['answer'])
            except Exception: return {'facts': []}
        def facts_for_unit(uid, ft, stage):
            """Consumed facts for a unit; stage controls whether the recovery
            extraction has already run ('post') or not ('pre')."""
            base = parse('A:' + uid)
            if base is None: return None
            if ft == 'T3':
                rec = parse(f'T3:{uid}') if stage >= 3 else None
                if ft == 'T3' and stage >= 4:
                    arm_ext = parse(f'CFP:{uid}:T3:dynamic:ext')  # dynamic consumed its own re-extraction
                    if arm_ext is not None: return arm_ext
                return rec if rec is not None else {'facts': []}
            return base
        def static_unit_cost(uid, ft):
            sst_keys = []
            for k, m in [(k, m) for k, m in []]: pass
            # static chain for this unit: A, (C:static if ext failed), B, (r1), (r2 coder if failed)
            base = parse('A:' + uid)
            ext_failed = base is not None and base['facts'] == []
            ks = [('A:' + uid, 'large')]
            if ft == 'T3':
                ks.append(('CFP:%s:T3:static:ext' % uid, 'coder'))
            ks.append(('B:' + uid, 'medium'))
            return sum(cost_of(cache, k) for k, _ in ks)

        # ---------------- stage 1 (large): A + dynamic T3 ext ----------------
        for t in tasks:
            uid = t['uid']
            if 'A:' + uid not in cache:
                call('A:' + uid, 'large', v.eprompt(dict(question=t['question'], context=t['context'])))
            k = f'CFP:{uid}:T3:dynamic:ext'
            if k not in cache:
                call(k, 'large', v.eprompt(dict(question=t['question'], context=t['context'])))
        # ---------------- stage 2 (coder): static T3 re-extraction ----------------
        for t in tasks:
            uid = t['uid']
            k = f'CFP:{uid}:T3:static:ext'
            if k not in cache:
                call(k, 'coder', v.eprompt(dict(question=t['question'], context=t['context'])))
        # ---------------- stage 3 (medium): T3 fault source + all r1 ----------------
        for t in tasks:
            uid = t['uid']
            k = f'T3:{uid}'
            if k not in cache:
                call(k, 'medium', v.eprompt(dict(question=t['question'], context=t['context'])))
        # build units now that facts exist
        units = []
        for t in tasks:
            uid = t['uid']; q = t['question']; gold = t['answer']
            base = parse('A:' + uid)
            if base is None: continue
            F0 = base['facts']
            ctx = {'C0': {'facts': [dict(f) for f in F0]}}
            if len(F0) >= 2: ctx['T1'] = {'facts': [dict(f) for f in F0[:-1]]}
            if len(F0) >= 1:
                f2 = [dict(f) for f in F0]; f2[-1]['value'] = f2[-1]['value'] * 1.5
                ctx['T2'] = {'facts': f2}
            if parse(f'T3:{uid}') is not None:
                ctx['T3'] = {'facts': [dict(f) for f in parse(f'T3:{uid}')['facts']]}
            for ft, facts in ctx.items():
                for arm in ['static', 'dynamic']:
                    units.append(dict(uid=uid, ft=ft, arm=arm, gold=gold, q=q, facts=facts,
                                      ext_failed=parse('A:' + uid)['facts'] == []))
        for u in units:
            k = f"CFP:{u['uid']}:{u['ft']}:{u['arm']}:r1"
            if k not in cache:
                call(k, 'medium', v.sprompt(dict(question=u['q']), {'facts': u['facts']['facts']}))
        # ---------------- stage 4 (coder): static r2 (all faults) + dynamic T3 r2 ----------------
        # (both are coder calls: static's frozen fallback and dynamic's post-large retry)
        for u in units:
            uid, ft, arm = u['uid'], u['ft'], u['arm']
            needs_coder_r2 = (arm == 'static') or (ft == 'T3' and arm == 'dynamic')
            if not needs_coder_r2: continue
            kR1 = f'CFP:{uid}:{ft}:{arm}:r1'
            val, _ = reasoning_out(cache, kR1, u['facts'])
            if close(val, u['gold']): continue
            kR2 = f'CFP:{uid}:{ft}:{arm}:r2'
            if kR2 not in cache:
                call(kR2, 'coder', v.sprompt(dict(question=u['q']), {'facts': u['facts']['facts']}))
        # ---------------- stage 5 (large): dynamic escalations, budget-gated ----------------
        for u in units:
            uid, ft, arm = u['uid'], u['ft'], u['arm']
            if ft == 'T3' or arm != 'dynamic': continue
            kR1 = f'CFP:{uid}:{ft}:{arm}:r1'
            val, _ = reasoning_out(cache, kR1, u['facts'])
            if close(val, u['gold']): continue
            static_realized = 0.0
            for k, m in [('A:' + uid, 'large'), ('B:' + uid, 'medium')]:
                static_realized += cost_of(cache, k)
            if u['ext_failed']:
                static_realized += cost_of(cache, f'CFP:{uid}:T3:static:ext')
                static_realized += cost_of(cache, f'D:static:{uid}')
            budget = static_realized * HEADROOM
            used = cost_of(cache, 'A:' + uid) + cost_of(cache, 'B:' + uid)
            if u['ext_failed']:
                used += cost_of(cache, f'CFP:{uid}:T3:dynamic:ext')
                used += cost_of(cache, f'D:dynamic:{uid}')
            used += cost_of(cache, kR1)
            kR2 = f'CFP:{uid}:{ft}:{arm}:r2'
            if kR2 in cache: continue
            if used > budget - MIN_TOKENS:
                continue  # run() will skip identically (recorded as escalation_skipped)
            call(kR2, 'large', v.sprompt(dict(question=u['q']), {'facts': u['facts']['facts']}))
        print('batched stages complete:', len(cache), 'cached calls,', round(time.time() - t0), 's')
    finally:
        if proc is not None: engine.stop_model(proc, logm)
        fcntl.flock(lock, fcntl.LOCK_UN); lock.close()
    # finalize outside the GPU lock (it re-acquires internally); zero new calls expected
    from .controlled_fault_propagation import run as finalize
    finalize()
    print('CFP finalized')

if __name__ == '__main__':
    run()
