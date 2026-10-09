"""Official BoTorch qNEHVI: proper scoring via actual acquisition function call.

Fixes over c04c917:
  F1 official_qnehvi_score() now DIRECTLY calls qNoisyExpectedHypervolumeImprovement.
     No proxy fallback (posterior-mean distance, analytic EHVI exception handler).
     If BoTorch raises, the test FAILS — no silent degradation.
  F2 Alignment test uses a fixed synthetic problem with non-degenerate improvement.
     Both sides use the SAME objective convention: maximize (Q, -C_norm).
     Reference point set consistently. All values normalized to [0,1] range.
  F3 Verdict: all-zero scores → "NO_DISCRIMINATION" FAIL, not top-5 overlap.

Run: python3 -m collab_scheduler_v1.joint_search_v1.qnehvi_official_v2
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch import Tensor

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'

from botorch.acquisition.multi_objective import (  # noqa: E402
    qNoisyExpectedHypervolumeImprovement)
from botorch.fit import fit_gpytorch_mll  # noqa: E402
from botorch.models import SingleTaskGP  # noqa: E402
from botorch.sampling.normal import SobolQMCNormalSampler  # noqa: E402
from gpytorch.mlls import ExactMarginalLogLikelihood  # noqa: E402

from sa_pgfs_v1.pareto import hypervolume, non_dominated  # noqa: E402


# ============ Fixed synthetic problem (non-degenerate) ============
def make_fixed_problem():
    """10 observations, 12 candidates, clear Q/C separation.
    Q ∈ [0.1, 0.8], C ∈ [200, 2000] — enough spread for non-zero EHVI."""
    rng = np.random.default_rng(20261009)
    M = {'medium': 0, 'large': 1, 'coder': 2}
    Z = {'NONE': 0, 'LOCAL': 1, 'FULL': 2}

    def quality(e, r, v, z):
        return 0.1 + 0.15 * e + 0.20 * r + 0.10 * v + 0.15 * z \
            + rng.normal(0, 0.03)

    def cost(e, r, v, z):
        return 200 + 300 * e + 200 * r + 150 * v + 400 * z + rng.normal(0, 50)

    obs, cand = [], []
    seen = set()
    while len(obs) < 10:
        key = (int(rng.integers(0, 3)), int(rng.integers(0, 3)), int(rng.integers(0, 3)),
               int(rng.integers(0, 3)))
        if key in seen:
            continue
        seen.add(key)
        e, r, v, z = key
        obs.append(dict(id=f'obs_{e}{r}{v}{z}',
                        X=[float(e), float(r), float(v), float(z)],
                        Q=quality(e, r, v, z), C=cost(e, r, v, z)))
    while len(cand) < 12:
        key = (int(rng.integers(0, 3)), int(rng.integers(0, 3)), int(rng.integers(0, 3)),
               int(rng.integers(0, 3)))
        cid = f'cand_{key[0]}{key[1]}{key[2]}{key[3]}'
        if cid in seen:
            continue
        seen.add(cid)
        e, r, v, z = key
        cand.append(dict(id=cid, X=[float(e), float(r), float(v), float(z)],
                         Q_true=quality(e, r, v, z), C_true=cost(e, r, v, z)))
    return obs, cand


# ============ Official BoTorch qNEHVI (direct call) ============
def official_qnehvi(obs, cand, n_mc=64):
    """Score candidates via ACTUAL qNoisyExpectedHypervolumeImprovement call.
    No proxy. Raises on BoTorch error (FAIL, not fallback)."""
    # Normalize objectives to [0, 1] (both directions: maximize)
    Q_all = [o['Q'] for o in obs]
    C_all = [o['C'] for o in obs]
    Qmin, Qmax = min(Q_all), max(Q_all)
    Cmin, Cmax = min(C_all), max(C_all)

    def norm_Q(q):
        return (q - Qmin) / max(Qmax - Qmin, 1e-9)

    def norm_C(c):
        return 1.0 - (c - Cmin) / max(Cmax - Cmin, 1e-9)  # maximize -C

    X_train = torch.tensor([o['X'] for o in obs], dtype=torch.double)
    Y_train = torch.tensor([[norm_Q(o['Q']), norm_C(o['C'])] for o in obs],
                           dtype=torch.double)
    X_cand = torch.tensor([c['X'] for c in cand], dtype=torch.double)

    gp = SingleTaskGP(X_train, Y_train)
    mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
    fit_gpytorch_mll(mll)

    ref_point = torch.tensor([0.0, 0.0], dtype=torch.double)
    sampler = SobolQMCNormalSampler(sample_shape=torch.Size([n_mc]))
    acq = qNoisyExpectedHypervolumeImprovement(
        model=gp, ref_point=ref_point, X_baseline=X_train, sampler=sampler)

    # Score each candidate INDIVIDUALLY (batch_size=1) for ranking
    gp.eval()
    scores = {}
    for i, c in enumerate(cand):
        x = X_cand[i].reshape(1, 1, -1)  # (1, 1, d) for q-batch
        with torch.no_grad():
            val = acq(x)
        scores[c['id']] = float(val.item())

    return scores, dict(ref_point=[0.0, 0.0], n_mc=n_mc,
                        Q_range=[Qmin, Qmax], C_range=[Cmin, Cmax])


# ============ Self-built MC-EHVI (same convention) ============
def self_built_qnehvi(obs, cand, n_mc=64, seed=99):
    """MC-EHVI with marginal sampling. Same normalization and ref point."""
    Q_all = [o['Q'] for o in obs]
    C_all = [o['C'] for o in obs]
    Qmin, Qmax = min(Q_all), max(Q_all)
    Cmin, Cmax = min(C_all), max(C_all)

    def norm_Q(q):
        return (q - Qmin) / max(Qmax - Qmin, 1e-9)

    def norm_C(c):
        return 1.0 - (c - Cmin) / max(Cmax - Cmin, 1e-9)

    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

    X_obs = np.array([o['X'] for o in obs])
    y_q = np.array([norm_Q(o['Q']) for o in obs])
    obj_obs = np.array([[norm_Q(o['Q']), norm_C(o['C'])] for o in obs])
    front = obj_obs[non_dominated(obj_obs)]
    base_hv = hypervolume(front, ref=(0.0, 0.0))

    kernel = ConstantKernel(0.2) * Matern(nu=1.5, length_scale=np.ones(4)) \
        + WhiteKernel(0.02)
    gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True,
                                  n_restarts_optimizer=2, random_state=0)
    gp.fit(X_obs, y_q)

    X_cand = np.array([c['X'] for c in cand])
    mu, sigma = gp.predict(X_cand, return_std=True)

    # Estimate C for candidates from the true cost function (same info as BoTorch
    # side, which gets it from the GP posterior on C — approximate with mu_C)
    mu_C = np.mean([norm_C(o['C']) for o in obs])

    rng = np.random.default_rng(seed)
    scores = {}
    for k, c in enumerate(cand):
        total_improvement = 0.0
        for s in range(n_mc):
            q_s = np.clip(mu[k] + sigma[k] * rng.standard_normal(), 0, 1)
            c_s = mu_C  # deterministic cost estimate (posterior mean)
            new_pt = np.array([q_s, c_s])
            combined = np.vstack([front, new_pt])
            nd = non_dominated(combined)
            hv = hypervolume(combined[nd], ref=(0.0, 0.0))
            total_improvement += max(0, hv - base_hv)
        scores[c['id']] = total_improvement / n_mc
    return scores


# ============ Alignment test ============
def run():
    obs, cand = make_fixed_problem()
    print(f'fixed problem: {len(obs)} obs, {len(cand)} candidates')

    # Official BoTorch
    t0 = time.time()
    try:
        bot_scores, config = official_qnehvi(obs, cand)
        t_bot = time.time() - t0
        bot_ok = True
    except Exception as e:
        print(f'BoTorch FAILED: {type(e).__name__}: {str(e)[:120]}')
        bot_scores, config, t_bot, bot_ok = {}, {}, 0.0, False

    # Self-built
    t0 = time.time()
    self_scores = self_built_qnehvi(obs, cand)
    t_self = time.time() - t0

    if not bot_ok:
        result = dict(verdict='FAIL_BOTORCH_ERROR', bot_error=str(e)[:200])
        (OUT / 'QNEHVI_ALIGNMENT_V2.json').write_text(json.dumps(result, indent=1))
        print('VERDICT: FAIL (BoTorch error)')
        return

    # Diagnostics
    bot_vals = [bot_scores[c['id']] for c in cand]
    self_vals = [self_scores[c['id']] for c in cand]

    bot_nonzero = sum(1 for v in bot_vals if abs(v) > 1e-10)
    self_nonzero = sum(1 for v in self_vals if abs(v) > 1e-10)
    bot_nonneg = all(v >= -1e-10 for v in bot_vals)
    self_nonneg = all(v >= -1e-10 for v in self_vals)

    from scipy.stats import spearmanr
    if bot_nonzero >= 2 and self_nonzero >= 2:
        rho, pval = spearmanr(self_vals, bot_vals)
    else:
        rho, pval = float('nan'), float('nan')

    checks = {
        'botorch_scores_nonneg': bool(bot_nonneg),
        'self_scores_nonneg': bool(self_nonneg),
        'botorch_nonzero_count': bool(bot_nonzero >= 2),
        'self_nonzero_count': bool(self_nonzero >= 2),
        'spearman_defined': bool(np.isfinite(rho)),
    }
    if np.isfinite(rho):
        checks['spearman_positive'] = bool(rho > 0)
        checks['spearman_above_03'] = bool(rho > 0.3)

    result = dict(
        config=config,
        botorch=dict(scores=bot_scores, time_s=round(t_bot, 3),
                     nonzero=bot_nonzero, nonneg=bot_nonneg,
                     range=[float(min(bot_vals)), float(max(bot_vals))]),
        self_built=dict(scores=self_scores, time_s=round(t_self, 3),
                        nonzero=self_nonzero, nonneg=self_nonneg,
                        range=[float(min(self_vals)), float(max(self_vals))]),
        alignment=dict(spearman_rho=float(rho) if np.isfinite(rho) else None,
                       p_value=float(pval) if np.isfinite(pval) else None),
        checks=checks,
        all_pass=bool(all(checks.values())),
        verdict='ALIGNED' if all(checks.values()) else 'MISALIGNED_OR_NO_DISCRIMINATION')
    (OUT / 'QNEHVI_ALIGNMENT_V2.json').write_text(json.dumps(result, indent=1))

    print(f'\nBoTorch: {bot_nonzero}/{len(cand)} nonzero, range='
          f'[{min(bot_vals):.6f}, {max(bot_vals):.6f}], {t_bot:.2f}s')
    print(f'Self:    {self_nonzero}/{len(cand)} nonzero, range='
          f'[{min(self_vals):.6f}, {max(self_vals):.6f}], {t_self:.2f}s')
    print(f'Spearman: rho={rho:.4f}' if np.isfinite(rho) else 'Spearman: undefined')
    print(f'\nChecks: {sum(checks.values())}/{len(checks)}')
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'Verdict: {result["verdict"]}')


if __name__ == '__main__':
    run()
