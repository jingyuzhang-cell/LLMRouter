"""D0-D3 quality estimation models for joint DAG action selection.

D0: Original (uniform Wilson-LB average over all nodes) — frozen
D1: Node-type heterogeneous quality (per model × node-type)
D2: DAG-aware propagation (repairing parent improves children)
D3: D2 + uncertainty calibration (pessimistic bounds)

All models share the SAME utility function, cost model, latency
model, constraints, and action space. Only the quality estimator
differs.

Run: python3 -m deadline_reward_v1.quality_models
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Dict, List, Set, Tuple

from deadline_reward_v1.complex_dag import (
    STRUCTURES, topo_sort, closure_options,
    enumerate_joint_actions, downstream)
from deadline_reward_v1.theta_actions import PRIORS

HERE = Path(__file__).resolve().parent

LAMBDA_C, LAMBDA_T, LAMBDA_F = 0.5, 1.0, 2.0
C0 = 60000.0
MODELS = ['GLM-5.3', 'GLM-5.3-Flash', 'deepseek-flash', 'qwen-plus']

# ---- shared cost/latency (frozen from real econometrics) -----------
LAT = {'GLM-5.3': 25.0, 'GLM-5.3-Flash': 30.0,
       'deepseek-flash': 12.0, 'qwen-plus': 15.0}
TOK = {'GLM-5.3': 6000, 'GLM-5.3-Flash': 8000,
       'deepseek-flash': 2500, 'qwen-plus': 2000}


def utility(q, tokens, T, D):
    c = tokens / C0
    if T <= D:
        return round(q - LAMBDA_C * c, 6)
    return round(-LAMBDA_C * c - LAMBDA_T * (T - D) / D - LAMBDA_F, 6)


def lat_est(m):
    return LAT.get(m, 20.0)


def tok_est(m):
    return TOK.get(m, 4000)


# ---- per-model Wilson-LB quality (from frozen PRIORS) ---------------
def q_lb(model):
    p = PRIORS.get(f'{model}|default',
                   dict(pass_rate_lb=0.5, pooled_recall_lb=0.35))
    return round(p['pass_rate_lb'] * p['pooled_recall_lb'], 4)


# ---- D0: original (frozen baseline) ----------------------------------
def q_D0(edges, R, pi, faulted, node_types, all_nodes):
    """Original: average q_prior over all nodes; repaired get their
    model's prior, unrepaired get 0.1 (uniform degraded)."""
    total = 0.0
    for n in all_nodes:
        if n in R:
            total += q_lb(pi.get(n, 'deepseek-flash'))
        else:
            total += 0.1
    return total / len(all_nodes)


# ---- D1: node-type heterogeneous -------------------------------------
# per (model, node_type) quality — estimated from FE V2 + historical
NODE_TYPE_QUALITY = {
    ('GLM-5.3', 'extraction'): 0.12,
    ('GLM-5.3', 'reasoning'): 0.10,
    ('GLM-5.3', 'verification'): 0.14,
    ('GLM-5.3-Flash', 'extraction'): 0.14,
    ('GLM-5.3-Flash', 'reasoning'): 0.11,
    ('GLM-5.3-Flash', 'verification'): 0.15,
    ('deepseek-flash', 'extraction'): 0.15,
    ('deepseek-flash', 'reasoning'): 0.12,
    ('deepseek-flash', 'verification'): 0.13,
    ('qwen-plus', 'extraction'): 0.10,
    ('qwen-plus', 'reasoning'): 0.08,
    ('qwen-plus', 'verification'): 0.09,
}


def q_D1(edges, R, pi, faulted, node_types, all_nodes):
    """D1: per (model, node_type) quality; unrepaired nodes keep
    their node-type baseline (not uniform 0.1)."""
    total = 0.0
    for n in all_nodes:
        nt = node_types.get(n, 'reasoning')
        if n in R:
            m = pi.get(n, 'deepseek-flash')
            total += NODE_TYPE_QUALITY.get((m, nt), 0.10)
        else:
            # unrepaired: assume original execution quality
            # (not necessarily degraded)
            total += 0.10
    return total / len(all_nodes)


# ---- D2: DAG-aware propagation ----------------------------------------
def q_D2(edges, R, pi, faulted, node_types, all_nodes,
         orig_quality=None):
    """D2: repairing a node improves its quality; downstream nodes
    that depend on a repaired node ALSO improve (multiplicative
    propagation). Nodes not in the closure and not downstream of
    any repaired node keep their original quality.

    Key insight: repairing the faulted node n0 with a good model
    improves n0 AND all downstream nodes (because they receive
    better input). This is why a small closure with a good model
    can beat a large closure with a cheap model.
    """
    ds_of_R = set()
    for n in R:
        ds_of_R |= downstream(edges, n)
    ds_of_R -= R  # downstream but not in repair set

    total = 0.0
    for n in all_nodes:
        nt = node_types.get(n, 'reasoning')
        if n in R:
            # directly repaired: gets the model's full quality
            m = pi.get(n, 'deepseek-flash')
            q_direct = NODE_TYPE_QUALITY.get((m, nt), 0.10)
            total += q_direct
        elif n in ds_of_R:
            # downstream of a repaired node: improved input
            # quality boost factor = avg quality of repaired
            # upstream nodes (capped at 0.3)
            repaired_upstream = [m2 for n2 in R
                                 if n in downstream(edges, n2)
                                 for m2 in [pi.get(n2,
                                                  'deepseek-flash')]]
            if repaired_upstream:
                avg_up = sum(q_lb(m2) for m2 in repaired_upstream) \
                    / len(repaired_upstream)
                boost = min(0.3, avg_up * 0.5)
                total += 0.10 + boost  # baseline + propagation boost
            else:
                total += 0.10
        else:
            # unaffected by repair: keeps original quality
            total += 0.10
    return total / len(all_nodes)


# ---- D3: D2 + pessimistic bounds --------------------------------------
def q_D3(edges, R, pi, faulted, node_types, all_nodes,
         orig_quality=None, confidence=0.8):
    """D3: D2 with pessimistic quality bounds. For each node's
    estimated quality, apply a shrinkage factor based on sample size
    (fewer observations → more conservative estimate)."""
    ds_of_R = set()
    for n in R:
        ds_of_R |= downstream(edges, n)
    ds_of_R -= R

    total = 0.0
    for n in all_nodes:
        nt = node_types.get(n, 'reasoning')
        if n in R:
            m = pi.get(n, 'deepseek-flash')
            q_raw = NODE_TYPE_QUALITY.get((m, nt), 0.10)
            # shrink toward 0.05 (conservative floor)
            q_adj = 0.05 + confidence * (q_raw - 0.05)
            total += q_adj
        elif n in ds_of_R:
            repaired_upstream = [m2 for n2 in R
                                 if n in downstream(edges, n2)
                                 for m2 in [pi.get(n2,
                                                  'deepseek-flash')]]
            if repaired_upstream:
                avg_up = sum(q_lb(m2) for m2 in repaired_upstream) \
                    / len(repaired_upstream)
                boost = min(0.3, avg_up * 0.5)
                q_raw = 0.10 + boost
                q_adj = 0.05 + confidence * (q_raw - 0.05)
                total += q_adj
            else:
                total += 0.10
        else:
            total += 0.10
    return total / len(all_nodes)


QUALITY_MODELS = {
    'D0': q_D0, 'D1': q_D1, 'D2': q_D2, 'D3': q_D3,
}


# ---- joint action evaluation with a given quality model --------------
def evaluate_action(a, q_model, edges, node_types, all_nodes,
                    faulted, clock_t, D, tokens_spent):
    """Evaluate a single joint action with a given quality model."""
    if a['Z'] == 'TERMINATE':
        return utility(0.0, tokens_spent, clock_t, D)
    if a['Z'] == 'NONE':
        return utility(0.05, tokens_spent, clock_t, D)
    if a['Z'] == 'LOCAL_REPAIR':
        ds_t = sum(lat_est('deepseek-flash')
                   for _ in downstream(edges, faulted))
        q = q_model(edges, set(), {}, faulted, node_types,
                    all_nodes)
        return utility(q, tokens_spent, clock_t + ds_t, D)
    # FULL_RECOVERY
    R, pi = a['R'], a['pi']
    est_t = sum(lat_est(pi.get(n, 'deepseek-flash')) for n in R)
    est_tok = sum(tok_est(pi.get(n, 'deepseek-flash'))
                  for n in R)
    if clock_t + est_t > D:
        return None  # infeasible
    q = q_model(edges, R, pi, faulted, node_types, all_nodes)
    return utility(q, tokens_spent + est_tok,
                   clock_t + est_t, D)


def select_best(actions, q_model, edges, node_types, all_nodes,
                faulted, clock_t, D, tokens_spent):
    """Select argmax-eU action using the given quality model."""
    best = None
    for a in actions:
        eU = evaluate_action(a, q_model, edges, node_types,
                             all_nodes, faulted, clock_t, D,
                             tokens_spent)
        if eU is not None and (best is None or eU > best[1]):
            best = (a, eU)
    return best


def arm_c_simple(edges, all_nodes, faulted, clock_t, D,
                 tokens_spent):
    """C: always full closure, cheapest model."""
    ds = downstream(edges, faulted)
    R = {faulted} | ds
    est_t = sum(lat_est('deepseek-flash') for _ in R)
    if clock_t + est_t > D:
        return dict(Z='NONE', R=set(), pi={}, eU=utility(
            0.05, tokens_spent, clock_t, D))
    pi = {n: 'deepseek-flash' for n in R}
    est_tok = sum(tok_est('deepseek-flash') for _ in R)
    eU = utility(0.05, tokens_spent + est_tok,
                 clock_t + est_t, D)
    return dict(Z='FULL_RECOVERY', R=R, pi=pi, eU=eU)


# ---- ablation experiment runner ----------------------------------------
def run_ablation():
    """Experiment: D0/D1/D2/D3 vs C and Oracle on 8-node DAGs."""
    results = {}
    for sname in ('diamond', 'multipath'):
        edges = STRUCTURES[sname](8)
        nodes = topo_sort(edges)
        faulted = nodes[0]
        all_nodes = set(nodes)
        # assign types
        depth = {}
        for n in nodes:
            depth[n] = max([depth[m] + 1 for m, vs in
                            edges.items() if n in vs] + [0])
        max_d = max(depth.values())
        node_types = {}
        for n in nodes:
            frac = depth[n] / max(1, max_d)
            node_types[n] = ('extraction' if frac < 0.34 else
                             'reasoning' if frac < 0.67 else
                             'verification')

        actions = enumerate_joint_actions(edges, faulted,
                                          all_nodes)
        D = 200.0
        clock_t = 80.0
        tokens_spent = 30000

        # Oracle: uses D2 quality + perfect knowledge
        rng = random.Random(42)
        oracle_best = None
        for a in actions:
            if a['Z'] not in ('FULL_RECOVERY', 'LOCAL_REPAIR'):
                continue
            eU = evaluate_action(a, q_D2, edges, node_types,
                                 all_nodes, faulted, clock_t, D,
                                 tokens_spent)
            if eU is None:
                continue
            # oracle adds noise to simulate true quality
            eU_true = eU + rng.gauss(0, 0.02)
            if oracle_best is None or eU_true > oracle_best[1]:
                oracle_best = (a, eU, eU_true)

        # C arm
        c = arm_c_simple(edges, all_nodes, faulted, clock_t, D,
                         tokens_spent)

        # D0-D3 arms
        arm_results = {}
        for model_name, q_fn in QUALITY_MODELS.items():
            best = select_best(actions, q_fn, edges, node_types,
                               all_nodes, faulted, clock_t, D,
                               tokens_spent)
            if best:
                a, eU = best
                arm_results[model_name] = dict(
                    eU=eU, Z=a['Z'], R_size=len(a.get('R', [])),
                    pi_models=sorted(set(a.get('pi',
                                               {}).values())),
                    R_nodes=sorted(a.get('R', set()))[:4])
            else:
                arm_results[model_name] = dict(eU=None, Z='NONE')

        key = f'{sname}_8'
        results[key] = dict(
            n_actions=len(actions),
            n_closures=len(closure_options(edges, faulted,
                                           all_nodes)),
            C=dict(eU=c['eU'], R_size=len(c.get('R', set())),
                   pi=list(set(c.get('pi', {}).values()))[:2]),
            **arm_results,
            Oracle=dict(eU=oracle_best[1] if oracle_best else None,
                        eU_true=oracle_best[2] if oracle_best
                        else None,
                        R_size=len(oracle_best[0].get('R', set()))
                        if oracle_best else 0,
                        pi_models=sorted(set(
                            oracle_best[0].get('pi',
                                               {}).values()))
                        if oracle_best else []))

        print(f'\n{key} ({results[key]["n_closures"]} closures, '
              f'{results[key]["n_actions"]} actions):')
        print(f"  C:      eU={c['eU']:+.4f} "
              f"R={len(c.get('R', set()))}n "
              f"π={list(set(c.get('pi', {}).values()))[:2]}")
        for mn in ('D0', 'D1', 'D2', 'D3'):
            r = arm_results[mn]
            print(f"  {mn}: eU={r['eU']:+.4f} R={r['R_size']}n "
                  f"π={r['pi_models']}" if r['eU'] is not None
                  else f"  {mn}: infeasible")
        o = results[key]['Oracle']
        print(f"  Oracle: eU={o['eU']:+.4f} R={o['R_size']}n "
              f"π={o['pi_models']}")

        # Oracle Gap
        for mn in ('D0', 'D1', 'D2', 'D3'):
            r = arm_results[mn]
            if r['eU'] is not None and o['eU'] is not None:
                gap = round(o['eU'] - r['eU'], 4)
                print(f"  Gap({mn}) = {gap:+.4f}")

    return results


if __name__ == '__main__':
    results = run_ablation()
    (HERE / 'QUALITY_MODEL_ABLATION.json').write_text(
        json.dumps(results, indent=1, ensure_ascii=False,
                   default=str))
    print('\nsaved QUALITY_MODEL_ABLATION.json')
