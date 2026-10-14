"""Independent evaluation: separate quality PREDICTORS (D0-D3) from
quality TRUTH (independent oracle with a DIFFERENT function).

The truth model is deliberately constructed to be structurally
different from all predictor models — it uses a NON-MULTIPLICATIVE
propagation (additive with saturation) and a different quality
baseline per node type — to test whether D2's multiplicative
propagation assumption is the right STRUCTURE, not just the right
numbers.

Run: python3 -m deadline_reward_v1.independent_eval
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from deadline_reward_v1.complex_dag import (
    STRUCTURES, topo_sort, closure_options,
    enumerate_joint_actions, downstream)
from deadline_reward_v1.quality_models import (
    q_D0, q_D1, q_D2, q_D3, utility, lat_est, tok_est, MODELS,
    select_best, arm_c_simple, NODE_TYPE_QUALITY)

HERE = Path(__file__).resolve().parent
LAMBDA_C, LAMBDA_T, LAMBDA_F = 0.5, 1.0, 2.0
C0 = 60000.0


# ---- INDEPENDENT TRUTH QUALITY MODEL (separate from D0-D3) ----------
def q_truth_additive(edges, R, pi, faulted, node_types, all_nodes,
                     node_health=None):
    """INDEPENDENT truth: additive propagation with saturation.

    Key differences from D2's multiplicative model:
    1. ADDITIVE not multiplicative: downstream gain = min(cap,
       base_gain × depth_of_repair) not product of parent qualities
    2. SATURATION: downstream quality caps at 0.3 regardless of
       how good the repaired parent is
    3. ASYMMETRIC: repair gain differs by node depth (deeper =
       less gain from upstream repair)
    4. Includes INTERACTION: repairing both parent and child gives
       less than sum of individual repairs (diminishing returns)
    """
    if node_health is None:
        node_health = {n: 0.10 for n in all_nodes}

    ds_of_R = set()
    for n in R:
        ds_of_R |= downstream(edges, n)
    ds_of_R -= R

    # compute depth from nearest repaired ancestor
    def min_repair_depth(node):
        best = 999
        for r in R:
            if node in downstream(edges, r):
                # find shortest path r → node
                d = _path_len(edges, r, node)
                if d < best:
                    best = d
        return best

    total = 0.0
    for n in all_nodes:
        nt = node_types.get(n, 'reasoning')
        base = node_health.get(n, 0.10)
        if n in R:
            m = pi.get(n, 'deepseek-flash')
            q_repair = NODE_TYPE_QUALITY.get((m, nt), 0.10)
            # diminishing returns: if upstream also repaired, less gain
            up_repaired = any(u in R for u in edges
                              if n in edges.get(u, []))
            if up_repaired:
                q_repair = q_repair * 0.7  # interaction penalty
            total += q_repair
        elif n in ds_of_R:
            d = min_repair_depth(n)
            gain = 0.08 / max(1, d)  # additive, decays with depth
            total += min(0.30, base + gain)  # saturation cap
        else:
            total += base
    return total / len(all_nodes)


def _path_len(edges, src, dst):
    if src == dst:
        return 0
    visited = {src}
    queue = [(src, 0)]
    while queue:
        node, d = queue.pop(0)
        for nxt in edges.get(node, []):
            if nxt == dst:
                return d + 1
            if nxt not in visited:
                visited.add(nxt)
                queue.append((nxt, d + 1))
    return 999


def q_truth_no_prop(edges, R, pi, faulted, node_types, all_nodes,
                    node_health=None):
    """Independent truth: NO propagation — each node independently
    good or bad, repairing one doesn't help others."""
    total = 0.0
    for n in all_nodes:
        nt = node_types.get(n, 'reasoning')
        if n in R:
            m = pi.get(n, 'deepseek-flash')
            total += NODE_TYPE_QUALITY.get((m, nt), 0.10)
        else:
            total += 0.10
    return total / len(all_nodes)


def q_truth_full_prop(edges, R, pi, faulted, node_types, all_nodes,
                      node_health=None):
    """Independent truth: FULL propagation — repairing any node
    improves ALL others equally (strongest possible propagation)."""
    total = 0.0
    avg_repair_q = 0.0
    if R:
        avg_repair_q = sum(
            NODE_TYPE_QUALITY.get(
                (pi.get(n, 'deepseek-flash'),
                 node_types.get(n, 'reasoning')), 0.10)
            for n in R) / len(R)
    for n in all_nodes:
        nt = node_types.get(n, 'reasoning')
        if n in R:
            m = pi.get(n, 'deepseek-flash')
            total += NODE_TYPE_QUALITY.get((m, nt), 0.10)
        else:
            total += max(0.10, avg_repair_q * 0.8)  # strong spillover
    return total / len(all_nodes)


TRUTH_MODELS = {
    'additive_saturation': q_truth_additive,
    'no_propagation': q_truth_no_prop,
    'full_propagation': q_truth_full_prop,
}


# ---- experiment --------------------------------------------------------
def run_independent_eval():
    results = {}
    for sname in ('diamond', 'multipath', 'chain'):
        for size in (8, 12):
            edges = STRUCTURES[sname](size)
            nodes = topo_sort(edges)
            faulted = nodes[0]
            all_nodes = set(nodes)
            depth = {}
            for n in nodes:
                depth[n] = max([depth[m] + 1 for m, vs in
                                edges.items() if n in vs] + [0])
            max_d = max(depth.values())
            node_types = {n: ('extraction' if depth[n] / max(1, max_d)
                              < 0.34 else
                              'reasoning' if depth[n] / max(1, max_d)
                              < 0.67 else 'verification')
                          for n in nodes}

            actions = enumerate_joint_actions(edges, faulted,
                                              all_nodes)
            D = 200.0
            clock_t = 80.0
            tokens_spent = 30000

            key = f'{sname}_{size}'
            results[key] = dict(n_actions=len(actions))

            for truth_name, truth_fn in TRUTH_MODELS.items():
                # find Oracle under THIS truth model
                oracle_best = None
                for a in actions:
                    if a['Z'] not in ('FULL_RECOVERY',
                                      'LOCAL_REPAIR'):
                        continue
                    R, pi = a.get('R', set()), a.get('pi', {})
                    est_t = sum(lat_est(pi.get(n, 'deepseek-flash'))
                                for n in R) if R else 0
                    if clock_t + est_t > D:
                        continue
                    est_tok = sum(tok_est(pi.get(n, 'deepseek-flash'))
                                  for n in R) if R else 0
                    q_true = truth_fn(edges, R, pi, faulted,
                                      node_types, all_nodes)
                    eU_true = utility(q_true,
                                      tokens_spent + est_tok,
                                      clock_t + est_t, D)
                    if oracle_best is None or \
                            eU_true > oracle_best[1]:
                        oracle_best = (a, eU_true)

                # each predictor selects its OWN action
                arm_eU = {}
                for pred_name, pred_fn in [
                        ('D0', q_D0), ('D1', q_D1),
                        ('D2', q_D2), ('D3', q_D3)]:
                    best = select_best(actions, pred_fn, edges,
                                       node_types, all_nodes,
                                       faulted, clock_t, D,
                                       tokens_spent)
                    if best:
                        a, eU_pred = best
                        # evaluate the CHOSEN action under TRUTH
                        R, pi = a.get('R', set()), a.get('pi', {})
                        est_t = sum(lat_est(pi.get(n,
                                                   'deepseek-flash'))
                                    for n in R) if R else 0
                        est_tok = sum(tok_est(pi.get(
                            n, 'deepseek-flash'))
                            for n in R) if R else 0
                        q_true = truth_fn(edges, R, pi, faulted,
                                          node_types, all_nodes)
                        eU_true = utility(q_true,
                                          tokens_spent + est_tok,
                                          clock_t + est_t, D)
                        arm_eU[pred_name] = dict(
                            eU_pred=eU_pred, eU_true=eU_true,
                            R_size=len(R),
                            regret=round(
                                oracle_best[1] - eU_true, 4)
                            if oracle_best else None)
                    else:
                        arm_eU[pred_name] = dict(
                            eU_pred=None, eU_true=None, regret=None)

                # C arm
                c = arm_c_simple(edges, all_nodes, faulted,
                                 clock_t, D, tokens_spent)
                R_c = c.get('R', set())
                pi_c = c.get('pi', {})
                est_t = sum(lat_est(pi_c.get(n, 'deepseek-flash'))
                            for n in R_c) if R_c else 0
                est_tok = sum(tok_est(pi_c.get(n,
                                               'deepseek-flash'))
                              for n in R_c) if R_c else 0
                q_true = truth_fn(edges, R_c, pi_c, faulted,
                                  node_types, all_nodes)
                c_eU_true = utility(q_true, tokens_spent + est_tok,
                                    clock_t + est_t, D)

                results[key][truth_name] = dict(
                    oracle_eU=round(oracle_best[1], 4)
                    if oracle_best else None,
                    oracle_R=len(oracle_best[0].get('R', set()))
                    if oracle_best else 0,
                    C=dict(eU_true=round(c_eU_true, 4),
                           regret=round(oracle_best[1] - c_eU_true, 4)
                           if oracle_best else None),
                    **{k: dict(
                        eU_true=round(v['eU_true'], 4)
                        if v['eU_true'] is not None else None,
                        R=v['R_size'],
                        regret=v['regret'])
                       for k, v in arm_eU.items()})

    return results


def main():
    results = run_independent_eval()
    report = dict(
        version='INDEPENDENT_EVAL_v1', zero_calls=True,
        truth_models=list(TRUTH_MODELS),
        predictors=['D0', 'D1', 'D2', 'D3', 'C'],
        note='Truth models are STRUCTURALLY DIFFERENT from all '
             'predictors: additive_saturation (non-multiplicative, '
             'with interaction penalty), no_propagation (null), '
             'full_propagation (max spillover). Gap(D2)=0 from exp2 '
             'was TAUTOLOGICAL (Oracle shared D2 quality function); '
             'this evaluation uses INDEPENDENT truth.',
        results=results)
    (HERE / 'INDEPENDENT_EVAL.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False,
                   default=str))

    for key, data in results.items():
        print(f'\n{key} ({data["n_actions"]} actions):')
        for tn in TRUTH_MODELS:
            if tn not in data:
                continue
            d = data[tn]
            o = d['oracle_eU']
            print(f'  truth={tn}: Oracle eU={o} R={d["oracle_R"]}n')
            for arm in ('C', 'D0', 'D1', 'D2', 'D3'):
                if arm not in d:
                    continue
                r = d[arm]
                print(f"    {arm:3s}: eU_true={r['eU_true']:+.4f} "
                      f"R={r.get('R', '?')}n "
                      f"regret={r['regret']:+.4f}"
                      if r.get('eU_true') is not None
                      else f"    {arm}: infeasible")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
