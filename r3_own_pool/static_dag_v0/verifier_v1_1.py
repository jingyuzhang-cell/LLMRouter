"""Verifier v1.1: capability-aware model (coder) + tool-grounded gate + fixed testbeds.

Changes over v1: (a) testbed B expressions are #-expanded into nested form with
const_N translated to numbers; (b) the verifier runs on coder, the strongest
in-pool verification model from the node capability table; (c) gate is
S3 AND (S1 OR S2) - execution consistency required, at least one semantic
check must pass; (d) S1 fact check receives the report context, mirroring the
decompose-v1 lesson that evidence checking needs the source. v0 head-to-head
on the same items and same model. AND-gate results also reported.
"""
import argparse
import json
import re

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
DEC = core.ROOT / 'static_dag_v0/dynamic_dag_v0/decompose_v1/RESULTS.json'
OUT = core.ROOT / 'static_dag_v0/verifier_v1_1'
MODEL = 'coder'
CONSTS = {'const_1': '1', 'const_2': '2', 'const_3': '3', 'const_4': '4', 'const_5': '5',
          'const_10': '10', 'const_100': '100', 'const_1000': '1000'}
S1 = ('You are checking extracted financial facts against the source report. QUESTION: {q}\nREPORT:\n{ctx}\n'
      'FACTS: {facts}\nIs every fact value actually present in the report with the meaning the question implies '
      '(right entity, period, scale)? Answer ONLY JSON {{"fact_check":"pass"|"fail","suspect_index":<int or null>}}')
S2 = ('You are checking an arithmetic plan, NOT the arithmetic. QUESTION: {q}\nFACTS: {facts}\nEXPRESSION: {expr}\n'
      'Does the structure match the asked relationship (operands, operations, averaging divisor, percent scaling)? '
      'Answer ONLY JSON {{"formula_check":"pass"|"fail"}}')
V0 = ('Check this financial computation. QUESTION: {q}\nFACTS: {facts}\nEXPRESSION: {expr}\nVALUE: {val}\n'
      'Does it correctly answer the question using accurate facts? '
      'Answer ONLY JSON {{"verdict":"yes"|"no"}}.')


def expand(program):
    """add(100,200), divide(#0,3) -> divide(add(100,200),3); const_N -> N."""
    text = program
    for k, n in CONSTS.items():
        text = text.replace(k, n)
    steps = re.findall(r'(add|subtract|multiply|divide)\(([^()]*)\)', text)
    env = {}
    for i, (op, args) in enumerate(steps):
        env[i] = f'{op}({args})'
    changed = True
    while changed:
        changed = False
        for i in env:
            new = env[i]
            for j in range(len(env)):
                new = new.replace(f'#{j}', env[j])
            if new != env[i]:
                env[i] = new
                changed = True
    final = env.get(len(env) - 1) if env else None
    for sub in env.values():
        if sub == final:
            continue
    return final


def to_vref(expr, facts):
    out = expr
    for i, f in enumerate(sorted({f['value'] for f in facts['facts']}, key=lambda x: -len(str(x)))):
        out = re.sub(r'(?<![\w.#])(-?' + re.escape(str(f)) + r')(?![\w.])', f'v{i}', out)
    return out


def run():
    if OUT.exists():
        raise FileExistsError('verifier_v1_1 already exists')
    OUT.mkdir()
    dec = json.loads(DEC.read_text())
    nodes = {n['node_id']: n for n in json.loads((SRC / 'NODES.json').read_text())}
    tasks = {t['uid']: t for t in json.loads((SRC / 'TASKS.json').read_text())}
    items = []
    for row in dec['rows']:
        n = nodes[row['node_id']]
        if not row['failure_aware'].get('expr'):
            continue
        items.append(dict(testbed='A_decompose', node_id=row['node_id'], question=n['question'],
                          facts=n['gold_facts'], expr=row['failure_aware']['expr'],
                          truth=bool(row['failure_aware'].get('ok'))))
    pos = [n for n in nodes.values() if n['node_type'] == 'verification' and n['node_id'].endswith('vfpos')][:20]
    neg = [n for n in nodes.values() if n['node_type'] == 'verification' and n['node_id'].endswith('vfneg')][:20]
    for n in pos + neg:
        expr = to_vref(expand(n['program']), n['gold_facts'])
        items.append(dict(testbed='B_verification', node_id=n['node_id'], question=n['question'],
                          facts=n['gold_facts'], expr=expr, truth=bool(n['expect_accept'])))
    engine.OUT = OUT
    import fcntl
    results = []
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        try:
            proc, log, _ = engine.start_model(MODEL)
            for it in items:
                q, facts, expr = it['question'], it['facts'], it['expr']
                ctx = (tasks[[n for n in nodes.values() if n['node_id'] == it['node_id']][0]['task_uid']]
                       ['context'][:14000]) if it['testbed'] == 'B_verification' else ''
                try:
                    val = exec_calc(expr, facts)
                    s3 = val is not None
                except Exception:
                    val, s3 = None, False
                try:
                    r1 = engine.call_model(MODEL, S1.format(q=q, ctx=ctx, facts=json.dumps(facts)))
                    s1 = v.decode(r1['answer'])['fact_check'] == 'pass'
                except Exception:
                    s1 = False
                try:
                    r2 = engine.call_model(MODEL, S2.format(q=q, facts=json.dumps(facts), expr=expr))
                    s2 = v.decode(r2['answer'])['formula_check'] == 'pass'
                except Exception:
                    s2 = False
                try:
                    r0 = engine.call_model(MODEL, V0.format(q=q, facts=json.dumps(facts), expr=expr, val=val))
                    v0 = v.decode(r0['answer'])['verdict'] == 'yes'
                except Exception:
                    v0 = None
                gate_new = s3 and (s1 or s2)
                gate_and = s1 and s2 and s3
                results.append(dict(**it, computed_value=val, s1_fact=s1, s2_formula=s2, s3_exec=s3,
                                    v0_pass=v0, v11_pass=gate_new, and_pass=gate_and,
                                    v11_correct=gate_new == it['truth'], v0_correct=(v0 == it['truth'])))
        finally:
            if proc is not None:
                engine.stop_model(proc, log)
    per = {}
    for tb in ('A_decompose', 'B_verification'):
        rows = [r for r in results if r['testbed'] == tb]
        false, true = [r for r in rows if not r['truth']], [r for r in rows if r['truth']]

        def acc(key):
            return float(np.mean([r[key] == r['truth'] for r in rows]))
        per[tb] = dict(n=len(rows), accuracy_v11=acc('v11_pass'), accuracy_v0=acc('v0_pass'),
                       accuracy_and=acc('and_pass'),
                       error_recall_v11=float(np.mean([not r['v11_pass'] for r in false])),
                       error_recall_v0=float(np.mean([not r['v0_pass'] for r in false if r['v0_pass'] is not None])),
                       false_alarm_v11=float(np.mean([not r['v11_pass'] for r in true])),
                       s1_pass_rate=float(np.mean([r['s1_fact'] for r in rows])),
                       s2_pass_rate=float(np.mean([r['s2_formula'] for r in rows])))
    core.write(OUT / 'RESULTS.json', dict(per_testbed=per, rows=results, model=MODEL,
                                          gate='S3 AND (S1 OR S2); AND-gate reported separately',
                                          s1_context='report context for testbed B items'))
    print(json.dumps(per, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
