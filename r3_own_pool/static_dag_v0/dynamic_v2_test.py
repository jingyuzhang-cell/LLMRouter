"""One-shot Dynamic v2 test on the 48 frozen live tasks (rules frozen from the dev iteration).

Sequential single pass over the 48 tasks in policy order; Static and Dyn v1 results are
reused from the live RAW_TAIL (already recorded). Dynamic v2 diverges from Static only
through the hysteresis: the reasoning fallback stays at the frozen second best (coder)
until coder accumulates a failure in this run, then switches to the stronger untried
model (large); extraction fallback is always coder (v2 never switches to medium without
coder failure evidence). Budget per task = 1.2 x Static realized; escalations
budget-gated.
"""
import json
import os
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .recovery_matrix_v2_devset import BASE
from .live_static_dynamic import OUT as LIVE, close, reasoning_out
from .dynamic_v2_dev import HEADROOM
from .dynamic_v2_policy import (extraction_fallback_model, escalation_feasible,
                                reasoning_fallback_model, refresh_needed)

OUT = BASE / 'dynamic_v2_test'
POOL = ['medium', 'large', 'coder']

def append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())

def _cost(cache, key):
    r = cache.get(key)
    return float((r['response'].get('usage') or {}).get('total_tokens') or 0) if r else 0.0

def _facts_of(cache, key):
    r = cache.get(key)
    try: return v.parse_facts(r['response']['answer'])
    except Exception: return {'facts': []}

def run():
    pol = json.loads((LIVE / 'LIVE_POLICY.json').read_text())
    tasks = pol['tasks']
    live_raw = json.loads((LIVE / 'RAW_TAIL.json').read_text())
    if (OUT / 'TEST_DONE.json').exists(): raise FileExistsError('v2 test complete')
    OUT.mkdir(parents=True, exist_ok=True)
    engine.OUT = OUT
    cache = {}
    for src in [LIVE / 'RESPONSES.jsonl', OUT / 'RESPONSES.jsonl']:
        if src.exists():
            for l in src.read_text().splitlines():
                r = json.loads(l); cache[r['key']] = r
    proc = logm = None; current = None
    def call(key, model, prompt):
        nonlocal proc, logm, current
        if key in cache:
            r = cache[key]
            if r['response'].get('status') != 'delivered': raise RuntimeError('cached infra failure: ' + key)
            return r
        if model != current:
            if proc is not None: engine.stop_model(proc, logm); proc = logm = None
            proc, logm, _ = engine.start_model(model); current = model
        append(OUT / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
        resp = engine.call_model(model, prompt)
        rec = dict(key=key, model=model, response=resp); append(OUT / 'RESPONSES.jsonl', rec)
        cache[key] = rec
        if resp.get('status') != 'delivered': raise RuntimeError('Infrastructure failure: ' + key)
        return rec
    t0 = time.time()
    try:
        rows = []
        f_reasoning_coder = 0  # hysteresis counters: fallback failures observed so far
        f_reasoning_large = 0
        f_extraction_coder = 0
        for t in tasks:
            uid = t['uid']; sst = live_raw['static'][uid]
            budget = sst['used'] * HEADROOM
            keys = [('A:' + uid, 'large'), ('B:' + uid, 'medium')]
            ext_failed = any(k.startswith('C:static:') for k, _ in sst['keys'])
            if ext_failed:
                fb_ext = extraction_fallback_model(f_extraction_coder)
                keys.append(('C:static:' + uid, fb_ext))  # shared-policy extraction fallback (same prompt as static's)
                facts = _facts_of(cache, 'C:static:' + uid)
                factsB = _facts_of(cache, 'B:' + uid)
                if facts['facts'] == [] and fb_ext == 'coder': f_extraction_coder += 1
                if refresh_needed(facts, factsB):        # R3: refresh only on materially changed output
                    keys.append(('D:static:' + uid, 'medium'))  # identical refresh call: reuse
                else:
                    keys.append(('B:' + uid, 'medium'))  # R3: output unchanged -> keep Static assignment
            else:
                facts = _facts_of(cache, 'A:' + uid)
            used = sum(_cost(cache, k) for k, _ in keys)
            val, _ = reasoning_out(cache, keys[-1][0], facts)
            ok = close(val, t['answer']); last = keys[-1][0]
            if not ok:
                # hysteresis (frozen): fallback starts at coder; after coder accumulates a
                # failure it switches to the stronger untried large, and switches back only
                # if large also fails. Score(m) = rank(m) - gamma * failures(m).
                fb = reasoning_fallback_model(f_reasoning_coder, f_reasoning_large)
                kE = f'E_v2:{uid}'
                if not escalation_feasible(budget - used):
                    rows.append(dict(uid=uid, success=int(ok), skipped='budget', keys=keys, used=used, lat=0.0,
                                     budget=budget, over_budget=False, realloc=False, fb_model=None)); continue
                keys.append((kE, fb))
                call(kE, fb, v.sprompt(dict(question=t['question']), {'facts': facts['facts']}))
                val, _ = reasoning_out(cache, kE, facts)
                ok = close(val, t['answer']); last = kE
                if not ok:
                    f_reasoning_coder += (fb == 'coder'); f_reasoning_large += (fb == 'large')
            used = sum(_cost(cache, k) for k, _ in keys)
            rows.append(dict(uid=uid, success=int(ok), skipped=None, keys=keys, used=used,
                             lat=sum(_lat(cache, k) for k, _ in keys),
                             realloc=(last != 'B:' + uid and last != 'D:static:' + uid) or ext_failed,
                             fb_model=last, budget=budget, over_budget=used > budget + 1e-9))
        # static comparison rows from live raw
        for r in rows:
            sst = live_raw['static'][r['uid']]
            r['static_success'] = int(sst['ok']); r['static_used'] = sst['used']
        v1 = json.loads((BASE / 'live_static_dynamic/LIVE_ANALYSIS.json').read_text())
        n = len(rows)
        rep = dict(
            n=n, f_reasoning_coder_failures=f_reasoning_coder,
            static_Q=round(sum(r['static_success'] for r in rows) / n, 4),
            dynv2_Q=round(sum(r['success'] for r in rows) / n, 4),
            dynv1_Q=v1['A_main']['dynamic_Q'],
            static_C=round(sum(r['static_used'] for r in rows) / n, 1),
            dynv2_C=round(sum(r['used'] for r in rows) / n, 1),
            help=[r['uid'] for r in rows if r['static_success'] == 0 and r['success'] == 1],
            harm=[r['uid'] for r in rows if r['static_success'] == 1 and r['success'] == 0],
            budget_violation=round(sum(1 for r in rows if r['used'] > r['budget'] + 1e-9) / n, 4),
            budget_skipped=[r['uid'] for r in rows if r.get('skipped')],
            detail=rows)
        core.write(OUT / 'TEST_ANALYSIS.json', rep)
        core.write(OUT / 'TEST_DONE.json', dict(unix_time=time.time(), wall_seconds=time.time() - t0))
        print(json.dumps({k: v for k, v in rep.items() if k != 'detail'}, ensure_ascii=False, indent=2))
    finally:
        if proc is not None: engine.stop_model(proc, logm)

def _lat(cache, key):
    r = cache.get(key)
    return float(r['response'].get('latency_s') or 0) if r else 0.0

if __name__ == '__main__':
    run()
