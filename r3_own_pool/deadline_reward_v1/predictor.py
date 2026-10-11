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
    # log_params = (mu_log, sigma_log) for lognormal nodes. The composed
    # family drives e1_on_time: all-lognormal -> Fenton-Wilkinson path
    # lognormal; any empirical node -> distribution-free Cantelli bound.
    families: Tuple[str, ...] = ()
    log_params: Tuple[Tuple[float, float], ...] = ()


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
        # any empirical node -> distribution-free bound; else normal
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
                                 if composed == 'lognormal' else ())


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


def e1_on_time(mu: float, p90: float, deadline: float, *,
               family: str = 'normal', log_params: Tuple = (),
               shift: float = 0.0) -> Tuple[float, float]:
    """Estimator E1 (CORRECTED rev A formula). Returns (P_on_time,
    E_lateness). Degenerate σ≤0 → point mass at μ.

    2026-10-11 admission repair #4 — family consistency: `family`
    selects the estimator. 'normal' (default; unchanged behavior when
    omitted — the stub/golden profiles are declared normal);
    'lognormal' uses the Fenton–Wilkinson path approximation over
    `log_params` (per-node (mu_log, sigma_log)) plus the deterministic
    `shift` — a parametric APPROXIMATION, labeled as such.

    'empirical' (REVISED after the operator's 2026-10-11 counterexample
    — the previous Cantelli-at-sigma-LB form was INVALID): Cantelli's
    upper bound on lateness is INCREASING in sigma, so substituting a
    sigma LOWER bound yields an over-optimistic number, not a lower
    bound (two-point law {0: .5, 100: .5}: true P(T<=90)=.5, the old
    formula returned .852). Only distribution-free statements valid for
    ANY law are used now:
      * quantile: d >= p90  =>  P(T <= d) >= P(T <= p90) >= 0.90
        (p90 is the quantile_sum path upper bound under the frozen
        independence caveat, so this inherits that caveat);
      * Markov (T >= 0):    P(T > d) <= mu / d   =>  P(T <= d) >= 1-mu/d;
      the reported p_on is the MAX of the applicable valid bounds, and
      0 when neither applies (d <= mu).
    e_late for the empirical family is the valid UPPER bound
    E[(T-d)+] <= E[T] = mu (T >= 0) — loose, but never an underestimate;
    mu-d would only be a lower bound and is never reported as an
    estimate. The mean fed in must be the family-true mean (lognormal
    mean exp(mu+sig^2/2) or the empirical sample mean) — never
    p50-by-default."""
    if family == 'lognormal' and log_params:
        return _lognormal_path(log_params, shift, deadline)
    if family == 'empirical':
        d_eff = deadline - shift
        bounds = []
        if d_eff >= p90:
            bounds.append(0.90)               # quantile definition
        if d_eff > 0:
            bounds.append(max(0.0, 1.0 - mu / d_eff))   # Markov, T >= 0
        p_on = max(bounds) if bounds else 0.0
        return p_on, mu            # valid upper bound: E[(T-d)+] <= mu
    sigma = (p90 - mu) / 1.2816
    if sigma <= 0:
        on_time = 1.0 if mu <= deadline else 0.0
        late = max(0.0, mu - deadline)
        return on_time, late
    on_time = normal_cdf((deadline - mu) / sigma)
    z = (mu - deadline) / sigma
    late = sigma * (normal_pdf(z) + z * normal_cdf(z))
    return on_time, max(0.0, late)
