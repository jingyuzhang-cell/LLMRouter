"""Acquisition functions: MC-EHVI and cost-aware EHVI.

Objectives in maximization form: (Q, 1-C/C_ref, 1-L/L_ref), reference HV point
at the origin. C and L of a candidate are deterministic; only Q is sampled
from the surrogate posterior. Cost-aware variant divides EHVI by the REAL
evaluation cost of running that graph (its token budget):
    a(G) = EHVI(G) / C_eval(G)
'per unit of real evaluation cost, how much Pareto hypervolume do we expect
to gain' — the acquisition that fits expensive LLM workflow evaluation.
"""
import numpy as np

from .pareto import hypervolume


def _sample_q(mu, sigma, n, rng):
    z = rng.standard_normal((n, len(mu)))
    return np.clip(mu + sigma * z, 0.0, 1.0)


def ehvi(mu, sigma, cand_obj, front_pts, n_samples=48, rng=None, eval_costs=None):
    """Vectorized MC-EHVI (optionally cost-aware) over candidates.

    mu, sigma: surrogate posterior for candidate Q (arrays).
    cand_obj: (n, 3) deterministic objectives (Q slot ignored, C/L used).
    front_pts: (k, 3) current non-dominated evaluated objectives.
    eval_costs: optional (n,) real-evaluation cost; returns EHVI / cost.
    """
    rng = rng or np.random.default_rng(0)
    front_hv = hypervolume(front_pts)
    qs = _sample_q(mu, sigma, n_samples, rng)
    base = cand_obj.copy()
    out = np.zeros(len(mu))
    for s in range(n_samples):
        base[:, 0] = qs[:, s]
        # improvement of adding each candidate alone (independent batches)
        for i in range(len(mu)):
            out[i] += hypervolume(np.vstack([front_pts, base[i]])) - front_hv
    out /= n_samples
    if eval_costs is not None:
        out = out / np.maximum(eval_costs, 1e-9)
    return out
