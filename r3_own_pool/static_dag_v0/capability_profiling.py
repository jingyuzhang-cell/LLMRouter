"""Capability Profiling and Predictive Routing — data collection (frozen before calls).

~900 audited-unused MultiHiertt train questions x 3 models (medium/large/coder) x 2 nodes
(extraction with each model's own prompt; reasoning on that model's own extraction output),
recording Q (parsed/evaluated correctness), C (tokens), L (latency) per (question, model,
node). Same eligibility, prompts, and generation config as the fresh holdout pipeline.
GTE question embeddings computed for the predictive-routing stage. Checkpointed per call.
"""
import hashlib
import json
import os
import re
import time

import numpy as np

from . import core, node_benchmark_build as build, node_benchmark_collect as collect
from . import run as engine, tool_aware_v1 as v
from .fresh_static_prepare import DATA, OUT as FRESH
from .fresh_static_confirmation import nodes_for
from .recovery_matrix_v2_devset import BASE

OUT = BASE / 'capability_profiling'
POOL = ['medium', 'large', 'coder']
N_TASKS = 900
CTX_CHAR_LIMIT = 20000  # cheap pre-filter; exact fit re-checked via tokenizer below

def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()

def norm(q):
    return re.sub(r'\s+', ' ', q).strip().lower()

def freeze_tasks():
    audit = json.loads((FRESH / 'EXPOSURE_AUDIT.json').read_text())
    used = set(audit['used_uids'])
    fresh_used = {t['uid'] for t in json.loads((FRESH / 'TASKS.json').read_text())}
    used |= fresh_used
    allow = set(audit['candidate_uids']['train']) - used
    # exposure guard: exclude questions whose normalized text matches any historically-used uid
    allrows = []
    for split in ['train', 'dev', 'test']:
        p = DATA / (split + '.json')
        if p.exists(): allrows += json.loads(p.read_text())
    used_q = {norm(r['qa']['question']) for r in allrows if r['uid'] in used}
    rows = {r['uid']: r for r in json.loads((DATA / 'train.json').read_text())}
    cand = []
    seen_q = set()
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(engine.MODELS['medium']['path'], local_files_only=True)
    for uid in allow:
        r = rows.get(uid)
        if r is None: continue
        qa = r['qa']; prog = qa.get('program', '')
        if qa.get('question_type') != 'arithmetic' or prog.count('(') < 2: continue
        if any(op not in build.ALLOWED_OPS for op in re.findall(r'([a-z_]+)\(', prog)): continue
        try: answer = float(qa['answer'])
        except (ValueError, TypeError): continue
        if not (answer == answer and abs(answer) != float('inf')): continue
        task = dict(uid=uid, question=qa['question'], program=prog, answer=answer, context=v.context(r))
        nn = [n for n in nodes_for(task) if n['node_type'] in ('extraction', 'reasoning')]
        if {n['node_id'] for n in nn} != {f'{uid}:ex0', f'{uid}:ex1', f'{uid}:rs'}: continue
        prompts = [v.eprompt(dict(question=t2['question'], context=t2['context'])) for t2 in [task]]
        sizes = [len(tok.apply_chat_template([dict(role='user', content=p)], tokenize=True, add_generation_prompt=True)) for p in prompts]
        if sizes[0] + 512 > 8192: continue
        qn = norm(qa['question'])
        if qn in seen_q or qn in used_q: continue
        seen_q.add(qn)
        cand.append(task)
    if len(cand) > N_TASKS:
        cand = cand[:N_TASKS]
    assert len(cand) >= 300, f'only {len(cand)} eligible'
    pol = dict(n=len(cand), pool='mh audit candidate train, historically-unused, hash-ordered',
               eligibility='arithmetic, >=2 ops allowed, finite answer, fits 8192, nodes = ex0/ex1/rs',
               nodes_per_task=2, calls_per_model=2 * N_TASKS,
               tasks=sorted(cand, key=lambda t: sha('prof:' + t['uid'])))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'PROFILE_POLICY.json').write_text(json.dumps(pol, ensure_ascii=False, indent=2))
    return pol

def append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())

def run():
    import fcntl
    if not (OUT / 'PROFILE_POLICY.json').exists():
        freeze_tasks()
    pol = json.loads((OUT / 'PROFILE_POLICY.json').read_text())
    tasks = pol['tasks']
    if (OUT / 'COLLECT_DONE.json').exists(): raise FileExistsError('profiling collection complete')
    engine.OUT = OUT
    lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
    import fcntl as _f
    _f.flock(lock, _f.LOCK_EX | _f.LOCK_NB)
    cache = {}
    for src in [BASE / 'live_static_dynamic/RESPONSES.jsonl', OUT / 'RESPONSES.jsonl']:
        if src.exists():
            for l in src.read_text().splitlines():
                r = json.loads(l); cache[r['key']] = r
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
            if resp.get('status') != 'delivered':  # one retry for transient failures
                resp = engine.call_model(model, prompt)
            rec = dict(key=key, model=model, response=resp); append(OUT / 'RESPONSES.jsonl', rec)
            cache[key] = rec
            if resp.get('status') != 'delivered':
                append(OUT / 'INFRA_FAILURES.jsonl', dict(key=key, model=model))
                print('INFRA-FAIL (skipping):', key[:60], flush=True)
            return rec
        # ---- embeddings (GTE, one load) ----
        if not (OUT / 'PROFILE_EMB.npz').exists():
            from sentence_transformers import SentenceTransformer
            from .node_router_compare import GTE
            st = SentenceTransformer(GTE)
            qs = [t['question'] for t in tasks]
            emb = st.encode(qs, normalize_embeddings=True, batch_size=8, show_progress_bar=False)
            np.savez(OUT / 'PROFILE_EMB.npz', questions=np.array(qs), emb=np.array(emb))
            del st
            import torch, subprocess, time as _t
            torch.cuda.empty_cache()
            for _ in range(60):
                q = subprocess.run(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],capture_output=True,text=True)
                try:
                    if int(q.stdout.strip()) < 1000: break
                except ValueError: break
                _t.sleep(2)
        # ---- Pass per model: extraction(planned per model) then reasoning on own facts ----
        for m in POOL:
            for t in tasks:
                k = f'EXT:{m}:{t["uid"]}'
                if k not in cache:
                    call(k, m, v.eprompt(dict(question=t['question'], context=t['context'])))
        for m in POOL:
            for t in tasks:
                uid = t['uid']; k = f'RSN:{m}:{uid}'
                if k in cache: continue
                facts = v.parse_facts(cache[f'EXT:{m}:{uid}']['response']['answer']) if False else None
                r = cache[f'EXT:{m}:{uid}']
                try: facts = v.parse_facts(r['response']['answer'])
                except Exception: facts = {'facts': []}
                call(k, m, v.sprompt(dict(question=t['question']), {'facts': facts['facts']}))
        core.write(OUT / 'COLLECT_DONE.json', dict(unix_time=time.time(), wall_seconds=time.time() - t0, calls=len(cache)))
        print('profiling collection complete:', len(cache), 'calls,', round(time.time() - t0), 's')
    finally:
        if proc is not None: engine.stop_model(proc, logm)
        _f.flock(lock, _f.LOCK_UN); lock.close()

if __name__ == '__main__':
    run()
