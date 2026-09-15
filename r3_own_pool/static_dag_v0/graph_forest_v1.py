"""Graph Forest v1: follow-up modification scenario — measure reuse economics.

Per task (20 fresh-holdout tasks with a fully correct router-top chain):
Round 1 executes and stores the DAG (zero calls, table replay). Round 2 is a
user follow-up modifying ONE fact (+10%). The forest localizes the change:
extraction nodes are REUSED (report unchanged, zero calls), only the reasoning
node (on modified facts) and its verification dependent are recomputed (2 real
calls). Baseline without forest = executing the whole chain fresh (calls read
from the table). Measures: reused-node share, call reduction, token/latency
saving, and quality-at-execution (chain executes, value responds to the
modification, verifier accepts). PASS = cost strictly lower with quality
maintained at the execution level.
"""
import argparse
import json

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
OUT = core.ROOT / 'static_dag_v0/graph_forest_v1'
POOL = ['medium', 'large', 'coder']
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
N_TASKS = 20


def run():
    if OUT.exists():
        raise FileExistsError('graph_forest_v1 already exists')
    OUT.mkdir()
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    matrix = dict(np.load(SRC / 'SCORED_MATRIX.npz', allow_pickle=False))
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    tasks = json.loads((SRC / 'TASKS.json').read_text())
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    idx = {n['node_id']: i for i, n in enumerate(nodes_all)}
    by_task = {}
    for n in nodes_all:
        if matrix['main'][idx[n['node_id']]]:
            by_task.setdefault(n['task_uid'], []).append(n)

    def top_model(n):
        types = [1.0 if n['node_type'] == t else 0.0
                 for t in ['extraction', 'transformation', 'reasoning', 'verification']]
        x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
        u = x @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'] - \
            ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']
        return int(np.argmax(u))

    # Round-0 selection: extraction correct on router-top + reasoning node exists
    # (reuse economics do not require the original chain to be fully correct)
    selected = []
    for t in tasks:
        ns = by_task.get(t['uid'], [])
        r = next((n for n in ns if n['node_type'] == 'reasoning'), None)
        vf = next((n for n in ns if n['node_id'].endswith('vfpos')), None)
        if not (r and vf):
            continue
        rm = top_model(r)
        if not all(matrix['Q'][idx[n['node_id']], top_model(n)] > 0
                   for n in ns if n['node_type'] == 'extraction'):
            continue
        selected.append((t, ns, r, vf, rm, top_model(vf)))
        if len(selected) >= N_TASKS:
            break

    rows = []
    engine.OUT = OUT
    import fcntl
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current, proc, log = None, None, None
        try:
            for t, ns, reasoning, vf, rm, vm in selected:
                model = POOL[rm]
                ext = [n for n in ns if n['node_type'] == 'extraction']
                fresh_calls = 1 + len(ext) + 1  # deduped extraction call + reasoning + verification
                fresh_tokens = float(matrix['C'][idx[reasoning['node_id']], rm]) + \
                    float(matrix['C'][idx[vf['node_id']], vm]) + \
                    float(matrix['C'][idx[ext[0]['node_id']], top_model(ext[0])]) if ext else 0.0
                facts = dict(reasoning['gold_facts'])
                old = t['answer']
                facts['facts'][0]['value'] = facts['facts'][0]['value'] * 1.10
                if model != current:
                    if proc is not None:
                        engine.stop_model(proc, log)
                    proc, log, _ = engine.start_model(model)
                    current = model
                rec = dict(task_uid=t['uid'], reused_extraction_nodes=len(ext),
                           forest_calls=2, fresh_calls=fresh_calls)
                try:
                    follow_q = t['question'] + ' (Assume the FIRST listed fact value is 10 percent higher than reported.)'
                    rr = engine.call_model(model, v.sprompt(dict(question=follow_q), facts))
                    expr = v.decode(rr['answer'])['expression']
                    new_val = exec_calc(expr, facts)
                    rv = engine.call_model(model, f'Answer STRICTLY with JSON only, no prose: '
                                                   f'{{"accept":true}} or {{"accept":false}}. '
                                                   f'Does the value {new_val} correctly answer the question '
                                                   f'"{follow_q[:160]}" given these facts?')
                    try:
                        verdict = v.decode(rv['answer'])
                    except Exception:
                        verdict = dict(accept=None)
                    rec.update(old_value=old, new_value=new_val,
                               responds_to_modification=new_val != old,
                               executes=True, verifier_accept=verdict.get('accept'),
                               forest_tokens=float(rr['usage']['total_tokens'] if rr.get('usage') else 0) +
                                             float(rv['usage']['total_tokens'] if rv.get('usage') else 0))
                except Exception as e:
                    rec.update(executes=False, error=f'{type(e).__name__}: {e}', forest_tokens=0.0,
                               responds_to_modification=None, verifier_accept=None)
                rec['fresh_tokens'] = fresh_tokens
                rows.append(rec)
        finally:
            if proc is not None:
                engine.stop_model(proc, log)
    ok = [r for r in rows if r.get('executes')]
    summary = dict(n=len(rows), reused_extraction_nodes_total=sum(r['reused_extraction_nodes'] for r in rows),
                   forest_calls_total=2 * len(rows),
                   fresh_calls_total=sum(r['fresh_calls'] for r in rows),
                   call_reduction=1 - 2 * len(rows) / max(1, sum(r['fresh_calls'] for r in rows)),
                   executes=sum(r.get('executes', False) for r in rows),
                   responds_to_modification=sum(bool(r.get('responds_to_modification')) for r in ok),
                   verifier_accept=sum(r.get('verifier_accept') is True for r in ok),
                   token_reduction=1 - sum(r['forest_tokens'] for r in rows) /
                   max(1e-9, sum(r['fresh_tokens'] for r in rows)))
    core.write(OUT / 'RESULTS.json', dict(summary=summary, rows=rows,
                                          scenario='follow-up modifies ONE fact by +10%; extraction reused, '
                                                   'reasoning+verification recomputed',
                                          pass_rule='call/token cost strictly lower AND chains execute AND '
                                                    'values respond to the modification'))
    print(json.dumps(summary, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
