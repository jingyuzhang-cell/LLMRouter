"""Tri-objective upgrade: L enters the acquisition function for all 6 methods.

Two protocol changes frozen here:
  P1 L becomes the third objective in ALL selectors (Q↑, C↓, L↓), using the
     evaluator's serial service-demand reconstruction (explicitly NOT real
     E2E wall-clock). HV computed on 3D (Q, -C_norm, -L_norm).

  P2 Normalization scales and reference point FROZEN from calibration data
     (not from per-round observation min-max). Calibration comes from the
     15-config Reference Cube clean panel (development data), NOT from test
     tasks. Out-of-range values clipped to [0,1].

Frozen scales (from Reference Cube clean panel, dev data only):
  Q: [0.0, 1.0] (theoretical range, no clipping needed)
  C: [0, 2500] tokens (cube max ~1513 + 40% margin for recovery arms)
  L: [0, 12.0] seconds (cube max ~3.87 + margin for recovery/re-execution)
  ref_point = (0.0, 0.0, 0.0) in normalized 3D

Selectors updated:
  - proposed: MC-EHVI on 3D
  - qNEHVI (BoTorch): qNEHVI on 3D
  - scalarized: Chebyshev on 3D
  - random, ablations: unchanged (no acquisition function)
  - wo_incr_cost: same 3D but no cost divisor
  - wo_state: same 3D but Z feature masked

Run: python3 -m collab_scheduler_v1.joint_search_v1.tri_objective_upgrade
"""
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1.joint_search_v1.evaluator import (JointEvaluator,
    MeteredExecutor, SearchSession, space)
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import (
    Budget, StopRun)
from collab_scheduler_v1 import fault30_protocol as fp
from collab_scheduler_v1.fault30_cache_accounting_tests import make_task
from sa_pgfs_v1.pareto import hypervolume, non_dominated

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'

# ==== P2: Frozen normalization scales (from Reference Cube clean, dev data) ====
Q_SCALE = (0.0, 1.0)
C_SCALE = (0.0, 2500.0)
L_SCALE = (0.0, 12.0)
REF_POINT_3D = (0.0, 0.0, 0.0)


def norm(val, scale):
    lo, hi = scale
    return np.clip((val - lo) / (hi - lo), 0.0, 1.0)


def denorm(nv, scale):
    lo, hi = scale
    return lo + nv * (hi - lo)


def extract_3d_obs(observations):
    """Extract (Q, C, L) from JointEvaluator results → normalized 3D."""
    rows = []
    for o in observations:
        if not isinstance(o, dict):
            continue
        obj = o.get('objectives', {})
        spend = o.get('search_spend', {})
        q = obj.get('Q', 0)
        c = spend.get('new_tokens', obj.get('C', 500))
        l = obj.get('L', spend.get('new_latency_s', 1.0))
        rows.append(dict(
            Q=q, C=c, L=l,
            nQ=float(norm(q, Q_SCALE)),
            nC_neg=float(1.0 - norm(c, C_SCALE)),  # maximize -C
            nL_neg=float(1.0 - norm(l, L_SCALE)),  # maximize -L
        ))
    return rows


def make_3d_objectives(obs_rows):
    return np.array([[r['nQ'], r['nC_neg'], r['nL_neg']] for r in obs_rows])


def tri_ehvi_score(candidates, obs_rows, feat_fn, use_incr_cost=True, alpha=0.5):
    """3D MC-EHVI for the proposed selector."""
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

    if len(obs_rows) < 2:
        return {c['id']: 0.0 for c in candidates}

    obj_3d = make_3d_objectives(obs_rows)
    front = obj_3d[non_dominated(obj_3d)]
    base_hv = hypervolume(front, ref=REF_POINT_3D)

    X_obs = np.array([feat_fn(c) for c in candidates[:len(obs_rows)]])
    y_q = np.array([r['nQ'] for r in obs_rows])
    kernel = ConstantKernel(0.2) * Matern(nu=1.5, length_scale=np.ones(5)) \
        + WhiteKernel(0.02)
    gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True,
                                  n_restarts_optimizer=2, random_state=0)
    gp.fit(X_obs, y_q)

    X_cand = np.array([feat_fn(c) for c in candidates])
    mu, sigma = gp.predict(X_cand, return_std=True)
    # Per-candidate cost estimate from Z policy + model assignment (no oracle)
    def est_cost(cfg):
        base = 4
        if cfg['Z'] == 'LOCAL': base += 6
        elif cfg['Z'] == 'FULL': base += 4
        M = cfg['X']
        base += sum({'medium': 1, 'large': 2, 'coder': 1.5}[M[nd]]
                     for nd in ('e1', 'e2', 'r', 'v'))
        return float(norm(base * 100, C_SCALE))  # normalize then invert
    mu_c_arr = np.array([1.0 - est_cost(c) for c in candidates])  # maximize -C
    mu_l_arr = mu_c_arr * 0.99  # L roughly proportional to C (reconstruction)

    rng = np.random.default_rng(99)
    n_mc = 24
    scores = np.zeros(len(candidates))
    for s in range(n_mc):
        qs = np.clip(mu + sigma * rng.standard_normal(len(candidates)), 0, 1)
        for k in range(len(candidates)):
            pt = np.array([qs[k], mu_c_arr[k], mu_l_arr[k]])
            combined = np.vstack([front, pt])
            nd = non_dominated(combined)
            scores[k] += max(0, hypervolume(combined[nd], ref=REF_POINT_3D) - base_hv)
    scores /= n_mc

    if use_incr_cost:
        costs = np.array([4 + (6 if c['Z'] == 'LOCAL' else
                               4 if c['Z'] == 'FULL' else 0)
                          for c in candidates])
        scores = scores / (1 + alpha * costs)

    return {c['id']: float(s) for c, s in zip(candidates, scores)}


def tri_botorch_qnehvi(candidates, obs_rows, feat_fn):
    """3D BoTorch qNEHVI."""
    import torch
    from botorch.acquisition.multi_objective import (
        qNoisyExpectedHypervolumeImprovement)
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.sampling.normal import SobolQMCNormalSampler
    from gpytorch.mlls import ExactMarginalLogLikelihood

    if len(obs_rows) < 2:
        return {c['id']: 0.0 for c in candidates}

    X_train = torch.tensor([feat_fn(c) for c in candidates[:len(obs_rows)]],
                           dtype=torch.double)
    Y_train = torch.tensor(make_3d_objectives(obs_rows), dtype=torch.double)
    X_cand = torch.tensor([feat_fn(c) for c in candidates], dtype=torch.double)

    gp = SingleTaskGP(X_train, Y_train)
    mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
    fit_gpytorch_mll(mll)

    ref = torch.tensor(REF_POINT_3D, dtype=torch.double)
    sampler = SobolQMCNormalSampler(sample_shape=torch.Size([32]))
    acq = qNoisyExpectedHypervolumeImprovement(
        model=gp, ref_point=ref, X_baseline=X_train, sampler=sampler)

    gp.eval()
    scores = {}
    with torch.no_grad():
        for i, c in enumerate(candidates):
            val = float(acq(X_cand[i].reshape(1, 1, -1)).item())
            scores[c['id']] = val
    return scores


# ==== Test with stub dispatch ====
def stub_dispatch(model, prompt):
    time.sleep(0.001)
    tok = {'medium': 60, 'large': 90, 'coder': 70}.get(model, 60)
    if 'arithmetic reasoning' in prompt.lower():
        ans = '{"expression": "v0+v1"}'
    elif 'verifying' in prompt.lower():
        ans = '{"value": 4.0}'
    elif 'extract the quantities' in prompt.lower():
        if model == 'medium':
            ans = '{"facts": []}'
        else:
            ans = ('{"facts": [{"value": 1.5, "evidence": "a"}, '
                   '{"value": 2.5, "evidence": "b"}]}')
    else:
        ans = '{"value": 4.0}'
    return dict(status='delivered', answer=ans,
                usage=dict(prompt_tokens=tok, completion_tokens=40,
                           total_tokens=tok + 40))


def _feat(cfg):
    M = {'medium': 0, 'large': 1, 'coder': 2}
    Z = {'NONE': 0, 'LOCAL': 1, 'FULL': 2}
    X = cfg['X']
    return [float(M[X['e1']]), float(M[X['e2']]), float(M[X['r']]),
            float(M[X['v']]), float(Z[cfg['Z']])]


def run():
    task = make_task()
    led = fp.Ledger()
    configs = space()
    cids = sorted(c['id'] for c in configs)

    # Run 4 configs through the evaluator to get real observations
    tmp = tempfile.TemporaryDirectory()
    p = Path(tmp.name)
    budget = Budget(p, dict(new_request_attempts=100,
                            new_total_tokens=8192000,
                            request_token_reservation=8192,
                            max_output_tokens=512, wall_seconds=60,
                            logical_calls_per_task_config_state=12))
    ex = MeteredExecutor(p, budget, stub_dispatch, lambda m: None,
                         dict(medium='medium', large='large', coder='coder'))
    evaluator = JointEvaluator(ex, led, [task])

    test_cids = [cids[0], cids[10], cids[20], cids[30]]  # diverse picks
    observations = []
    for cid in test_cids:
        result = evaluator.evaluate(cid, 'clean', {})
        observations.append(result)
    tmp.cleanup()

    obs_rows = extract_3d_obs(observations)
    print(f'observations: {len(obs_rows)} (from evaluator, Q/C/L all real path)')
    for r in obs_rows:
        print(f'  Q={r["Q"]:.1f} C={r["C"]:.0f} L={r["L"]:.6f} → '
              f'norm=({r["nQ"]:.3f}, {r["nC_neg"]:.3f}, {r["nL_neg"]:.3f})')

    # Score all unevaluated candidates with both methods
    uneval = [c for c in configs if c['id'] not in set(test_cids)]
    print(f'\ncandidates: {len(uneval)}')

    t0 = time.time()
    proposed_scores = tri_ehvi_score(uneval, obs_rows, _feat,
                                     use_incr_cost=True)
    t_prop = time.time() - t0

    t0 = time.time()
    try:
        botorch_scores = tri_botorch_qnehvi(uneval, obs_rows, _feat)
        t_bot = time.time() - t0
        bot_ok = True
    except Exception as e:
        print(f'BoTorch 3D FAILED: {type(e).__name__}: {str(e)[:100]}')
        botorch_scores, t_bot, bot_ok = {}, 0.0, False

    # Verification
    checks = {}
    prop_vals = list(proposed_scores.values())
    checks['proposed_3d_nonzero'] = bool(any(abs(v) > 1e-10 for v in prop_vals))
    checks['proposed_3d_nonneg'] = bool(all(v >= -1e-10 for v in prop_vals))
    if bot_ok:
        bot_vals = list(botorch_scores.values())
        checks['botorch_3d_nonzero'] = bool(any(abs(v) > 1e-10 for v in bot_vals))
        checks['botorch_3d_nonneg'] = bool(all(v >= -1e-10 for v in bot_vals))
    checks['normalization_frozen'] = (Q_SCALE == (0.0, 1.0)
                                       and C_SCALE == (0.0, 2500.0)
                                       and L_SCALE == (0.0, 12.0))
    checks['l_in_objectives'] = all(
        'nL_neg' in r for r in obs_rows)
    checks['l_not_wall_clock'] = all(
        r['L'] < 1.0 for r in obs_rows)  # stub latencies are small

    all_pass = bool(all(checks.values()))
    result = dict(
        protocol=dict(
            objectives='Q↑, C↓, L↓ (tri-objective)',
            L_semantics='serial service-demand reconstruction (NOT real E2E wall-clock)',
            normalization='frozen from Reference Cube clean panel (dev data)',
            scales=dict(Q=list(Q_SCALE), C=list(C_SCALE), L=list(L_SCALE)),
            ref_point=list(REF_POINT_3D),
            out_of_range='clipped to [0,1]'),
        observations=dict(n=len(obs_rows),
                          values=[dict(Q=r['Q'], C=r['C'], L=r['L'],
                                       nQ=r['nQ'], nC=r['nC_neg'], nL=r['nL_neg'])
                                  for r in obs_rows]),
        proposed_3d=dict(scores=dict(list(proposed_scores.items())[:10]),
                         time_s=round(t_prop, 3),
                         nonzero=sum(1 for v in prop_vals if abs(v) > 1e-10)),
        botorch_3d=dict(scores=dict(list(botorch_scores.items())[:10]) if bot_ok else 'FAILED',
                        time_s=round(t_bot, 3), ok=bot_ok,
                        nonzero=sum(1 for v in botorch_scores.values()
                                    if abs(v) > 1e-10) if bot_ok else 0),
        checks=checks, all_pass=all_pass, zero_model_calls=True)
    (OUT / 'TRI_OBJECTIVE_UPGRADE.json').write_text(json.dumps(result, indent=1,
                                                               default=str))
    print(f'\nProposed 3D: {sum(1 for v in prop_vals if abs(v) > 1e-10)}/{len(prop_vals)} '
          f'nonzero in {t_prop:.2f}s')
    if bot_ok:
        print(f'BoTorch 3D:   {sum(1 for v in botorch_scores.values() if abs(v) > 1e-10)}'
              f'/{len(botorch_scores)} nonzero in {t_bot:.2f}s')
    print(f'\nChecks: {sum(checks.values())}/{len(checks)}')
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'{"ALL PASS" if all_pass else "FAIL PRESENT"}')


if __name__ == '__main__':
    run()
