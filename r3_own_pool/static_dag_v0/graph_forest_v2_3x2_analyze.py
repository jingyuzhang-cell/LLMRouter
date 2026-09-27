"""Graph Forest v2 — 3x2 paired analysis (zero additional model calls).

Assembles the six-cell table from frozen artifacts plus gpu_3x2/RAW.json:
                follow-up strategy
write condition   A reuse   B regen   C full rerun
  V0              frozen    frozen    new (gpu)
  V1D deployable  repaired  = V0-B    = V0-C   (B/C ignore the forest)
  V1O oracle      repaired  = V0-B    = V0-C

Q = fraction of the 20 follow-ups whose value matches the exact expected
value (gold-program derivation, EVALUATION ONLY). Costs are follow-up-phase
calls/tokens plus write-phase repair calls where applicable; round-1 write
costs are common to all cells and reported separately.
"""
import json
from pathlib import Path

from .decompose_v1 import exec_calc

GF2 = Path('/root/r3_own_pool/static_dag_v0/graph_forest_v2')
SRC = Path('/root/r3_own_pool/static_dag_v0/fresh_static_confirmation')
V1 = Path('/root/r3_own_pool/static_dag_v0/graph_forest_v1')


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def run():
    diag = json.loads((GF2 / 'DIAGNOSTIC.json').read_text())
    expected = {r['task_uid']: r['expected_new'] for r in diag['rows'] if 'expected_new' in r}
    reuse = json.loads((GF2 / 'REUSE_ARM.json').read_text())
    rr = {r['task_uid']: r for r in reuse['rows']}
    v1 = json.loads((V1 / 'RESULTS.json').read_text())
    wv = json.loads((GF2 / 'WRITE_VALIDATION.json').read_text())
    wrows = {r['task_uid']: r for r in wv['rows']}
    raw = json.loads((GF2 / 'gpu_3x2' / 'RAW.json').read_text())
    repairs, arm_c = raw['repairs'], raw['arm_c']
    tasks = json.loads((SRC / 'TASKS.json').read_text())
    tmap = {t['uid']: t for t in tasks}
    nodes = json.loads((SRC / 'NODES.json').read_text())
    nmap = {n['task_uid']: n for n in nodes if n['node_id'].endswith(':rs')}
    uids = [r['task_uid'] for r in v1['rows']]

    def eval_on(expr, uid, modified):
        facts = json.loads(json.dumps(nmap[uid]['gold_facts']))
        if modified:
            facts['facts'][0]['value'] *= 1.10
        try:
            return exec_calc(expr, facts)
        except Exception:
            return None

    cells = {}
    # V0-A: frozen reuse arm
    cells[('V0', 'A')] = dict(Q=sum(bool(rr[u]['reuse_correct']) for u in uids), n=20,
                              fu_calls=0, fu_tokens=0.0, write_calls=0, write_tokens=0.0)
    # V0-B: frozen v1 regen arm (2 calls/task; 1 task exec-failed counted wrong)
    cells[('V0', 'B')] = dict(Q=sum(bool(rr[u]['v1_regen_correct']) for u in uids), n=20,
                              fu_calls=2 * 20, fu_tokens=sum(r.get('forest_tokens', 0) for r in v1['rows']),
                              write_calls=0, write_tokens=0.0)
    # V0-C: gpu full rerun
    cells[('V0', 'C')] = dict(Q=sum(bool(arm_c[u]['correct']) for u in uids), n=20,
                              fu_calls=sum(3 for u in uids),
                              fu_tokens=sum(arm_c[u]['tokens'] for u in uids),
                              write_calls=0, write_tokens=0.0)
    # V1D/V1O-A: repaired expressions re-executed on modified facts
    for arm, tag in [('V1D', 'V1D'), ('V1O', 'V1O')]:
        q, wtok, wcalls, harm, fixed = 0, 0.0, 0, 0, 0
        for u in uids:
            rep = repairs.get(f'{tag}:{u}')
            expr = wrows[u]['stored_expr']
            if rep is not None:
                wcalls += 1
                wtok += rep['tokens']
                if rep['exec']:
                    expr = rep['new_expr']
                orig_ok = close(eval_on(wrows[u]['stored_expr'], u, False), tmap[u]['answer'])
                new_ok = close(eval_on(expr, u, False), tmap[u]['answer'])
                if orig_ok and not new_ok:
                    harm += 1
                if not orig_ok and new_ok:
                    fixed += 1
            q += bool(close(eval_on(expr, u, True), expected[u]))
        cells[(tag, 'A')] = dict(Q=q, n=20, fu_calls=0, fu_tokens=0.0,
                                 write_calls=wcalls, write_tokens=wtok,
                                 repair_harm=harm, repair_fixed=fixed)
    # B and C are forest-ignoring: identical under any V (replicated rows)
    for tag in ['V1D', 'V1O']:
        cells[(tag, 'B')] = dict(cells[('V0', 'B')], replicated=True)
        cells[(tag, 'C')] = dict(cells[('V0', 'C')], replicated=True)

    table = {f'{k[0]}-{k[1]}': v for k, v in cells.items()}
    transitions = {}
    for key, rep in repairs.items():
        uid = key.split(':')[1]
        gold = tmap[uid]['answer']
        transitions[key] = dict(old_expr=rep['old_expr'], new_expr=rep['new_expr'],
                                changed=rep['changed'], flags=rep['flags'],
                                old_correct=close(eval_on(rep['old_expr'], uid, False), gold),
                                new_correct=close(eval_on(rep['new_expr'], uid, False), gold)
                                if rep['exec'] else None)
    hypotheses = dict(
        H1_write_validation_lifts_reuse_Q=dict(
            V0A=cells[('V0', 'A')]['Q'], V1D_A=cells[('V1D', 'A')]['Q'],
            V1O_A=cells[('V1O', 'A')]['Q']),
        H2_reuse_cost_dominance=dict(
            A_calls=0, B_calls=cells[('V0', 'B')]['fu_calls'],
            C_calls=cells[('V0', 'C')]['fu_calls'],
            A_tokens=0, B_tokens=cells[('V0', 'B')]['fu_tokens'],
            C_tokens=cells[('V0', 'C')]['fu_tokens']),
        H3_write_intervention_harm=dict(
            V1D_harm=cells[('V1D', 'A')].get('repair_harm'),
            V1D_fixed=cells[('V1D', 'A')].get('repair_fixed'),
            V1O_fixed=cells[('V1O', 'A')].get('repair_fixed')))
    out = dict(cells=table, repair_transitions=transitions, hypotheses=hypotheses)
    (GF2 / 'PAIRED_3X2.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(table, indent=1))
    print(json.dumps(out['hypotheses'], indent=1))


if __name__ == '__main__':
    run()
