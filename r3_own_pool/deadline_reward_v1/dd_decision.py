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

DEFAULT_THETA_BASE = dict(DEFAULT_THETA)

HERE = Path(__file__).resolve().parent

_NODE_PRIORS: Optional[dict] = None
NODE_QUALITY: Optional[dict] = None


def node_priors() -> dict:
    global _NODE_PRIORS, NODE_QUALITY
    if _NODE_PRIORS is None:
        p = HERE / 'FULL_DAG_NODE_PRIORS.json'
        if p.exists():
            d = json.loads(p.read_text())
            _NODE_PRIORS = d.get('node_priors', {})
            NODE_QUALITY = d.get('node_quality', {})
        else:
            _NODE_PRIORS, NODE_QUALITY = {}, {}
    return _NODE_PRIORS


def lat_of(node_type: str, model_id: str) -> float:
    """Median real latency for (node_type, model); fallback to the
    generic reservation latency."""
    e = node_priors().get(f'{node_type}|{model_id}')
    if e:
        return e['lat_med']
    return budget_reservation(model_id, DEFAULT_THETA,
                              0)['latency_s_reserved']


def _node_quality_ratio(node_type: str, model_id: str) -> float:
    """Relative recall ratio for (node_type, model) from the 68
    scored historical calls, vs the model's own cross-node mean.
    Only cells with n>=30 enter; shrunk 50% toward 1.0 (weak signal,
    denominator caveat documented in FULL_DAG_NODE_PRIORS)."""
    qs = NODE_QUALITY.get(f'{node_type}|{model_id}')
    if not qs or qs['n'] < 30:
        return 1.0
    cells = [v for k, v in NODE_QUALITY.items()
             if k.split('|')[0] in ('tl', 'er', 'xc')
             and k.endswith(f'|{model_id}') and v['n'] >= 30]
    if len(cells) < 2:
        return 1.0
    mean_r = sum(v['recall'] * v['n'] for v in cells) / sum(
        v['n'] for v in cells)
    if mean_r <= 0:
        return 1.0
    ratio = qs['recall'] / mean_r
    return round(1.0 + 0.5 * (ratio - 1.0), 4)   # 50% shrink


def q_node(node_type: str, model_id: str, theta: dict,
            store=None) -> float:
    """Pessimistic (Wilson-LB) pass x pooled-recall prior for one
    node slot, with the weak node-type quality ratio applied."""
    if store is not None:
        key = theta_actions.prior_key(model_id, theta)
        p = (store.prior(key) if key is not None
             and key in store.counts else prior_for(model_id, theta))
    else:
        p = prior_for(model_id, theta)
    base = p['pass_rate_lb'] * p['pooled_recall_lb']
    return round(base * _node_quality_ratio(node_type, model_id), 6)


def downstream(node: str) -> set:
    """Downstream of a node over the REAL edges (fe->tl->xc; er->xc;
    no fe->er)."""
    import deadline_reward_v1.full_dag_tasks as fdt
    seen, stack = set(), [node]
    while stack:
        n = stack.pop()
        for m in fdt.EDGES.get(n, []):
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen


def expected_task_quality(planned_pi: Dict[str, str],
                          faulted: str,
                          candidate: Tuple[str, dict],
                          fallback: Tuple[str, dict],
                          store=None,
                          candidate_prior=None,
                          fallback_prior=None) -> dict:
    """E[terminal q] for both branches with MULTIPLICATIVE downstream
    propagation: a node downstream of the faulted one inherits the
    repaired slot's quality as a multiplier (garbage upstream caps
    what downstream can deliver). Without this, the plain 4-node
    mean dilutes a single slot's quality difference x1/4 — too weak
    against the cost term (simulation finding 2026-10-14: DD could
    never discover a better repair)."""
    from deadline_reward_v1.full_dag_protocol import TUNED_THETA
    down = downstream(faulted)

    def q_mean(n):
        """Healthy slots at posterior MEAN (their uncertainty is
        common to every candidate and largely cancels in the
        comparison; pessimism belongs on the DECIDED slot only —
        LB-everywhere was found to squash propagation gains below
        the linear cost term)."""
        if store is not None:
            key = theta_actions.prior_key(planned_pi[n],
                                          TUNED_THETA[planned_pi[n]])
            if key is not None and key in store.counts:
                pr = store.prior(key)
                return pr['pass_rate'] * pr['pooled_recall']
        pr = theta_actions.prior_for(planned_pi[n],
                                     TUNED_THETA[planned_pi[n]])
        return pr['pass_rate'] * pr['pooled_recall']

    def q_task(slot_q):
        total = 0.0
        for n in ('fe', 'tl', 'er', 'xc'):
            if n == faulted:
                total += slot_q
            elif n in down:
                total += q_mean(n) * slot_q
            else:
                total += q_mean(n)
        return round(total / 4, 6)

    # the DECIDED slot uses the decision-time prior — the Thompson
    # sample when sampling (exploration), the LB otherwise
    if candidate_prior is not None:
        q_succ = candidate_prior['pass_rate'] \
            * candidate_prior['pooled_recall']
        q_succ = round(q_succ * _node_quality_ratio(
            faulted, candidate[0]), 6)
    else:
        q_succ = q_node(faulted, candidate[0], candidate[1], store)
    if fallback_prior is not None:
        q_fail = fallback_prior['pass_rate'] \
            * fallback_prior['pooled_recall']
        q_fail = round(q_fail * _node_quality_ratio(
            faulted, fallback[0]), 6)
    else:
        q_fail = q_node(faulted, fallback[0], fallback[1], store)
    return dict(success=q_task(q_succ), failure=q_task(q_fail))


def choose(planned_pi, clock, faulted_node, faulted_model,
           stale_closure: set, global_budget_tokens: int,
           caps_tokens: int, model_menu: List[str],
           utility_fn, prior_store=None,
           mode='lb', rng=None) -> dict:
    """Two-branch argmax with closure pricing and task-level quality.
    prior_store: optional PriorStore — priors then come from DEV
    counts + all COMPLETED tasks' outcomes (within-run learning; the
    store is updated only after a task ends, so task k's outcome can
    never inform task k's decision).
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

    def _prior(m, th):
        if prior_store is not None:
            key = theta_actions.prior_key(m, th)
            if key is not None and key in prior_store.counts:
                if mode == 'thompson' and rng is not None:
                    return prior_store.sample(key, rng)
                return prior_store.prior(key)
        return prior_for(m, th)

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
            p = _prior(m, th)
            pr = p['pass_rate_lb']
            mr = p['pooled_recall_lb'] * _node_quality_ratio(
                faulted_node, m)
            cand_lat = lat_of(faulted_node, m)
            eq = expected_task_quality(
                planned_pi, faulted_node, (m, th), fallback,
                store=prior_store,
                candidate_prior=p,
                fallback_prior=(
                    _prior('qwen-plus', dict(DEFAULT_THETA_BASE))
                    if m != 'qwen-plus' else p))
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
