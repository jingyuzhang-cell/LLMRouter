"""Freeze the NEW 200-question confirmation set (before any router-method development on
the 900-question dev corpus) and collect 3 models x 2 nodes with the stable sequential
runner. Same eligibility, prompts, and propagated protocol as the 900-question corpus;
excludes every previously used uid (audit used, fresh-100, the 900 profiling tasks)."""
import hashlib
import json
import re
import time

from . import core, node_benchmark_build as build
from . import run as engine, tool_aware_v1 as v
from .fresh_static_prepare import DATA, OUT as FRESH
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL, append, norm
from .recovery_matrix_v2_audit import close

OUT = BASE / 'confirmation_200'
N_TASKS = 200

def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()

def freeze_tasks():
    audit = json.loads((FRESH / 'EXPOSURE_AUDIT.json').read_text())
    used = set(audit['used_uids'])
    used |= {t['uid'] for t in json.loads((FRESH / 'TASKS.json').read_text())}
    used |= {t['uid'] for t in json.loads((CPROF / 'PROFILE_POLICY.json').read_text())['tasks']}
    allrows = []
    for split in ['train', 'dev', 'test']:
        p = DATA / (split + '.json')
        if p.exists(): allrows += json.loads(p.read_text())
    used_q = {norm(r['qa']['question']) for r in allrows if r['uid'] in used}
    from .fresh_static_confirmation import nodes_for
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(engine.MODELS['medium']['path'], local_files_only=True)
    cand = []
    for uid in sorted(set(audit['candidate_uids']['train']) - used, key=lambda u: sha('conf:' + u)):
        r0 = next((r for r in allrows if r['uid'] == uid), None)
        if r0 is None: continue
        qa = r0['qa']; prog = qa.get('program', '')
        if qa.get('question_type') != 'arithmetic' or prog.count('(') < 2: continue
        if any(op not in build.ALLOWED_OPS for op in re.findall(r'([a-z_]+)\(', prog)): continue
        try: answer = float(qa['answer'])
        except (ValueError, TypeError): continue
        if not (answer == answer and abs(answer) != float('inf')): continue
        task = dict(uid=uid, question=qa['question'], program=prog, answer=answer, context=v.context(r0))
        nn = [n for n in nodes_for(task) if n['node_type'] in ('extraction', 'reasoning')]
        if {n['node_id'] for n in nn} != {f'{uid}:ex0', f'{uid}:ex1', f'{uid}:rs'}: continue
        prompt = v.eprompt(dict(question=task['question'], context=task['context']))
        size = len(tok.apply_chat_template([dict(role='user', content=prompt)], tokenize=True, add_generation_prompt=True))
        if size + 512 > 8192: continue
        qn = norm(qa['question'])
        if qn in used_q: continue
        used_q.add(qn)
        cand.append(task)
        if len(cand) >= N_TASKS: break
    assert len(cand) == N_TASKS, f'only {len(cand)} eligible'
    pol = dict(n=len(cand), frozen_before='router-method development on the 900-question dev corpus',
               protocol='identical to capability_profiling (propagated: reasoning consumes own extraction)',
               tasks=cand)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'CONF_POLICY.json').write_text(json.dumps(pol, ensure_ascii=False, indent=2))
    return pol

def run():
    import fcntl
    if not (OUT / 'CONF_POLICY.json').exists():
        freeze_tasks()
    tasks = json.loads((OUT / 'CONF_POLICY.json').read_text())['tasks']
    if (OUT / 'CONF_DONE.json').exists(): raise FileExistsError('confirmation collection complete')
    engine.OUT = OUT
    lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    cache = {}
    if (OUT / 'RESPONSES.jsonl').exists():
        for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l); cache[r['key']] = r
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
            resp = engine.call_model(model, prompt)
            if resp.get('status') != 'delivered':
                resp = engine.call_model(model, prompt)
            rec = dict(key=key, model=model, response=resp); append(OUT / 'RESPONSES.jsonl', rec)
            cache[key] = rec
            return rec
        for m in POOL:
            for t in tasks:
                k = f'EXT:{m}:{t["uid"]}'
                if k not in cache:
                    call(k, m, v.eprompt(dict(question=t['question'], context=t['context'])))
        for m in POOL:
            for t in tasks:
                uid = t['uid']; k = f'RSN:{m}:{uid}'
                if k in cache: continue
                r = cache[f'EXT:{m}:{uid}']
                try: facts = v.parse_facts(r['response']['answer'])
                except Exception: facts = {'facts': []}
                call(k, m, v.sprompt(dict(question=t['question']), {'facts': facts['facts']}))
        core.write(OUT / 'CONF_DONE.json', dict(unix_time=time.time(), wall_seconds=time.time() - t0, calls=len(cache)))
        print('confirmation collection complete:', len(cache), 'calls')
    finally:
        if proc is not None: engine.stop_model(proc, logm)
        fcntl.flock(lock, fcntl.LOCK_UN); lock.close()

if __name__ == '__main__':
    run()
