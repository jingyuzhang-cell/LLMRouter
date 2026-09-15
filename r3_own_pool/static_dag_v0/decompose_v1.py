"""Decompose v1: failure-aware decomposition vs fixed split vs plain re-ask.

Diagnosis first: >=8/20 hard failures are average-type whose gold programs
need constants outside the v1 whitelist {0,1,100} - structurally inexpressible.
All arms therefore run under an EXTENDED executor (any rational constant;
operator set unchanged) so the comparison isolates the decomposition strategy:
(0) original language = 0 by construction, no calls;
(1) plain re-ask: same sprompt but constants allowed (cheapest fix);
(2) fixed 3-split v0 template under the extended executor;
(3) failure-aware chain: D1 aligns facts with the report context and states
    the asked relationship, D2 plans steps then the expression, D4 verifies
    semantically (diagnostic). Success = executed value ~= gold.
"""
import argparse
import ast
import json
import operator
import re
from fractions import Fraction

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
DYN = core.ROOT / 'static_dag_v0/dynamic_dag_v0'
OUT = DYN / 'decompose_v1'
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
SPROMPT_CONST = ('Choose the arithmetic reasoning needed to answer the financial question using the extracted '
                 'facts. Return ONLY JSON {"expression":"..."}. Reference fact values as v0,v1,... in their '
                 'listed order. Allowed operators: + - * / and parentheses. Small numeric constants such as '
                 '2 or 3 ARE permitted (e.g. dividing a sum by the number of years averages it). '
                 'Do not do the arithmetic.\nQUESTION: {q}\nFACTS: {facts}')
D1 = ('Align the bare financial facts with the report. For each fact state what it measures (entity, period, '
      'unit/scale), then state the single quantitative relationship the question asks for. Return ONLY JSON '
      '{{"facts":[{{"index":i,"meaning":"..."}}],"relationship":"..."}}.\nQUESTION: {q}\nREPORT:\n{ctx}\n'
      'FACT VALUES: {vals}')
D2 = ('Using the aligned facts and the relationship, first list the arithmetic steps, then write the single '
      'final expression over fact values v0,v1,.... Allowed operators: + - * / and parentheses; small numeric '
      'constants permitted (divide by the count to average). Return ONLY JSON '
      '{{"steps":["..."],"expression":"..."}}.\nQUESTION: {q}\nALIGNMENT: {align}')
D4 = ('Verify semantically: does the expression implement the stated relationship over the aligned facts? '
      'Return ONLY JSON {{"correct":true|false,"reason":"..."}}.\nRELATIONSHIP: {rel}\nEXPRESSION: {expr}')


def exec_calc(expression, facts):
    """Extended executor: any rational constant; operators and v-refs unchanged."""
    funcs = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
    tree = ast.parse(expression, mode='eval')
    def walk(n):
        if isinstance(n, ast.Expression):
            return walk(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return Fraction(str(n.value))
        if isinstance(n, ast.Name) and re.fullmatch(r'v[0-9]+', n.id):
            return Fraction(str(facts['facts'][int(n.id[1:])]['value']))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.Uadd)):
            return walk(n.operand) * (-1 if isinstance(n.op, ast.USub) else 1)
        if isinstance(n, ast.BinOp) and type(n.op) in funcs:
            return funcs[type(n.op)](walk(n.left), walk(n.right))
        raise ValueError('not allowed')
    return float(walk(tree))


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def top_model(dev, n, emb, qmap):
    types = [1.0 if n['node_type'] == t else 0.0
             for t in ['extraction', 'transformation', 'reasoning', 'verification']]
    x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
    u = x @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'] - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']
    return ['medium', 'large', 'coder'][int(np.argmax(u))]


def run():
    if OUT.exists():
        raise FileExistsError('decompose_v1 already exists')
    OUT.mkdir()
    dyn = json.loads((DYN / 'RESULTS.json').read_text())
    pool = dyn['decompose_pilot_pool'][:20]
    nodes = {n['node_id']: n for n in json.loads((SRC / 'NODES.json').read_text())}
    tasks = {t['uid']: t for t in json.loads((SRC / 'TASKS.json').read_text())}
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    engine.OUT = DYN
    import fcntl
    rows = []
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        current = None
        try:
            for nid in pool:
                n = nodes[nid]
                model = top_model(dev, n, emb, qmap)
                t = tasks[n['task_uid']]
                facts = n['gold_facts']
                vals = [f['value'] for f in facts['facts']]
                ctx = t['context'][:14000]
                row = dict(node_id=nid, model=model,
                           inexpressible_in_v1_language=bool(any(f'const_{k}' in n['program'] for k in (2, 3, 4, 5))
                                                            or re.search(r'[,(\s]\s*[2-9]\s*[,)]', n['program'])))
                if model != current:
                    if proc is not None:
                        engine.stop_model(proc, log)
                    proc, log, _ = engine.start_model(model)
                    current = model
                try:
                    r1 = engine.call_model(model, SPROMPT_CONST.format(q=n['question'], facts=json.dumps(facts)))
                    expr1 = v.decode(r1['answer'])['expression']
                    row['plain'] = dict(expr=expr1, ok=close(exec_calc(expr1, facts), n['answer']))
                except Exception as e:
                    row['plain'] = dict(error=f'{type(e).__name__}: {e}', ok=False)
                try:
                    ra = engine.call_model(model, D1.format(q=n['question'], ctx=ctx, vals=vals))
                    align = v.decode(ra['answer'])
                    rb = engine.call_model(model, D2.format(q=n['question'], align=json.dumps(align)))
                    d2 = v.decode(rb['answer'])
                    expr2 = d2['expression']
                    ok2 = close(exec_calc(expr2, facts), n['answer'])
                    rv = engine.call_model(model, D4.format(rel=align.get('relationship', ''), expr=expr2))
                    try:
                        verdict = v.decode(rv['answer'])
                    except Exception:
                        verdict = dict(correct=None)
                    row['failure_aware'] = dict(expr=expr2, ok=ok2, verdict=verdict,
                                                relationship=align.get('relationship'))
                except Exception as e:
                    row['failure_aware'] = dict(error=f'{type(e).__name__}: {e}', ok=False)
                rows.append(row)
        finally:
            if proc is not None:
                engine.stop_model(proc, log)
    plain_ok = sum(r['plain'].get('ok', False) for r in rows)
    aware_ok = sum(r['failure_aware'].get('ok', False) for r in rows)
    aware_verdict_agree = sum(1 for r in rows
                              if r['failure_aware'].get('verdict', {}).get('correct') is r['failure_aware'].get('ok'))
    summary = dict(n=len(rows),
                   calls_attempted=4 * len(rows),
                   no_decompose_v1_language=0,
                   fixed_v0_template_reference='0/10 (frozen result, original executor)',
                   plain_const_lang=plain_ok, failure_aware=aware_ok,
                   inexpressible_class=sum(r['inexpressible_in_v1_language'] for r in rows),
                   verdict_agrees_with_outcome=aware_verdict_agree)
    core.write(OUT / 'RESULTS.json', dict(summary=summary, rows=rows,
                                          arms=['no-decompose (v1 language): 0 by construction',
                                                'plain re-ask with constants allowed',
                                                'failure-aware D1(report alignment)->D2(steps+expr)->D4(verify)'],
                                          success_rule='extended-executor value ~= gold'))
    print(json.dumps(summary, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
