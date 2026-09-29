"""Regression tests for the acquisition.ehvi axis fix (2026-09-27).

The bug: `base[:, 0] = qs[:, s]` indexed the CANDIDATE axis instead of the
SAMPLE axis (qs is (n_samples, n_cand)) — crashes unless n_samples happens to
equal n_cand, and silently misassigns otherwise. These tests pin the fixed
semantics; T1 fails on the old code by construction (n_samples != n_cand).

Run: python3 -m sa_pgfs_v1.test_acquisition_regression
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sa_pgfs_v1.acquisition import ehvi  # noqa: E402
from sa_pgfs_v1.pareto import hypervolume  # noqa: E402


def t1_axis_correctness():
    """n_samples != n_cand must work; zero-sigma EHVI == exact HV gain."""
    front = np.array([[0.8, 0.8, 0.8], [0.5, 0.9, 0.9]])
    cand = np.array([[0.9, 0.5, 0.5], [0.4, 0.95, 0.95], [0.6, 0.6, 0.6]])
    mu = np.array([0.85, 0.45, 0.55])
    got = ehvi(mu, np.zeros(3), cand, front, n_samples=17,
               rng=np.random.default_rng(0))
    for i in range(3):
        exact = hypervolume(np.vstack([front, [mu[i], *cand[i][1:]]])) \
            - hypervolume(front)
        assert abs(got[i] - exact) < 1e-12, (i, got[i], exact)
    print('T1 axis correctness (n_samples=17 != n_cand=3, zero-sigma exact): PASS')


def t2_dominated_candidate_zero_gain():
    front = np.array([[0.9, 0.9, 0.9]])
    cand = np.array([[0.2, 0.2, 0.2]])  # dominated everywhere
    got = ehvi(np.array([0.2]), np.array([0.0]), cand, front, n_samples=9,
               rng=np.random.default_rng(0))
    assert abs(got[0]) < 1e-12, got
    print('T2 fully dominated candidate -> EHVI 0: PASS')


def t3_monotone_in_mu():
    front = np.array([[0.7, 0.8, 0.8]])
    cand = np.array([[0.75, 0.85, 0.85]])
    lo = ehvi(np.array([0.60]), np.array([0.05]), cand, front, n_samples=400,
              rng=np.random.default_rng(1))[0]
    hi = ehvi(np.array([0.90]), np.array([0.05]), cand, front, n_samples=400,
              rng=np.random.default_rng(1))[0]
    assert hi > lo + 1e-4, (lo, hi)
    print(f'T3 EHVI monotone in mu ({lo:.4f} < {hi:.4f}): PASS')


def t4_cost_aware_scaling():
    front = np.array([[0.7, 0.8, 0.8]])
    cand = np.array([[0.8, 0.85, 0.85], [0.8, 0.85, 0.85]])
    base = ehvi(np.array([0.8, 0.8]), np.array([0.0]), cand, front, n_samples=8,
                rng=np.random.default_rng(0))
    div = ehvi(np.array([0.8, 0.8]), np.array([0.0]), cand, front, n_samples=8,
               rng=np.random.default_rng(0), eval_costs=np.array([2.0, 0.5]))
    assert np.allclose(div, base / np.array([2.0, 0.5])), (base, div)
    print('T4 cost-aware division: PASS')


def t5_identical_candidates_symmetry():
    """With sigma=0 identical candidates must score identically (exact);
    with sigma>0 they draw independent MC noise, so only exactness holds."""
    front = np.array([[0.6, 0.7, 0.7]])
    cand = np.tile([0.7, 0.8, 0.8], (4, 1))
    got = ehvi(np.full(4, 0.7), np.zeros(4), cand, front, n_samples=13,
               rng=np.random.default_rng(2))
    assert np.ptp(got) < 1e-12, got
    exact = hypervolume(np.vstack([front, [0.7, 0.8, 0.8]])) - hypervolume(front)
    assert abs(got[0] - exact) < 1e-12, (got[0], exact)
    print('T5 identical candidates (zero-sigma exact + symmetric): PASS')


if __name__ == '__main__':
    t1_axis_correctness()
    t2_dominated_candidate_zero_gain()
    t3_monotone_in_mu()
    t4_cost_aware_scaling()
    t5_identical_candidates_symmetry()
    print('ALL EHVI REGRESSION TESTS PASS')
