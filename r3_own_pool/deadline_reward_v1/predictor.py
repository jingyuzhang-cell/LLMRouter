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


def _profile(priors: dict, node: str, model: str) -> dict:
    prof = (priors.get('node_profiles', {}).get(f'{node}|{model}')
            or priors['profiles'][f'{node}|{model}'])
    return prof


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
        return ActionPrediction(q_mean=round(q, 10),
                                 d_cost_tokens=cost,
                                 mu_service_s=round(mu, 10),
                                 w_p90_s=round(p90, 10))


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def e1_on_time(mu: float, p90: float, deadline: float) -> Tuple[float, float]:
    """Estimator E1 (CORRECTED rev A formula). Returns (P_on_time,
    E_lateness). Degenerate σ≤0 → point mass at μ."""
    sigma = (p90 - mu) / 1.2816
    if sigma <= 0:
        on_time = 1.0 if mu <= deadline else 0.0
        late = max(0.0, mu - deadline)
        return on_time, late
    on_time = normal_cdf((deadline - mu) / sigma)
    z = (mu - deadline) / sigma
    late = sigma * (normal_pdf(z) + z * normal_cdf(z))
    return on_time, max(0.0, late)
