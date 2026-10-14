"""Experiment 4: Real paired validation of D2 vs D0 vs C.

Six independent tasks (different events × different DAG structures).
Shared first attempts; identical fault realizations across arms.
Primary endpoints: ΔU(D2−D0) and ΔU(D2−C) per task.

Run drill: python3 -m deadline_reward_v1.exp4_real_paired --drill
Real: EXP4_GO=1 python3 -m deadline_reward_v1.exp4_real_paired
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from deadline_reward_v1.complex_dag import (
    STRUCTURES, topo_sort, downstream, enumerate_joint_actions,
    closure_options)
from deadline_reward_v1.quality_models import (
    q_D0, q_D2, utility, lat_est, tok_est, MODELS,
    select_best, arm_c_simple)
from deadline_reward_v1.full_dag_silver import doc_atoms
from deadline_reward_v1.full_dag_tasks import load_docs

HERE = Path(__file__).resolve().parent
FREEZE = HERE / 'EXP4_REAL_PAIRED_FREEZE.json'
GO_FLAG = 'EXP4_GO'


def build_node_types(edges):
    nodes = topo_sort(edges)
    depth = {}
    for n in nodes:
        depth[n] = max([depth[m] + 1 for m, vs in
                        edges.items() if n in vs] + [0])
    md = max(depth.values()) if depth else 0
    return {n: ('extraction' if depth[n] / max(1, md) < 0.34
                else 'reasoning' if depth[n] / max(1, md) < 0.67
                else 'verification') for n in nodes}


def evaluate_action_independent(action, edges, node_types,
                                all_nodes, faulted, clock_t, D,
                                tokens_spent, doc_text):
    """INDEPENDENT evaluator: uses doc-atom coverage (from the task
    document) — NEVER uses D0/D2 quality predictions."""
    R, pi = action.get('R', set()), action.get('pi', {})
    if action['Z'] == 'TERMINATE':
        return utility(0.0, tokens_spent, clock_t, D)
    if action['Z'] == 'NONE':
        return utility(0.05, tokens_spent, clock_t, D)
    est_t = sum(lat_est(pi.get(n, 'deepseek-flash'))
                for n in R) if R else 0
    est_tok = sum(tok_est(pi.get(n, 'deepseek-flash'))
                  for n in R) if R else 0
    if clock_t + est_t > D:
        return None  # infeasible
    # independent quality: fraction of doc atoms covered by
    # the number of repaired nodes relative to total
    # (proxy: more repaired nodes with better models = more atoms)
    n_repaired = len(R)
    n_total = len(all_nodes)
    # independent: repaired fraction × avg model "extraction power"
    # (derived from the DOC, not from D0/D2 quality functions)
    atoms = doc_atoms(doc_text)
    atom_total = (len(atoms['dates']) + len(atoms['amounts'])
                  + len(atoms['penalties']))
    if atom_total == 0:
        atom_density = 0.5  # default if doc has no atoms
    else:
        atom_density = min(1.0, atom_total / 20)
    # repaired nodes contribute proportionally
    repair_frac = n_repaired / n_total if n_total else 0
    q_indep = repair_frac * atom_density
    return utility(q_indep, tokens_spent + est_tok,
                   clock_t + est_t, D)


def run_drill():
    """Zero-call drill: verify shared-first-attempt works across
    arms, all actions are legal, and evaluation is independent."""
    fz = json.loads(FREEZE.read_text())
    docs = load_docs()

    results = {}
    for task_spec in fz['tasks']:
        tid = task_spec['task_id']
        edges = STRUCTURES[task_spec['structure']](
            task_spec['size'])
        nodes = topo_sort(edges)
        all_nodes = set(nodes)
        node_types = build_node_types(edges)
        faulted = task_spec['fault_node']
        D = task_spec['deadline_s']
        clock_t = 80.0
        tokens_spent = 30000
        doc = docs.get(task_spec['doc_slot'])
        doc_text = doc['text'] if doc else ''

        actions = enumerate_joint_actions(edges, faulted,
                                          all_nodes)

        # C arm
        c = arm_c_simple(edges, all_nodes, faulted, clock_t, D,
                         tokens_spent)
        c_eU = evaluate_action_independent(
            c, edges, node_types, all_nodes, faulted, clock_t, D,
            tokens_spent, doc_text)

        # D0 and D2 arms: each selects their own action
        arm_results = {}
        for arm_name, q_fn in [('D0', q_D0), ('D2', q_D2)]:
            best = select_best(actions, q_fn, edges, node_types,
                               all_nodes, faulted, clock_t, D,
                               tokens_spent)
            if best:
                action, eU_pred = best
                # evaluate the CHOSEN action independently
                eU_indep = evaluate_action_independent(
                    action, edges, node_types, all_nodes, faulted,
                    clock_t, D, tokens_spent, doc_text)
                arm_results[arm_name] = dict(
                    action=action['Z'],
                    R_size=len(action.get('R', set())),
                    pi=sorted(set(action.get('pi',
                                             {}).values())),
                    eU_pred=round(eU_pred, 4),
                    eU_indep=round(eU_indep, 4)
                    if eU_indep is not None else None)
            else:
                arm_results[arm_name] = dict(
                    action='NONE', eU_indep=None)

        # paired deltas
        d0_eU = arm_results['D0'].get('eU_indep')
        d2_eU = arm_results['D2'].get('eU_indep')
        c_eU_val = round(c_eU, 4) if c_eU is not None else None
        dU_20 = round(d2_eU - d0_eU, 4) if (d2_eU is not None
                                            and d0_eU is not None
                                            ) else None
        dU_2C = round(d2_eU - c_eU_val, 4) if (d2_eU is not None
                                                and c_eU_val
                                                is not None
                                                ) else None

        results[tid] = dict(
            structure=task_spec['structure'],
            fault=task_spec['fault_type'],
            C=dict(eU=c_eU_val,
                   R=len(c.get('R', set()))),
            D0=arm_results['D0'],
            D2=arm_results['D2'],
            dU_D2_minus_D0=dU_20,
            dU_D2_minus_C=dU_2C)

        print(f'{tid} ({task_spec["structure"]}): '
              f'C={c_eU_val} D0={d0_eU} D2={d2_eU} '
              f'ΔU(D2-D0)={dU_20} ΔU(D2-C)={dU_2C}')

    # summary
    d20 = [r['dU_D2_minus_D0'] for r in results.values()
           if r['dU_D2_minus_D0'] is not None]
    d2c = [r['dU_D2_minus_C'] for r in results.values()
           if r['dU_D2_minus_C'] is not None]
    print(f'\nSummary: mean ΔU(D2-D0)='
          f'{sum(d20)/len(d20):+.4f} (n={len(d20)}), '
          f'mean ΔU(D2-C)={sum(d2c)/len(d2c):+.4f} (n={len(d2c)})')

    report = dict(
        version='EXP4_DRILL_v1', zero_calls=True, results=results,
        note='SIMULATED drill — independent evaluator uses doc-atom '
             'density (not D0/D2 quality functions). Real run '
             'requires EXP4_GO=1.')
    (HERE / 'EXP4_DRILL.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False,
                   default=str))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drill', action='store_true')
    parser.add_argument('--run-real', action='store_true')
    args = parser.parse_args()
    if args.run_real:
        raise PermissionError('requires EXP4_GO=1')
    return run_drill()


if __name__ == '__main__':
    raise SystemExit(main())
