"""Verifier v1: step-level node verification vs the v0 final-answer checker.

Three steps per item: S1 fact check (values plausible for the question's
entities/scale, nothing essential missing), S2 formula check (expression
STRUCTURE matches the asked relationship - operands, operations, averaging
divisors, percent scaling; arithmetic ignored), S3 deterministic execution
consistency (claimed value equals extended-executor recomputation). Verdict =
pass iff all three pass. Two labeled testbeds: A = decompose-v1 chains (20,
ground truth = expression value vs gold), B = fresh verification nodes (40,
20 gold-accept / 20 perturbed-reject). v0 baseline (single final-answer
question) runs head-to-head on the same items. Model: medium (frozen).
"""
import argparse
import json

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
DEC = core.ROOT / 'static_dag_v0/dynamic_dag_v0/decompose_v1/RESULTS.json'
OUT = core.ROOT / 'static_dag_v0/verifier_v1'
MODEL = 'medium'
S1 = ('You are checking extracted financial facts for consistency. QUESTION: {q}\nFACTS: {facts}\n'
      'For each fact value: is it plausible for the entity/scale/period the question discusses, and is any fact '
      'essential to the implied arithmetic obviously missing or malformed? '
      'Answer ONLY JSON {{"fact_check":"pass"|"fail","suspect_index":<int or null>,"reason":"..."}}')
S2 = ('You are checking an arithmetic plan, NOT the arithmetic itself. QUESTION: {q}\nFACTS: {facts}\n'
      'EXPRESSION: {expr}\nDoes the expression structure match the relationship the question asks - right operands, '
      'right operations, correct divisor for averages, correct percent scaling, no needed quantity dropped? '
      'Answer ONLY JSON {{"formula_check":"pass"|"fail","issue":"..."}}')
V0 = ('Check this financial computation. QUESTION: {q}\nFACTS: {facts}\nEXPRESSION: {expr}\nVALUE: {val}\n'
      'Does it correctly answer the question using accurate facts? '
      'Answer ONLY JSON {{"verdict":"yes"|"no"}}.')


def steps_ok(model, q, facts, expr):
    r1 = engine.call_model(model, S1.format(q=q, facts=json.dumps(facts)))
    s1 = v.decode(r1['answer'])['fact_check'] == 'pass'
    r2 = engine.call_model(model, S2.format(q=q, facts=json.dumps(facts), expr=expr))
    s2 = v.decode(r2['answer'])['formula_check'] == 'pass'
    try:
        s3 = exec_calc(expr, facts) is not None
    except Exception:
        s3 = False
    return s1, s2, s3, s1 and s2 and s3


def run():
    if OUT.exists():
        raise FileExistsError('verifier_v1 already exists')
    OUT.mkdir()
    dec = json.loads(DEC.read_text())
    nodes = {n['node_id']: n for n in json.loads((SRC / 'NODES.json').read_text())}
    items = []
    for row in dec['rows']:
        n = nodes[row['node_id']]
        items.append(dict(testbed='A_decompose', node_id=row['node_id'], question=n['question'],
                          facts=n['gold_facts'], expr=row['failure_aware'].get('expr'),
                          claimed_value=None, truth=bool(row['failure_aware'].get('ok'))))
    ver_nodes = [n for n in nodes.values() if n['node_type'] == 'verification' and n['node_id'].endswith('vfpos')][:20]
    neg_nodes = [n for n in nodes.values() if n['node_type'] == 'verification' and n['node_id'].endswith('vfneg')][:20]
    for n in ver_nodes + neg_nodes:
        items.append(dict(testbed='B_verification', node_id=n['node_id'], question=n['question'],
                          facts=n['gold_facts'], expr=None, expect_accept=n['expect_accept'],
                          truth=bool(n['expect_accept'])))
        # expression for B: translate gold program literals to v-refs over its facts
        import re as _re
        index = {f['value']: i for i, f in enumerate(n['gold_facts']['facts'])}
        expr = n['program']
        for val, i in index.items():
            expr = _re.sub(r'(?<![\w.#])(-?' + _re.escape(str(val)) + r')(?![\w.])', f'v{i}', expr)
        items[-1]['expr'] = expr
        items[-1]['claimed_value'] = None
    engine.OUT = OUT
    import fcntl
    results = []
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        try:
            proc, log, _ = engine.start_model(MODEL)
            for it in items:
                q = it['question']
                facts = it['facts']
                expr = it['expr']
                if expr is None:
                    results.append(dict(**it, skipped='no expression'))
                    continue
                try:
                    val = exec_calc(expr, facts)
                except Exception:
                    val = None
                r0 = engine.call_model(MODEL, V0.format(q=q, facts=json.dumps(facts), expr=expr, val=val))
                try:
                    v0_verdict = v.decode(r0['answer'])['verdict'] == 'yes'
                except Exception:
                    v0_verdict = None
                s1, s2, s3, verdict = steps_ok(MODEL, q, facts, expr)
                results.append(dict(**it, computed_value=val, v0_pass=v0_verdict,
                                    s1_fact=s1, s2_formula=s2, s3_exec=s3, v1_pass=verdict,
                                    v1_correct=verdict == it['truth'], v0_correct=v0_verdict == it['truth']))
        finally:
            if proc is not None:
                engine.stop_model(proc, log)
    def agreement(rows, key):
        got = [r[key] for r in rows if r.get(key) is not None]
        truth = [r['truth'] for r in rows if r.get(key) is not None]
        return float(np.mean([g == t for g, t in zip(got, truth)])) if got else None
    per = {}
    for tb in ('A_decompose', 'B_verification'):
        rows = [r for r in results if r['testbed'] == tb and 'v1_pass' in r]
        per[tb] = dict(n=len(rows), v0_agreement=agreement(rows, 'v0_pass'), v1_agreement=agreement(rows, 'v1_pass'),
                       s1_pass_rate=float(np.mean([r['s1_fact'] for r in rows])),
                       s2_pass_rate=float(np.mean([r['s2_formula'] for r in rows])),
                       v1_on_true_items=float(np.mean([r['v1_pass'] for r in rows if r['truth']])) if any(r['truth'] for r in rows) else None,
                       v1_on_false_items=float(np.mean([r['v1_pass'] for r in rows if not r['truth']])) if any(not r['truth'] for r in rows) else None)
    summary = dict(per_testbed=per,
                   overall=dict(v0=agreement(results, 'v0_pass'), v1=agreement(results, 'v1_pass')),
                   reference_v0_on_A_from_decompose=7 / 20)
    core.write(OUT / 'RESULTS.json', dict(summary=summary, rows=results,
                                          steps='S1 fact check + S2 formula structure check + S3 deterministic '
                                                'execution consistency; verdict = AND',
                                          model=MODEL))
    print(json.dumps(summary, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
