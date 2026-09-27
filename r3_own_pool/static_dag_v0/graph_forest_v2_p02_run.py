"""P0-2 runner: {A, B, C'} x {V0, V1D} on the fresh_static 96-task panel.

Real calls (~330): V1 repair retries, B regenerations, C' full reruns
(extraction on mutated context + reasoning). Arm A and all value/exec
computation happen in the analyzer (zero calls). C' pilot gate per PROTOCOL.
Generation/repair rules frozen in graph_forest_v2_p02/PROTOCOL.json.
"""
import fcntl
import json
import time
from pathlib import Path

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .graph_forest_v2_3x2 import repair_prompt
from .multidag_dynamic import parse_facts_safe

ROOT = core.ROOT
OUT = ROOT / 'static_dag_v0/graph_forest_v2_p02'
SRC = ROOT / 'static_dag_v0/fresh_static_confirmation'
POOL = ['medium', 'large', 'coder']
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
PILOT_N, PILOT_MIN = 10, 6


def _fmt(v):
    return f'{v * 1.10:g}'


def run():
    dry = json.loads((OUT / 'DRYRUN.json').read_text())
    rows = sorted([r for r in dry['fresh_rows'] if r['ok']], key=lambda r: r['uid'])
    nodes = json.loads((SRC / 'NODES.json').read_text())
    tasks = json.loads((SRC / 'TASKS.json').read_text())
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    tmap = {t['uid']: t for t in tasks}
    rs_node = {n['task_uid']: n for n in nodes if n['node_id'].endswith(':rs')}
    ex_node = {n['task_uid']: n for n in nodes if n['node_id'].endswith(':ex0')}

    def top_model(n):
        types = [1.0 if n['node_type'] == t else 0.0
                 for t in ['extraction', 'transformation', 'reasoning', 'verification']]
        x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
        u = x @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'] - \
            ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']
        return int(np.argmax(u))

    r_model = {r['uid']: r['model'] for r in rows}
    e_model = {r['uid']: POOL[top_model(ex_node[r['uid']])] for r in rows}

    engine.OUT = OUT
    cache, calls = {}, []
    path = OUT / 'RESPONSES.jsonl'
    if path.exists():
        for l in path.read_text().splitlines():
            rec = json.loads(l)
            cache[rec['key']] = rec

    def call(key, model, prompt):
        if key in cache:
            return cache[key]['response']
        import hashlib
        with (OUT / 'REQUESTS.jsonl').open('a') as f:
            f.write(json.dumps(dict(key=key, model=model,
                                    prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                                    unix_time=time.time())) + '\n')
        resp = engine.call_model(model, prompt)
        rec = dict(key=key, model=model, response=resp)
        with path.open('a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        cache[key] = rec
        calls.append(key)
        return resp

    def mutated_context(r):
        t = tmap[r['uid']]
        return t['context'].replace(r['variant'], _fmt(r['facts0']), 1)

    with (ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current, proc, log = None, None, None
        try:
            def ensure(model):
                nonlocal current, proc, log
                if model != current:
                    if proc is not None:
                        engine.stop_model(proc, log)
                    proc, log, _ = engine.start_model(model)
                    current = model

            def batched(jobs):
                out = {}
                for model in sorted({m for m, _, _ in jobs}):
                    ensure(model)
                    for m, key, prompt in jobs:
                        if m == model:
                            out[key] = call(key, model, prompt)
                return out

            # ---- phase 1: V1 repair retries (flagged nodes only) ----
            jobs = [(r['model'], f"p02:repair:{r['uid']}",
                     repair_prompt(rs_node[r['uid']]['question'], rs_node[r['uid']]['gold_facts'],
                                   r['expr'], r['flagged']))
                    for r in rows if r['flagged']]
            reps = batched(jobs)
            print(f'phase1 repairs: {len(reps)}', flush=True)

            # ---- phase 2: B regenerations (original question + modified facts) ----
            jobs = []
            for r in rows:
                facts = json.loads(json.dumps(rs_node[r['uid']]['gold_facts']))
                facts['facts'][0]['value'] = r['facts0'] * 1.10
                jobs.append((r['model'], f"p02:B:{r['uid']}",
                             v.sprompt(dict(question=rs_node[r['uid']]['question']), facts)))
            bs = batched(jobs)
            print(f'phase2 B: {len(bs)}', flush=True)

            # ---- phase 3: C' extraction with pilot gate ----
            def c_extract(r):
                t = tmap[r['uid']]
                return v.eprompt(dict(question=rs_node[r['uid']]['question'],
                                      context=mutated_context(r)))
            pilot = batched([(e_model[r['uid']], f"p02:C_e:{r['uid']}", c_extract(r))
                             for r in rows[:PILOT_N]])
            hits = 0
            for r in rows[:PILOT_N]:
                facts, _ = parse_facts_safe(pilot[f"p02:C_e:{r['uid']}"]['answer'])
                want = r['facts0'] * 1.10
                if any(abs(f['value'] - want) <= 1e-3 * max(1, abs(want))
                       for f in facts['facts']):
                    hits += 1
            print(f'pilot propagation: {hits}/{PILOT_N}', flush=True)
            if hits < PILOT_MIN:
                raise RuntimeError(f'PILOT GATE FAILED: source mutation propagated only '
                                   f'{hits}/{PILOT_N}; abort before full budget')
            rest = batched([(e_model[r['uid']], f"p02:C_e:{r['uid']}", c_extract(r))
                            for r in rows[PILOT_N:]])
            ces = {**pilot, **rest}
            print(f'phase3 C_e: {len(ces)}', flush=True)

            # ---- phase 4: C' reasoning on its own extracted facts ----
            jobs = []
            for r in rows:
                facts, _ = parse_facts_safe(ces[f"p02:C_e:{r['uid']}"]['answer'])
                jobs.append((r['model'], f"p02:C_r:{r['uid']}",
                             v.sprompt(dict(question=rs_node[r['uid']]['question']), facts)))
            crs = batched(jobs)
            core.write(OUT / 'RAW_KEYS.json', dict(
                new_calls=calls, pilot_hits=hits,
                keys=dict(repairs=sorted(reps), B=sorted(bs),
                          C_e=sorted(ces), C_r=sorted(crs))))
            print(json.dumps(dict(done=True, new_calls=len(calls), pilot_hits=hits)))
        finally:
            if proc is not None:
                engine.stop_model(proc, log)


if __name__ == '__main__':
    run()
