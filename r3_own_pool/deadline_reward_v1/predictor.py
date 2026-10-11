"""M6 — per-joint-action outcome predictor (zero real calls).

For a candidate action's EXECUTE set (from the M3 judgment) and model
assignment π, predicts the three quantities the two-stage decision needs:
whole-DAG final quality q̂, incremental physical cost ΔC, and the critical-
path SERVICE time belief (μ, p90). Switch overhead is owned by the
compensator and composed ONCE at the policy (reward doc §3.3a).

Statistical assumptions (rev E ruling): all profiles are declared SYNTHETIC
PRIORS entries (family/parameters recorded); μ is the declared mean (never
a generic p50); the path p90 is a CONSERVATIVE UPPER BOUND (sum of node
p90s under declared independence); σ=(p90−μ)/1.2816 is exact only for the
declared normal family. No real-model calibration is claimed or implied.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple


@dataclass(frozen=True)
class ActionPrediction:
    q_mean: float
    d_cost_tokens: float
    mu_service_s: float
    w_p90_s: float
    # distribution-family audit (2026-10-11 admission repair #4): the
    # frozen distribution audit found 0/40 normal, 12/40 lognormal,
    # 28/40 empirical — the on-time estimator must not unconditionally
    # assume normality. families = per-executing-node declared family;
    # log_params = (mu_log, sigma_log) for all-lognormal paths;
    # ladders = per-node (threshold, CDF) staircase points for
    # empirical-composed paths (see e1_on_time for each branch's
    # INDEPENDENT accuracy claim).
    families: Tuple[str, ...] = ()
    log_params: Tuple[Tuple[float, float], ...] = ()
    ladders: Tuple[Tuple[Tuple[float, float], ...], ...] = ()


def _profile(priors: dict, node: str, model: str) -> dict:
    prof = (priors.get('node_profiles', {}).get(f'{node}|{model}')
            or priors['profiles'][f'{node}|{model}'])
    return prof


def validate_node_profiles(priors: dict) -> None:
    """Latency-profile legality (boundary audit task 4).

    A declared NORMAL profile must satisfy p90 >= mean — a quantile below
    the mean is statistically contradictory and must NOT be silently
    coerced into the point-mass model for formal feasibility decisions
    (p90 == mean is the legitimate zero-variance limit). DETERMINISTIC
    profiles are explicit point masses and always legal. Raises
    ValueError naming every offending profile."""
    bad = []
    for key, prof in priors.get('node_profiles', {}).items():
        if prof.get('family', 'normal') == 'normal':
            mean, p90 = float(prof['lat_mean_s']), float(prof['lat_p90_s'])
            if p90 < mean:
                bad.append(f'{key}(mean={mean}, p90={p90})')
    if bad:
        raise ValueError(
            'inconsistent normal latency profile(s) — p90 < mean is '
            'statistically contradictory; use family=deterministic for '
            'explicit point masses: ' + '; '.join(bad))


class OutcomePredictor:
    def __init__(self, priors: dict) -> None:
        self.priors = priors
        pol = priors.get('policy', {})
        self.q_observed_done = float(pol.get('q_observed_done', 1.0))
        self.q_failed_unrecovered = float(
            pol.get('q_failed_unrecovered', 0.0))
        self.composition = pol.get('quality_composition', 'min')

    def node_quality(self, node: str, model: str) -> float:
        return float(_profile(self.priors, node, model)['q_success'])

    def predict(self, *, execute: Iterable[Tuple[str, bool]],
                pi: Dict[str, str], node_model: Dict[str, Optional[str]],
                node_status: Dict[str, str]) -> ActionPrediction:
        # p90 aggregation (phase-3 fix 2): 'quantile_sum' (default) sums
        # per-node p90s — under the DECLARED independence+normal family
        # this OVERSTATES the true path p90 (sqrt(sum sigma^2) <= sum
        # sigma), i.e. the on-time probability derived from it is a
        # conservative LOWER bound — used for the golden scenarios.
        # 'variance' is the exact independent-normal aggregation.
        agg = self.priors.get('policy', {}).get('p90_aggregation',
                                                'quantile_sum')
        mus, p90s, sigmas = [], [], []
        """execute: the judgment's (node, new_call) list; π resolves the
        model for executing nodes; non-executing DONE nodes reuse their
        cached output (observed-state belief); a FAILED node left out of
        the execute set caps the whole-DAG quality at the failure floor."""
        q_factors = []
        cost = 0.0
        families = []
        log_params = []
        ladder_profiles = []
        for node, new_call in execute:
            status = node_status.get(node)
            model = pi.get(node) or node_model.get(node)
            if status == 'FAILED' and not new_call:
                # unrecovered failure inside the execute set: quality floor
                q_factors.append(self.q_failed_unrecovered)
                continue
            if not new_call:
                # identity-unchanged cache hit: same output, observed belief
                q_factors.append(self.q_observed_done)
                continue
            prof = _profile(self.priors, node, model)
            q_factors.append(float(prof['q_success']))
            cost += float(prof.get('tokens_p90', 0.0))
            m_i = float(prof['lat_mean_s'])
            p_i = float(prof['lat_p90_s'])
            mus.append(m_i)
            p90s.append(p_i)
            sigmas.append(max(0.0, (p_i - m_i) / 1.2816))
            fam = prof.get('family', 'normal')
            families.append(fam)
            if fam == 'lognormal':
                log_params.append((float(prof['mu_log']),
                                   float(prof['sigma_log'])))
            ladder_profiles.append(prof)
        for node in ('e1', 'e2', 'r', 'v'):
            # reused DONE nodes outside the execute set
            if node not in dict(execute) and node_status.get(node) == 'DONE':
                q_factors.append(self.q_observed_done)
            if node_status.get(node) == 'FAILED' \
                    and node not in dict(execute):
                q_factors.append(self.q_failed_unrecovered)
        if self.composition == 'product':
            q = 1.0
            for f in q_factors:
                q *= f
        else:  # 'min' — weakest link over the final answer path
            q = min(q_factors) if q_factors else self.q_observed_done
        mu = sum(mus)
        if agg == 'variance':
            p90 = mu + 1.2816 * (sum(s * s for s in sigmas) ** 0.5)
        else:
            p90 = sum(p90s)
        # composed family: pure-lognormal path -> lognormal estimator;
        # any empirical node -> staircase/Markov bound path; else normal
        if families and len(log_params) == len(families):
            composed = 'lognormal'
        elif 'empirical' in families:
            composed = 'empirical'
        else:
            composed = 'normal'
        return ActionPrediction(q_mean=round(q, 10),
                                 d_cost_tokens=cost,
                                 mu_service_s=round(mu, 10),
                                 w_p90_s=round(p90, 10),
                                 families=tuple(families),
                                 log_params=tuple(log_params)
                                 if composed == 'lognormal' else (),
                                 ladders=tuple(_node_ladder(p)
                                               for p in ladder_profiles)
                                 if composed == 'empirical' else ())


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _lognormal_path(log_params, shift: float, deadline: float
                    ) -> Tuple[float, float]:
    """Fenton–Wilkinson: a sum of independent lognormals is approximated
    by a lognormal matched on the first two moments, shifted by the
    deterministic addend `shift` (switch overhead + contention)."""
    m1 = [math.exp(ml + sl * sl / 2) for ml, sl in log_params]
    v1 = [(math.exp(sl * sl) - 1) * m * m
          for (_, sl), m in zip(log_params, m1)]
    tot_m, tot_v = sum(m1), sum(v1)
    s2 = math.log(1.0 + tot_v / (tot_m * tot_m))
    ml = math.log(tot_m) - s2 / 2.0
    sl = math.sqrt(s2)
    dd = deadline - shift
    if dd <= 0:
        return 0.0, tot_m + shift - deadline
    p = normal_cdf((math.log(dd) - ml) / sl)
    # E[(X - dd)+], X ~ LogNormal(ml, sl)
    epos = (math.exp(ml + s2 / 2)
            * (1 - normal_cdf((math.log(dd) - ml - s2) / sl))
            - dd * (1 - p))
    return p, max(0.0, epos)


_PHI_LADDER = (-0.8416, -0.2533, 0.0, 0.5244, 0.8416, 1.2816, 1.6449,
               2.3263, 3.0902)
# Phi(z): .20, .40, .50, .70, .80, .90, .95, .99, .999 — the staircase
# candidate thresholds for declared normal / lognormal nodes in a mixed
# empirical path.


def _node_ladder(prof: dict) -> Tuple[Tuple[float, float], ...]:
    """Staircase (threshold, CDF) points for one node under its DECLARED
    distribution model: empirical cells use their saved sorted samples
    (F = rank/n); normal and lognormal cells use a quantile ladder."""
    fam = prof.get('family', 'normal')
    if fam == 'empirical':
        s = sorted(prof['lat_sorted'])
        n = len(s)
        return tuple((float(v), (i + 1) / n) for i, v in enumerate(s))
    if fam == 'lognormal':
        ml, sl = float(prof['mu_log']), float(prof['sigma_log'])
        return tuple((math.exp(ml + z * sl), normal_cdf(z))
                     for z in _PHI_LADDER)
    mu, p90 = float(prof['lat_mean_s']), float(prof['lat_p90_s'])
    sig = (p90 - mu) / 1.2816
    if sig <= 0:
        return ((mu, 1.0),)
    return tuple((mu + z * sig, normal_cdf(z)) for z in _PHI_LADDER)


def _staircase_bound(ladders, budget: float) -> float:
    """max over thresholds t_i of  prod_i F_i(t_i)  s.t.  sum t_i <=
    budget, t_i drawn from node i's ladder. Under the DECLARED per-node
    distributions and independence the event {X_i <= t_i for all i}
    implies T = sum X_i <= sum t_i <= budget, so the product is a valid
    lower bound on P(T <= budget) — valid CONDITIONAL ON THE DECLARED
    MODELS, never claimed distribution-free. This replaces the invalid
    quantile-sum claim (per-node P90s do NOT bound the path P90 for
    general laws: two independent {0 w.p. .9, 100 w.p. .1} nodes have
    P90_i = 0 but path on-time at d=1 is .81, not >= .90)."""
    if budget < 0 or not ladders:
        return 0.0
    cand = sorted({0.0} | {t for lad in ladders for t, _ in lad})
    best = [1.0] * len(cand)          # no nodes placed yet: product 1
    for lad in ladders:
        nxt = [0.0] * len(cand)
        for b, cap in enumerate(cand):
            m = 0.0
            for t, f in lad:
                if t > cap:
                    break
                j = bisect.bisect_right(cand, cap - t) - 1
                if j >= 0:
                    v = best[j] * f
                    if v > m:
                        m = v
            nxt[b] = m
        best = nxt
        if not any(best):
            return 0.0
    # read the DP at the ACTUAL budget, not the largest candidate
    return best[bisect.bisect_right(cand, budget) - 1]


def e1_on_time(mu_service: float, p90_service: float, deadline: float, *,
               family: str = 'normal', log_params: Tuple = (),
               ladders: Tuple = (), shift: float = 0.0
               ) -> Tuple[float, float]:
    """Estimator E1 — UNIFIED service-side interface (round 3 fix #4):
    mu_service/p90_service are SERVICE-side (no deterministic addends);
    `shift` (switch overhead + contention) is applied EXACTLY ONCE,
    inside this function. Returns (P_on_time, E_lateness).

    Each family's accuracy claim is INDEPENDENT and stated separately
    (round 3 fix #6 — no approximation is ever labeled a strict bound):

    * 'normal' — PARAMETRIC ESTIMATE under the declared normal family:
      sigma=(p90-mu)/1.2816, normal CDF, closed-form E[(T-d)+]. No
      distribution-free guarantee. (Default family; identical results
      to the historical (mu_total, p90_total, d) call convention.)
    * 'lognormal' — Fenton–Wilkinson moment-matched path APPROXIMATION
      over `log_params` (sum of lognormals is not lognormal); closed
      form CDF and partial expectation, deterministic shift subtracted
      from the deadline. An approximation, not a bound.
    * 'empirical' — a LOWER BOUND on P(T<=d), valid conditional on the
      DECLARED per-node empirical distributions plus independence
      (staircase product bound), combined with Markov's inequality on
      the service time (T_service >= 0, P(T_service > d_eff) <=
      mu_service/d_eff — valid conditional on the declared mean):
        p_on = max( staircase(ladders, d_eff),  1 - mu_service/d_eff )
      No unconditional 0.90 claim is ever made (the quantile-sum form
      was INVALID and is removed — see _staircase_bound). e_late is the
      valid UPPER bound E[(T-d)+] <= E[T_service] - min(0, d_eff):
      mu_service when d_eff >= 0 (since (x-d)+ <= x for x >= 0), and
      mu_service - d_eff when d_eff < 0 (lateness is then certain)."""
    if family == 'lognormal' and log_params:
        return _lognormal_path(log_params, shift, deadline)
    if family == 'empirical':
        d_eff = deadline - shift
        if d_eff < 0:
            return 0.0, mu_service - d_eff   # certain lateness
        bounds = []
        if d_eff > 0:
            bounds.append(max(0.0, 1.0 - mu_service / d_eff))  # Markov
        stair = _staircase_bound(ladders, d_eff)
        if stair > 0.0:
            bounds.append(stair)
        if not bounds:
            return 0.0, mu_service
        return max(bounds), mu_service
    mu = mu_service + shift
    p90 = p90_service + shift
    sigma = (p90 - mu) / 1.2816
    if sigma <= 0:
        on_time = 1.0 if mu <= deadline else 0.0
        late = max(0.0, mu - deadline)
        return on_time, late
    on_time = normal_cdf((deadline - mu) / sigma)
    z = (mu - deadline) / sigma
    late = sigma * (normal_pdf(z) + z * normal_cdf(z))
    return on_time, max(0.0, late)
