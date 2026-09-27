"""Graph Forest v2 diagnostic (zero model calls): decompose verifier_accept=0/19.

graph_forest_v1 measured reuse economics (call −50%, token −91.4%) but
quality-at-verifier collapsed (verifier_accept=0/19). The v1 raw responses were
not persisted, so the recorded new_value cannot be re-derived from model output.
However every task's reasoning node stores the MultiHiertt GOLD program and gold
facts, so the exact expected value under the v1 follow-up modification
(fact[0] × 1.10) is derivable in closed form. This diagnostic:

 1. maps each gold program's numeric literals to fact indices (value matching,
    candidate enumeration arbitrated by reproducing the gold answer exactly);
 2. computes the exact expected follow-up value;
 3. classifies each v1 task:
      DEGENERATE  fact[0] unreferenced — modification cannot propagate, the
                  scenario itself is broken (v1 counted these as
                  responds_to_modification=True on float noise);
      V1_CORRECT  recorded new_value matches expected (verifier false reject);
      V1_DRIFT    recorded new_value deviates (verifier correctly rejected);
      MAPPING_FAILED  literal↔fact mapping could not reproduce gold answer;
 4. cross-tabs with the v1 verifier verdicts.

No GPU, no model server, pure post-processing of frozen artifacts.
"""
import json
import re
from fractions import Fraction
from itertools import product
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
SRC = ROOT / 'static_dag_v0/fresh_static_confirmation'
V1 = ROOT / 'static_dag_v0/graph_forest_v1'
OUT = ROOT / 'static_dag_v0/graph_forest_v2'

OPS = {'add': '+', 'subtract': '-', 'multiply': '*', 'divide': '/'}


def parse_program(prog):
    """MultiHiertt DSL -> [(op, [('num'|'ref'|'const', value), ...]), ...]."""
    stmts = []
    for part in prog.split('), '):
        part = part.rstrip(')').strip()
        m = re.match(r'([a-z_]+)\((.*)', part)
        op, argstr = m.group(1), m.group(2)
        args = []
        for a in argstr.split(','):
            a = a.strip()
            if not a:
                continue
            if a.startswith('#'):
                args.append(('ref', int(a[1:])))
            elif a.startswith('const_'):
                args.append(('const', Fraction(a[6:])))
            else:
                args.append(('num', Fraction(a)))
        stmts.append((op, args))
    return stmts


def eval_expr(expr, facts):
    env = {f'v{i}': Fraction(str(f['value'])) for i, f in enumerate(facts['facts'])}
    return eval(expr, {'__builtins__': {}}, env)


def build_expr(stmts, assign):
    """Render as parenthesized expression over v-indices; assign is (si,ai)->fi."""
    results = []
    for si, (op, args) in enumerate(stmts):
        if op not in OPS:
            return None
        terms = []
        for ai, (kind, val) in enumerate(args):
            if kind == 'ref':
                terms.append(f'({results[val]})')
            elif kind == 'const':
                terms.append(str(val))
            else:
                fi = assign.get((si, ai))
                if fi is None:
                    return None
                terms.append(f'v{fi}')
        if len(terms) == 1 and op == 'add':
            results.append(terms[0])
        else:
            results.append(f' {OPS[op]} '.join(f'({t})' for t in terms))
    return results[-1]


def gold_expression(node):
    """Return the gold program as a v-referencing expression, or None."""
    stmts = parse_program(node['program'])
    facts = node['gold_facts']
    vals = [Fraction(str(f['value'])) for f in facts['facts']]
    lits = [(si, ai, v) for si, (op, args) in enumerate(stmts)
            for ai, (k, v) in enumerate(args) if k == 'num']
    cand = [[fi for fi in range(len(vals)) if vals[fi] == val] for _, _, val in lits]
    if any(not c for c in cand):
        return None
    want = Fraction(str(node['answer']))
    for combo in product(*cand):
        assign = {(si, ai): fi for (si, ai, _), fi in zip(lits, combo)}
        expr = build_expr(stmts, assign)
        if expr is None:
            continue
        got = eval_expr(expr, facts)
        if abs(float(got - want)) <= max(1e-4, 1e-4 * abs(float(want))):
            return expr
    return None


def run():
    OUT.mkdir(exist_ok=False)
    v1 = json.loads((V1 / 'RESULTS.json').read_text())
    nodes = json.loads((SRC / 'NODES.json').read_text())
    rmap = {n['task_uid']: n for n in nodes if n['node_type'] == 'reasoning'}

    rows = []
    for r in v1['rows']:
        uid = r['task_uid']
        node = rmap[uid]
        rec = dict(task_uid=uid, program=node['program'], answer=node['answer'],
                   old_value=r.get('old_value'), v1_new=r.get('new_value'),
                   v1_responds=r.get('responds_to_modification'),
                   verifier_accept=r.get('verifier_accept'), executes=r.get('executes'))
        expr = gold_expression(node)
        if expr is None:
            rec.update(cls='MAPPING_FAILED')
            rows.append(rec)
            continue
        facts = json.loads(json.dumps(node['gold_facts']))
        facts['facts'][0]['value'] = float(Fraction(str(facts['facts'][0]['value'])) * Fraction(11, 10))
        expected = float(eval_expr(expr, facts))
        rec.update(expression=expr, expected_new=expected, fact0_referenced=bool(re.search(r'\bv0\b', expr)))
        if not rec['fact0_referenced']:
            rec.update(cls='DEGENERATE')
        elif not r.get('executes'):
            rec.update(cls='V1_EXEC_FAILED')
        elif abs(r['new_value'] - expected) <= max(1e-4, 1e-4 * abs(expected)):
            rec.update(cls='V1_CORRECT')
        else:
            rec.update(cls='V1_DRIFT',
                       rel_err=(r['new_value'] - expected) / abs(expected) if expected else float('inf'))
        rows.append(rec)

    cls = lambda c: [r for r in rows if r['cls'] == c]
    executed = [r for r in rows if r.get('executes')]
    rejected = [r for r in executed if r.get('verifier_accept') is False]
    drift = cls('V1_DRIFT')
    summary = dict(
        n_tasks=len(rows),
        mapping_failed=len(cls('MAPPING_FAILED')),
        degenerate=len(cls('DEGENERATE')),
        v1_exec_failed=len(cls('V1_EXEC_FAILED')),
        v1_correct=len(cls('V1_CORRECT')),
        v1_drift=len(drift),
        verifier=dict(rejected=len(rejected),
                      correct_rejects=len([r for r in rejected if r['cls'] == 'V1_DRIFT']),
                      false_rejects=len([r for r in rejected if r['cls'] == 'V1_CORRECT'])),
        quality_retention_exact=len(cls('V1_CORRECT')) / max(1, len(cls('V1_CORRECT')) + len(drift)),
        median_abs_rel_drift=sorted(abs(r['rel_err']) for r in drift)[len(drift) // 2] if drift else None,
    )
    (OUT / 'DIAGNOSTIC.json').write_text(json.dumps(
        dict(summary=summary, rows=rows,
             method='gold program mapped to v-references (enumeration arbitrated by exact gold-answer '
                    'reproduction); fact[0]×1.1 substituted; expected value in exact Fraction arithmetic; '
                    'zero model calls',
             inputs=[str(SRC / 'NODES.json'), str(V1 / 'RESULTS.json')]), indent=1))
    lines = ['# Graph Forest v2 Diagnostic (zero model calls)', '',
             f"- tasks: {summary['n_tasks']}  mapping_failed: {summary['mapping_failed']}",
             f"- DEGENERATE (fact[0] unreferenced by gold expression): {summary['degenerate']}",
             f"- V1_CORRECT (verifier false reject): {summary['v1_correct']}",
             f"- V1_DRIFT (verifier correct reject): {summary['v1_drift']}",
             f"- verifier: rejected={summary['verifier']['rejected']} "
             f"correct_rejects={summary['verifier']['correct_rejects']} "
             f"false_rejects={summary['verifier']['false_rejects']}",
             f"- exact quality retention among propagatable executed: {summary['quality_retention_exact']:.3f}",
             f"- median |rel_err| among drift: {summary['median_abs_rel_drift']}", '',
             '| task | class | expression | expected | v1_new | rel_err |', '|---|---|---|---|---|---|']
    for r in rows:
        lines.append(f"| {r['task_uid'][:8]} | {r['cls']} | {r.get('expression', '-')} | "
                     f"{r.get('expected_new', '-')} | {r.get('v1_new', '-')} | {r.get('rel_err', '-')} |")
    (OUT / 'DIAGNOSTIC.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    run()
