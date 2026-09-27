"""P1b-audit: zero-call structural-signal audit of the 9 critical P0-2 tasks.

Groups (from graph_forest_v2_p02/RESULTS.json per_task):
  reuse_harm   stored correct, A0 wrong   (2)  -> update-aware validity failed
  regen_recover stored wrong, B correct   (3)  -> regeneration helped
  regen_harm   stored correct, B wrong    (4)  -> regeneration damaged
Question: do DEPLOYABLE structural signals (expression shape, fact-shape,
duplicate values, reference coverage) separate these from the bulk? Plus an
ORACLE-ONLY diagnostic: structural equivalence of stored vs gold expression
(random-perturbation equivalence) as the ceiling separator for T_reuse.
"""
import json
import random
from pathlib import Path

import numpy as np

from .decompose_v1 import exec_calc
from .graph_forest_v2_diagnostic import gold_expression

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'static_dag_v0/graph_forest_v2_p02'
SRC = ROOT / 'static_dag_v0/fresh_static_confirmation'


def feats(expr, facts):
    vals = [float(f['value']) for f in facts['facts']]
    import re
    ops = {o: expr.count(o) for o in '+-*/'}
    vrefs = set(re.findall(r'v(\d+)', expr))
    dup = len(vals) != len(set(vals))
    return dict(n_plus=ops['+'], n_minus=ops['-'], n_mul=ops['*'], n_div=ops['/'],
                n_vrefs=len(vrefs), n_facts=len(vals), refs_all=len(vrefs) >= len(vals),
                dup_fact_values=dup)


def structurally_equivalent(e1, e2, n_facts, k=24, seed=0):
    """Oracle-only: evaluate both on k random positive fact vectors."""
    rng = random.Random(seed)
    for _ in range(k):
        vals = [rng.uniform(0.5, 500.0) for _ in range(n_facts)]
        f = {'facts': [dict(value=v, evidence='x') for v in vals]}
        try:
            a, b = exec_calc(e1, f), exec_calc(e2, f)
        except Exception:
            return False
        if abs(a - b) > 1e-6 * max(1, abs(a)):
            return False
    return True


def run():
    res = json.loads((OUT / 'RESULTS.json').read_text())
    dry = json.loads((OUT / 'DRYRUN.json').read_text())
    rows = {r['uid']: r for r in dry['fresh_rows'] if r['ok']}
    nodes = json.loads((SRC / 'NODES.json').read_text())
    rs = {n['task_uid']: n for n in nodes if n['node_id'].endswith(':rs')}

    def correct(val, p):
        return val is not None and p['target'] is not None and \
            abs(val - p['target']) <= max(1e-4, 1e-4 * abs(p['target']))

    groups = dict(reuse_harm=[], regen_recover=[], regen_harm=[], other=[])
    for p in res['per_task']:
        uid = p['uid']
        r = rows[uid]
        node = rs[uid]
        gexpr = gold_expression(node)
        f = feats(r['expr'], node['gold_facts'])
        f['equiv_gold'] = bool(gexpr and structurally_equivalent(
            r['expr'], gexpr, len(node['gold_facts']['facts']))) if gexpr else None
        f['round1_correct'] = p['round1_correct']
        if p['round1_correct'] and not correct(p['A0'], p):
            groups['reuse_harm'].append((uid, f))
        elif (not p['round1_correct']) and correct(p['B'], p):
            groups['regen_recover'].append((uid, f))
        elif p['round1_correct'] and not correct(p['B'], p) and correct(p['A0'], p):
            groups['regen_harm'].append((uid, f))
        else:
            groups['other'].append((uid, f))

    def summarize(fs):
        if not fs:
            return {}
        out = {}
        for k in fs[0]:
            vals = [f[k] for f in fs if f[k] is not None]
            if vals and all(isinstance(v, (bool, int, float)) for v in vals):
                out[k] = round(float(np.mean(vals)), 3)
        return out

    out = {}
    for g, items in groups.items():
        out[g] = dict(n=len(items), mean_features=summarize([f for _, f in items]),
                      tasks=[dict(uid=u, **f) for u, f in items])
    # oracle separator check on stored-correct tasks
    sc = groups['reuse_harm'] + groups['regen_harm'] + \
         [x for x in groups['other'] if x[1]['round1_correct'] and x[1]['equiv_gold'] is not None]
    sep = dict(n_stored_correct=len(sc),
               equiv_gold=[f['equiv_gold'] for _, f in sc],
               harm_non_equiv=[f['equiv_gold'] for _, f in groups['reuse_harm']],
               dup_in_harm=[f['dup_fact_values'] for _, f in groups['reuse_harm']])
    (OUT / 'P1B_AUDIT.json').write_text(json.dumps(dict(groups=out, oracle_separator=sep), indent=1))
    print(json.dumps(dict(group_sizes={g: d['n'] for g, d in out.items()},
                          means={g: d['mean_features'] for g, d in out.items()},
                          oracle_separator=sep), indent=1))


if __name__ == '__main__':
    run()
