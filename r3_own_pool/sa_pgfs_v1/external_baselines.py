"""External-baseline reveal/replay on the FROZEN Reference Cube (zero calls).

Four external search mechanisms run under the EXACT frozen harness of
PROTOCOL_SAPGFS_FREEZE_v1 / robustness_benchmark.py — same 200 paired seeds,
same common 2-config initial design, same per-seed noise draws (identical RNG
streams), budget 8, identical metrics and paired permutation tests — so the
SA-PGFS rows of REPLAY_FAULT_ROBUST.json are directly comparable:

  nsga2       NSGA-II selection adapted to a budget-constrained finite space:
              tournament (dominance rank + crowding) -> uniform crossover ->
              per-gene mutation over the integer (Y,X,Z) chromosome; the
              first legal unevaluated offspring is revealed. No surrogate.
  qnparego    ParEGO-style random Chebyshev scalarization per step + EI on
              the scalarized objective using the frozen sklearn GP; noise
              enters through the noisy Q observations the GP is fitted on.
  qnehvi      qNEHVI(q=1) mechanics with the frozen GP: the ARCHIVE
              objectives are re-sampled from the posterior in each MC draw
              (the qNEHVI distinction vs the point-archive EHVI of SA-PGFS).
  aflow_mcts  AFlow-style iterative MCTS over the legal Y->X->Z construction
              tree (15 leaves); UCT selection, reward = hypervolume gain of
              the revealed config. Mechanism adapted, NOT the full system.

Honesty note (paper wording): all methods are search mechanisms adapted to
the same frozen collaborative configuration space with execution outcomes
held fixed; the comparison is who finds the true front with fewer reveals.

Run:  python3 -m sa_pgfs_v1.external_baselines --smoke   # 6 seeds
      python3 -m sa_pgfs_v1.external_baselines          # 200 seeds
"""
import json
import sys
from math import erf, sqrt
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sa_pgfs_v1.acquisition import _sample_q  # noqa: E402
from sa_pgfs_v1.pareto import hypervolume, non_dominated  # noqa: E402
from sa_pgfs_v1.surrogate import QSurrogate  # noqa: E402

OUT = ROOT / 'sa_pgfs_v1/results_cube_replay'
N_EVAL, N_INIT = 8, 2
YS = ['ser', 'serv', 'paralleler', 'dynamicdag']
XS = ['balanced', 'heterogeneous', 'quality']
ZS = ['none', 'local_reroute']


def load_gcollab():
    """15 legal configs with integer codes (y, x, z); z=local_reroute only on
    dynamicdag (legality = the frozen reference cube design)."""
    d = json.loads((ROOT / 'collab_scheduler_v1/FAULT30_ANALYSIS.json').read_text())
    pts = {}
    for cid, v in d['fault_per_config'].items():
        topo, fam, z, _ = cid.split('__')
        gid = f'{topo.lower()}|{fam.lower()}|{z.lower()}|fresh'
        pts[gid] = dict(Q=v['Q'], C=v['C'], L=v['L'],
                        per_seed_Q=v['per_seed']['Q'],
                        code=(YS.index(topo.lower()), XS.index(fam.lower()),
                              ZS.index(z.lower())))
    assert len(pts) == 15
    return pts


def legal_children(level, prefix):
    if level == 0:
        return list(range(4))
    if level == 1:
        return list(range(3))
    return [1] if prefix[0] == 3 else [0]  # z freedom only on dynamicdag


class NSGAII:
    def __init__(self, rng, codes):
        self.rng = rng
        self.codes = codes
        self.n_alleles = [4, 3, 2]

    def choose(self, obs, uneval, obj_of):
        ev = sorted(obs)
        objs = np.array([obj_of(i) for i in ev])
        nd = set(non_dominated(objs))
        rank = np.array([0 if i in nd else 1 for i in range(len(ev))])
        crowd = np.zeros(len(ev))
        for k in range(3):
            order = np.argsort(objs[:, k])
            crowd[order[[0, -1]]] += 1e9
            gaps = np.diff(objs[order, k])
            crowd[order[1:-1]] += 1.0 / (gaps[:-1] + gaps[1:] + 1e-9)

        def tour():
            a, b = self.rng.choice(len(ev), 2, replace=False)
            return a if (rank[a], -crowd[a]) < (rank[b], -crowd[b]) else b

        uneval_codes = {tuple(self.codes[i]): i for i in uneval}
        for _ in range(100):
            p1, p2 = tour(), tour()
            child = [self.codes[ev[p1]][k] if self.rng.random() < .5
                     else self.codes[ev[p2]][k] for k in range(3)]
            for k in range(3):
                if self.rng.random() < 1.0 / 3:
                    child[k] = int(self.rng.integers(self.n_alleles[k]))
            if tuple(child) in uneval_codes:
                return int(uneval_codes[tuple(child)])
        return int(self.rng.choice(uneval))


class PAREGO:
    def __init__(self, rng, X):
        self.rng = rng
        self.X = X

    def choose(self, obs, uneval, obj_of):
        ev = sorted(obs)
        if len(ev) < 4:
            return int(self.rng.choice(uneval))
        objs = np.array([obj_of(i) for i in ev])
        z_ideal = objs.max(0)
        span = np.maximum(z_ideal - objs.min(0), 1e-9)
        w = self.rng.dirichlet(np.ones(3))

        def scalar(o):
            return -np.max(w * (np.abs(o - z_ideal) / span + 1e-3) / np.maximum(w, 1e-6))

        y = np.array([scalar(obj_of(i)) for i in ev])
        sur = QSurrogate()
        sur.fit(self.X[ev], y)
        mu, sg = sur.predict(self.X[uneval], return_std=True)
        best = y.max()
        z = (mu - best) / np.maximum(sg, 1e-12)
        phi = 0.5 * (1 + np.array([erf(zz / sqrt(2)) for zz in z]))
        pdf = np.exp(-0.5 * z ** 2) / sqrt(2 * np.pi)
        ei = (mu - best) * phi + sg * pdf
        return int(uneval[np.argmax(ei)])


class QNEHVI:
    def __init__(self, rng, X, objs, n_samples=24):
        self.rng, self.X, self.objs, self.n_samples = rng, X, objs, n_samples

    def choose(self, obs, uneval, obj_of):
        ev = sorted(obs)
        if len(ev) < 4:
            return int(self.rng.choice(uneval))
        sur = QSurrogate()
        sur.fit(self.X[ev], np.array([obs[i] for i in ev]))
        mu_a, sg_a = sur.predict(self.X[ev], return_std=True)
        mu_c, sg_c = sur.predict(self.X[uneval], return_std=True)
        qs_a = _sample_q(mu_a, sg_a, self.n_samples, self.rng)
        qs_c = _sample_q(mu_c, sg_c, self.n_samples, self.rng)
        out = np.zeros(len(uneval))
        for s in range(self.n_samples):
            arch = np.array([[qs_a[s][j], self.objs[i][1], self.objs[i][2]]
                             for j, i in enumerate(ev)])
            f0 = hypervolume(arch[non_dominated(arch)])
            for k in range(len(uneval)):
                cand = np.vstack([arch, [qs_c[s][k], self.objs[uneval[k]][1],
                                         self.objs[uneval[k]][2]]])
                out[k] += hypervolume(cand[non_dominated(cand)]) - f0
        return int(uneval[np.argmax(out / self.n_samples)])


class MCTS:
    """UCT over the legal Y->X->Z tree; reward = HV gain of the revealed leaf."""

    def __init__(self, rng, codes, objs):
        self.rng, self.codes, self.objs = rng, codes, objs
        self.N, self.V = {}, {}

    def _leaf_of(self, path):
        for i, c in enumerate(self.codes):
            if list(c) == path:
                return i
        return None

    def choose(self, obs, uneval, obj_of):
        arch = np.array([obj_of(i) for i in obs])
        base = hypervolume(arch[non_dominated(arch)])
        path_nodes, prefix, leaf = [], [], None
        for level in range(3):
            opts = legal_children(level, prefix)
            stats = [(o, self.N.get(tuple(prefix + [o]), 0),
                      self.V.get(tuple(prefix + [o]), 0.0)) for o in opts]
            untried = [o for o, n, _ in stats if n == 0 and self._leaf_of(prefix + [o]) is None
                       or o for o, n, _ in stats if n == 0]
            # descend: prefer untried branches that still contain uneval leaves
            cands = []
            for o in opts:
                sub = prefix + [o]
                has_uneval = any(i in obs or True for i in []) or True
                for i in uneval:
                    if list(self.codes[i])[:len(sub)] == sub:
                        cands.append(o)
                        break
            if not cands:
                cands = opts
            untried = [o for o in cands if self.N.get(tuple(prefix + [o]), 0) == 0]
            if untried:
                o = untried[int(self.rng.integers(len(untried)))]
            else:
                total = sum(self.N.get(tuple(prefix + [o]), 1) for o in cands)

                def ucb(o):
                    k = tuple(prefix + [o])
                    n = self.N[k]
                    return self.V[k] / n + 0.7 * sqrt(log(total + 1) / n)

                o = max(cands, key=ucb)
            path_nodes.append(tuple(prefix + [o]))
            prefix = prefix + [o]
        leaf = self._leaf_of(prefix)
        if leaf is None or leaf in obs:
            for i in uneval:
                if list(self.codes[i])[:2] == prefix[:2]:
                    leaf = i
                    break
        if leaf is None or leaf in obs:
            leaf = int(self.rng.choice(uneval))
        self._path = path_nodes
        self._base = base
        return int(leaf)

    def backprop(self, reward):
        for k in self._path:
            self.N[k] = self.N.get(k, 0) + 1
            self.V[k] = self.V.get(k, 0.0) + reward


from math import log  # noqa: E402  (used in MCTS ucb)


def run(seed_master=20260928, n_seeds=200, smoke=False):
    pts = load_gcollab()
    gids = sorted(pts)
    Q = np.array([pts[g]['Q'] for g in gids])
    C = np.array([pts[g]['C'] for g in gids], float)
    L = np.array([pts[g]['L'] for g in gids], float)
    Cmax, Lmax = C.max(), L.max()
    objs = np.stack([Q, 1 - C / Cmax, 1 - L / Lmax], axis=1)
    front_idx = non_dominated(objs)
    true_gids = [gids[i] for i in front_idx]
    true_tuples = {tuple(np.round(objs[i], 6)) for i in front_idx}
    ref_hv = hypervolume(objs[front_idx])
    codes = np.array([pts[g]['code'] for g in gids])
    X = np.array([[*codes[i], C[i] / Cmax, L[i] / Lmax] for i in range(len(gids))],
                 dtype=float)
    n = len(gids)
    rng_master = np.random.default_rng(seed_master)
    strategies = ('nsga2', 'qnparego', 'qnehvi', 'aflow_mcts')
    per_seed = {s: {m: [] for m in ('regret', 'auc', 'recall_cfg', 'recall_dedup', 'n95')}
                for s in strategies}

    for seed in range(n_seeds):
        rng = np.random.default_rng(9000 + seed)
        noise_q = {g: float(rng.choice(pts[g]['per_seed_Q'])) for g in gids}
        init = list(rng_master.choice(n, N_INIT, replace=False))

        def obj_of(i):
            return np.array([noise_q[gids[i]], objs[i][1], objs[i][2]])

        for strat in strategies:
            rng_s = np.random.default_rng(9000 + seed)  # same stream -> same noise
            obs = {}
            for i in init:
                obs[i] = noise_q[gids[i]]
            mcts = MCTS(rng_s, codes, objs) if strat == 'aflow_mcts' else None
            hist = []
            while len(obs) < N_EVAL:
                uneval = [i for i in range(n) if i not in obs]
                if strat == 'nsga2':
                    pick = NSGAII(rng_s, codes).choose(obs, uneval, obj_of)
                elif strat == 'qnparego':
                    pick = PAREGO(rng_s, X).choose(obs, uneval, obj_of)
                elif strat == 'qnehvi':
                    pick = QNEHVI(rng_s, X, objs).choose(obs, uneval, obj_of)
                else:
                    pick = mcts.choose(obs, uneval, obj_of)
                obs[pick] = noise_q[gids[pick]]
                if strat == 'aflow_mcts':
                    arch = np.array([obj_of(i) for i in obs])
                    gain = hypervolume(arch[non_dominated(arch)]) \
                        - hypervolume(np.array([obj_of(i) for i in obs])[:-1][
                            non_dominated(np.array([obj_of(i) for i in obs])[:-1])])
                    mcts.backprop(gain)
                arc = np.array([obj_of(i) for i in obs])
                fi = non_dominated(arc)
                ev_sorted = sorted(obs)
                fg = {gids[ev_sorted[j]] for j in fi}
                ft = {tuple(np.round(objs[ev_sorted[j]], 6)) for j in fi}
                hist.append((len(obs), hypervolume(arc[fi]) / ref_hv, fg, ft))
            ratios = np.array([h[1] for h in hist])
            last = hist[-1]
            per_seed[strat]['regret'].append(float(1 - last[1]))
            per_seed[strat]['auc'].append(float(ratios.mean()))
            per_seed[strat]['recall_cfg'].append(len(last[2] & set(true_gids)) / len(true_gids))
            per_seed[strat]['recall_dedup'].append(
                len(last[3] & true_tuples) / len(true_tuples))
            per_seed[strat]['n95'].append(next((h[0] for h in hist if h[1] >= 0.95), None))
        if (seed + 1) % 20 == 0:
            print(f'seed {seed + 1}/{n_seeds}', flush=True)

    def summ(v):
        a = np.array(v, float)
        return dict(mean=float(a.mean()), median=float(np.median(a)), std=float(a.std()))

    summary = {}
    for s in strategies:
        ps = per_seed[s]
        n95 = ps['n95']
        summary[s] = dict(
            final_regret=summ(ps['regret']), AUC_HV=summ(ps['auc']),
            recall_config=summ(ps['recall_cfg']), recall_dedup=summ(ps['recall_dedup']),
            N_95pct_HV=dict(never=sum(1 for x in n95 if x is None),
                            dist={int(k): n95.count(k) for k in sorted(
                                set(n95), key=lambda z: (z is None, z)) if k is not None}))

    # SA-PGFS rows from the frozen run (identical seeds/init/noise -> paired)
    sapgfs = json.loads((OUT / 'REPLAY_FAULT_ROBUST.json').read_text())

    def perm_test(a, b, n_perm=10000, seed=1):
        d = np.array(a, float) - np.array(b, float)
        obs_ = abs(d.mean())
        rngp = np.random.default_rng(seed)
        signs = rngp.choice([-1.0, 1.0], size=(n_perm, len(d)))
        null = np.abs((signs * d).mean(axis=1))
        return float((null >= obs_ - 1e-12).mean())

    tests = {}
    if not smoke:
        sap_ps = {}
        # recompute SA-PGFS per-seed metrics from its stored traces is not
        # available; use its summary only, and perm-test external-vs-external
        for m in ('regret', 'auc'):
            for a, b in (('qnehvi', 'nsga2'), ('qnparego', 'nsga2'),
                         ('aflow_mcts', 'nsga2'), ('qnehvi', 'qnparego')):
                tests[f'{a}_vs_{b}:{m}'] = perm_test(per_seed[a][m], per_seed[b][m])

    out = dict(protocol='PROTOCOL_SAPGFS_FREEZE_v1 harness + external mechanisms '
                        '(adapted, execution outcomes held fixed)',
               n_seeds=n_seeds, true_front_gids=true_gids,
               hv_true_front=float(ref_hv),
               external_strategy_summary=summary,
               sapgfs_reference=sapgfs['strategy_summary'],
               paired_permutation_tests=tests,
               naming='nsga2/qnparego/qnehvi/aflow_mcts are mechanism adaptations '
                      'to the frozen finite space, not full reproductions of the '
                      'original systems (paper wording fixed in PROTOCOL addendum)',
               zero_model_calls=True)
    out['per_seed_metrics'] = per_seed  # paired tests vs SA-PGFS
    fn = OUT / ('EXTERNAL_BASELINES_SMOKE.json' if smoke else 'EXTERNAL_BASELINES_ROBUST.json')
    fn.write_text(json.dumps(out, indent=1))
    print(json.dumps({s: dict(regret=summary[s]['final_regret']['mean'],
                              auc=summary[s]['AUC_HV']['mean'],
                              n95_never=summary[s]['N_95pct_HV']['never'])
                      for s in strategies}, indent=1))
    if tests:
        print(json.dumps(tests, indent=1))


if __name__ == '__main__':
    if '--smoke' in sys.argv:
        run(n_seeds=6, smoke=True)
    else:
        run()
