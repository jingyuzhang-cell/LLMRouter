"""P1b-3-B Step 1: Adapter-Recompile — ZERO calls (final trust-branch experiment, part 1).

Frozen adapter (train-derived): compile ALL percentage / percentage_change
family selections to their RAW-ratio forms (x100 base rate 2.4% on train; the
model's pct->x100 instinct is the convention violation). Keeps the model's
family choices and operand roles; overrides ONLY the scale convention at
compile time. Three-layer criteria per protocol:
  L1 fidelity Q_contract = P(E equiv E_gold)          (from 15/76)
  L2 trust discrimination: reuse-harm recall (0/2 -> stop if unchanged),
     reuse-safe retention (10/19)                     (DECISIVE layer)
  L3 policy Q/C/L replay of frozen P0-2 outcomes.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, '/root/r3_own_pool')
from static_dag_v0.decompose_v1 import exec_calc
from static_dag_v0.graph_forest_v2_diagnostic import gold_expression
from static_dag_v0.graph_forest_v2_p1b_contract import equiv

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'static_dag_v0/graph_forest_v2_p1b3'
P1B2 = ROOT / 'static_dag_v0/graph_forest_v2_p1b2'
P02 = ROOT / 'static_dag_v0/graph_forest_v2_p02'


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def _comp(tok):
    if isinstance(tok, str) and re.fullmatch(r'f\d+', tok):
        return f"v{tok[1:]}"
    if isinstance(tok, dict) and isinstance(tok.get('sum_of'), list):
        parts = [_comp(x) for x in tok['sum_of']]
        return '(' + ') + ('.join(parts) + ')' if all(parts) else None
    return None


def adapter_recompile(c):
    """Frozen adapter: pct-family -> raw-ratio compilation."""
    if not c:
        return None
    f = c.get('family')
    try:
        if f == 'percentage':
            p, w = _comp(c['part']), _comp(c['whole'])
            return f'({p}) / ({w})' if p and w else None
        if f == 'percentage_change':
            new, old = _comp(c['new']), _comp(c['old'])
            return f'(({new}) - ({old})) / ({old})' if new and old else None
    except Exception:
        return None
    return None


def evaluate(contracts_expr, ct, rows, rs, dev, p02, oracle, label):
    per = []
    for uid in rows:
        node = rs[uid]
        expr = contracts_expr.get(uid)
        gexpr = gold_expression(node)
        eg = equiv(expr, gexpr, node['gold_facts']) if expr else None
        es = equiv(expr, rows[uid]['expr'], node['gold_facts']) if expr else None
        per.append(dict(uid=uid, dev=uid in dev, expr=expr, equiv_gold=eg, equiv_stored=es,
                        stored_correct=rows[uid]['round1_correct'],
                        A=close(p02[uid]['A0'], p02[uid]['target']),
                        B=close(p02[uid]['B'], p02[uid]['target']),
                        cB_tok=p02[uid]['cB_tok'],
                        v_tokens=ct[uid]['tokens'] if uid in ct else 0.0))
    clean = [p for p in per if not p['dev']]
    sc = [p for p in clean if p['stored_correct']]
    harm = [p for p in sc if not p['A']]
    safe = [p for p in sc if p['A']]
    sig = lambda p: p['equiv_stored'] is False
    q, cost = [], []
    for p in clean:
        act = sig(p)
        q.append(float(p['B']) if act else float(p['A']))
        cost.append((p['cB_tok'] if act else 0.0) + p['v_tokens'])
    return dict(label=label,
                L1_fidelity=f'{sum(bool(p["equiv_gold"]) for p in clean)}/{len(clean)}',
                L2=dict(harm_caught=f'{sum(sig(p) for p in harm)}/{len(harm)}',
                        safe_retained=f'{sum(not sig(p) for p in safe)}/{len(safe)}',
                        false_interventions=len(safe) - sum(not sig(p) for p in safe)),
                L3_policy=dict(Q=round(float(np.mean(q)), 4), C=round(float(np.mean(cost)), 1)),
                per_task=per)


def run():
    OUT.mkdir(parents=True, exist_ok=False)
    ct = json.loads((P1B2 / 'CONTRACTS_test_v1.json').read_text())['contracts']
    dry = json.loads((P02 / 'DRYRUN.json').read_text())
    rows = {r['uid']: r for r in dry['fresh_rows'] if r['ok']}
    p02 = {p['uid']: p for p in json.loads((P02 / 'RESULTS.json').read_text())['per_task']}
    audit = json.loads((P02 / 'P1B_AUDIT.json').read_text())
    oracle = {t['uid']: t['equiv_gold'] for g in audit['groups'].values() for t in g['tasks']}
    dev = {r['task_uid'] for r in json.loads(
        (ROOT / 'static_dag_v0/graph_forest_v1/RESULTS.json').read_text())['rows']}
    nodes = json.loads((ROOT / 'static_dag_v0/fresh_static_confirmation/NODES.json').read_text())
    rs = {n['task_uid']: n for n in nodes if n['node_id'].endswith(':rs')}

    # original P1b-2 expressions
    orig = {uid: c['expr'] for uid, c in ct.items()}
    # adapter: recompile pct-family; keep others as-is
    adapted = {}
    for uid, c in ct.items():
        rec = adapter_recompile(c.get('contract'))
        if rec:
            try:
                exec_calc(rec, rs[uid]['gold_facts'])
                adapted[uid] = rec
            except Exception:
                adapted[uid] = c['expr']
        else:
            adapted[uid] = c['expr']
    r_orig = evaluate(orig, ct, rows, rs, dev, p02, oracle, 'P1b-2 original')
    r_adapt = evaluate(adapted, ct, rows, rs, dev, p02, oracle, 'Step1 adapter-recompile')
    out = dict(step='Step1 adapter-recompile (zero calls)',
               frozen_adapter='percentage -> part/whole ; percentage_change -> (new-old)/old ; '
                              'all other families unchanged (train x100 base rate 2.4%)',
               original={k: r_orig[k] for k in ('label', 'L1_fidelity', 'L2', 'L3_policy')},
               adapted={k: r_adapt[k] for k in ('label', 'L1_fidelity', 'L2', 'L3_policy')},
               adapted_per_task=r_adapt['per_task'])
    (OUT / 'RESULTS_STEP1.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(dict(original=out['original'], adapted=out['adapted']), indent=1))


if __name__ == '__main__':
    run()
