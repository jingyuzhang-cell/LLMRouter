"""Work-package B mechanism ablations on the CORRECTED v2 protocol (zero calls).

Three preregistered, CPU-only ablations answering "does SA-PGFS have
mechanism value beyond standard GP+EHVI?" — all on the corrected harness
(true-value metrics, correlated fault-seed noise, (count+1)/(B+1) with Holm,
200 paired seeds, budget 8 incl. 2 shared init). Supersedes the historical
state ablation (6e9702e), which used the broken HV implementation.

B1 state-aware vs state-blind (fair: SAME cross-state observation stream and
   data volume; only state information differs):
     v2_1 fair design: BOTH arms train on the SAME pooled samples (clean+fault
              observations of every evaluated config); blind uses input X,
              aware uses input [X, state-bit] — only the state feature differs;
              prediction on fault-state candidates in both arms
   Both arms observe, for every evaluated config, its Q in BOTH states
   (the tables are measured); target metric = FAULT-state true HV gap.
   C/L columns visible to both arms identically.

B2 representation (same GP + same EHVI acquisition, same budget):
     onehot       : one-hot(Y,X,Z) + C/L
     integer      : integer codes + C/L        (the ACTUAL frozen encoding)
     structural   : node count, edge count, depth, width, role-model
                    indicators + C/L           (graph features per config)
   Metrics: fault true HV gap, AUC, recall.

B3 surrogate necessity (same EHVI acquisition):
     gp           : the frozen sklearn GP
     constant     : non-learning predictor (predict observed mean, sigma =
                    observed std) — isolates what the GP's structure learning
                    contributes
   (acquisition necessity is already covered in REPLAY_V2 via scalarized
    vs ehvi under the same GP.)

Run: python3 -m sa_pgfs_v1.ablation_mechanisms [--smoke]
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sa_pgfs_v1.acquisition import ehvi as ehvi_fn  # noqa: E402
from sa_pgfs_v1.pareto import hypervolume, non_dominated  # noqa: E402
from sa_pgfs_v1.replay_v2 import N_EVAL, N_INIT, N_PERM, load_gcollab  # noqa: E402
from sa_pgfs_v1.surrogate import QSurrogate  # noqa: E402

OUT = ROOT / 'sa_pgfs_v1/results_cube_replay'
YS, XS = ['ser', 'serv', 'paralleler', 'dynamicdag'], \
    ['balanced', 'heterogeneous', 'quality']
STRUCT = {  # per gid: (nodes, edges, depth, width, [e_m, r_m, v_m onehot3 x3])
}
ARMS = {
    'B1_state': ['aware', 'blind'],
    'B2_repr': ['onehot', 'integer', 'structural'],
    'B3_surrogate': ['gp', 'constant'],
}


def struct_features(code):
    y, x, z = code
    nodes = {'ser': 2, 'serv': 3, 'paralleler': 3, 'dynamicdag': 4}[YS[y]]
    edges = nodes - 1
    depth = nodes
    width = 2 if YS[y] in ('paralleler', 'dynamicdag') else 1
    fam = {'balanced': ('medium', 'large', 'medium'),
           'heterogeneous': ('large', 'medium', 'coder'),
           'quality': ('large', 'large', 'large')}[XS[x]]
    ms = {'medium': 0, 'large': 1, 'coder': 2}
    h = np.zeros(9)
    h[ms[fam[0]]] = 1
    h[3 + ms[fam[1]]] = 1
    h[6 + ms[fam[2]]] = 1
    return [nodes, edges, depth, width, z, *h]


class ConstPredictor:
    def fit(self, X, y):
        self.mu, self.sg = float(np.mean(y)), float(np.std(y)) + 1e-6

    def predict(self, X, return_std=True):
        return np.full(len(X), self.mu), np.full(len(X), self.sg)


def run(seed_master=20261009, n_seeds=200, smoke=False):
    pts = load_gcollab()  # fault table
    clean = json.loads((ROOT / 'collab_scheduler_v1/CUBE_CLEAN_ANALYSIS.json')
                       .read_text())['complete']
    gids = sorted(pts)
    gid2cid = {f'{t.lower()}|{f.lower()}|{z.lower()}|fresh': f'{t}__{f}__{z}__FRESH'
               for t in ('SER', 'SERV', 'PARALLELER', 'DYNAMICDAG')
               for f in ('BALANCED', 'HETEROGENEOUS', 'QUALITY')
               for z in (['NONE', 'LOCAL_REROUTE'] if t == 'DYNAMICDAG' else ['NONE'])}
    Qc = np.array([clean[gid2cid[g]]['Q'] if gid2cid[g] in clean
                   else clean[f'{g.split("|")[0].upper()}__{g.split("|")[1].upper()}__NONE__FRESH']['Q']
                   for g in gids])
    Q = np.array([pts[g]['Q'] for g in gids])
    C = np.array([pts[g]['C'] for g in gids], float)
    L = np.array([pts[g]['L'] for g in gids], float)
    Cmax, Lmax = C.max(), L.max()
    objs = np.stack([Q, 1 - C / Cmax, 1 - L / Lmax], axis=1)
    fi = non_dominated(objs)
    ref_hv = hypervolume(objs[fi])
    true_set, true_gids = set(fi), [gids[i] for i in fi]
    codes = {g: pts[g]['code'] for g in gids}
    n = 15

    def feats(arm, g, with_cl=True):
        y, x, z = codes[g]
        if arm == 'onehot':
            v = [0.0] * 9
            v[y] = 1
            v[4 + x] = 1
            v[7 + z] = 1
        elif arm == 'integer':
            v = [float(y), float(x), float(z)]
        else:
            v = [float(t) for t in struct_features(codes[g])]
        if with_cl:
            v += [C[gids.index(g)] / Cmax, L[gids.index(g)] / Lmax]
        return v

    Xb2 = {a: np.array([feats(a, g) for g in gids]) for a in ARMS['B2_repr']}
    Xi = Xb2['integer']
    rng_master = np.random.default_rng(seed_master)
    per = {f'{ab}_{a}': {'gap': [], 'auc': [], 'n95': []}
           for ab, arms in ARMS.items() for a in arms}

    for seed in range(n_seeds):
        rng = np.random.default_rng(21000 + seed)
        s_idx = int(rng.integers(3))
        obs_q = {i: pts[gids[i]]['per_seed_Q'][s_idx] for i in range(n)}
        obs_qc = {i: Qc[i] for i in range(n)}
        init = list(rng_master.choice(n, N_INIT, replace=False))

        def nobj(i):
            return np.array([obs_q[i], objs[i][1], objs[i][2]])

        for ab, arms in ARMS.items():
            for a in arms:
                key = f'{ab}_{a}'
                rng_s = np.random.default_rng(21000 + seed)
                obs = {i: obs_q[i] for i in init}
                obs_c = {i: obs_qc[i] for i in init}
                ev0 = sorted(obs)
                t0 = objs[ev0][non_dominated(objs[ev0])]
                hist = [(N_INIT, hypervolume(t0) / ref_hv)]  # init included (v2_1)
                while len(obs) < N_EVAL:
                    ev, uneval = sorted(obs), [i for i in range(n) if i not in obs]
                    arc = np.array([nobj(i) for i in ev])
                    front = arc[non_dominated(arc)]
                    if ab == 'B3_surrogate' and a == 'constant':
                        sur = ConstPredictor()
                        sur.fit(np.zeros((len(ev), 1)), np.array([obs[i] for i in ev]))
                        mu, sg = sur.predict(np.zeros((len(uneval), 1)))
                    else:
                        sur = QSurrogate()
                        if ab == 'B1_state':
                            # v2_1: same pooled samples; only the state feature
                            # differs between arms
                            Xp = np.vstack([Xi[ev], Xi[ev]])
                            Zp = np.vstack([np.zeros((len(ev), 1)),
                                            np.ones((len(ev), 1))])
                            yp = np.array([obs_c[i] for i in ev] + [obs[i] for i in ev])
                            if a == 'aware':
                                sur.fit(np.hstack([Xp, Zp]), yp)
                                mu, sg = sur.predict(
                                    np.hstack([Xi[uneval], np.ones((len(uneval), 1))]))
                            else:
                                sur.fit(Xp, yp)
                                mu, sg = sur.predict(Xi[uneval])
                        else:
                            Xa = Xb2[a] if ab == 'B2_repr' else Xi
                            sur.fit(Xa[ev], np.array([obs[i] for i in ev]))
                            mu, sg = sur.predict(Xa[uneval])
                    acq = ehvi_fn(mu, sg, objs[uneval], front, n_samples=16, rng=rng_s)
                    pick = int(uneval[np.argmax(acq)])
                    obs[pick] = obs_q[pick]
                    obs_c[pick] = obs_qc[pick]
                    ev = sorted(obs)
                    tarc = objs[ev]
                    hist.append((len(obs),
                                 hypervolume(tarc[non_dominated(tarc)]) / ref_hv))
                per[key]['gap'].append(1 - hist[-1][1])
                per[key]['auc'].append(float(np.mean([h[1] for h in hist])))
                per[key]['n95'].append(next((h[0] for h in hist if h[1] >= .95), None))
        if (seed + 1) % 50 == 0:
            print(f'seed {seed + 1}/{n_seeds}', flush=True)

    def summ(v):
        a = np.array(v, float)
        return dict(mean=float(a.mean()), median=float(np.median(a)), std=float(a.std()))

    def perm(x, y):
        d = np.array(x, float) - np.array(y, float)
        o = abs(d.mean())
        rp = np.random.default_rng(11)
        signs = rp.choice([-1.0, 1.0], size=(N_PERM, len(d)))
        return (float((np.abs((signs * d).mean(axis=1)) >= o - 1e-12).sum()) + 1) / (N_PERM + 1)

    summary = {k: dict(gap=summ(v['gap']), auc=summ(v['auc']),
                       n95_never=sum(1 for x in v['n95'] if x is None))
               for k, v in per.items()}
    tests = {}
    fams = {'B1_state': ('aware', 'blind'), 'B2_repr': ('structural', 'onehot'),
            'B3_surrogate': ('gp', 'constant')}
    if not smoke:
        for ab, (x, y) in fams.items():
            for m in ('gap', 'auc'):
                tests[f'{ab}:{x}_vs_{y}:{m}'] = perm(per[f'{ab}_{x}'][m], per[f'{ab}_{y}'][m])
        tests['B2_repr:integer_vs_onehot:gap'] = perm(per['B2_repr_integer']['gap'],
                                                      per['B2_repr_onehot']['gap'])
        # Holm over the 7 tests
        fam = sorted(tests.items(), key=lambda kv: kv[1])
        m_ = len(fam)
        holm = {k: min(1.0, max((m_ - j) * fam[j][1] for j in range(i + 1)))
                for i, (k, _) in enumerate(fam)}
    else:
        holm = None
    out = dict(version='work-package B v2_1: same-samples state-feature B1; AUC/N95 from initial design '
                        '(supersedes historical 6e9702e state ablation which used the '
                        'broken HV)',
               design_notes=dict(
                   B1='same cross-state stream and data volume; only state '
                      'information differs; both arms see C/L identically; '
                      'metric = fault-state true HV gap',
                   B2='same GP + EHVI; only feature encoding differs (C/L '
                      'included in all arms)',
                   B3='same EHVI; GP vs non-learning constant predictor',
                   stats='p=(count+1)/(B+1), B=10000, Holm within 7 pre-specified '
                         'tests; wording rule: n.s. != equivalence'),
               n_seeds=n_seeds, true_front=true_gids, summary=summary,
               permutation_tests=tests, holm=holm, per_seed=per,
               zero_model_calls=True)
    fn = OUT / ('MECHANISM_ABLATIONS_V2_1_SMOKE.json' if smoke else 'MECHANISM_ABLATIONS_V2_1.json')
    fn.write_text(json.dumps(out, indent=1))
    for k, m in summary.items():
        print(f"{k:24s} gap={m['gap']['mean']:+.4f}/{m['gap']['median']:+.4f} "
              f"auc={m['auc']['mean']:.3f} n95never={m['n95_never']}")
    if tests:
        print(json.dumps(tests, indent=1))


if __name__ == '__main__':
    run(n_seeds=6, smoke=True) if '--smoke' in sys.argv else run()
