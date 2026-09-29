"""Pareto primitives for SA-PGFS: dominance, 3D hypervolume, knee, selection.

Objectives are always handled in maximization form (Q, -C, -L). All routines
assume objectives normalized to ~[0,1] with reference point at the origin.
"""
import numpy as np


def dominates(a, b):
    """a dominates b iff a >= b componentwise and a > b somewhere."""
    return bool(np.all(a >= b) and np.any(a > b))


def non_dominated(points):
    """Return indices of the non-dominated subset (O(n^2), n is small here)."""
    pts = np.asarray(points, dtype=float)
    keep = []
    for i in range(len(pts)):
        if not any(dominates(pts[j], pts[i]) for j in range(len(pts)) if j != i):
            keep.append(i)
    return keep


def hypervolume(points, ref=(0.0, 0.0, 0.0)):
    """Exact hypervolume in 2D or 3D, maximization form, via slicing.

    2026-09-27 fix: both previous branches effectively returned the box of a
    single extreme point (2D: asc-x sweep with `y > best_y` never fires again
    on a front, where x asc implies y desc; 3D: desc-z with `z > best_z`
    processes only the highest-z point) and could DECREASE when a point was
    added. Corrected to the standard staircase sweeps, pinned by
    test_pareto_regression.py.
    """
    pts = np.asarray([p for p in np.asarray(points, dtype=float)
                      if np.all(p > np.asarray(ref))], dtype=float)
    if not len(pts):
        return 0.0
    ref = np.asarray(ref, dtype=float)
    d = pts.shape[1]
    if d == 2:
        # covered width at height band = max{x : q.x >= band top}; sweep x DESC,
        # band [p.x, prev_x] uses the max y of already-seen (x >= prev_x) points
        order = np.argsort(-pts[:, 0])
        hv, max_y, prev_x = 0.0, 0.0, None
        for p in pts[order]:
            if prev_x is not None and prev_x > p[0]:
                hv += (prev_x - p[0]) * max_y
            max_y = max(max_y, p[1])
            prev_x = p[0]
        hv += (prev_x - ref[0]) * max_y
        return float(hv)
    if d == 3:
        # sweep z DESC; band [p.z, prev_z] is covered by the 2D front of points
        # with z >= prev_z (slices BEFORE adding p); bottom band uses the union
        order = np.argsort(-pts[:, 2])
        hv, prev_z = 0.0, None
        slices = np.zeros((0, 2))
        for p in pts[order]:
            if prev_z is not None and prev_z > p[2]:
                hv += hypervolume(slices, ref=ref[:2]) * (prev_z - p[2])
            merged = np.vstack([slices, p[:2]]) if len(slices) else p[:2].reshape(1, 2)
            slices = merged[non_dominated(merged)]
            prev_z = p[2]
        hv += hypervolume(slices, ref=ref[:2]) * (prev_z - ref[2])
        return float(hv)
    raise ValueError('only 2D/3D supported')


def hv_contribution(points, i):
    """Loss in HV if point i is removed (0 for duplicated points)."""
    pts = [p for j, p in enumerate(points) if j != i]
    return max(0.0, hypervolume(points) - hypervolume(pts))


def knee_point(points):
    """Index of the knee: max distance to the line through the Q-extreme and
    the (-C,-L)-extreme (cheapest) points of the front (2D Q-vs-cost view)."""
    pts = np.asarray(points, dtype=float)
    cost = 1.0 - pts[:, 1]  # second objective normalized -C
    q = pts[:, 0]
    hi = int(np.argmax(q))
    lo = int(np.argmax(cost))
    if hi == lo:
        return hi
    p1, p2 = np.array([q[hi], cost[hi]]), np.array([q[lo], cost[lo]])
    line = p2 - p1
    n = np.hypot(*line)
    if n < 1e-12:
        return hi
    dist = [abs(np.cross(line, np.array([q[i], cost[i]]) - p1)) / n for i in range(len(pts))]
    return int(np.argmax(dist))


def select_budget(points, budgets, costs, latencies=None):
    """Budget-constrained selection: argmax Q subject to C <= B (and L <= Lmax)."""
    ok = [i for i in range(len(points)) if costs[i] <= budgets[0]
          and (latencies is None or latencies[i] <= budgets[1])]
    return max(ok, key=lambda i: points[i][0]) if ok else None


def select_weighted(points, w):
    """Preference-conditioned selection w=(w_Q,w_C,w_L) over a Pareto set."""
    scores = [w[0] * p[0] + w[1] * p[1] + w[2] * p[2] for p in points]
    return int(np.argmax(scores))
