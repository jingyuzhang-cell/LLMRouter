"""Graph individual G = (Y, X, Z, M) for SA-PGFS.

Y topology: named template from space.TOPOLOGIES (nodes carry roles and DAG
  edges); X model assignment: role-slot -> model; Z recovery: none|switch;
  M reuse policy: fresh|reuse_extraction.

φ(G) features feed the Q surrogate; D(G,G') is the structural distance used
by the diversity archive (MEoH-style dominance-dissimilarity, graphs instead
of code ASTs).
"""
import numpy as np

MODELS = ['medium', 'large', 'coder']


class Graph:
    __slots__ = ('topo', 'assign', 'recovery', 'reuse', 'gid')

    def __init__(self, topo, assign, recovery, reuse):
        self.topo = topo            # dict: id, nodes[(role,slot)], edges, parallel
        self.assign = dict(assign)  # slot -> model
        self.recovery = recovery    # 'none' | 'switch'
        self.reuse = reuse          # 'fresh' | 'reuse_extraction'
        self.gid = (topo['id'], tuple(sorted(assign.items())), recovery, reuse)

    def __repr__(self):
        return f'G({self.topo["id"]}|{self.assign}|{self.recovery[:3]}|{self.reuse[:2]})'

    def features(self, C=None, L=None):
        """φ(G), FIXED LENGTH across topologies: structural counts/flags plus
        per-role model histograms (3 bins each: extraction, reasoning,
        verification/judge), deterministic C/L when provided."""
        roles = [r for r, _ in self.topo['nodes']]
        t = self.topo

        def hist(role):
            h = np.zeros(3)
            for slot, m in self.assign.items():
                if next(r for r, s in t['nodes'] if s == slot) == role:
                    h[MODELS.index(m)] += 1
            n = h.sum()
            return h / n if n else h

        f = [len(t['nodes']), len(t['edges']), t['depth'], t['width'],
             roles.count('extraction'), roles.count('reasoning'),
             roles.count('verification') + roles.count('judge'),
             1.0 if 'dual_r' in t['id'] else 0.0,
             1.0 if 'SERJ' in t['id'] else 0.0,
             1.0 if self.recovery == 'switch' else 0.0,
             1.0 if self.reuse != 'fresh' else 0.0]
        f += list(hist('extraction')) + list(hist('reasoning')) + \
            list(hist('verification') + hist('judge'))
        if C is not None:
            f += [C / 6000.0, L / 10.0]
        return np.array(f, dtype=float)

    def distance(self, other):
        """D_graph: node-set Jaccard + edge-set Jaccard + depth diff + policy diff."""
        a, b = self.topo, other.topo
        na = {r for r, _ in a['nodes']}
        nb = {r for r, _ in b['nodes']}
        dn = 1.0 - len(na & nb) / max(1, len(na | nb))
        ea, eb = set(map(tuple, a['edges'])), set(map(tuple, b['edges']))
        de = 1.0 - len(ea & eb) / max(1, len(ea | eb))
        dd = abs(a['depth'] - b['depth']) / 3.0
        same_slots = set(self.assign) & set(other.assign)
        dm = (sum(self.assign[s] != other.assign[s] for s in same_slots) /
              max(1, len(set(self.assign) | set(other.assign))))
        dz = float(self.recovery != other.recovery)
        dzm = float(self.reuse != other.reuse)
        return 0.25 * dn + 0.25 * de + 0.15 * min(dd, 1.0) + 0.15 * dm + 0.1 * dz + 0.1 * dzm
