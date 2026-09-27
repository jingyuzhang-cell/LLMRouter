"""Dual archive: Pareto archive (convergence) + diversity archive (exploration).

Diversity scoring follows MEoH's dominance-dissimilarity idea, adapted from
code-AST distance to GRAPH distance D(G_i, G_j) (node/edge/depth/policy mix):
a dominated graph is penalized by each dominator proportionally to their
STRUCTURAL SIMILARITY — near-duplicates of a dominator die, structurally
novel dominated graphs survive for exploration and later LLM mutation.
"""
import numpy as np

from .pareto import dominates, non_dominated


class DualArchive:
    def __init__(self, max_diverse=12):
        self.points = []    # (graph, obj3) evaluated, obj in max form
        self.max_diverse = max_diverse

    def add(self, graph, obj):
        self.points.append((graph, np.asarray(obj, dtype=float)))

    def pareto_front(self):
        objs = np.array([o for _, o in self.points])
        idx = non_dominated(objs)
        return idx, objs[idx]

    def hv(self):
        _, front = self.pareto_front()
        from .pareto import hypervolume
        return hypervolume(front)

    def dominance_dissimilarity(self):
        """MEoH-style score per member: 0 (best) if non-dominated; else
        sum over dominators of -(1 - D(g, g_dom)) (near-duplicate penalized)."""
        objs = np.array([o for _, o in self.points])
        nd = set(non_dominated(objs))
        scores = np.zeros(len(self.points))
        for i in range(len(self.points)):
            if i in nd:
                continue
            pen = 0.0
            for j in range(len(self.points)):
                if j != i and dominates(objs[j], objs[i]):
                    pen -= (1.0 - self.points[i][0].distance(self.points[j][0]))
            scores[i] = pen
        return scores

    def diverse_pool(self):
        """Top-K by dominance-dissimilarity (all non-dominated included first)."""
        scores = self.dominance_dissimilarity()
        order = sorted(range(len(self.points)), key=lambda i: -scores[i])
        keep = order[:self.max_diverse]
        return [self.points[i] for i in sorted(keep)]
