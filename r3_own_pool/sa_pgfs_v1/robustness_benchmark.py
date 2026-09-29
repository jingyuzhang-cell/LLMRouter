"""SA-PGFS robustness benchmark on the FROZEN protocol (zero model calls).

Implements PROTOCOL_SAPGFS_FREEZE_v1 exactly:
  - search space G_collab (15 cooperative configs; Single excluded, external baseline)
  - 200 replay seeds; per seed, COMMON 2-config initial design and COMMON noise
    draw per config across all strategies (paired design)
  - noise: per-seed empirical Q (uniform over the 3 measured fault seeds)
  - budget 8 evaluations; strategies random / greedy_q / ehvi / cost_aware_ehvi
  - metrics: final normalized HV regret, AUC-HV, Pareto recall (config-level AND
    deduplicated by objective tuple), N_95%HV distribution
  - paired permutation tests (10k sign shuffles) for ehvi-vs-random,
    ehvi-vs-greedy, costaware-vs-random on final regret and AUC-HV

Run:  python3 -m sa_pgfs_v1.robustness_benchmark            # full (200 seeds)
      python3 -m sa_pgfs_v1.robustness_benchmark --smoke    # 6 seeds, no stats
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sa_pgfs_v1.acquisition import ehvi  # noqa: E402
from sa_pgfs_v1.pareto import hypervolume, non_dominated  # noqa: E402
from sa_pgfs_v1.surrogate import QSurrogate  # noqa: E402

OUT = ROOT / 'sa_pgfs_v1/results_cube_replay'
STRATEGIES = ('random', 'greedy_q', 'ehvi', 'cost_aware_ehvi')
N_EVAL, N_INIT = 8, 2


def load_gcollab():
    d = json.loads((ROOT / 'collab_scheduler_v1/FAULT30_ANALYSIS.json').read_text())
    pts = {}
    for cid, v in d['fault_per_config'].items():
        topo, fam, z, _ = cid.split('__')
        gid = f'{topo.lower()}|{fam.lower()}|{z.lower()}|fresh'
        pts[gid] = dict(Q=v['Q'], C=v['C'], L=v['L'], per_seed_Q=v['per_seed']['Q'])
    return pts


def features(gid):
    y, x, z, _ = gid.split('|')
    Y = {'ser': 0, 'serv': 1, 'paralleler': 2, 'dynamicdag': 3}
    F = {'balanced': 0, 'heterogeneous': 1, 'quality': 2}
    Z = {'none': 0, 'local_reroute': 1}
    return [Y[y], F[x], Z[z]]  # integer categorical codes (GP kernel sees distances)


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
    X = np.array([[*features(g), C[i] / Cmax, L[i] / Lmax]
                  for i, g in enumerate(gids)], dtype=float)
    n = len(gids)
    rng_master = np.random.default_rng(seed_master)

    per_seed = {s: {m: [] for m in ('regret', 'auc', 'recall_cfg', 'recall_dedup', 'n95')}
                for s in STRATEGIES}
    for seed in range(n_seeds):
        rng = np.random.default_rng(9000 + seed)
        noise_q = {g: float(rng.choice(pts[g]['per_seed_Q'])) for g in gids}
        init = list(rng_master.choice(n, N_INIT, replace=False))
        for strat in STRATEGIES:
            rng_s = np.random.default_rng(9000 + seed)  # same stream -> same noise
            obs = {}

            def obj_of(i):
                return np.array([noise_q[gids[i]], objs[i][1], objs[i][2]])

            for i in init:
                obs[i] = noise_q[gids[i]]
            hist = []
            while len(obs) < N_EVAL:
                ev = sorted(obs)
                if strat == 'random':
                    pick = int(rng_s.choice([i for i in range(n) if i not in obs]))
                elif len(obs) >= 4:
                    sur = QSurrogate()
                    sur.fit(X[ev], np.array([obs[i] for i in ev]))
                    uneval = np.array([i for i in range(n) if i not in obs])
                    mu, sg = sur.predict(X[uneval], return_std=True)
                    if strat == 'greedy_q':
                        pick = int(uneval[np.argmax(mu)])
                    else:
                        arc = np.array([obj_of(i) for i in obs])
                        front = arc[non_dominated(arc)]
                        cand = objs[uneval]
                        costs = C[uneval] / Cmax if strat == 'cost_aware_ehvi' else None
                        acq = ehvi(mu, sg, cand, front, n_samples=16, rng=rng_s,
                                   eval_costs=costs)
                        pick = int(uneval[np.argmax(acq)])
                else:
                    pick = int(rng_s.choice([i for i in range(n) if i not in obs]))
                obs[pick] = noise_q[gids[pick]]
                arc = np.array([obj_of(i) for i in obs])
                fi = non_dominated(arc)
                hv = hypervolume(arc[fi]) / ref_hv
                fg = {gids[i] for i in [sorted(obs)[j] for j in range(len(obs))] if False}
                found_gids = {gids[i] for i in obs if i in
                              set(np.array(sorted(obs))[fi])}
                ft = {tuple(np.round(objs[i], 6)) for i in obs
                      if i in set(np.array(sorted(obs))[fi])}
                hist.append((len(obs), hv, found_gids, ft))
            ratios = np.array([h[1] for h in hist])
            last = hist[-1]
            per_seed[strat]['regret'].append(float(1 - last[1]))
            per_seed[strat]['auc'].append(float(ratios.mean()))
            per_seed[strat]['recall_cfg'].append(
                len(last[2] & set(true_gids)) / len(true_gids))
            per_seed[strat]['recall_dedup'].append(
                len(last[3] & true_tuples) / len(true_tuples))
            per_seed[strat]['n95'].append(next((h[0] for h in hist if h[1] >= 0.95), None))
        if (seed + 1) % 20 == 0:
            print(f'seed {seed + 1}/{n_seeds} done', flush=True)

    def summ(v):
        a = np.array(v, dtype=float)
        return dict(mean=float(a.mean()), median=float(np.median(a)), std=float(a.std()))

    summary = {}
    for s in STRATEGIES:
        ps = per_seed[s]
        n95 = ps['n95']
        summary[s] = dict(
            final_regret=summ(ps['regret']), AUC_HV=summ(ps['auc']),
            recall_config=summ(ps['recall_cfg']), recall_dedup=summ(ps['recall_dedup']),
            N_95pct_HV=dict(never=sum(1 for x in n95 if x is None),
                            dist={int(k): n95.count(k) for k in sorted(set(n95),
                                                                      key=lambda z: (z is None, z))
                                  if k is not None}))

    def perm_test(a, b, n_perm=10000, seed=1):
        """Paired permutation on mean difference (a-b): two-sided p."""
        d = np.array(a, float) - np.array(b, float)
        obs = abs(d.mean())
        rng = np.random.default_rng(seed)
        signs = rng.choice([-1.0, 1.0], size=(n_perm, len(d)))
        null = np.abs((signs * d).mean(axis=1))
        return float((null >= obs - 1e-12).mean())

    tests = {}
    if not smoke:
        pairs = [('ehvi', 'random'), ('ehvi', 'greedy_q'),
                 ('cost_aware_ehvi', 'random')]
        for m in ('regret', 'auc'):
            for a, b in pairs:
                tests[f'{a}_vs_{b}:{m}'] = perm_test(per_seed[a][m], per_seed[b][m])

    out = dict(protocol='PROTOCOL_SAPGFS_FREEZE_v1',
               status='robustness benchmark (measured fault cube, G_collab only, '
                      'paired design, per-seed empirical noise)',
               n_seeds=n_seeds, true_front_gids=true_gids, hv_true_front=float(ref_hv),
               strategy_summary=summary, paired_permutation_tests=tests,
               zero_model_calls=True)
    fn = OUT / ('REPLAY_FAULT_ROBUST_SMOKE.json' if smoke else 'REPLAY_FAULT_ROBUST.json')
    out['per_seed_metrics'] = per_seed  # paired tests vs external baselines
    fn.write_text(json.dumps(out, indent=1))
    print(json.dumps({s: dict(regret=summary[s]['final_regret']['mean'],
                              auc=summary[s]['AUC_HV']['mean'],
                              recall_dedup=summary[s]['recall_dedup']['mean'],
                              n95_never=summary[s]['N_95pct_HV']['never'])
                      for s in STRATEGIES}, indent=1))
    if tests:
        print(json.dumps(tests, indent=1))


if __name__ == '__main__':
    if '--smoke' in sys.argv:
        run(n_seeds=6, smoke=True)
    else:
        run()
