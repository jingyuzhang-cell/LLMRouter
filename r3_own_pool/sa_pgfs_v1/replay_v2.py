"""Corrected replay v2 (2026-10-08 audit response; zero model calls).

Supersedes the frozen replay's SEARCH-COMPARISON claims (cube measurements
unchanged). Fixes, per external audit RF-2/3/5:

  F1 qNParEGO: proper augmented Chebyshev — weights no longer cancel
     (old code divided by w, degenerating to one fixed scalarization)
  F2 NSGA-II: full non-dominated sorting + STANDARD crowding distance
     (old reciprocal inverted the preference) + rank-based tournament
  F3 recall mapping: arcs built from sorted(obs) consistently in ALL
     methods (old code mapped front indices through the wrong list)
  F4 MCTS tree: z children [0,1] on dynamicdag (old [1] hid the three
     DYNAMICDAG NONE leaves, reachable only via random fallback)
  F5 noise model: ONE fault-seed index per replay seed shared by all
     configs (preserves cross-config fault correlation; old independent
     per-config draws broke it)
  F6 primary metric = TRUE-VALUE HV of the discovered set (mean Q),
     evaluated from the initial design (budget 2); noisy ratio secondary
  F7 permutation p = (count+1)/(B+1), never 0; pre-specified family
     {ehvi vs each other method} x {gap, AUC} with Holm correction
  F8 Scalarized baseline added (fixed 7-weight library, round-robin EI)

Protocol amendment recorded in the output JSON (integer-coded features are
the ACTUAL frozen implementation; v2 keeps them for continuity and notes
one-hot as an untested alternative).

Run: python3 -m sa_pgfs_v1.replay_v2 [--smoke]
"""
import json
import sys
from math import erf, sqrt
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sa_pgfs_v1.acquisition import _sample_q, ehvi as ehvi_fn  # noqa: E402
from sa_pgfs_v1.pareto import hypervolume, non_dominated  # noqa: E402
from sa_pgfs_v1.surrogate import QSurrogate  # noqa: E402

OUT = ROOT / 'sa_pgfs_v1/results_cube_replay'
N_EVAL, N_INIT, N_PERM = 8, 2, 10000
YS, XS, ZS = ['ser', 'serv', 'paralleler', 'dynamicdag'], \
    ['balanced', 'heterogeneous', 'quality'], ['none', 'local_reroute']
WEIGHTS = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (.5, .5, 0), (.5, 0, .5),
           (0, .5, .5), (1 / 3, 1 / 3, 1 / 3)]
STRATS = ('random', 'greedy_q', 'scalarized', 'nsga2', 'qnparego',
          'qnehvi', 'aflow_mcts', 'ehvi', 'cost_aware_ehvi')


def load_gcollab():
    d = json.loads((ROOT / 'collab_scheduler_v1/FAULT30_ANALYSIS.json').read_text())
    pts = {}
    for cid, v in d['fault_per_config'].items():
        topo, fam, z, _ = cid.split('__')
        pts[f'{topo.lower()}|{fam.lower()}|{z.lower()}|fresh'] = dict(
            Q=v['Q'], C=v['C'], L=v['L'], per_seed_Q=v['per_seed']['Q'],
            code=(YS.index(topo.lower()), XS.index(fam.lower()), ZS.index(z.lower())))
    assert len(pts) == 15
    return pts


def nds_ranks(objs):
    ranks, remaining = np.zeros(len(objs), int), set(range(len(objs)))
    r = 0
    while remaining:
        front = {i for i in remaining if not any(
            np.all(objs[j] >= objs[i]) and np.any(objs[j] > objs[i])
            for j in remaining if j != i)}
        for i in front:
            ranks[i] = r
        remaining -= front
        r += 1
    return ranks


def crowding(objs):
    d = np.zeros(len(objs))
    if len(objs) <= 2:
        d[:] = np.inf
        return d
    for k in range(objs.shape[1]):
        span = objs[:, k].max() - objs[:, k].min()
        if span <= 0:
            continue
        order = np.argsort(objs[:, k])
        d[order[[0, -1]]] = np.inf
        d[order[1:-1]] += (objs[order[2:], k] - objs[order[:-2], k]) / span
    return d


def ei_pick(X_tr, y_tr, X_cand, rng):
    sur = QSurrogate()
    sur.fit(X_tr, y_tr)
    mu, sg = sur.predict(X_cand, return_std=True)
    best = y_tr.max()
    z = (mu - best) / np.maximum(sg, 1e-12)
    phi = 0.5 * (1 + np.array([erf(zz / sqrt(2)) for zz in z]))
    pdf = np.exp(-0.5 * z ** 2) / sqrt(2 * np.pi)
    return int(np.argmax((mu - best) * phi + sg * pdf))


def run(seed_master=20261008, n_seeds=200, smoke=False):
    pts = load_gcollab()
    gids = sorted(pts)
    Q = np.array([pts[g]['Q'] for g in gids])
    C = np.array([pts[g]['C'] for g in gids], float)
    L = np.array([pts[g]['L'] for g in gids], float)
    Cmax, Lmax = C.max(), L.max()
    objs = np.stack([Q, 1 - C / Cmax, 1 - L / Lmax], axis=1)  # true values
    fi = non_dominated(objs)
    true_gids = [gids[i] for i in fi]
    true_set = set(fi)
    true_tuples = {tuple(np.round(objs[i], 6)) for i in fi}
    ref_hv = hypervolume(objs[fi])
    codes = np.array([pts[g]['code'] for g in gids])
    X = np.array([[*codes[i], C[i] / Cmax, L[i] / Lmax] for i in range(15)], float)
    rng_master = np.random.default_rng(seed_master)
    per = {s: {m: [] for m in ('gap', 'gap_noisy', 'auc', 'rec_eval', 'rec_front',
                               'rec_front_dedup', 'n95')} for s in STRATS}

    for seed in range(n_seeds):
        rng = np.random.default_rng(11000 + seed)
        s_idx = int(rng.integers(3))                       # F5: shared fault seed
        obs_q = {i: pts[gids[i]]['per_seed_Q'][s_idx] for i in range(15)}
        init = list(rng_master.choice(15, N_INIT, replace=False))

        def noisy_obj(i):
            return np.array([obs_q[i], objs[i][1], objs[i][2]])

        for strat in STRATS:
            rng_s = np.random.default_rng(11000 + seed)    # paired stream
            obs = {}
            for i in init:
                obs[i] = obs_q[i]
            mN, mV = {}, {}  # MCTS visit counts / cumulative rewards
            ev0 = sorted(obs)
            a0 = np.array([noisy_obj(i) for i in ev0])  # v2_1: init included
            hist = [(N_INIT, hypervolume(objs[ev0][non_dominated(objs[ev0])])
                     / ref_hv, hypervolume(a0[non_dominated(a0)]) / ref_hv,
                     set(), set())]
            w_ptr = 0
            while len(obs) < N_EVAL:
                uneval = [i for i in range(15) if i not in obs]
                ev = sorted(obs)
                arc = np.array([noisy_obj(i) for i in ev])  # F3: sorted-consistent
                if strat == 'random':
                    pick = int(rng_s.choice(uneval))
                elif strat == 'greedy_q':
                    if len(ev) >= 4:
                        sur = QSurrogate()
                        sur.fit(X[ev], np.array([obs[i] for i in ev]))
                        mu, _ = sur.predict(X[uneval])
                        pick = int(uneval[np.argmax(mu)])
                    else:
                        pick = int(rng_s.choice(uneval))
                elif strat == 'scalarized':
                    w = WEIGHTS[w_ptr % len(WEIGHTS)]
                    w_ptr += 1
                    z = arc.max(0)
                    scal = arc @ np.array(w)
                    if len(ev) >= 4:
                        pick = uneval[ei_pick(X[ev], scal, X[uneval], rng_s)]
                    else:
                        pick = int(rng_s.choice(uneval))
                elif strat == 'nsga2':
                    ranks, crowd = nds_ranks(arc), crowding(arc)
                    code_ev = {i: codes[i] for i in ev}

                    def tour():
                        a, b = rng_s.choice(len(ev), 2, replace=False)
                        ka = (ranks[a], -crowd[a])
                        kb = (ranks[b], -crowd[b])
                        return a if ka < kb else b

                    uneval_codes = {tuple(codes[i]): i for i in uneval}
                    pick = None
                    for _ in range(100):
                        p1, p2 = tour(), tour()
                        child = [codes[ev[p1]][k] if rng_s.random() < .5
                                 else codes[ev[p2]][k] for k in range(3)]
                        for k in range(3):
                            if rng_s.random() < 1 / 3:
                                child[k] = int(rng_s.integers([4, 3, 2][k]))
                        if tuple(child) in uneval_codes:
                            pick = uneval_codes[tuple(child)]
                            break
                    if pick is None:
                        pick = int(rng_s.choice(uneval))
                elif strat == 'qnparego':
                    if len(ev) >= 4:
                        w = rng_s.dirichlet(np.ones(3))
                        zst = arc.max(0)
                        def cheb(o):
                            return -(np.max(w * (zst - o)) + 0.05 * np.dot(w, zst - o))
                        pick = uneval[ei_pick(X[ev], np.array([cheb(noisy_obj(i))
                                                                for i in ev]),
                                              X[uneval], rng_s)]
                    else:
                        pick = int(rng_s.choice(uneval))
                elif strat == 'qnehvi':
                    if len(ev) >= 4:
                        sur = QSurrogate()
                        sur.fit(X[ev], np.array([obs[i] for i in ev]))
                        mu_a, sg_a = sur.predict(X[ev], return_std=True)
                        mu_c, sg_c = sur.predict(X[uneval], return_std=True)
                        qa = _sample_q(mu_a, sg_a, 24, rng_s)
                        qc = _sample_q(mu_c, sg_c, 24, rng_s)
                        outk = np.zeros(len(uneval))
                        for s in range(24):
                            a = np.array([[qa[s][j], objs[ev[j]][1], objs[ev[j]][2]]
                                          for j in range(len(ev))])
                            f0 = hypervolume(a[non_dominated(a)])
                            for k in range(len(uneval)):
                                cc = np.vstack([a, [qc[s][k], objs[uneval[k]][1],
                                                    objs[uneval[k]][2]]])
                                outk[k] += hypervolume(cc[non_dominated(cc)]) - f0
                        pick = int(uneval[np.argmax(outk)])
                    else:
                        pick = int(rng_s.choice(uneval))
                else:  # aflow_mcts (F4 legal tree) or ehvi variants
                    if strat == 'aflow_mcts':
                        N, V = mN, mV
                        prefix, plen = [], []
                        for lev in range(3):
                            opts = [1, 0] if prefix and prefix[0] == 3 and lev == 2 \
                                else (list(range(4)) if lev == 0 else
                                      (list(range(3)) if lev == 1 else [0]))
                            cands = [o for o in opts if any(
                                list(codes[i])[:lev + 1] == prefix + [o]
                                for i in uneval)] or opts
                            un = [o for o in cands if N.get(tuple(prefix + [o]), 0) == 0]
                            if un:
                                o = un[int(rng_s.integers(len(un)))]
                            else:
                                tot = sum(N[tuple(prefix + [o])] for o in cands)
                                o = max(cands, key=lambda o: V[tuple(prefix + [o])]
                                        / N[tuple(prefix + [o])]
                                        + 0.7 * sqrt(np.log(tot + 1)
                                                     / N[tuple(prefix + [o])]))
                            plen.append(tuple(prefix + [o]))
                            prefix = prefix + [o]
                        leaf = next((i for i in uneval if list(codes[i]) == prefix), None)
                        if leaf is None:
                            leaf = next((i for i in uneval
                                         if list(codes[i])[:2] == prefix[:2]),
                                        int(rng_s.choice(uneval)))
                        pick = leaf
                    else:
                        if len(ev) >= 4:
                            sur = QSurrogate()
                            sur.fit(X[ev], np.array([obs[i] for i in ev]))
                            mu, sg = sur.predict(X[uneval], return_std=True)
                            front = arc[non_dominated(arc)]
                            cand = objs[uneval]
                            costs = C[uneval] / Cmax if strat == 'cost_aware_ehvi' else None
                            acq = ehvi_fn(mu, sg, cand, front, n_samples=16,
                                          rng=rng_s, eval_costs=costs)
                            pick = int(uneval[np.argmax(acq)])
                        else:
                            pick = int(rng_s.choice(uneval))
                obs[pick] = obs_q[pick]
                if strat == 'aflow_mcts':
                    arc_after = np.array([noisy_obj(i) for i in sorted(obs)])
                    gain = hypervolume(arc_after[non_dominated(arc_after)]) - \
                        hypervolume(arc[non_dominated(arc)])
                    for k in plen:
                        mN[k] = mN.get(k, 0) + 1
                        mV[k] = mV.get(k, 0.0) + gain
                ev = sorted(obs)
                # F6: TRUE-value discovered-set metrics
                tarc = objs[ev]
                tr = hypervolume(tarc[non_dominated(tarc)]) / ref_hv
                narc = np.array([noisy_obj(i) for i in ev])
                nr = hypervolume(narc[non_dominated(narc)]) / ref_hv
                fidx = non_dominated(tarc)
                rec_front = {ev[j] for j in fidx}
                hist.append((len(obs), tr, nr,
                             rec_front & true_set,
                             {tuple(np.round(objs[ev[j]], 6)) for j in fidx} & true_tuples))
            per[strat]['gap'].append(1 - hist[-1][1])
            per[strat]['gap_noisy'].append(1 - hist[-1][2])
            per[strat]['auc'].append(float(np.mean([h[1] for h in hist])))
            per[strat]['rec_eval'].append(len(true_set & set(obs)) / len(true_set))
            per[strat]['rec_front'].append(len(hist[-1][3]) / len(true_set))
            per[strat]['rec_front_dedup'].append(len(hist[-1][4]) / len(true_tuples))
            per[strat]['n95'].append(next((h[0] for h in hist if h[1] >= 0.95), None))
        if (seed + 1) % 25 == 0:
            print(f'seed {seed + 1}/{n_seeds}', flush=True)

    def summ(v):
        a = np.array(v, float)
        return dict(mean=float(a.mean()), median=float(np.median(a)), std=float(a.std()))

    summary = {}
    for s in STRATS:
        ps = per[s]
        summary[s] = dict(gap=summ(ps['gap']), gap_noisy=summ(ps['gap_noisy']),
                          auc=summ(ps['auc']), rec_eval=summ(ps['rec_eval']),
                          rec_front=summ(ps['rec_front']),
                          rec_front_dedup=summ(ps['rec_front_dedup']),
                          n95_never=sum(1 for x in ps['n95'] if x is None),
                          n95_dist={int(k): ps['n95'].count(k) for k in sorted(
                              set(ps['n95']), key=lambda z: (z is None, z))
                              if k is not None})

    def perm(a, b):
        d = np.array(a, float) - np.array(b, float)
        obs_ = abs(d.mean())
        rngp = np.random.default_rng(7)
        signs = rngp.choice([-1.0, 1.0], size=(N_PERM, len(d)))
        null = np.abs((signs * d).mean(axis=1))
        return (float((null >= obs_ - 1e-12).sum()) + 1) / (N_PERM + 1)  # F7

    tests = {}
    if not smoke:
        for m in ('gap', 'auc'):
            for other in STRATS:
                if other != 'ehvi':
                    tests[f'ehvi_vs_{other}:{m}'] = perm(per['ehvi'][m], per[other][m])
        # Holm over the 16 pre-specified ehvi-vs-other tests
        fam = sorted(tests.items(), key=lambda kv: kv[1])
        m_ = len(fam)
        holm = {}
        for i, (k, p) in enumerate(fam):
            holm[k] = min(1.0, max((m_ - j) * fam[j][1] for j in range(i + 1)))
    out = dict(
        version='replay_v2_1 (v2 fixes + AUC/N95 from initial design; supersedes '
                'comparison claims of the frozen replay; cube measurements unchanged)',
        protocol_amendment=dict(
            features='integer categorical codes (ACTUAL frozen implementation; '
                     'one-hot noted as untested alternative)',
            noise='one shared fault-seed index per replay seed (cross-config '
                  'correlation preserved)',
            primary_metric='true-value discovered-set HV gap (mean Q), budgets 2..8 '
                            'from initial design; noisy ratio secondary',
            p_value='(count+1)/(B+1), B=10000; Holm over 16 pre-specified '
                    'ehvi-vs-other tests',
            naming='qNEHVI adapted = independent marginal sampling approximation '
                   '(no joint posterior covariance); MCTS = UCT over the legal '
                   'Y-X-Z template tree; scalarized = fixed 7-weight linear '
                   'scalarization (arc @ w), round-robin EI'),
        n_seeds=n_seeds, true_front=true_gids, hv_true_front=float(ref_hv),
        summary=summary, per_seed=per, permutation_tests=tests,
        holm_corrected=holm if not smoke else None, zero_model_calls=True)
    fn = OUT / ('REPLAY_V2_1_SMOKE.json' if smoke else 'REPLAY_V2_1.json')
    fn.write_text(json.dumps(out, indent=1))
    for s in STRATS:
        m = summary[s]
        print(f"{s:18s} gap={m['gap']['mean']:+.4f}/{m['gap']['median']:+.4f} "
              f"auc={m['auc']['mean']:.3f} rec_eval={m['rec_eval']['mean']:.3f} "
              f"rec_front={m['rec_front']['mean']:.3f} n95never={m['n95_never']}")
    if not smoke:
        print(json.dumps(holm, indent=1))


if __name__ == '__main__':
    run(n_seeds=6, smoke=True) if '--smoke' in sys.argv else run()
