"""Regression tests for pareto.hypervolume (2026-09-27 fix).

The previous 2D/3D branches returned the box of a single extreme point and
violated monotonicity under point addition. These tests pin exact known
values, monotonicity, and cross-check against a brute-force grid integral
on random point sets.

Run: python3 -m sa_pgfs_v1.test_pareto_regression
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sa_pgfs_v1.pareto import hypervolume  # noqa: E402


def t1_known_2d():
    assert abs(hypervolume(np.array([[0.6, 0.85], [0.7, 0.8]]), ref=(0, 0)) - 0.59) < 1e-12
    assert abs(hypervolume(np.array([[0.7, 0.8]]), ref=(0, 0)) - 0.56) < 1e-12
    # chain front (x asc, y asc after anti-sort): {(0.6,0.8),(0.7,0.85)}
    assert abs(hypervolume(np.array([[0.6, 0.8], [0.7, 0.85]]), ref=(0, 0)) - 0.595) < 1e-12
    # dominated point must not change the value
    a = np.array([[0.6, 0.85], [0.7, 0.8]])
    b = np.vstack([a, [0.5, 0.5]])
    assert abs(hypervolume(a, ref=(0, 0)) - hypervolume(b, ref=(0, 0))) < 1e-12
    print('T1 2D known values + domination invariance: PASS')


def t2_known_3d():
    pts = np.array([[0.7, 0.8, 0.8], [0.6, 0.85, 0.85]])
    # z in [0.8,0.85]: xy-front {0.6x0.85}=0.51 ; z in [0,0.8]: union 0.59
    assert abs(hypervolume(pts, ref=(0, 0, 0)) - (0.59 * 0.8 + 0.51 * 0.05)) < 1e-12
    assert abs(hypervolume(np.array([[0.7, 0.8, 0.8]]), ref=(0, 0, 0)) - 0.448) < 1e-12
    # tie z-levels merge in xy: {(0.7,0.8,0.5),(0.6,0.9,0.5)} -> 2D union at z 0..0.5
    pts = np.array([[0.7, 0.8, 0.5], [0.6, 0.9, 0.5]])
    area = 0.6 * 0.9 + 0.1 * 0.8  # x<0.6 -> 0.9 ; 0.6..0.7 -> 0.8
    assert abs(hypervolume(pts, ref=(0, 0, 0)) - area * 0.5) < 1e-12
    print('T2 3D known values + z-tie merge: PASS')


def t3_monotonicity():
    rng = np.random.default_rng(0)
    for _ in range(200):
        pts = rng.random((5, 3))
        h1 = hypervolume(pts, ref=(0, 0, 0))
        h2 = hypervolume(np.vstack([pts, rng.random(3)]), ref=(0, 0, 0))
        assert h2 >= h1 - 1e-12, (h1, h2, pts)
        pts2 = rng.random((5, 2))
        g1 = hypervolume(pts2, ref=(0, 0))
        g2 = hypervolume(np.vstack([pts2, rng.random(2)]), ref=(0, 0))
        assert g2 >= g1 - 1e-12, (g1, g2, pts2)
    print('T3 monotonicity under point addition (200 random cases): PASS')


def t4_bruteforce_crosscheck():
    """Grid-integral cross-check on random 2D/3D sets (coarse but unbiased)."""
    rng = np.random.default_rng(1)
    for _ in range(5):
        pts = rng.random((4, 3))
        xs = np.linspace(1e-3, 1, 60)
        vol = 0.0
        for z in xs:
            for y in xs:
                w = max([p[0] for p in pts if p[1] >= y and p[2] >= z], default=0.0)
                vol += w * (xs[1] - xs[0]) ** 2
        got = hypervolume(pts, ref=(0, 0, 0))
        assert abs(got - vol) < 0.02, (got, vol, pts)
    print('T4 3D brute-force grid cross-check (5 random sets): PASS')


if __name__ == '__main__':
    t1_known_2d()
    t2_known_3d()
    t3_monotonicity()
    t4_bruteforce_crosscheck()
    print('ALL PARETO HV REGRESSION TESTS PASS')
