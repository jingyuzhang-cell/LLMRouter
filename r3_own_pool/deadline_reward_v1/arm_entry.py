"""Frozen five-arm entry points (V2.3 protocol §2 + DAG_QUALITY_CALIBRATION
PROTOCOL_v1). THE selection layer every arm routes through — zero real model
calls, zero oracle access (no gold, no fault registry, no future outputs).

The arms differ by WHICH dimensions of the joint action a_t = (Z_t, R_t, π_t)
are decided by the M6 two-stage policy versus fixed by the static recipe:

  SS   static recovery + static assignment: the fixed LOCAL recipe with the
       planned models. NO policy scoring, NO constraint filter — static
       means it executes regardless of feasibility (that blindness is the
       ablation, not a bug).
  DS   dynamic recovery + static assignment: the two-stage policy over
       candidates whose π equals the planned assignment on every node —
       the policy chooses the SCOPE (schedule-only / LOCAL / FULL).
  SD   static recovery + dynamic assignment: scope frozen to the LOCAL
       recipe (R = failed closure), the policy chooses π over the menus.
  DD   both dynamic: the policy over ALL candidates (NONE / LOCAL / FULL /
       FULL_DYNAMIC) — the complete joint mechanism.
  NONE no recovery: accept the failure; still-pending planned nodes run
       under the planned models (the floor).

DS/SD/DD all route through the SAME policy._score_and_pick — the arms are
different candidate SETS over one decision rule, never relabeled outputs.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from . import policy
from .reassign import Candidate, enumerate_candidates

ARMS = ('SS', 'DS', 'SD', 'DD', 'NONE')
_PLANNED_NODES = ('e1', 'e2', 'r', 'v')


def pi_is_planned(cand: Candidate, planned: Dict[str, str]) -> bool:
    """π constrained to the planned assignment on every node it assigns."""
    return all(cand.pi.get(n) == planned.get(n) for n in cand.pi)


def select_candidates(cands: List[Candidate], arm: str,
                      planned: Dict[str, str]) -> List[Candidate]:
    """The arm's ablation constraint over the enumerated legal candidates."""
    if arm == 'DS':
        return [c for c in cands if pi_is_planned(c, planned)]
    if arm == 'SD':
        return [c for c in cands if c.arm == 'LOCAL']
    if arm == 'DD':
        return list(cands)
    raise ValueError('select_candidates is for the policy arms (DS/SD/DD): '
                     + arm)


def static_recipe_pick(cands: List[Candidate],
                       planned: Dict[str, str]) -> Optional[Candidate]:
    """SS: the LOCAL candidate with the planned models — the fixed recipe.
    First match in enumeration order (LOCAL π-variants are deterministic)."""
    return next((c for c in cands if c.arm == 'LOCAL'
                 and pi_is_planned(c, planned)), None)


def decide_arm(state, uid: str, cands: List[Candidate], arm: str,
               planned: Dict[str, str], params: dict, predictor,
               compensator, engine_current_model) -> dict:
    """One arm's decision at one decision point. Returns an audit record:
    mode (static_recipe / policy / no_recovery), the chosen Candidate (or
    None), degraded flag, and for policy arms the FULL scored table +
    violation vector — proof the decision was a real computation."""
    if arm == 'NONE':
        return dict(arm=arm, mode='no_recovery', chosen=None,
                    degraded=False, pool_size=0, table=[], violations=[])
    if arm == 'SS':
        pick = static_recipe_pick(cands, planned)
        return dict(arm=arm, mode='static_recipe', chosen=pick,
                    degraded=pick is None, pool_size=1, table=[],
                    violations=[])
    pool = select_candidates(cands, arm, planned)
    decision = policy._score_and_pick(
        state, uid, pool, params, predictor, compensator,
        engine_current_model)
    return dict(arm=arm, mode='policy', chosen=decision.chosen,
                degraded=decision.degraded, pool_size=len(pool),
                table=[c.row for c in pool if c.row is not None],
                violations=decision.violations,
                d_remain=decision.d_remain,
                b_remain_tokens=decision.b_remain_tokens)


def enumerate_for(state, uid: str, planned: Dict[str, str]
                  ) -> List[Candidate]:
    """Thin wrapper pinning the enumeration used by every arm."""
    return enumerate_candidates(state, uid, planned)


__all__ = ['ARMS', 'decide_arm', 'enumerate_for', 'pi_is_planned',
           'select_candidates', 'static_recipe_pick']
