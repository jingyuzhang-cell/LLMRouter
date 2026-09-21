"""Evidence Reconstruction v2 (batched by model: 3 loads total).

Strategies per task:
  S0: Original chain (from cached capability_profiling responses)
  S1: Large re-extract + medium reasoning
  S2: Cross-model extraction (coder) + medium reasoning
  S3: Targeted Evidence Reconstruction + medium reasoning
"""
import fcntl, hashlib, json, math, os, random, re, time

from . import core, run as engine, tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .recovery_matrix_v2_audit import close

OUT = BASE / 'evidence_reconstruction_v2'
POOL = ['medium', 'large', 'coder']
SEED = 20260918
N_TASKS = 100

def _append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())

def _norm(q):
    return re.sub(r'\s+', ' ', q).strip().lower()

def _close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))

def _parse(key, cache):
    r = cache.get(key)
    if not r: return {'facts': []}
    try: return v.parse_facts(r['response']['answer'])
    except: return {'facts': []}

def freeze():
    from .fresh_static_prepare import DATA
    audit = json.loads((BASE / 'fresh_static_confirmation/EXPOSURE_AUDIT.json').read_text())
    used = set(audit['used_uids'])
    used |= {t['uid'] for t in json.loads((BASE / 'fresh_static_confirmation/TASKS.json').read_text())}
    used |= {t['uid'] for t in json.loads((CPROF / 'PROFILE_POLICY.json').read_text())['tasks']}
    allrows = []
    for split in ['train']:
        p = DATA / (split + '.json')
        if p.exists(): allrows += json.loads(p.read_text())
    used_q = {_norm(r['qa']['question']) for r in allrows if r['uid'] in used}
    from . import node_benchmark_build as build
    from .fresh_static_confirmation import nodes_for
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(engine.MODELS['medium']['path'], local_files_only=True)
    train = [r for r in json.loads((DATA / 'train.json').read_text()) if r['uid'] not in used]
    rng = random.Random(SEED); rng.shuffle(train)
    cand = []; seen_q = set()
    for r in train:
        uid = r['uid']; qa = r['qa']; q = _norm(qa['question'])
        if q in used_q or q in seen_q: continue
        prog = qa.get('program', '')
        if qa.get('question_type') != 'arithmetic' or prog.count('(') < 2: continue
        if any(op not in build.ALLOWED_OPS for op in re.findall(r'([a-z_]+)\(', prog)): continue
        try: answer = float(qa['answer'])
        except (ValueError, TypeError): continue
        if not math.isfinite(answer): continue
        task = dict(uid=uid, question=qa['question'], program=prog, answer=answer, context=v.context(r))
        nn = [n for n in nodes_for(task) if n['node_type'] in ('extraction', 'reasoning')]
        if {n['node_id'] for n in nn} != {uid + ':ex0', uid + ':ex1', uid + ':rs'}: continue
        prompt = v.eprompt(dict(question=task['question'], context=task['context']))
        size = len(tok.apply_chat_template([dict(role='user', content=prompt)], tokenize=True, add_generation_prompt=True))
        if size + 512 > 8192: continue
        cand.append(task)
        if len(cand) >= N_TASKS: break
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'ERV2_POLICY.json').write_text(json.dumps(dict(n=len(cand), tasks=cand), ensure_ascii=False, indent=2))
    return cand

def run():
    if not (OUT / 'ERV2_POLICY.json').exists():
        freeze()
    pol = json.loads((OUT / 'ERV2_POLICY.json').read_text())
    tasks = {t['uid']: t for t in pol['tasks']}
    if (OUT / 'ERV2_DONE.json').exists(): raise FileExistsError('done')
    engine.OUT = OUT
    cache = {}
    for src in [BASE / 'capability_profiling/RESPONSES.jsonl', OUT / 'RESPONSES.jsonl']:
        if src.exists():
            for l in src.read_text().splitlines():
                r = json.loads(l); cache[r['key']] = r
    lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    proc = logm = None; current = None
    t0 = time.time()
    calls_made = 0
    try:
        def call(key, model, prompt):
            nonlocal calls_made
            if key in cache:
                r = cache[key]
                if r['response'].get('status') != 'delivered': return r
                return r
            nonlocal proc, logm, current
            if model != current:
                if proc is not None: engine.stop_model(proc, logm); proc = logm = None
                proc, logm, _ = engine.start_model(model); current = model
            _append(OUT / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
            resp = engine.call_model(model, prompt)
            if resp.get('status') != 'delivered': resp = engine.call_model(model, prompt)
            rec = dict(key=key, model=model, response=resp)
            _append(OUT / 'RESPONSES.jsonl', rec); cache[key] = rec
            calls_made += 1
            return rec
        # ---- Stage 1 (large): original extractions + S1 re-extractions ----
        for t in tasks.values():
            uid = t['uid']; q = t['question']; ctx = t['context'][:14000]
            kA = 'A:' + uid
            if kA not in cache:
                call(kA, 'large', v.eprompt(dict(question=q, context=ctx)))
            k1 = 'S1_ext:' + uid
            if k1 not in cache:
                call(k1, 'large', v.eprompt(dict(question=q, context=ctx)))
        # ---- Stage 2 (coder): cross-model extractions ----
        for t in tasks.values():
            uid = t['uid']
            k2 = 'S2_ext:' + uid
            if k2 not in cache:
                call(k2, 'coder', v.eprompt(dict(question=t['question'], context=t['context'][:14000])))
        # ---- Stage 3 (medium): S3 targeted + all reasoning calls ----
        for t in tasks.values():
            uid = t['uid']; q = t['question']; gold = t['answer']
            ctx = t['context'][:14000]
            factsA = _parse_from_cache(cache, 'A:' + uid)
            f0_str = json.dumps([f['value'] for f in factsA['facts']])
            # S3: targeted evidence reconstruction
            k3 = 'S3_target:' + uid
            if k3 not in cache:
                R_TARGET = ('The following facts were extracted from a financial report, but they may be '
                            'incomplete for answering the question. Identify what specific quantities, '
                            'entities, or relationships are mentioned in the question but MISSING from the '
                            'current facts. Search the report ONLY for those missing items.\n'
                            'Return ONLY JSON {{"facts":[{{"value":number,"evidence":"source text"}}]}} '
                            'with ONLY newly found facts.\n'
                            'QUESTION: {q}\nCURRENT FACTS: {facts}\nREPORT:\n{ctx}')
                call(k3, 'medium', R_TARGET.format(q=q, facts=f0_str, ctx=ctx))
            # S0 baseline rsn
            k0 = 'S0_rsn:' + uid
            if k0 not in cache:
                call(k0, 'medium', v.sprompt(dict(question=q), {'facts': factsA['facts']}))
            # S1 rsn (on S1 facts)
            factsS1 = _parse_from_cache(cache, 'S1_ext:' + uid)
            k1r = 'S1_rsn:' + uid
            if k1r not in cache:
                call(k1r, 'medium', v.sprompt(dict(question=q), {'facts': factsS1['facts']}))
            # S2 rsn (on S2 facts)
            factsS2 = _parse_from_cache(cache, 'S2_ext:' + uid)
            k2r = 'S2_rsn:' + uid
            if k2r not in cache:
                call(k2r, 'medium', v.sprompt(dict(question=q), {'facts': factsS2['facts']}))
            # S3 rsn (on merged facts)
            merged = list(factsA['facts'])
            new_facts = _parse_from_cache(cache, 'S3_target:' + uid)
            existing = {round(f['value'], 6) for f in merged}
            for nf in new_facts['facts']:
                if round(nf['value'], 6) not in existing:
                    merged.append(dict(value=nf['value'], evidence='reconstructed'))
                    existing.add(round(nf['value'], 6))
            k3r = 'S3_rsn:' + uid
            if k3r not in cache:
                call(k3r, 'medium', v.sprompt(dict(question=q), {'facts': merged}))
        core.write(OUT / 'ERV2_DONE.json', dict(unix_time=time.time(), wall_seconds=time.time() - t0, calls=calls_made))
        print('ERV2 batched complete:', calls_made, 'calls in', round(time.time() - t0), 's')
    finally:
        if proc is not None: engine.stop_model(proc, logm)
        fcntl.flock(lock, fcntl.LOCK_UN); lock.close()

def _parse_from_cache(cache, key):
    r = cache.get(key)
    if not r: return {'facts': []}
    try: return v.parse_facts(r['response']['answer'])
    except: return {'facts': []}

if __name__ == '__main__':
    run()
