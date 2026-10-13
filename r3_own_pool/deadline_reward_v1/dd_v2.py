"""DD-V2 predictor/filter/fallback implementation (zero-call build).

Root-cause chain fixed per the attribution (2fbe6f7):
  V2-1  REAL latency priors from the independent reliability FIT
        binding (10 measured cells) — replaces PRIORS_STUB's
        node_profiles (v|coder 7.0s -> measured 0.33s etc.).
  V2-2  Contention DECOUPLED: candidate feasibility uses the task's
        OWN service+switch estimate only; the batch-queue signal is
        reported separately (service-latency vs E2E objectives are
        distinct by construction).
  V2-3  Quality predictor within data support: per-(node,model)
        production-parity parse rates (independent trajectories) with
        EXPLICIT uncertainty (Wilson intervals); conditions without
        support degrade to a declared wide interval, never fabricated
        precision.
  V2-4  DD-V2 arms: soft-constraint scoring + static fallback; the
        original DD-V1 remains byte-identical (arm_entry untouched).

Run: python3 -m deadline_reward_v1.test_dd_v2   (zero-call tests)
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent

# ---- V2-1: real latency priors from the FIT binding -----------------

def load_fit_binding(run_glob='run_*'):
    runs = sorted((HERE / 'reliability_runs').glob(run_glob))
    binding = json.loads((runs[-1] / 'BINDING.json').read_text())['binding']
    return {c: dict(mean=b['mean'], p90=b['declared_p90'],
                    family=b['family']) for c, b in binding.items()}


def build_v2_latency_profiles():
    """node_profiles for the predictor from MEASURED FIT cells."""
    fit = load_fit_binding()
    prof = {}
    for cell, b in fit.items():
        node, model = cell.split('|')
        prof[cell] = dict(
            q_success=None,  # filled by V2-3, never the stub constant
            lat_mean_s=b['mean'], lat_p90_s=b['p90'],
            tokens_p90=None,  # filled from PRIORS_REAL token measurements
            family=b['family'], source='reliability_fit_measured')
    # tokens from the real 1200-call calibration (clean cells)
    real = json.loads((HERE / 'PRIORS_REAL_V1.json').read_text())
    for cell in list(prof):
        n, m = cell.split('|')
        src = real['profiles'].get(f'{n}|{m}|clean')
        if src:
            prof[cell]['tokens_p90'] = src['tok_p90']
    return prof


# ---- V2-3: quality predictor within data support ---------------------

def load_quality_evidence():
    """Per-(node,model) production-parity parse rates + Wilson intervals
    from the independent formal trajectories (same computation as the
    supplementary beliefs; zero calls)."""
    import glob
    from collections import defaultdict
    from deadline_reward_v1 import detection as det
    from static_dag_v0.multidag_dynamic import value_of, json_value
    files = sorted(glob.glob(str(
        HERE.parent / 'collab_scheduler_v1/joint_search_v1/'
        'formal_campaign_v2*/**/TRAJECTORY.jsonl'), recursive=True))
    ctx, recs = {}, {}
    for f in files:
        for line in open(f):
            e = json.loads(line)
            r = e.get('response')
            if not isinstance(r, dict) or r.get('status') != 'delivered' \
                    or r.get('injected_fault'):
                continue
            parts = e['key'].split(':')
            ctx.setdefault((parts[2], parts[4], parts[3]), r['answer'])
            recs.setdefault((parts[3], e['model'],
                             e['prompt_sha256']),
                            (parts[2], parts[4], r['answer']))
    rate = defaultdict(lambda: [0, 0])
    for (node, model, _sha), (sc, uid, ans) in recs.items():
        ok = None
        if node in ('e1', 'e2'):
            ok = int(bool(det.parse_facts(ans)))
        elif node == 'v':
            ok = int(json_value(ans) is not None)
        elif node == 'r':
            # r evaluability: the expression evaluates against its OWN
            # episode's e1/e2 context (recoverable from ctx index)
            a1 = ctx.get((sc, uid, 'e1'))
            a2 = ctx.get((sc, uid, 'e2'))
            if a1 is not None and a2 is not None:
                from static_dag_v0.multidag_dynamic import parse_facts_safe
                f1, _ = parse_facts_safe(a1)
                f2, _ = parse_facts_safe(a2)
                fl = f1['facts'] + f2['facts']
                _, err = value_of(ans, dict(facts=fl))
                ok = int(not err)
        if ok is not None:
            rate[(node, model)][0] += ok
            rate[(node, model)][1] += 1
    return dict(rate)


def wilson(x, n, z=1.959963984540054):
    if n == 0:
        return (0.0, 1.0)          # NO DATA = maximal uncertainty
    p = x / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


class V2QualityPredictor:
    """Quality belief WITHIN data support. NODE-level beliefs are
    parse/evaluability rates with Wilson intervals — a DECLARED PROXY
    (node contract satisfaction), never claimed as terminal task
    correctness. RECOVERY quality (the composed whole-task belief after
    a recovery action) is estimated from independent development
    trajectories where the SAME recovery action family ran and the
    TERMINAL v2.1 outcome was observed; without such evidence the
    belief keeps the full [0,1] interval (supported=False)."""

    def __init__(self, recovery_evidence=None):
        self.ev = load_quality_evidence()
        # recovery_evidence: {(action_family, failed_node): (successes,
        # n)} built from INDEPENDENT dev trajectories (never P3-60)
        self.recovery = recovery_evidence or {}
        self.calls = {}

    def recovery_quality(self, failed_node, action_arm):
        """Terminal-correctness belief for executing `action_arm`
        after a failure on `failed_node`. Evidence keyed by
        (family, node); no evidence -> wide interval, supported=False."""
        key = (action_arm, failed_node)
        x, n = self.recovery.get(key, (0, 0))
        if n == 0:
            return dict(q=0.5, lo=0.0, hi=1.0, n=0, supported=False,
                        kind='terminal')
        lo, hi = wilson(x, n)
        return dict(q=round((lo + hi) / 2, 4), lo=round(lo, 4),
                    hi=round(hi, 4), n=n, supported=True,
                    kind='terminal')

    def node_quality(self, node, model):
        x, n = self.ev.get((node, model), (0, 0))
        if n == 0:
            return dict(q=0.5, lo=0.0, hi=1.0, n=0, supported=False)
        lo, hi = wilson(x, n)
        return dict(q=round((lo + hi) / 2, 4), lo=round(lo, 4),
                    hi=round(hi, 4), n=n, supported=True)

    def compose(self, factors: List[dict]):
        """Conservative composition: point = min of point estimates;
        interval = [min lo, min hi] (weakest link, with uncertainty)."""
        pts = [f['q'] for f in factors]
        lo = min(f['lo'] for f in factors)
        hi = min(f['hi'] for f in factors)
        any_unsup = any(not f['supported'] for f in factors)
        return dict(q=round(min(pts), 4), lo=round(lo, 4),
                    hi=round(hi, 4), unsupported=any_unsup)


# ---- V2-2 policy variant: contention-decoupled feasibility -----------

def make_v2_params(soft_constraints=True, static_fallback=True):
    lat = build_v2_latency_profiles()
    qp = V2QualityPredictor()
    for cell in lat:
        n, m = cell.split('|')
        lat[cell]['q_success'] = qp.node_quality(n, m)['q']
    return dict(
        version='DD-V2',
        priors=dict(
            node_profiles=lat,
            switch=dict(stop_s=1.5, start_s=dict(medium=65.0,
                                                  large=70.0, coder=60.0),
                        source='measured'),
            policy=dict(quality_composition='min',
                        q_observed_done=1.0, q_failed_unrecovered=0.0,
                        p90_aggregation='quantile_sum',
                        q_min=0.80, eps=0.10,
                        lam_c=0.5, lam_t=1.0, lam_f=2.0, c0=4000.0)),
        contention_mode='decoupled',     # V2-2: NOT in feasibility
        soft_constraints=soft_constraints,   # V2-4a
        static_fallback=static_fallback,     # V2-4b
        quality_predictor=qp)


def v2_score_and_pick(state, uid, cands, params, predictor, compensator,
                      engine_current_model):
    """DD-V2 decision: contention-decoupled feasibility + soft
    constraints + static fallback. The original policy._score_and_pick
    is UNTOUCHED (DD-V1 preserved)."""
    from deadline_reward_v1.reassign import ARMS
    from deadline_reward_v1 import reward as reward_mod
    from deadline_reward_v1.predictor import e1_on_time
    from deadline_reward_v1.compensator import DeadlineCompensator

    st = state.tasks[uid]
    pol = params['priors']['policy']
    q_min, eps = pol['q_min'], pol['eps']
    soft = params['soft_constraints']
    d_remain = compensator.d_remain(state, uid)
    b_remain = compensator.b_remain(state)['tokens']
    engine_model = engine_current_model()
    d_total = state.task_deadlines[uid] - st.release_time
    qp: V2QualityPredictor = params['quality_predictor']

    scored = []
    for cand in cands:
        execute = ([(n, True) for n, _ in cand.judgment.execute]
                   if cand.arm == 'FULL' else list(cand.judgment.execute))
        # V2-2: feasibility mu = OWN service + OWN switches only
        mu = 0.0
        p90 = 0.0
        cost = 0.0
        factors = []
        for node, new_call in execute:
            status = st.node_status.get(node)
            if not new_call:
                factors.append(dict(q=1.0, lo=1.0, hi=1.0, supported=True))
                continue
            if status == 'FAILED' and node not in cand.pi:
                factors.append(dict(q=0.0, lo=0.0, hi=0.0, supported=True))
                continue
            model = cand.pi.get(node) or st.node_model.get(node)
            cell = f'{node}|{model}'
            b = params['priors']['node_profiles'][cell]
            factors.append(qp.node_quality(node, model)
                           if status == 'FAILED' else
                           qp.node_quality(node, model))
            mu += b['lat_mean_s']
            p90 += b['lat_p90_s']
            cost += b.get('tokens_p90') or 300
        for node in ('e1', 'e2', 'r', 'v'):
            if node not in dict(execute):
                if st.node_status.get(node) == 'DONE':
                    factors.append(dict(q=1.0, lo=1.0, hi=1.0,
                                        supported=True))
                elif st.node_status.get(node) == 'FAILED':
                    factors.append(dict(q=0.0, lo=0.0, hi=0.0,
                                        supported=True))
        comp = qp.compose(factors)
        sw = sum(1.5 + params['priors']['switch']['start_s'].get(
            cand.pi.get(n) or st.node_model.get(n) or '', 65.0)
            for n, nc in execute if nc)
        p_on, e_late = e1_on_time(mu + sw, p90 + sw, d_remain)
        score = reward_mod.expected_rtask(
            q_hat=comp['q'], d_cost=cost, p_on_time=p_on,
            e_late=e_late, d_total=max(d_total, 1e-9),
            lam_c=pol['lam_c'], lam_t=pol['lam_t'], lam_f=pol['lam_f'],
            c0=pol['c0'])
        deficits = []
        if comp['q'] < q_min:
            deficits.append(dict(constraint='q_min',
                                 deficit=round(q_min - comp['q'], 10)))
        if p_on < 1.0 - eps:
            deficits.append(dict(constraint='on_time',
                                 deficit=round(1.0 - eps - p_on, 10)))
        if cost > b_remain:
            deficits.append(dict(constraint='budget',
                                 deficit=cost - b_remain))
        # V2-4a soft constraints: infeasible candidates stay in the
        # pool with a risk penalty instead of being dropped
        penalty = 0.0
        if deficits:
            for d in deficits:
                penalty += d['deficit']
        eff_score = score - (0.0 if not deficits or not soft else penalty)
        cand.row = dict(
            arm=cand.arm, pi=dict(cand.pi), q=comp['q'],
            q_lo=comp['lo'], q_hi=comp['hi'],
            unsupported=comp['unsupported'],
            mu_own=round(mu + sw, 6),
            mu_e2e=round(mu + sw, 6),   # alias for run_cell's
            # remaining-work convention (decoupled = own-service E2E)
            contention=0.0,
            p_on_time=round(p_on, 6),
            dcost=cost, score=round(score, 8),
            soft_penalty=round(penalty, 8),
            eff_score=round(eff_score, 8),
            feasible=not deficits, deficits=deficits,
            estimator='v2_measured_prior_decoupled',
            kinds=dict(cand.kinds),
            execute=[(n, bool(nc)) for n, nc in cand.judgment.execute],
            reuse=list(cand.judgment.reuse))
        scored.append(cand)

    # ---- Fix 1 (ruling b6c7966): eff_score DRIVES the selection ----
    # HARD gates (never relaxed): DAG legality (the judgment itself),
    # physical budget. Everything else competes on the risk-adjusted
    # score; the static SS fallback and NONE are COMPETITORS, not
    # automatic winners.
    hard_ok = [c for c in scored
               if c.row['dcost'] <= b_remain]      # physical budget gate
    # legality gate is structural: only legal candidates were ever
    # enumerated (M3); rows carry their judgment for audit.
    if not hard_ok:
        return None, scored, 'degraded'
    best = sorted(hard_ok, key=lambda c: (-c.row['eff_score'],
                                          c.row['dcost'],
                                          ARMS.index(c.arm)))[0]
    # identify the static SS-recipe candidate IN the pool (same
    # legality/budget hard gates apply to it)
    fb = next((c for c in hard_ok if c.arm == 'LOCAL'
               and all(c.pi.get(n) == v for n, v in
                       state._panel_models.items() if n in c.pi)), None)
    if fb is not None:
        fb.row['fallback_candidate'] = True
    # if the WINNER IS the static candidate itself -> static_fallback
    # (the competition was uniform; the static recipe won on score)
    if fb is not None and best is fb:
        fb.row['fallback'] = True
        return fb, scored, 'static_fallback'
    if best.row['feasible']:
        if fb is not None:
            best.row['selected_over_fallback_margin'] = round(
                best.row['eff_score'] - fb.row['eff_score'], 8)
        return best, scored, 'joint_selection'
    # soft-constraint winner distinct from the static candidate
    if fb is not None:
        best.row['selected_over_fallback_margin'] = round(
            best.row['eff_score'] - fb.row['eff_score'], 8)
    return best, scored, 'joint_selection_soft'


# ---- Fix 3 (ruling b6c7966): V2 decision entry (arm_entry contract) --
def decide_arm_v2(state, uid, cands, planned, params_v2=None, *,
                  soft=True, fallback=True, engine_current_model=lambda:
                  None):
    """Same return contract as arm_entry.decide_arm so the AUDITED
    run_cell/execute chain drives V2 unchanged. Modes:
      joint_selection / joint_selection_soft — a dynamic candidate won
        on (risk-adjusted) score over the static fallback
      static_fallback — the SS-recipe candidate won the comparison
      degraded — no candidate passed the physical-budget hard gate
    DD-V1 (arm_entry.decide_arm) is NOT modified."""
    from deadline_reward_v1 import policy as P
    params = params_v2 or make_v2_params(soft_constraints=soft,
                                         static_fallback=fallback)
    compensator = P.DeadlineCompensator(params['priors'])
    chosen, scored, mode = v2_score_and_pick(
        state, uid, cands, params, None, compensator,
        engine_current_model)
    return dict(arm='DD-V2', mode=mode, chosen=chosen,
                degraded=(chosen is None), pool_size=len(scored),
                table=[dict(c.row) for c in scored if c.row],
                violations=[dict(arm=c.row['arm'], pi=c.row['pi'],
                                 deficits=c.row['deficits'])
                            for c in scored if c.row['deficits']],
                reason=None if chosen is not None else
                'physical_budget_gate')
