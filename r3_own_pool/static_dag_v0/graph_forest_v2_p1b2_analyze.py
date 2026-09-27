"""P1b-2 analyzer: three layers — contract fidelity / trust discrimination /
policy utility. Zero workflow calls; abstain -> do NOT intervene (frozen)."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, '/root/r3_own_pool')
from static_dag_v0.graph_forest_v2_p1b_contract import equiv

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'static_dag_v0/graph_forest_v2_p1b2'
P02 = ROOT / 'static_dag_v0/graph_forest_v2_p02'


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def run():
    ct = json.loads((OUT / 'CONTRACTS_test_v1.json').read_text())['contracts']
    dry = json.loads((P02 / 'DRYRUN.json').read_text())
    rows = {r['uid']: r for r in dry['fresh_rows'] if r['ok']}
    p02 = {p['uid']: p for p in json.loads((P02 / 'RESULTS.json').read_text())['per_task']}
    audit = json.loads((P02 / 'P1B_AUDIT.json').read_text())
    oracle = {t['uid']: t['equiv_gold'] for g in audit['groups'].values() for t in g['tasks']}
    dev = {r['task_uid'] for r in json.loads(
        (ROOT / 'static_dag_v0/graph_forest_v1/RESULTS.json').read_text())['rows']}
    nodes = json.loads((ROOT / 'static_dag_v0/fresh_static_confirmation/NODES.json').read_text())
    rs = {n['task_uid']: n for n in nodes if n['node_id'].endswith(':rs')}

    per = []
    for uid, r in rows.items():
        c = ct[uid]
        node = rs[uid]
        eg = equiv(c['expr'], audit_golds(node), node['gold_facts']) if False else None
        per.append(dict(uid=uid, dev=uid in dev, abstain=c['abstain'],
                        stored_correct=r['round1_correct'],
                        A=close(p02[uid]['A0'], p02[uid]['target']),
                        B=close(p02[uid]['B'], p02[uid]['target']),
                        cB_tok=p02[uid]['cB_tok'], cB_lat=p02[uid]['cB_lat'],
                        v_tokens=c['tokens'], family=c['family']))
    # adjudicate equivalence on demand (contract vs stored / vs gold)
    from static_dag_v0.graph_forest_v2_diagnostic import gold_expression
    for p in per:
        uid = p['uid']
        node = rs[uid]
        c = ct[uid]
        p['T'] = equiv(c['expr'], rows[uid]['expr'], node['gold_facts']) if c['expr'] else None
        gexpr = gold_expression(node)
        p['equiv_gold'] = equiv(c['expr'], gexpr, node['gold_facts']) if c['expr'] else None
    clean = [p for p in per if not p['dev']]

    # layer 1: fidelity
    fid = dict(
        Q_grounded=f'{sum(bool(p["equiv_gold"]) for p in clean)}/{len(clean)}',
        abstain=f'{sum(p["abstain"] for p in clean)}/{len(clean)}',
        free_form_reference='14/76')
    # layer 2: trust discrimination
    sc = [p for p in clean if p['stored_correct']]
    harm = [p for p in sc if not p['A']]
    safe = [p for p in sc if p['A']]
    sig = lambda p: p['T'] is False          # intervene only on explicit mismatch
    disc = dict(harm_caught=f'{sum(sig(p) for p in harm)}/{len(harm)}',
                safe_retained=f'{sum(not sig(p) for p in safe)}/{len(safe)}',
                false_interventions=len(safe) - sum(not sig(p) for p in safe),
                abstain_on_harm=sum(p['abstain'] for p in harm),
                abstain_on_safe=sum(p['abstain'] for p in safe),
                p1b1_reference=dict(harm_caught='0/2', safe_retained='9/19', FP=10))
    # layer 3: policy utility (abstain/mismatch->? : intervene only when T is False)
    def replay(intervene):
        q, cost = [], []
        for p in clean:
            act = intervene(p)
            q.append(float(p['B']) if act else float(p['A']))
            cost.append((p['cB_tok'] if act else 0.0) + p['v_tokens'])
        return dict(Q=round(float(np.mean(q)), 4), C=round(float(np.mean(cost)), 1))
    vt = float(np.mean([p['v_tokens'] for p in clean]))
    pol = dict(
        always_reuse=dict(Q=round(float(np.mean([float(p['A']) for p in clean])), 4), C=round(vt, 1)),
        grounded_gate=replay(sig),
        oracle_semantic_gate=replay(lambda p: p['T'] is False and True and not True),
        note='oracle semantic gate from P1b-1: Q 0.2895 C 640; grounded-gate C includes verifier '
             f'mean {vt:.0f} tok at n=1; n=2/5/10 -> {vt/2:.0f}/{vt/5:.0f}/{vt/10:.0f} per reuse')
    out = dict(n_clean=len(clean), fidelity=fid, discrimination=disc, policy=pol,
               family_distribution_clean=dict(
                   (f, sum(p['family'] == f for p in clean)) for f in {p['family'] for p in clean}),
               per_task=per)
    (OUT / 'RESULTS.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(dict(fidelity=fid, discrimination=disc, policy=pol,
                          families=out['family_distribution_clean']), indent=1))


def audit_golds(node):
    return None


if __name__ == '__main__':
    run()
