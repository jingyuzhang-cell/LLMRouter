"""Zero-call search simulation on the composed space (SA-PGFS stage A).

Compares candidate-selection strategies under a REAL-EVALUATION budget, where
one 'real evaluation' of graph G costs C(G) tokens (running the workflow on
the frozen panel) and returns a noisy Q observation (finite-panel noise,
sigma=0.02). Strategies:
    random            uniform over unevaluated
    greedy_q          argmax surrogate mean (exploitation-only control)
    ehvi              MC-EHVI over (Q, -C, -L)
    cost_aware_ehvi   EHVI / C_eval  — per-unit-cost hypervolume gain

Outputs HV-vs-#evaluations and HV-vs-spent-cost curves (mean over seeds) and
the state-conditioned frontier demo (reuse_ext / reuse_full). No GPU, no
model calls: ground truth is the frozen-artifact-composed space.
"""
import json
import time
from pathlib import Path

import numpy as np

from .acquisition import ehvi
from .archive import DualArchive
from .pareto import hypervolume, non_dominated
from .space import apply_state, build_space
from .surrogate import QSurrogate

OUT = Path('/root/r3_own_pool/sa_pgfs_v1/results_sim_v1')
STRATEGIES = ['random', 'greedy_q', 'ehvi', 'cost_aware_ehvi']
N_INIT, N_EVAL, N_SEEDS, SIGMA_OBS = 5, 50, 8, 0.02
PREFILTER = 100


def run():
    OUT.mkdir(exist_ok=False)
    graphs, truth, calib = build_space()
    n = len(graphs)
    Cmax, Lmax = truth['C'].max(), truth['L'].max()
    objs = np.stack([truth['Q'], 1 - truth['C'] / Cmax, 1 - truth['L'] / Lmax], axis=1)
    ref_idx = non_dominated(objs)
    ref_hv = hypervolume(objs[ref_idx])
    feats = np.array([g.features(C=truth['C'][i], L=truth['L'][i])
                      for i, g in enumerate(graphs)])
    rng_master = np.random.default_rng(20260926)

    traces = {s: np.zeros((N_SEEDS, N_EVAL - N_INIT)) for s in STRATEGIES}
    cost_traces = {s: np.zeros((N_SEEDS, N_EVAL - N_INIT)) for s in STRATEGIES}
    found_fronts = {s: [] for s in STRATEGIES}
    for seed in range(N_SEEDS):
        init = rng_master.choice(n, N_INIT, replace=False)
        for strat in STRATEGIES:
            rng = np.random.default_rng(1000 + seed)
            obs_q = {}
            arc = DualArchive()
            spent = 0.0

            def evaluate(i):
                nonlocal spent
                q = float(np.clip(truth['Q'][i] + rng.normal(0, SIGMA_OBS), 0, 1))
                obs_q[i] = q
                spent += float(truth['C'][i])
                arc.add(graphs[i], np.array([q, 1 - truth['C'][i] / Cmax,
                                             1 - truth['L'][i] / Lmax]))

            for i in init:
                evaluate(int(i))
            hv_trace, ct_trace = [], []
            while len(obs_q) < N_EVAL:
                ev = sorted(obs_q)
                sur = QSurrogate()
                sur.fit(feats[ev], np.array([obs_q[i] for i in ev]))
                uneval = np.array([i for i in range(n) if i not in obs_q])
                mu, sigma = sur.predict(feats[uneval], return_std=True)
                if strat == 'random':
                    pick = int(rng.integers(len(uneval)))
                elif strat == 'greedy_q':
                    pick = int(np.argmax(mu))
                else:
                    score = mu + 2 * sigma
                    top = np.argsort(-score)[:PREFILTER]
                    cand = uneval[top]
                    _, front = arc.pareto_front()
                    costs = truth['C'][cand] / Cmax if strat == 'cost_aware_ehvi' else None
                    acq = ehvi(mu[top], sigma[top], objs[cand], front, n_samples=24,
                               rng=rng, eval_costs=costs)
                    pick = int(top[np.argmax(acq)])
                evaluate(int(uneval[pick]))
                hv_trace.append(arc.hv() / ref_hv)
                ct_trace.append(spent)
            traces[strat][seed] = hv_trace
            cost_traces[strat][seed] = ct_trace
            fi, _ = arc.pareto_front()
            found_fronts[strat].append(sorted(graphs[i].gid for i in fi))
            print(f'seed {seed} {strat:16s} final HV/ref = {hv_trace[-1]:.3f} '
                  f'spent={spent:.0f}tok', flush=True)

    summary = {}
    for s in STRATEGIES:
        t = traces[s][:, -1]
        summary[s] = dict(final_hv_ratio_mean=float(t.mean()), final_hv_ratio_std=float(t.std()),
                           mean_spent=float(cost_traces[s][:, -1].mean()))
    ref_gids = sorted(graphs[i].gid for i in ref_idx)
    state_demo = _state_demo(graphs, truth)

    np.savez(OUT / 'traces.npz', **{f'hv_{s}': traces[s] for s in STRATEGIES},
             **{f'cost_{s}': cost_traces[s] for s in STRATEGIES})
    (OUT / 'RESULTS.json').write_text(json.dumps(
        dict(calibration=calib, n_space=n, reference_front=ref_gids,
             reference_hv=float(ref_hv), summary=summary,
             found_fronts_last_seed={s: found_fronts[s][-1] for s in STRATEGIES},
             state_conditioned_demo=state_demo,
             protocol=dict(n_init=N_INIT, n_eval=N_EVAL, seeds=N_SEEDS,
                           sigma_obs=SIGMA_OBS, prefilter=PREFILTER,
                           noise='N(0,0.02) clipped [0,1]', zero_model_calls=True)), indent=1))
    _plot(traces, cost_traces)
    print(json.dumps(summary, indent=1))


def _state_demo(graphs, truth):
    """Offline design front vs follow-up state fronts (reuse changes C/L/Q)."""
    out = {}
    Cmax, Lmax = truth['C'].max(), truth['L'].max()
    for name, st in [('fresh', None), ('reuse_ext', 'reuse_ext'), ('reuse_full', 'reuse_full')]:
        t = truth if st is None else apply_state(graphs, truth, st)
        objs = np.stack([t['Q'], 1 - t['C'] / Cmax, 1 - t['L'] / Lmax], axis=1)
        nd = non_dominated(objs)
        front = [(graphs[i].topo['id'], graphs[i].recovery,
                  round(float(t['Q'][i]), 3), round(float(t['C'][i]), 1),
                  round(float(t['L'][i]), 2)) for i in sorted(nd, key=lambda i: t['C'][i])]
        out[name] = dict(front=front, hv=float(hypervolume(objs[nd])))
    objs_fresh = np.stack([truth['Q'], 1 - truth['C'] / Cmax, 1 - truth['L'] / Lmax], axis=1)
    nd_fresh = set(non_dominated(objs_fresh))
    re_ext = apply_state(graphs, truth, 'reuse_ext')
    objs_ext = np.stack([re_ext['Q'], 1 - re_ext['C'] / Cmax, 1 - re_ext['L'] / Lmax], axis=1)
    nd_ext = set(non_dominated(objs_ext))
    out['promoted_by_reuse_ext'] = [graphs[i].gid for i in (nd_ext - nd_fresh)]
    return out


def _plot(traces, cost_traces):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    xs = np.arange(N_INIT + 1, N_EVAL + 1)
    colors = dict(random='#999999', greedy_q='#1f77b4', ehvi='#ff7f0e',
                  cost_aware_ehvi='#d62728')
    for s in STRATEGIES:
        m, sd = traces[s].mean(0), traces[s].std(0)
        axes[0].plot(xs, m, label=s, color=colors[s])
        axes[0].fill_between(xs, m - sd, m + sd, alpha=.15, color=colors[s])
        mc, sc = cost_traces[s].mean(0), cost_traces[s].std(0)
        axes[1].plot(mc, m, label=s, color=colors[s])
        axes[1].fill_betweenx(m, np.maximum(mc - sc, 0), mc + sc, alpha=.15, color=colors[s])
    axes[0].set_xlabel('# real workflow evaluations')
    axes[1].set_xlabel('cumulative real evaluation cost (tokens)')
    for ax in axes:
        ax.set_ylabel('HV / HV(reference front)')
        ax.grid(alpha=.3)
    axes[0].legend(fontsize=8)
    fig.suptitle('SA-PGFS stage-A search simulation (zero model calls, composed space)', fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / 'hv_curves.png', dpi=150)


if __name__ == '__main__':
    t0 = time.time()
    run()
    print(f'wall {time.time() - t0:.1f}s')
