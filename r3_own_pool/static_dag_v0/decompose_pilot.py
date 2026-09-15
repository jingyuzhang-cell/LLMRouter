"""Decompose pilot: split hard-failed reasoning nodes into v2a->v2b->v2c sub-DAGs.

10 reasoning nodes where every pool model failed. Each becomes: v2a select
facts/outline steps -> v2b write expression over selected facts -> tool
executes -> v2c verify the computed answer. The sub-chain runs on the frozen
router's top model for that node (deployable choice). 30 calls total. Success
per node = tool-executed value matches gold AND v2c accepts with that answer.
"""
import argparse
import json
import time

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
DYN = core.ROOT / 'static_dag_v0/dynamic_dag_v0'
OUT = DYN / 'decompose_pilot'
A_PROMPT = ('Given the financial question and the candidate fact values, select the facts needed and outline '
            'the arithmetic steps to answer. Return ONLY JSON {{"steps":[{{"desc":"...","uses_facts":[fact indices]}}]}}.\n'
            'QUESTION: {q}\nFACTS: {facts}')
B_PROMPT = ('Using only the selected facts and steps, write the single arithmetic expression that answers the '
            'question. Return ONLY JSON {{"expression":"..."}} referencing fact values as v0,v1,... in listed '
            'order. Allowed operators: + - * / and parentheses; numeric constants 0,1,100 only.\n'
            'QUESTION: {q}\nSTEPS: {steps}')
C_PROMPT = ('Check this financial answer. Given the question, facts, expression and its computed value, does it '
            'correctly answer the question? Return ONLY JSON {{"accept":true|false,"final_answer":number}}.\n'
            'QUESTION: {q}\nFACTS: {facts}\nEXPRESSION: {expr}\nVALUE: {value}')


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def run():
    if OUT.exists():
        raise FileExistsError('decompose pilot already exists')
    dyn = json.loads((DYN / 'RESULTS.json').read_text())
    candidates = dyn['decompose_pilot_pool'][:10]
    nodes = {n['node_id']: n for n in json.loads((SRC / 'NODES.json').read_text())}
    matrix = dict(np.load(SRC / 'SCORED_MATRIX.npz', allow_pickle=False))
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    ids = [n['node_id'] for n in nodes.values()]
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    rows = []
    for nid in candidates:
        n = nodes[nid]
        i = ids.index(nid)
        types = [1.0 if n['node_type'] == t else 0.0
                 for t in ['extraction', 'transformation', 'reasoning', 'verification']]
        x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
        u = x @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'] - \
            0.05 / 1000 * dev['mean_C'] - 0.05 / 10 * dev['mean_L']
        rows.append(dict(node=n, pick=['medium', 'large', 'coder'][int(np.argmax(u))]))
    OUT.mkdir()
    by_model = {}
    for r in rows:
        by_model.setdefault(r['pick'], []).append(r)
    results = []
    engine.OUT = DYN
    import fcntl
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        try:
            for model, group in by_model.items():
                proc, log, _ = engine.start_model(model)
                for r in group:
                    n = r['node']
                    facts = n['gold_facts']
                    trace = dict(node_id=n['node_id'], model=model, sub_nodes=[])
                    try:
                        ra = engine.call_model(model, A_PROMPT.format(q=n['question'], facts=json.dumps(facts)))
                        steps = v.decode(ra['answer'])
                        trace['sub_nodes'].append(dict(stage='v2a_select', status=ra['status'], out=steps))
                        rb = engine.call_model(model, B_PROMPT.format(q=n['question'], steps=json.dumps(steps)))
                        expression = v.decode(rb['answer'])['expression']
                        value = v.calculate(expression, facts)
                        trace['sub_nodes'].append(dict(stage='v2b_expression', status=rb['status'],
                                                       out=expression, tool_value=value))
                        rc = engine.call_model(model, C_PROMPT.format(
                            q=n['question'], facts=json.dumps(facts), expr=expression, value=value))
                        verdict = v.decode(rc['answer'])
                        trace['sub_nodes'].append(dict(stage='v2c_verify', status=rc['status'], out=verdict))
                        trace['decompose_success'] = bool(
                            close(value, n['answer']) and verdict.get('accept') is True
                            and close(verdict.get('final_answer'), n['answer']))
                        trace['expression_correct'] = bool(close(value, n['answer']))
                    except Exception as e:
                        trace['error'] = f'{type(e).__name__}: {e}'
                        trace['decompose_success'] = False
                        trace['expression_correct'] = False
                    results.append(trace)
                engine.stop_model(proc, log)
                proc = log = None
        finally:
            if proc is not None:
                engine.stop_model(proc, log)
    summary = dict(n=len(results), calls=3 * len(results),
                   decompose_success=sum(r['decompose_success'] for r in results),
                   expression_correct=sum(r.get('expression_correct', False) for r in results),
                   models={m: len(g) for m, g in by_model.items()})
    core.write(OUT / 'RESULTS.json', dict(summary=summary, rows=results,
                                          prompts=dict(a=A_PROMPT, b=B_PROMPT, c=C_PROMPT),
                                          success_rule='tool value==gold AND v2c accept AND v2c answer==gold'))
    print(json.dumps(summary, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
