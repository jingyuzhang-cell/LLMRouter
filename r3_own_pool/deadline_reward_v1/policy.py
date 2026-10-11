"""M5+M6 — the joint dynamic policy: candidates (Z, R, π), two-stage
decision (constraint filter → argmax Ê[R_task]), degradation (EARLY_STOP),
plan application, and the episode driver. Zero real model calls.

This is the MAINLINE_FREEZE decision loop made executable:
  detection (occurred D-observations only) → legal info (state view +
  live D_remain/B_remain) → joint candidates (recovery recipe × model
  assignment over frozen per-node menus) → filter (q̂≥Q_min,
  P̂(T≤D_remain)≥1−ε, ΔC≤B_remain) → argmax Ê[R_task] (E1 on the composed
  E2E belief: service + switch overhead, each counted once) → execute via
  the M1 engine (M3 legality, M4 recovery semantics) → feedback → settle.

No gold, no fault registry, no future outputs ever enter decide().
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import dag_closure as dc
from . import reward as reward_mod
from .reassign import ARMS, Candidate, apply_decision, enumerate_candidates
from .compensator import DeadlineCompensator
from .predictor import (OutcomePredictor, e1_on_time,
                        validate_node_profiles)

# baseline remaining-work default for tasks that have not decided yet:
# the planned V1 stage's service under the planned model (set from the
# priors at episode start; policy.run_episode overwrites with exact
# profile values when priors are available)
BASE_PRIORS_V_SERVICE_DEFAULT = 0.0


def _profile_value(priors: dict, node: str, model: str, key: str,
                   default: float = 0.0) -> float:
    prof = (priors.get('node_profiles', {}).get(f'{node}|{model}')
            or priors.get('profiles', {}).get(f'{node}|{model}', {}))
    return float(prof.get(key, default))



@dataclass
class Decision:
    task: str
    candidates: List[Candidate]
    chosen: Optional[Candidate]
    degraded: bool
    violations: List[dict]
    d_remain: float
    b_remain_tokens: float


def run_episode(engine, state, tasks: List[dict], node_models: Dict[str, str],
                params: dict) -> dict:
    validate_node_profiles(params['priors'])   # boundary task 4
    predictor = OutcomePredictor(params['priors'])
    compensator = DeadlineCompensator(params['priors'])
    v_model = node_models.get('v', 'coder')
    sw = params['priors']['switch']
    # Co-resident baseline estimate (boundary task 3, errata): the other
    # task's remaining v work = v mean + a FULL switch allowance
    # (stop + start) regardless of the resident model at execution time —
    # observable (priors + planned binding) and conservative vs missing
    # the co-task's switch entirely, which real interleaved execution
    # DOES charge (caught by the tight deterministic sample).
    v_default = (float(_profile_value(params['priors'], 'v', v_model,
                                      'lat_mean_s', 0.0))
                 + float(sw['stop_s']) + float(sw['start_s'][v_model]))
    global BASE_PRIORS_V_SERVICE_DEFAULT
    BASE_PRIORS_V_SERVICE_DEFAULT = v_default
    chosen_pi: Dict[str, Dict[str, str]] = {}
    engine.start_panel(tasks, node_models)
    engine.run_jobs('A', engine.planned_jobs(tasks, node_models,
                                             ('e1', 'e2')))
    engine.run_jobs('R1', engine.planned_jobs(tasks, node_models, ('r',)))

    def decision_round(stage_tag):
        for t in tasks:
            uid = t['uid']
            st = state.tasks[uid]
            if st.degraded:
                continue
            if not any(st.node_status[n] == dc.FAILED for n in dc.TOPO):
                continue
            cands = enumerate_candidates(state, uid, node_models)
            decision = _score_and_pick(state, uid, cands, params, predictor,
                                       compensator,
                                       lambda: engine.current_model)
            engine._append(dict(
                event='decision', task=uid, stage=stage_tag,
                degraded=decision.degraded,
                d_remain=round(decision.d_remain, 6),
                b_remain_tokens=decision.b_remain_tokens,
                chosen=(dict(arm=decision.chosen.arm,
                             pi=dict(decision.chosen.pi),
                             score=decision.chosen.row['score'])
                        if decision.chosen else None),
                violations=decision.violations,
                table=[c.row for c in cands]))
            if decision.degraded:
                st.degraded = True
                st.violations.extend(decision.violations)
                # this task's plans will not run: release any earlier
                # reservations and stop contributing contention
                state.release_reservations(uid)
                state.remaining_work_est.pop(uid, None)
            else:
                chosen_pi[uid] = dict(decision.chosen.pi)
                # Budget reservation, OWNED by this task+decision: later
                # tasks see allocation - spent - reservations; only THIS
                # task's physical calls drain it; residuals release at
                # plan end (boundary task 1).
                state.reserve(uid, decision.chosen.row['dcost'])
                # Conservative remaining-work estimate for OTHER tasks'
                # contention bounds (cleared when this task's stages end).
                state.remaining_work_est[uid] = (
                    decision.chosen.row['mu_e2e']
                    - decision.chosen.row['contention'])  # own bound incl.
                    # per-call switch allowance — others' contention est
                    # must cover my real remaining work incl. re-switches
                apply_decision(engine, state, t, node_models,
                               decision.chosen)

    # Baseline remaining work BEFORE any decision so the FIRST decider
    # already sees other tasks' shared-timeline work (boundary task 3):
    # each task's not-yet-run V1 stage under its planned model.
    for t in tasks:
        state.remaining_work_est.setdefault(
            t['uid'], BASE_PRIORS_V_SERVICE_DEFAULT)
    decision_round('post_R1')
    v_jobs = []
    for t in tasks:
        uid = t['uid']
        st = state.tasks[uid]
        if st.degraded:
            continue  # D10 EARLY_STOP: zero further calls for this task
        v_model = chosen_pi.get(uid, {}).get('v') or node_models['v']
        v_jobs.append(dict(task=t, node='v', kind='plain', model=v_model))
    if v_jobs:
        engine.run_jobs('V1', v_jobs)
    for t in tasks:  # V1 landed: no remaining planned work to contend for
        state.remaining_work_est.pop(t['uid'], None)
    decision_round('post_V1')
    # Plan-end settlement of reservations (boundary task 1): every task's
    # plans have fully executed or degraded — unused residuals return to
    # the pool BEFORE settlement so C_full accounting sees the truth.
    for t in tasks:
        state.release_reservations(t['uid'])
    summaries = engine.write_task_summaries(tasks)
    engine.write_session_summary(len(tasks))
    settlement = reward_mod.settle(
        engine, state, tasks, lam_c=params['lam_c'], lam_t=params['lam_t'],
        lam_f=params['lam_f'], c0=params['c0'],
        session_bonus=params.get('session_bonus', 1.0),
        session_penalty=params.get('session_penalty', 2.0))
    return dict(summaries=summaries, settlement=settlement,
                chosen_pi=chosen_pi)


def _score_and_pick(state, uid, cands, params, predictor, compensator,
                    engine_current_model) -> Decision:
    """Score every candidate (rows attached for audit), apply the filter,
    pick by Ê[R_task] with the D9 tie-break, or degrade with the full
    violation vector (D10)."""
    st = state.tasks[uid]
    q_min, eps = params['q_min'], params['eps']
    b_remain = compensator.b_remain(state)['tokens']
    d_remain = compensator.d_remain(state, uid)
    engine_model = engine_current_model()
    feasible: List[Candidate] = []
    d_total = state.task_deadlines[uid] - st.release_time  # frozen D
    for cand in cands:
        # M4 semantics: a FULL (E-arm) replay is NEVER cache-substituted —
        # every replayed node is a charged new call, so the predictor must
        # see new_call=True for the whole execute set (phase-3 fix 1).
        execute = ([(n, True) for n, _ in cand.judgment.execute]
                   if cand.arm == 'FULL' else list(cand.judgment.execute))
        pred = predictor.predict(execute=execute, pi=cand.pi,
                                 node_model=st.node_model,
                                 node_status=st.node_status)
        pred_family = ('lognormal' if pred.log_params else
                       'empirical' if 'empirical' in pred.families
                       else 'normal')
        # round 3 fix #6: each family's accuracy claim is INDEPENDENT —
        # normal/lognormal are parametric estimate / approximation; only
        # the empirical branch is a (declared-model) lower bound.
        pred_claim = {
            'normal': 'declared_normal_parametric_estimate',
            'lognormal': 'fenton_wilkinson_approximation',
            'empirical': 'declared_model_lower_bound(staircase+markov)',
        }[pred_family]
        # OWN switch cost: a PROVABLE per-call bound — on the shared
        # serial executor each of my new calls needs at most one
        # stop+start (cross-task interleaving can force a re-switch before
        # EVERY call, so the sequential estimate is not an upper bound;
        # the tight deterministic sample caught exactly this).
        sw = sum(compensator.stop_s
                 + compensator.start_s.get(
                     (cand.pi.get(n) or st.node_model.get(n) or ''), 0.0)
                 for n, new_call in execute if new_call)
        sw_seq = compensator.switch_overhead(
            engine_model,
            [cand.pi.get(n) or st.node_model.get(n)
             for n, new_call in execute if new_call])
        # Cross-task contention (boundary task 3): the co-resident tasks'
        # DECLARED remaining-work estimate (priors-derived v mean plus a
        # full switch allowance for the co-task; replaced by that task's
        # own chosen-plan estimate once it decides). It is an ESTIMATE /
        # heuristic penalty — a provable upper bound only when each
        # co-task's actual remaining work (service + its switches) stays
        # within its estimate; never claimed as a general guarantee.
        contention = sum(
            state.remaining_work_est.get(u, 0.0)
            for u in state.tasks if u != uid)
        mu_e2e = pred.mu_service_s + sw + contention  # composed ONCE (B6)
        # Deterministic addends shift mean AND quantile together
        # (phase-3 fix 2); sigma is unchanged by the shift.
        p90_e2e = pred.w_p90_s + sw + contention
        # Round 3 fix #4: SERVICE-side quantities + ONE shift — the
        # estimator applies the deterministic addends exactly once
        # (mu_e2e/p90_e2e above remain the audit-row totals).
        p_on, e_late = e1_on_time(
            pred.mu_service_s, pred.w_p90_s, d_remain, family=pred_family,
            log_params=pred.log_params, ladders=pred.ladders,
            shift=sw + contention)
        # Conservatism applicability (boundary task 2, revised round 3):
        # empirical rows carry a declared-model LOWER bound on p_on;
        # normal quantile_sum rows are conservative only while D >= mu
        # (below the mean the inflated sigma RAISES the probability);
        # lognormal rows are an approximation — no bound claimed.
        agg_mode = params['priors'].get('policy', {}).get(
            'p90_aggregation', 'quantile_sum')
        if pred_family == 'empirical':
            p_conservative = True
        elif pred_family == 'lognormal':
            p_conservative = False
        else:
            p_conservative = (agg_mode == 'variance'
                              or d_remain >= mu_e2e)
        # e_late feasibility uses d_remain; NORMALIZATION uses the frozen
        # task duration D so decisions optimize the settlement objective
        # (phase-3 fix 3).
        score = reward_mod.expected_rtask(
            q_hat=pred.q_mean, d_cost=pred.d_cost_tokens, p_on_time=p_on,
            e_late=e_late, d_total=max(d_total, 1e-9),
            lam_c=params['lam_c'], lam_t=params['lam_t'],
            lam_f=params['lam_f'], c0=params['c0'])
        deficits = []
        if pred.q_mean < q_min:
            deficits.append(dict(constraint='q_min',
                                 deficit=round(q_min - pred.q_mean, 10)))
        if p_on < 1.0 - eps:
            deficits.append(dict(constraint='on_time',
                                 deficit=round(1.0 - eps - p_on, 10)))
        if pred.d_cost_tokens > b_remain:
            deficits.append(dict(constraint='budget',
                                 deficit=pred.d_cost_tokens - b_remain))
        cand.row = dict(arm=cand.arm, pi=dict(cand.pi),
                        q=round(pred.q_mean, 10), mu_e2e=round(mu_e2e, 10),
                        p90=round(p90_e2e, 10),
                        dcost=pred.d_cost_tokens,
                        switch=round(sw, 10),
                        switch_seq=round(sw_seq, 10),
                        contention=round(contention, 10),
                        p_on_time=round(p_on, 10), e_late=round(e_late, 10),
                        p_conservative=p_conservative,
                        estimator=pred_family,
                        estimator_claim=pred_claim,
                        score=round(score, 10), feasible=not deficits,
                        deficits=deficits, kinds=dict(cand.kinds))
        if not deficits:
            feasible.append(cand)
    if feasible:
        best = sorted(feasible, key=lambda c: (-c.row['score'],
                                               c.row['dcost'],
                                               ARMS.index(c.arm)))[0]
        return Decision(task=uid, candidates=cands, chosen=best,
                        degraded=False, violations=[], d_remain=d_remain,
                        b_remain_tokens=b_remain)
    violations = [dict(arm=c.arm, pi=dict(c.pi), deficits=c.row['deficits'])
                  for c in cands]
    return Decision(task=uid, candidates=cands, chosen=None, degraded=True,
                    violations=violations, d_remain=d_remain,
                    b_remain_tokens=b_remain)
