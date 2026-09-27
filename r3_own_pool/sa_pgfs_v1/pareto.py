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
    """Exact hypervolume in 2D or 3D, maximization form, via slicing."""
    pts = np.asarray([p for p in np.asarray(points, dtype=float)
                      if np.all(p > np.asarray(ref))], dtype=float)
    if not len(pts):
        return 0.0
    ref = np.asarray(ref, dtype=float)
    d = pts.shape[1]
    if d == 2:
        order = np.argsort(pts[:, 0])
        hv, best_x = 0.0, ref[1]
        for p in pts[order]:
            if p[1] > best_x:
                hv += (p[0] - ref[0]) * (p[1] - best_x)
                best_x = p[1]
        return float(hv)
    if d == 3:
        order = np.argsort(-pts[:, 2])  # descend z
        hv, best_z = 0.0, ref[2]
        slices = []
        for p in pts[order]:
            if p[2] > best_z:
                dz = p[2] - best_z
                slices = np.array(slices) if len(slices) else np.zeros((0, 2))
                merged = np.vstack([slices, [p[0], p[1]]]) if len(slices) else p[:2].reshape(1, 2)
                hv += hypervolume(merged, ref=ref[:2]) * dz
                keep = non_dominated(merged)
                slices = merged[keep]
                best_z = p[2]
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
