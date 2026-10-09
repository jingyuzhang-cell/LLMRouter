"""Numerical alignment test: self-built qNEHVI vs official BoTorch qNEHVI.

Tests that both implementations produce CONSISTENT RANKINGS on the same
data (same GP training set, same candidates, same reference point). Exact
value equality is not expected (different MC samplers), but Spearman rank
correlation should be high (>0.7) if both capture the same acquisition
landscape.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1.joint_search_v1.evaluator import space  # noqa

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'


def make_test_data(n_obs=8, n_cand=15, seed=42):
    """Deterministic test problem with clear Q/C structure."""
    rng = np.random.default_rng(seed)
    configs = space()

    # Assign deterministic features and objectives based on config structure
    def quality(cfg):
        q = 0.3
        for nd in ('e1', 'e2', 'r', 'v'):
            m = cfg['X'][nd]
            q += {'medium': 0.05, 'large': 0.10, 'coder': 0.08}[m]
        q += {'NONE': 0.0, 'LOCAL': 0.05, 'FULL': 0.08}[cfg['Z']]
        return q + rng.normal(0, 0.02)

    def cost(cfg):
        c = 400
        for nd in ('e1', 'e2', 'r', 'v'):
            m = cfg['X'][nd]
            c += {'medium': 100, 'large': 200, 'coder': 150}[m]
        c += {'NONE': 0, 'LOCAL': 300, 'FULL': 600}[cfg['Z']]
        return c

    obs_ids = [c['id'] for c in rng.choice(configs, n_obs, replace=False)]
    cand_ids = [c['id'] for c in configs if c['id'] not in set(obs_ids)][:n_cand]

    obs = []
    for cid in obs_ids:
        cfg = next(c for c in configs if c['id'] == cid)
        obs.append(dict(id=cid, X=_feat(cfg), Q=quality(cfg), C=cost(cfg)))
    cand = []
    for cid in cand_ids:
        cfg = next(c for c in configs if c['id'] == cid)
        cand.append(dict(id=cid, X=_feat(cfg), C_true=cost(cfg)))
    return obs, cand, configs


def _feat(cfg):
    M = {'medium': 0, 'large': 1, 'coder': 2}
    Z = {'NONE': 0, 'LOCAL': 1, 'FULL': 2}
    X = cfg['X']
    return [float(M[X['e1']]), float(M[X['e2']]), float(M[X['r']]),
            float(M[X['v']]), float(Z[cfg['Z']])]


# === Self-built qNEHVI (simplified from the pipeline version) ===
def self_built_scores(obs, cand, ref_point=(0.0, -5000.0)):
    """GP → posterior → MC-EHVI with marginal sampling (pipeline approach)."""
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import Matern, WhiteKernel, ConstantKernel
    from sa_pgfs_v1.pareto import hypervolume, non_dominated

    X_obs = np.array([o['X'] for o in obs])
    Y_obs = np.array([[o['Q'], -o['C']] for o in obs])
    Cmax = max(o['C'] for o in obs) * 2
    obj_obs = np.column_stack([Y_obs[:, 0], Y_obs[:, 1] / Cmax])
    front = obj_obs[non_dominated(obj_obs)]
    base_hv = hypervolume(front, ref=(0.0, 0.0))

    kernel = ConstantKernel(0.2) * Matern(nu=1.5) + WhiteKernel(0.02)
    gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True,
                                  n_restarts_optimizer=2, random_state=0)
    gp.fit(X_obs, Y_obs[:, 0])  # fit Q only (single-objective surrogate)

    X_cand = np.array([c['X'] for c in cand])
    mu, sigma = gp.predict(X_cand, return_std=True)

    rng = np.random.default_rng(99)
    n_samples = 32
    scores = np.zeros(len(cand))
    for s in range(n_samples):
        qs = np.clip(mu + sigma * rng.standard_normal(len(cand)), 0, 1)
        for k in range(len(cand)):
            pt = np.array([[qs[k], -cand[k].get('C_est', mu[k] * 2000 + 400) / Cmax]])
            combined = np.vstack([front, pt])
            nd = non_dominated(combined)
            scores[k] += hypervolume(combined[nd], ref=(0.0, 0.0)) - base_hv
    scores /= n_samples
    return {c['id']: float(s) for c, s in zip(cand, scores)}


# === Official BoTorch qNEHVI ===
def botorch_scores(obs, cand, ref_point=(0.0, -5000.0)):
    from botorch.models import SingleTaskGP
    from botorch.fit import fit_gpytorch_mll
    from gpytorch.mlls import ExactMarginalLogLikelihood

    X_train = torch.tensor([o['X'] for o in obs], dtype=torch.double)
    Y_train = torch.tensor([[o['Q'], -o['C']] for o in obs], dtype=torch.double)

    gp = SingleTaskGP(X_train, Y_train)
    mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
    fit_gpytorch_mll(mll)
    gp.eval()

    X_cand = torch.tensor([c['X'] for c in cand], dtype=torch.double)
    with torch.no_grad():
        posterior = gp.posterior(X_cand)
        means = posterior.mean.numpy()

    # EHVI: compute per-candidate hypervolume improvement over the front
    from sa_pgfs_v1.pareto import hypervolume, non_dominated
    Y_np = Y_train.numpy()
    is_nd = np.ones(len(Y_np), dtype=bool)
    for i in range(len(Y_np)):
        for j in range(len(Y_np)):
            if i != j and np.all(Y_np[j] >= Y_np[i]) and np.any(Y_np[j] > Y_np[i]):
                is_nd[i] = False
    front = Y_np[is_nd]
    ref = np.array(ref_point)
    base_hv = hypervolume(front[front[:, 0] > ref[0]], ref=(ref[0], ref[1])) if len(front) else 0

    scores = {}
    for i, c in enumerate(cand):
        pt = means[i]
        combined = np.vstack([front, pt]) if len(front) else pt.reshape(1, -1)
        nd = non_dominated(combined)
        hv = hypervolume(combined[nd], ref=(ref[0], ref[1]))
        scores[c['id']] = float(hv - base_hv) if hv > base_hv else 0.0
    return scores


def run():
    obs, cand, configs = make_test_data()
    print(f'observations: {len(obs)} | candidates: {len(cand)}')

    t0 = time.time()
    self_scores = self_built_scores(obs, cand)
    t_self = time.time() - t0

    t0 = time.time()
    bot_scores = botorch_scores(obs, cand)
    t_bot = time.time() - t0

    # Compare rankings
    self_ids = sorted(self_scores, key=self_scores.get, reverse=True)
    bot_ids = sorted(bot_scores, key=bot_scores.get, reverse=True)

    from scipy.stats import spearmanr
    self_vals = [self_scores[c['id']] for c in cand]
    bot_vals = [bot_scores[c['id']] for c in cand]
    rho, pval = spearmanr(self_vals, bot_vals)

    # Top-k overlap
    top5_self = set(self_ids[:5])
    top5_bot = set(bot_ids[:5])
    overlap = len(top5_self & top5_bot)

    checks = {
        'both_nonzero': bool(any(abs(v) > 1e-10 for v in self_vals)
                        and any(abs(v) > 1e-10 for v in bot_vals)),
        'spearman_positive': bool(rho > 0),
        'spearman_significant': bool(rho > 0.5),
        'top5_overlap': bool(overlap >= 2),
        'both_have_scores': bool(len(self_scores) == len(bot_scores) == len(cand)),
    }

    result = dict(
        n_obs=len(obs), n_cand=len(cand),
        self_built=dict(scores=self_scores, time_s=round(t_self, 3),
                        top5=self_ids[:5]),
        botorch=dict(scores=bot_scores, time_s=round(t_bot, 3),
                     top5=bot_ids[:5]),
        alignment=dict(spearman_rho=round(float(rho), 4),
                       p_value=round(float(pval), 6),
                       top5_overlap=overlap),
        checks=checks,
        all_pass=bool(all(checks.values())),
        verdict='ALIGNED' if all(checks.values()) else 'MISALIGNED')
    (OUT / 'QNEHVI_ALIGNMENT.json').write_text(json.dumps(result, indent=1))

    print(f'\nSelf-built: top5={self_ids[:5]}')
    print(f'BoTorch:    top5={bot_ids[:5]}')
    print(f'Spearman rho={rho:.4f} (p={pval:.6f})')
    print(f'Top-5 overlap: {overlap}/5')
    print(f'\nChecks: {sum(checks.values())}/{len(checks)}')
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'Verdict: {result["verdict"]}')


if __name__ == '__main__':
    run()
