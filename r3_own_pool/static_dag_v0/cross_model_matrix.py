"""Cross-model Propagation Matrix: E_i -> R_j for all 9 pairs.
Freezes a 200-task stratified subset from the 900-question corpus, reuses all
existing extraction outputs (E_m for all 3 models), and collects the 6
off-diagonal reasoning calls (R_j on E_i's facts for i!=j). The 3 diagonal
cells already exist from prior collection.

Answers: does upstream extraction quality mask downstream reasoning complementarity?
If E_large->R_medium > E_medium->R_medium, medium's reasoning advantage is real
but its own extraction drags it down."""
import hashlib
import json
import re
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL, append
from .recovery_matrix_v2_audit import close

OUT = BASE / 'cross_model_matrix'
N_SUBSET = 200
SEED = 20260918

def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()

def freeze_subset():
    pol = json.loads((CPROF / 'PROFILE_POLICY.json').read_text())
    tasks = {t['uid']: t for t in pol['tasks']}
    resp = {}
    for l in (CPROF / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); resp[r['key']] = r
    # compute per-task Q for all 3 models to stratify
    strat = {'all_fail': [], 'headroom': [], 'large_win': [], 'nonlarge_win': []}
    for uid, t in tasks.items():
        qs = {}
        for m in POOL:
            ext = resp.get(f'EXT:{m}:{uid}'); rsn = resp.get(f'RSN:{m}:{uid}')
            if ext is None or rsn is None: qs[m] = None; continue
            try:
                facts = v.parse_facts(ext['response']['answer'])
                val = exec_calc(v.decode(rsn['response']['answer'])['expression'], facts)
                qs[m] = int(close(val, t['answer']))
            except Exception:
                qs[m] = 0
        if any(q is None for q in qs.values()): continue
        vals = list(qs.values())
        if all(x == 0 for x in vals): strat['all_fail'].append(uid)
        elif all(x == 1 for x in vals): strat['large_win'].append(uid)  # all correct
        elif len(set(vals)) > 1:
            winners = [m for m in POOL if qs[m] == 1]
            if 'large' in winners: strat['large_win'].append(uid)
            else: strat['nonlarge_win'].append(uid)
        else: strat['headroom'].append(uid)
    # proportional stratified sample
    rng = __import__('random').Random(SEED)
    total_valid = sum(len(v) for v in strat.values())
    subset = []
    for k, ids in strat.items():
        n_take = max(5, round(N_SUBSET * len(ids) / total_valid))
        rng.shuffle(ids)
        subset.extend(ids[:n_take])
    subset = subset[:N_SUBSET]
    pol_out = dict(n=len(subset), stratification={k: len(v) for k, v in strat.items()},
                   subset_uids=subset, note='stratified from 900-dev; extraction reused; 6 off-diagonal reasoning new')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'CROSS_MODEL_POLICY.json').write_text(json.dumps(pol_out, ensure_ascii=False, indent=2))
    return pol_out, tasks, resp

def run():
    import fcntl
    if not (OUT / 'CROSS_MODEL_POLICY.json').exists():
        pol, tasks, resp = freeze_subset()
    else:
        pol = json.loads((OUT / 'CROSS_MODEL_POLICY.json').read_text())
        tasks = {t['uid']: t for t in json.loads((CPROF / 'PROFILE_POLICY.json').read_text())['tasks']}
        resp = {}
        for l in (CPROF / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l); resp[r['key']] = r
    subset = pol['subset_uids']
    if (OUT / 'CROSS_MODEL_DONE.json').exists(): raise FileExistsError('cross-model complete')
    engine.OUT = OUT
    cache = {}
    if (OUT / 'RESPONSES.jsonl').exists():
        for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l); cache[r['key']] = r
    lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    proc = logm = None; current = None
    t0 = time.time()
    try:
        def call(key, model, prompt):
            if key in cache:
                r = cache[key]
                if r['response'].get('status') != 'delivered': return r
                return r
            nonlocal proc, logm, current
            if model != current:
                if proc is not None: engine.stop_model(proc, logm); proc = logm = None
                proc, logm, _ = engine.start_model(model); current = model
            append(OUT / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
            resp2 = engine.call_model(model, prompt)
            if resp2.get('status') != 'delivered':
                resp2 = engine.call_model(model, prompt)
            rec = dict(key=key, model=model, response=resp2); append(OUT / 'RESPONSES.jsonl', rec)
            cache[key] = rec
            return rec
        # collect 6 off-diagonal cells: R_j on E_i's facts (i != j)
        for ext_m in POOL:
            for rsn_m in POOL:
                if ext_m == rsn_m: continue  # diagonal already exists
                for uid in subset:
                    key = f'X:{ext_m}:{rsn_m}:{uid}'
                    if key in cache: continue
                    ext = resp.get(f'EXT:{ext_m}:{uid}')
                    if ext is None: continue
                    try: facts = v.parse_facts(ext['response']['answer'])
                    except Exception: facts = {'facts': []}
                    prompt = v.sprompt(dict(question=tasks[uid]['question']), {'facts': facts['facts']})
                    call(key, rsn_m, prompt)
        core.write(OUT / 'CROSS_MODEL_DONE.json', dict(unix_time=time.time(), wall_seconds=time.time() - t0, calls=len(cache)))
        print('cross-model matrix complete:', len(cache), 'calls')
    finally:
        if proc is not None: engine.stop_model(proc, logm)
        fcntl.flock(lock, fcntl.LOCK_UN); lock.close()

if __name__ == '__main__':
    run()
