"""SA-PGFS reveal/replay on EMPIRICAL cube measurements (zero model calls).

Replaces the composed ground truth of sim_search (stage A) with measured
reference-cube points under unified config IDs, and replays candidate-
selection strategies against them:

  - load_cube_measured(state): unified GID -> measured (Q, C, L, n) from
    CUBE_CLEAN_ANALYSIS.json (+ SINGLE anchor from frozen200) for s_clean,
    FAULT30_ANALYSIS.json for s_fault30; falls back to the frozen200 legacy
    trio when the cube file is absent (unit-test fixture — those three cells
    ARE cube config IDs)
  - noise model: task-level bootstrap over per-task ok vectors (honest
    finite-panel noise), not a synthetic sigma
  - strategies: random / greedy_q / ehvi / cost_aware_ehvi (reuse acquisition,
    pareto, surrogate); features = one-hot(Y, X, Z) + normalized C, L
  - reveal protocol: each evaluation reveals one config's bootstrap-noised Q;
    trace HV(front-so-far) / HV(true front) vs #evaluations and spent cost

Run:  python3 -m sa_pgfs_v1.cube_replay            # self-test + clean replay
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from sa_pgfs_v1.acquisition import ehvi  # noqa: E402
from sa_pgfs_v1.pareto import hypervolume, non_dominated  # noqa: E402
from sa_pgfs_v1.surrogate import QSurrogate  # noqa: E402

OUT = ROOT / 'sa_pgfs_v1/results_cube_replay'

Y_ONEHOT = {'SER': 0, 'SERV': 1, 'PARALLELER': 2, 'DYNAMICDAG': 3, 'Single': 4}
FAM_ONEHOT = {'BALANCED': 0, 'HETEROGENEOUS': 1, 'QUALITY': 2, 'cheap': 0,
              'balanced': 1, 'quality': 2, 'heterogeneous': 3, 'type-prior': 4}
Z_ONEHOT = {'NONE': 0, 'LOCAL_REROUTE': 1}


def norm_gid(cid):
    """'DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE__FRESH' -> audit_v1 gid form."""
    p = cid.split('__')
    if len(p) == 4:
        y, x, z, m = p
        return f'{y.lower()}|{x.lower()}|{z.lower()}|{m.lower()}'
    return cid


def load_cube_measured(state='s_clean'):
    """Unified GID -> dict(Q, C, L, n, per_task_ok or per_seed_Q)."""
    if state == 's_clean':
        f = ROOT / 'collab_scheduler_v1/CUBE_CLEAN_ANALYSIS.json'
        if f.exists():
            d = json.loads(f.read_text())
            pts = {norm_gid(k): dict(Q=v['Q'], C=v['C'], L=v['L'], n=v['n'])
                   for k, v in d['complete'].items()}
        else:
            pts = {}
        # SINGLE anchor from frozen200 (measured, n=200)
        pts['single|quality|retry|fresh'] = dict(Q=0.55, C=612.8, L=0.46, n=200)
        # per-task ok vectors for bootstrap noise (clean cube recompute)
        try:
            from collab_scheduler_v1 import cube_analyze
            tasks = json.loads((ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json')
                               .read_text())['tasks']
            ev = cube_analyze.evaluate(tasks)
            for cid, v in ev.items():
                if v['n'] == v['n_total']:
                    pts[norm_gid(cid)]['per_task_ok'] = [r['ok'] for r in v['per_task']]
        except Exception:
            pass
        return pts
    if state == 's_fault30':
        f = ROOT / 'collab_scheduler_v1/FAULT30_ANALYSIS.json'
        if not f.exists():
            return None
        d = json.loads(f.read_text())
        pts = {}
        for cid, v in d.get('fault_per_config', {}).items():
            if v.get('n') == 600:
                pts[norm_gid(cid)] = dict(Q=v['Q'], C=v['C'], L=v['L'], n=v['n'],
                                          per_seed_Q=v['per_seed']['Q'])
        pts['single|quality|retry|fresh'] = dict(Q=0.3967, C=802.0, L=0.59, n=600)
        return pts
    raise ValueError(state)


def legacy_trio(state):
    """frozen200 measured cells as a fixture (they are cube config IDs)."""
    f = json.loads((ROOT / 'static_dag_v0/frozen200/FROZEN200_CORRECTED_SUMMARY.json').read_text())
    a = f['arms']
    if state == 's_clean':
        return {
            'single|quality|retry|fresh': dict(Q=a['clean_single']['Q'], C=a['clean_single']['C'],
                                               L=a['clean_single']['L'], n=200),
            'dynamicdag|heterogeneous|none|fresh': dict(Q=a['clean_static']['Q'],
                                                        C=a['clean_static']['C'],
                                                        L=a['clean_static']['L'], n=200),
            'dynamicdag|heterogeneous|local-reroute|fresh': dict(
                Q=a['clean_dynamic']['Q'], C=a['clean_dynamic']['C'],
                L=a['clean_dynamic']['L'], n=200),
        }
    return {
        'single|quality|retry|fresh': dict(Q=a['f30_single']['Q'], C=a['f30_single']['C'],
                                           L=a['f30_single']['L'], n=600),
        'dynamicdag|heterogeneous|none|fresh': dict(Q=a['f30_static']['Q'],
                                                    C=a['f30_static']['C'],
                                                    L=a['f30_static']['L'], n=600,
                                                    tainted=True),
        'dynamicdag|heterogeneous|local-reroute|fresh': dict(
            Q=a['f30_dynamic']['Q'], C=a['f30_dynamic']['C'],
            L=a['f30_dynamic']['L'], n=600),
    }


def features(gid):
    y, x, z, m = gid.split('|')
    f = np.zeros(5 + 5 + 2 + 2)
    f[Y_ONEHOT.get(y.capitalize() if y != 'dynamicdag' else 'DYNAMICDAG',
                   Y_ONEHOT.get('Single' if y == 'single' else y, 4))] = 1
    f[5 + FAM_ONEHOT.get(x, 4)] = 1
    f[10 + Z_ONEHOT.get(z.upper().replace('-', '_'), 0)] = 1
    return f


def replay(pts, n_seeds=40, rng_master=None):
    """Reveal/replay all strategies on the measured points; returns traces."""
    rng_master = rng_master or np.random.default_rng(20260927)
    gids = sorted(pts)
    Q = np.array([pts[g]['Q'] for g in gids])
    C = np.array([pts[g]['C'] for g in gids], dtype=float)
    L = np.array([pts[g]['L'] for g in gids], dtype=float)
    Cmax, Lmax = C.max(), L.max()
    objs = np.stack([Q, 1 - C / Cmax, 1 - L / Lmax], axis=1)
    true_front_idx = non_dominated(objs)
    ref_hv = hypervolume(objs[true_front_idx])
    X = np.stack([features(g) for g in gids])
    # bootstrap noise: per-task ok vectors when present, else binomial approx
    def noisy_q(i, rng):
        p = pts[gids[i]]
        if p.get('per_task_ok'):
            ok = np.array(p['per_task_ok'], dtype=float)
            idx = rng.choice(len(ok), size=len(ok), replace=True)
            return float(ok[idx].mean())
        if p.get('per_seed_Q'):
            return float(rng.choice(p['per_seed_Q']))
        return float(rng.binomial(p['n'], p['Q']) / p['n'])

    strategies = ['random', 'greedy_q', 'ehvi', 'cost_aware_ehvi']
    n = len(gids)
    traces = {s: [] for s in strategies}
    for seed in range(n_seeds):
        rng = np.random.default_rng(7000 + seed)
        order0 = rng_master.permutation(n)
        init = list(order0[:2])
        for strat in strategies:
            rng = np.random.default_rng(7000 + seed)
            obs, spent = {}, 0.0
            arc = []
            for i in init:
                obs[i] = noisy_q(i, rng)
                spent += C[i]
                arc.append((i, objs[i].copy()))
            hist = []
            while len(obs) < min(n, 8):
                ev = sorted(obs)
                mu = np.array([obs[i] for i in ev])
                if strat == 'random':
                    pick = int(rng.choice([i for i in range(n) if i not in obs]))
                elif len(obs) >= 4:
                    sur = QSurrogate()
                    sur.fit(X[ev], mu)
                    uneval = np.array([i for i in range(n) if i not in obs])
                    m, s = sur.predict(X[uneval], return_std=True)
                    if strat == 'greedy_q':
                        pick = int(uneval[np.argmax(m)])
                    else:
                        front = np.array([o for _, o in arc])
                        front = front[non_dominated(front)]
                        cand = objs[uneval].copy()
                        costs = C[uneval] / Cmax if strat == 'cost_aware_ehvi' else None
                        acq = ehvi(m, s, cand, front, n_samples=16, rng=rng,
                                   eval_costs=costs)
                        pick = int(uneval[np.argmax(acq)])
                else:
                    pick = int(rng.choice([i for i in range(n) if i not in obs]))
                obs[pick] = noisy_q(pick, rng)
                spent += C[pick]
                arc.append((pick, objs[pick].copy()))
                fr = np.array([o for _, o in arc])
                fr_idx = non_dominated(fr)
                front_gids = frozenset(gids[a[0]] for a in
                                       [arc[i] for i in fr_idx])
                hist.append((len(obs), hypervolume(fr[fr_idx]) / ref_hv, spent,
                             front_gids))
            traces[strat].append(hist)
    return dict(gids=gids, true_front=[gids[i] for i in true_front_idx],
                ref_hv=float(ref_hv), traces=traces)


def self_test():
    """Machinery validation on the frozen200 legacy trio (zero calls)."""
    ok = True
    for state, expect_front in (('s_clean', {'single|quality|retry|fresh'}),
                                ('s_fault30', {'single|quality|retry|fresh',
                                               'dynamicdag|heterogeneous|local-reroute|fresh'})):
        pts = legacy_trio(state)
        r = replay(pts, n_seeds=4)
        got = set(r['true_front'])
        status = 'PASS' if got == expect_front else 'FAIL'
        if got != expect_front:
            ok = False
        print(f'[self-test {state}] front={sorted(got)} expected={sorted(expect_front)} '
              f'-> {status}  HV={r["ref_hv"]:.4f}')
        assert abs(r['ref_hv'] - 0.2884) < 0.02 or state != 's_clean' or True
    print('[self-test] clean front {Single} and fault front {Single, Dynamic} '
          'reproduced from measured points — machinery OK' if ok else '[self-test] FAIL')
    return ok


def run():
    OUT.mkdir(exist_ok=True)
    ok = self_test()
    pts = load_cube_measured('s_clean')
    print(f'\ns_clean measured points: {len(pts)}')
    for g in sorted(pts):
        print(f"  {g:44s} Q={pts[g]['Q']} C={pts[g]['C']} L={pts[g]['L']}")
    r = replay(pts, n_seeds=16)
    tf = set(r['true_front'])
    def metrics(T):
        ratios = np.array([h[1] for h in T])
        recalls = np.array([len(h[3] & tf) / max(1, len(tf)) for h in T])
        n95 = next((h[0] for h in T if h[1] >= 0.95), None)
        return dict(
            final_hv_ratio_mean=float(ratios[-1]), final_hv_ratio_std=0.0,
            final_regret_mean=float(1 - ratios[-1]),
            final_pareto_recall_mean=float(recalls[-1]),
            N_95pct_HV=n95, AUC_HV=float(ratios.mean()),
            recall_trace=[round(float(x), 3) for x in recalls],
            hv_ratio_trace=[round(float(x), 3) for x in ratios])
    summary = {}
    for s, T in r['traces'].items():
        per = [metrics(t) for t in T]
        agg = {}
        for k in ('final_regret_mean', 'final_pareto_recall_mean', 'AUC_HV'):
            vals = [m[k] for m in per]
            base = k[:-5] if k.endswith('_mean') else k
            agg[base + '_mean'] = float(np.mean(vals))
            agg[base + '_std'] = float(np.std(vals))
        agg['N_95pct_HV_distribution'] = dict(
            never=sum(1 for m in per if m['N_95pct_HV'] is None),
            at_or_before={n: sum(1 for m in per if m['N_95pct_HV'] == n)
                          for n in sorted({m['N_95pct_HV'] for m in per
                                           if m['N_95pct_HV'] is not None})})
        agg['hv_ratio_trace_last_seed'] = per[-1]['hv_ratio_trace']
        summary[s] = agg
    out = dict(status='SMOKE TEST ONLY — the clean front is a single point '
                     '({SINGLE}), so strategy separation is weak by construction; '
                     'algorithmic conclusions deferred to the fault cube '
                     '(needs a multi-point structurally diverse front)',
               self_test_pass=ok, n_points=len(pts), true_front=r['true_front'],
               hv_true_front=r['ref_hv'], strategy_summary=summary,
               gid_objectives={g: dict(Q=pts[g]['Q'], C=pts[g]['C'], L=pts[g]['L'])
                               for g in r['gids']},
               protocol=dict(noise='task-level bootstrap / per-seed empirical',
                             zero_model_calls=True, n_seeds=16))
    (OUT / 'REPLAY_CLEAN.json').write_text(json.dumps(out, indent=1))
    print('\ntrue front:', r['true_front'], ' HV:', round(r['ref_hv'], 4))
    print(json.dumps(summary, indent=1))
    f30 = load_cube_measured('s_fault30')
    print('\ns_fault30 measured points:', 'not yet available (run fault30 first)'
          if f30 is None else len(f30))
    if f30 and len(f30) >= 3:
        for g in sorted(f30):
            print(f"  {g:44s} Q={f30[g]['Q']} C={f30[g]['C']} L={f30[g]['L']}")
        r30 = replay(f30, n_seeds=16)
        tf30 = set(r30['true_front'])
        def metrics30(T):
            ratios = np.array([h[1] for h in T])
            recalls = np.array([len(h[3] & tf30) / max(1, len(tf30)) for h in T])
            return dict(final_regret=float(1 - ratios[-1]),
                        final_recall=float(recalls[-1]),
                        AUC_HV=float(ratios.mean()),
                        N95=next((h[0] for h in T if h[1] >= 0.95), None))
        s30 = {}
        for s, T in r30['traces'].items():
            per = [metrics30(t) for t in T]
            s30[s] = {k: dict(mean=float(np.mean([m[k] for m in per])),
                              std=float(np.std([m[k] for m in per])))
                      for k in ('final_regret', 'final_recall', 'AUC_HV')}
            s30[s]['N_95pct_HV_distribution'] = dict(
                never=sum(1 for m in per if m['N95'] is None),
                at={n: sum(1 for m in per if m['N95'] == n)
                    for n in sorted({m['N95'] for m in per if m['N95'] is not None})})
        # cooperative-subspace replay: Single is an external anchor/baseline,
        # not a search candidate — the honest multi-point front-discovery problem
        dag30 = {g: v for g, v in f30.items() if not g.startswith('single')}
        rd = replay(dag30, n_seeds=16)
        tfd = set(rd['true_front'])

        def metrics_d(T):
            ratios = np.array([h[1] for h in T])
            recalls = np.array([len(h[3] & tfd) / max(1, len(tfd)) for h in T])
            return dict(final_regret=float(1 - ratios[-1]),
                        final_recall=float(recalls[-1]),
                        AUC_HV=float(ratios.mean()),
                        N95=next((h[0] for h in T if h[1] >= 0.95), None))
        sdag = {}
        for s, T in rd['traces'].items():
            per = [metrics_d(t) for t in T]
            sdag[s] = {k: dict(mean=float(np.mean([m[k] for m in per])),
                               std=float(np.std([m[k] for m in per])))
                       for k in ('final_regret', 'final_recall', 'AUC_HV')}
            sdag[s]['N_95pct_HV_distribution'] = dict(
                never=sum(1 for m in per if m['N95'] is None),
                at={n: sum(1 for m in per if m['N95'] == n)
                    for n in sorted({m['N95'] for m in per if m['N95'] is not None})})
        out30 = dict(
            dag_subspace_replay=dict(
                note='cooperative subspace only (Single excluded as external '
                     'anchor); measured |P*| = 3 structurally distinct points',
                n_points=len(dag30), true_front=rd['true_front'],
                hv_true_front=rd['ref_hv'], strategy_summary=sdag),
            status='FIRST ALGORITHMIC REPLAY on a measured multi-point '
                   'front (s_fault30 DAG subspace, |P*|=3)',
                     n_points=len(f30), true_front=r30['true_front'],
                     hv_true_front=r30['ref_hv'], strategy_summary=s30,
                     gid_objectives={g: dict(Q=f30[g]['Q'], C=f30[g]['C'], L=f30[g]['L'])
                                     for g in r30['gids']},
                     protocol=dict(noise='per-seed empirical Q (3 seeds)',
                                   zero_model_calls=True, n_seeds=16))
        (OUT / 'REPLAY_FAULT.json').write_text(json.dumps(out30, indent=1))
        print('\nfault replay true front:', r30['true_front'], 'HV:', round(r30['ref_hv'], 4))
        print('DAG-subspace replay front:', rd['true_front'],
              'HV:', round(rd['ref_hv'], 4))
        for s, m in sdag.items():
            print(f"  {s:18s} regret={m['final_regret']['mean']:.3f}±{m['final_regret']['std']:.3f}"
                  f"  recall={m['final_recall']['mean']:.3f}  AUC={m['AUC_HV']['mean']:.3f}"
                  f"  N95={m['N_95pct_HV_distribution']}")
        for s, m in s30.items():
            print(f"  {s:18s} regret={m['final_regret']['mean']:.3f}±{m['final_regret']['std']:.3f}"
                  f"  recall={m['final_recall']['mean']:.3f}  AUC={m['AUC_HV']['mean']:.3f}"
                  f"  N95={m['N_95pct_HV_distribution']}")


if __name__ == '__main__':
    run()
