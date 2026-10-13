"""DD-Online decision method v2 (zero calls).

Closes the three declared gaps of the round-6e964ec differentiation
report, in the direction the operator designated (improve the DECISION
METHOD, do not add engineering features):

  1. closure pricing: repairing a node with STALE downstream must pay
     the re-execution of that closure (tokens AND latency) in BOTH
     branches — an unpriced closure made DD over-optimistic on
     delayed faults (S4/S5).
  2. task-level quality propagation: E[terminal q] = mean over the
     four nodes of pass x recall priors, with the faulted node's slot
     replaced by the candidate (success branch) or the fallback
     (failure branch). No per-node silver exists for tl/er/xc, so the
     recall prior is shared — the NODE-TYPE differentiation enters
     through latency (real, per node type x model) and closure size.
  3. per-node-type latency priors (FULL_DAG_NODE_PRIORS.json, 68 real
     historical calls): candidate and closure time estimates use the
     (node_type, model) median instead of a flat reservation.

Decision inputs remain: DEV priors, observable node feedback, DAG
state, remaining budget, remaining deadline, theta support table.
Never same-task candidate outcomes. Reward coefficients unchanged.

Used by full_dag_executor.RealRunner (real run) and dd_vs_fixed_diff
(offline states). The protocol dry-run keeps its simpler rule.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from deadline_reward_v1 import theta_actions
from deadline_reward_v1.theta_actions import (
    DEFAULT_THETA, PRIORS, UNINFORMED_PRIOR, budget_reservation,
    enumerate_legal_thetas, prior_for, theta_legal)

HERE = Path(__file__).resolve().parent

_NODE_PRIORS: Optional[dict] = None


def node_priors() -> dict:
    global _NODE_PRIORS
    if _NODE_PRIORS is None:
        p = HERE / 'FULL_DAG_NODE_PRIORS.json'
        _NODE_PRIORS = (json.loads(p.read_text())['node_priors']
                        if p.exists() else {})
    return _NODE_PRIORS


def lat_of(node_type: str, model_id: str) -> float:
    """Median real latency for (node_type, model); fallback to the
    generic reservation latency."""
    e = node_priors().get(f'{node_type}|{model_id}')
    if e:
        return e['lat_med']
    return budget_reservation(model_id, DEFAULT_THETA,
                              0)['latency_s_reserved']


def q_node(node_type: str, model_id: str, theta: dict) -> float:
    """pass x recall prior for one node slot."""
    p = prior_for(model_id, theta)
    return round(p['pass_rate'] * p['mean_recall'], 6)


def expected_task_quality(planned_pi: Dict[str, str],
                          faulted: str,
                          candidate: Tuple[str, dict],
                          fallback: Tuple[str, dict]) -> dict:
    """E[terminal q] for both branches. Healthy and stale-re-run
    nodes use their planned (tuned) prior; the faulted slot uses the
    candidate (success) or the fallback (failure)."""
    node_of = {'fe': 'fe', 'tl': 'tl', 'er': 'er', 'xc': 'xc'}
    q_succ, q_fail = [], []
    for n in ('fe', 'tl', 'er', 'xc'):
        tuned = theta_actions.DEFAULT_THETA
        from deadline_reward_v1.full_dag_protocol import TUNED_THETA
        tuned = TUNED_THETA[planned_pi[n]]
        if n == faulted:
            q_succ.append(q_node(n, candidate[0], candidate[1]))
            q_fail.append(q_node(n, fallback[0], fallback[1]))
        else:
            q_succ.append(q_node(n, planned_pi[n], tuned))
            q_fail.append(q_node(n, planned_pi[n], tuned))
    return dict(
        success=round(sum(q_succ) / 4, 6),
        failure=round(sum(q_fail) / 4, 6))


def choose(planned_pi, clock, faulted_node, faulted_model,
           stale_closure: set, global_budget_tokens: int,
           caps_tokens: int, model_menu: List[str],
           utility_fn) -> dict:
    """Two-branch argmax with closure pricing and task-level quality.
    Returns the chosen (model, theta) plus full diagnostics."""
    fallback = ('qwen-plus', dict(DEFAULT_THETA))
    fb_res = budget_reservation('qwen-plus', dict(DEFAULT_THETA), 4000)
    fb_lat = lat_of(faulted_node, 'qwen-plus')
    # closure re-execution applies to BOTH branches (the fixed output
    # must propagate), priced with planned models' node-type latencies
    from deadline_reward_v1.full_dag_protocol import TUNED_THETA
    clo_tok = 0
    clo_lat = 0.0
    for d in sorted(stale_closure):
        m = planned_pi[d]
        res = budget_reservation(m, TUNED_THETA[m], 4000)
        clo_tok += res['tokens_in'] + res['tokens_out_reserved']
        clo_lat += lat_of(d, m)

    cands = []
    for m in model_menu:
        thetas = ([a['theta'] for a in enumerate_legal_thetas(m)]
                  if m == faulted_model else
                  [dict(DEFAULT_THETA)]
                  + [a['theta'] for a in enumerate_legal_thetas(m)])
        for th in thetas:
            ok, _ = theta_legal(m, th)
            if not ok:
                continue
            res = budget_reservation(m, th, 4000)
            tok_cand = res['tokens_in'] + res['tokens_out_reserved']
            if (global_budget_tokens + tok_cand + clo_tok
                    > caps_tokens):
                continue  # budget-illegal (incl. closure price)
            p = prior_for(m, th)
            pr, mr = p['pass_rate'], p['mean_recall']
            cand_lat = lat_of(faulted_node, m)
            eq = expected_task_quality(planned_pi, faulted_node,
                                       (m, th), fallback)
            # SUCCESS branch: candidate quality, candidate time/cost
            U_succ = utility_fn(
                eq['success'], tok_cand + clo_tok,
                clock.t + cand_lat + clo_lat, clock.D)
            # FAILURE branch: fallback quality, +fallback time/cost
            U_fail = utility_fn(
                eq['failure'],
                tok_cand + clo_tok + fb_res['tokens_in']
                + fb_res['tokens_out_reserved'],
                clock.t + cand_lat + clo_lat + fb_lat, clock.D)
            eU = round(pr * U_succ + (1 - pr) * U_fail, 6)
            cands.append(dict(
                model=m, theta=th, eU=eU, pr=pr, mr=mr,
                U_succ=U_succ, U_fail=U_fail,
                q_task_succ=eq['success'], q_task_fail=eq['failure'],
                cand_lat=cand_lat, clo_lat=round(clo_lat, 3),
                clo_tokens=clo_tok, legal=True))
    if not cands:
        return dict(model=fallback[0], theta=fallback[1], eU=None,
                    note='no budget-legal candidate; fallback',
                    candidates=[])
    cands.sort(key=lambda c: -c['eU'])
    return dict(model=cands[0]['model'], theta=cands[0]['theta'],
                eU=cands[0]['eU'], chosen=cands[0],
                candidates=cands[:5])
