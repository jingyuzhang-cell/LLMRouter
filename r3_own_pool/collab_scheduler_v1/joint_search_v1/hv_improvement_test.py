"""Targeted HV improvement test: Q=1 + lower C/L → positive improvement expected.

Scenario: All observed configs have Q=1.0 (same quality) but VARYING C and L.
Some unevaluated candidates have LOWER C and L → they should produce positive
HV improvement in the C/L dimensions even though Q is unchanged. A dominated
negative control (higher C AND higher L than an observed point) should score 0.

Tests both proposed (MC-EHVI) and BoTorch qNEHVI on the SAME frozen scales,
reference point, and observations.
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from sa_pgfs_v1.pareto import hypervolume, non_dominated  # noqa

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'

# Same frozen scales
Q_SCALE = (0.0, 1.0)
C_SCALE = (0.0, 2500.0)
L_SCALE = (0.0, 12.0)
REF = (0.0, 0.0, 0.0)


def norm(val, scale):
    return np.clip((val - scale[0]) / (scale[1] - scale[0]), 0.0, 1.0)


def make_scenario():
    """4 observed (Q=1, varying C/L) + 3 test candidates:
       BETTER: same Q, lower C and L → positive HV improvement expected
       DOMINATED: same Q, higher C and L → zero improvement expected
       L_ONLY: same Q, same C, lower L → positive improvement in L dim"""
    obs = [
        dict(id='obs_1', Q=1.0, C=800, L=2.0),
        dict(id='obs_2', Q=1.0, C=500, L=4.0),
        dict(id='obs_3', Q=1.0, C=1200, L=1.0),
        dict(id='obs_4', Q=1.0, C=300, L=6.0),
    ]
    candidates = [
        dict(id='BETTER_lowCL', Q_est=1.0, C_est=150, L_est=0.5,
             expect='positive'),
        dict(id='DOMINATED_highCL', Q_est=1.0, C_est=1500, L_est=8.0,
             expect='zero'),
        dict(id='L_ONLY_lowL', Q_est=1.0, C_est=500, L_est=0.5,
             expect='positive'),
    ]
    return obs, candidates


def to_3d(Q, C, L):
    return np.array([norm(Q, Q_SCALE),
                     1.0 - norm(C, C_SCALE),
                     1.0 - norm(L, L_SCALE)])


def direct_hv_improvement(obs, cand_3d):
    """Exact HV improvement (no sampling): add candidate to front, compute delta."""
    obs_3d = np.array([to_3d(o['Q'], o['C'], o['L']) for o in obs])
    front = obs_3d[non_dominated(obs_3d)]
    base_hv = hypervolume(front, ref=REF)
    combined = np.vstack([front, cand_3d])
    new_front = combined[non_dominated(combined)]
    new_hv = hypervolume(new_front, ref=REF)
    return new_hv - base_hv


def proposed_mc_ehvi(obs, candidates, n_mc=100, seed=99):
    """MC-EHVI: sample Q from a GP-like posterior around Q_est."""
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

    X_obs = np.array([[o['C'] / 2500, o['L'] / 12] for o in obs])
    y_obs = np.array([o['Q'] for o in obs])

    kernel = ConstantKernel(0.2) * Matern(nu=1.5, length_scale=np.ones(2)) \
        + WhiteKernel(0.01)
    gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True,
                                  n_restarts_optimizer=1, random_state=0)
    gp.fit(X_obs, y_obs)

    obs_3d = np.array([to_3d(o['Q'], o['C'], o['L']) for o in obs])
    front = obs_3d[non_dominated(obs_3d)]
    base_hv = hypervolume(front, ref=REF)

    rng = np.random.default_rng(seed)
    X_cand = np.array([[c['C_est'] / 2500, c['L_est'] / 12] for c in candidates])
    mu, sigma = gp.predict(X_cand, return_std=True)

    scores = {}
    for k, c in enumerate(candidates):
        total = 0.0
        cand_3d = to_3d(c['Q_est'], c['C_est'], c['L_est'])
        for s in range(n_mc):
            q_s = np.clip(mu[k] + sigma[k] * rng.standard_normal(), 0, 1)
            pt = np.array([q_s, cand_3d[1], cand_3d[2]])  # sample Q, fix C/L
            combined = np.vstack([front, pt])
            nd = non_dominated(combined)
            total += max(0, hypervolume(combined[nd], ref=REF) - base_hv)
        scores[c['id']] = total / n_mc
    return scores


def botorch_qnehvi_3d(obs, candidates):
    """BoTorch qNEHVI on 3D."""
    import torch
    from botorch.acquisition.multi_objective import (
        qNoisyExpectedHypervolumeImprovement)
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.sampling.normal import SobolQMCNormalSampler
    from gpytorch.mlls import ExactMarginalLogLikelihood

    obs_3d = np.array([to_3d(o['Q'], o['C'], o['L']) for o in obs])
    cand_3d = np.array([to_3d(c['Q_est'], c['C_est'], c['L_est'])
                        for c in candidates])

    X_train = torch.tensor(
        np.array([[o['C'] / 2500, o['L'] / 12] for o in obs]),
        dtype=torch.double)
    Y_train = torch.tensor(obs_3d, dtype=torch.double)
    X_cand = torch.tensor(
        np.array([[c['C_est'] / 2500, c['L_est'] / 12] for c in candidates]),
        dtype=torch.double)

    gp = SingleTaskGP(X_train, Y_train)
    mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
    fit_gpytorch_mll(mll)

    ref = torch.tensor(REF, dtype=torch.double)
    sampler = SobolQMCNormalSampler(sample_shape=torch.Size([32]))
    acq = qNoisyExpectedHypervolumeImprovement(
        model=gp, ref_point=ref, X_baseline=X_train, sampler=sampler)

    gp.eval()
    scores = {}
    with torch.no_grad():
        for i, c in enumerate(candidates):
            scores[c['id']] = float(acq(X_cand[i].reshape(1, 1, -1)).item())
    return scores


def run():
    obs, candidates = make_scenario()

    # Compute 3D points
    obs_3d = np.array([to_3d(o['Q'], o['C'], o['L']) for o in obs])
    front = obs_3d[non_dominated(obs_3d)]
    print('Observed 3D points (Q, -C, -L):')
    for o, p in zip(obs, obs_3d):
        marker = ' *FRONT*' if any(np.all(p == f) for f in front) else ''
        print(f'  {o["id"]}: ({p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f}){marker}')
    base_hv = hypervolume(front, ref=REF)
    print(f'Front HV: {base_hv:.6f}')

    # Exact HV improvement (no sampling)
    print('\n--- Exact HV improvement (deterministic, no sampling) ---')
    exact = {}
    for c in candidates:
        cand_3d = to_3d(c['Q_est'], c['C_est'], c['L_est'])
        imp = direct_hv_improvement(obs, cand_3d)
        exact[c['id']] = imp
        print(f'  {c["id"]:20s} 3D={cand_3d.round(3)} → improvement={imp:.6f} '
              f'({"POSITIVE" if imp > 1e-10 else "ZERO"}) [expect: {c["expect"]}]')

    # Proposed MC-EHVI
    print('\n--- Proposed MC-EHVI ---')
    prop_scores = proposed_mc_ehvi(obs, candidates)
    for c in candidates:
        v = prop_scores[c['id']]
        print(f'  {c["id"]:20s} score={v:.6f} '
              f'({"POSITIVE" if v > 1e-10 else "ZERO"}) [expect: {c["expect"]}]')

    # BoTorch qNEHVI
    print('\n--- BoTorch qNEHVI ---')
    try:
        bot_scores = botorch_qnehvi_3d(obs, candidates)
        bot_ok = True
        for c in candidates:
            v = bot_scores[c['id']]
            print(f'  {c["id"]:20s} score={v:.6f} '
                  f'({"POSITIVE" if v > 1e-10 else "ZERO"}) [expect: {c["expect"]}]')
    except Exception as e:
        print(f'  FAILED: {type(e).__name__}: {str(e)[:100]}')
        bot_scores, bot_ok = {}, False

    # Verification
    checks = {}
    for c in candidates:
        cid = c['id']
        expected_positive = c['expect'] == 'positive'
        checks[f'exact_{cid}_correct'] = bool(
            (exact[cid] > 1e-10) == expected_positive)
        checks[f'proposed_{cid}_correct'] = bool(
            (prop_scores[cid] > 1e-10) == expected_positive)
        if bot_ok:
            checks[f'botorch_{cid}_correct'] = bool(
                (bot_scores[cid] > 1e-10) == expected_positive)

    checks['front_nonempty'] = bool(len(front) > 0)
    checks['base_hv_positive'] = bool(base_hv > 0)

    all_pass = bool(all(checks.values()))
    result = dict(
        scenario=dict(obs=obs, candidates=candidates, front_size=len(front),
                      base_hv=float(base_hv)),
        exact_improvement=exact,
        proposed_scores=prop_scores,
        botorch_scores=bot_scores if bot_ok else 'FAILED',
        checks=checks, all_pass=all_pass,
        zero_model_calls=True)
    (OUT / 'HV_IMPROVEMENT_TEST.json').write_text(json.dumps(result, indent=1))
    print(f'\nChecks: {sum(checks.values())}/{len(checks)}')
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'{"ALL PASS" if all_pass else "FAIL PRESENT"}')


if __name__ == '__main__':
    run()
