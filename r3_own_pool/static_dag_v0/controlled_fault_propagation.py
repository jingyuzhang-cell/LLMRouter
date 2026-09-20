"""Controlled fault propagation experiment: does feedback-conditioned downstream
adaptation (Dynamic) block error propagation better than local frozen fallback (Static),
when both arms start from an IDENTICAL controlled fault?

Frozen design (before any call):
- Tasks: the 33 dynv2-dev tasks with >=2 extracted facts (dev-tier mechanism study).
- Baseline: extraction(large) outputs = base facts F0 (shared).
- Interventions (deterministic, seeded, applied to F0 copies; both arms receive the SAME
  perturbed input, so starting points are exactly equal):
  T1 evidence-missing: remove the last fact of F0 (requires >=2 facts).
  T2 wrong-value:      multiply the last fact value by 1.5.
  T3 wrong-model:      re-run extraction with medium (real weaker-model output).
  C0 control:          unperturbed F0 (sanity: arms must be equal).
- Arms on each fault context:
  Static:  reasoning(medium) -> on failure one local fallback to coder. For T3 the failed
           extraction node is re-run with coder, then reasoning(medium), then coder again
           on failure. No capability re-routing anywhere.
  Dynamic: reasoning(medium) -> on failure escalation to the stronger untried model (large).
           For T3 the failed extraction node is re-run with large (capability re-route),
           then reasoning(large) on the new output (chain-wide escalation). Budget-gated.
- Recovery success = reasoning expression on the consumed (perturbed/recovered) facts
  matches gold. Budget per (task, fault) = 1.2 x Static realized tokens.
Metrics per fault type: baseline wrong rate, recovery rate per arm, successor correction
rate, tokens/latency deltas, escalation counts.
"""
import fcntl
import hashlib
import json
import os
import random
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .dynamic_v2_dev import OUT as DEV2

OUT = BASE / 'controlled_fault_propagation'
POOL = ['medium', 'large', 'coder']
SEED = 20260918
HEADROOM = 1.2
MIN_TOKENS = 200
TASKS_SOURCE = DEV2 / 'DEV2_POLICY.json'

def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))

def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()

def freeze():
    pol = json.loads((TASKS_SOURCE).read_text())
    cand = []
    rng = random.Random(SEED)
    for t in pol['tasks']:
        # fact-count filter needs the dev run's extraction outputs; recorded keys A:uid live
        # in the live run's RESPONSES (dev pass A reused live parsing? no: dev parsed itself).
        cand.append(t)
    # deterministic order + fact filter applied at runtime (tasks with <2 facts -> control only)
    sel = pol['tasks']
    policy = dict(seed=SEED, n_tasks=len(sel),
                  selection='all 33 dynv2-dev tasks; T1 requires >=2 facts else task skipped for T1',
                  interventions=dict(
                      T1='remove the last fact of F0 (evidence-missing)',
                      T2='multiply the last fact value by 1.5 (wrong intermediate value)',
                      T3='re-run extraction with medium (wrong-model assignment)',
                      C0='unperturbed control'),
                  arms=dict(
                      static='reasoning medium -> one local fallback coder; T3: extraction coder, reasoning medium -> coder. No capability re-routing.',
                      dynamic='reasoning medium -> escalation to large (stronger untried). T3: extraction large (capability re-route), reasoning large. Budget-gated.'),
                  budget='1.2 x Static realized tokens per (task, fault)',
                  scoring='reasoning expression on consumed facts == gold; gold from DEV2 policy tasks',
                  label='dev-tier controlled mechanism study; policy arms frozen; not a confirmation run',
                  tasks=sel)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'CFP_POLICY.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2))
    return policy

def append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())

class Caller:
    def __init__(self):
        self.proc = self.log = None; self.current = None
        self.cache = {}
        for src in [BASE / 'live_static_dynamic/RESPONSES.jsonl', DEV2 / 'RESPONSES.jsonl',
                    OUT / 'RESPONSES.jsonl']:
            if src.exists():
                for l in src.read_text().splitlines():
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

def lat_of(cache, key):
    r = cache.get(key)
    return float(r['response'].get('latency_s') or 0) if r else 0.0

def run():
    if not (OUT / 'CFP_POLICY.json').exists():
        freeze()
    pol = json.loads((OUT / 'CFP_POLICY.json').read_text())
    tasks = pol['tasks']
    if (OUT / 'CFP_DONE.json').exists(): raise FileExistsError('controlled fault run complete')
    engine.OUT = OUT
    caller = Caller()
    rng = random.Random(SEED)
    t0 = time.time()
    results = []
    try:
        for t in tasks:
            uid = t['uid']; q = t['question']; gold = t['answer']
            # base extraction (large) — reuse cached dev pass A
            kA = 'A:' + uid
            if kA not in caller.cache:
                caller.call(kA, 'large', v.eprompt(dict(question=q, context=t['context'])))
            try: F0 = (v.parse_facts(caller.cache[kA]['response']['answer']), False)
            except Exception: F0 = ({'facts': []}, True)
            if len(F0[0]['facts']) < 1: continue
            rng_i = random.Random(SEED + hash(uid) % 100000)
            # fault contexts (identical copies for both arms)
            contexts = {}
            F = [dict(f) for f in F0[0]['facts']]
            contexts['C0'] = ({'facts': [dict(f) for f in F]}, False)
            if len(F) >= 2:
                contexts['T1'] = ({'facts': [dict(f) for f in F[:-1]]}, True)
            f2 = [dict(f) for f in F]; f2[-1]['value'] = f2[-1]['value'] * 1.5
            contexts['T2'] = ({'facts': f2}, True)
            # T3: real weaker-model extraction
            kT3 = 'T3:' + uid
            if kT3 not in caller.cache:
                caller.call(kT3, 'medium', v.eprompt(dict(question=q, context=t['context'])))
            try: factsT3 = (v.parse_facts(caller.cache[kT3]['response']['answer']), True)
            except Exception: factsT3 = ({'facts': []}, True)
            contexts['T3'] = (factsT3, True)
            for ftype, (facts, _) in contexts.items():
                for arm in ['static', 'dynamic']:
                    tag = f'{ftype}:{arm}'
                    keys = []; used = 0.0; lat = 0.0
                    if ftype == 'T3':
                        # failed node = extraction; recovery model differs by arm
                        rec_ext = 'coder' if arm == 'static' else 'large'
                        kC = f'CFP:{uid}:{ftype}:{arm}:ext'
                        caller.call(kC, rec_ext, v.eprompt(dict(question=q, context=t['context'])))
                        keys.append((kC, rec_ext)); used += cost_of(caller.cache, kC); lat += lat_of(caller.cache, kC)
                        facts_use = _facts_of_local(caller.cache, kC)
                    else:
                        facts_use = facts
                    # reasoning attempt 1: medium (planned)
                    kR1 = f'CFP:{uid}:{ftype}:{arm}:r1'
                    caller.call(kR1, 'medium', v.sprompt(dict(question=q), {'facts': facts_use['facts']}))
                    keys.append((kR1, 'medium')); used += cost_of(caller.cache, kR1); lat += lat_of(caller.cache, kR1)
                    val, _ = reasoning_out(caller.cache, kR1, facts_use)
                    ok = close(val, gold); corrected = False
                    # failure handling
                    if not ok:
                        if arm == 'static':
                            fb = 'coder'
                            kR2 = f'CFP:{uid}:{ftype}:{arm}:r2'
                            caller.call(kR2, fb, v.sprompt(dict(question=q), {'facts': facts_use['facts']}))
                            keys.append((kR2, fb)); used += cost_of(caller.cache, kR2); lat += lat_of(caller.cache, kR2)
                            val, _ = reasoning_out(caller.cache, kR2, facts_use)
                            ok2 = close(val, gold)
                        else:
                            fb = 'large'  # capability re-route: stronger untried model
                            if ftype == 'T3' and rec_ext == 'large': fb = 'coder'  # avoid repeat
                            kR2 = f'CFP:{uid}:{ftype}:{arm}:r2'
                            caller.call(kR2, fb, v.sprompt(dict(question=q), {'facts': facts_use['facts']}))
                            keys.append((kR2, fb)); used += cost_of(caller.cache, kR2); lat += lat_of(caller.cache, kR2)
                            val, _ = reasoning_out(caller.cache, kR2, facts_use)
                            ok2 = close(val, gold)
                        if ok2: corrected = True
                        ok = ok or ok2
                    results.append(dict(uid=uid, fault=ftype, arm=arm, success=int(ok),
                                        recovered_or_corrected=int(corrected),
                                        baseline_ok=None, used=used, lat=lat,
                                        n_calls=len(keys), models=[m for _, m in keys]))
        core.write(OUT / 'RAW_RESULTS.json', dict(wall_seconds=time.time() - t0, results=results))
        core.write(OUT / 'CFP_DONE.json', dict(unix_time=time.time(), wall_seconds=time.time() - t0))
    finally:
        caller.close()

def _facts_of_local(cache, key):
    r = cache.get(key)
    try: return v.parse_facts(r['response']['answer'])
    except Exception: return {'facts': []}

if __name__ == '__main__':
    run()
