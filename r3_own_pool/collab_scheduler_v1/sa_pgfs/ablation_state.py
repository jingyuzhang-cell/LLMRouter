"""Ablation: State-aware vs State-blind SA-PGFS (zero LLM calls).

Question: does explicitly conditioning the surrogate + acquisition on the
execution state (s_clean vs s_fault30) improve search efficiency, compared
to the same SA-PGFS machinery with NO state information?

Design (pre-frozen, supplementary to the main protocol — does NOT alter
the frozen main results):

  State-blind: the surrogate is trained on observations from BOTH states
    pooled together (no state feature, no state-specific archive). The
    acquisition and everything else identical.

  State-aware: the surrogate is trained only on observations from the
    current state (as in the main experiment). This is the main result.

  Evaluation: for each state s ∈ {s_clean, s_fault30}, 200 paired seeds,
  same n_0=3 initial design per seed, same budget t=3..14 on |G_collab|=14.
  Metrics: AUC-HV, N_95, signed normalized HV regret.

  Fairness control: both arms see exactly the same number of observations
  at each step and the same initial configs for the target state. The
  state-blind arm has access to ALL observations from both states (the
  generous version of "no state info"); the state-aware arm only sees the
  current state's observations. This means state-blind has MORE data —
  the question is whether state-specific relevance beats raw data volume.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/sa_pgfs'
CUBE = ROOT / 'collab_scheduler_v1/REFERENCE_CUBE.json'
F30 = ROOT / 'collab_scheduler_v1/FAULT30_ANALYSIS.json'
CLEAN = ROOT / 'collab_scheduler_v1/cube_clean/CUBE_CLEAN.json'

from collab_scheduler_v1.sa_pgfs.replay import (compute_hv, front_indices,
                                                 gp_predict, encode_config,
                                                 normalize, c_eval_estimate)

N_SEEDS = 200
N_INIT = 3
N_MC = 48
WEIGHTS = [[0.6, 0.2, 0.2], [0.4, 0.3, 0.3], [1/3, 1/3, 1/3], [0.2, 0.4, 0.4]]


def load_all():
    f30 = json.loads(F30.read_text())
    clean = json.loads(CLEAN.read_text())
    clean_items = {cid: (cfg['Q'], cfg['C'], cfg['L'])
                   for cid, cfg in clean['results'].items()}
    fault_items = {cid: (cfg['Q'], cfg['C'], cfg['L'])
                   for cid, cfg in f30['fault_per_config'].items()}
    clean_items.pop('SINGLE__QUALITY__RETRY__FRESH', None)
    fault_items.pop('SINGLE__QUALITY__RETRY__FRESH', None)
    return clean_items, fault_items


def run_ablation_seed(norm_target, norm_pooled, cids, features_pooled, algo, seed):
    """One replay seed. algo='state_aware' or 'state_blind'."""
    rng = np.random.default_rng(seed)
    n = len(cids)
    c_evals = np.array([c_eval_estimate(cid) for cid in cids], dtype=float)
    c_evals = c_evals / c_evals.max()
    init = rng.choice(n, N_INIT, replace=False)
    evaluated = set(init.tolist())
    D = [(i, norm_target[cids[i]]) for i in sorted(evaluated)]

    full_pts = [norm_target[c] for c in cids]
    hv_star = compute_hv(full_pts)
    if hv_star == 0:
        hv_star = 1e-9
    all_q_target = np.array([norm_target[c][0] for c in cids])
    all_c_target = np.array([norm_target[c][1] for c in cids])
    all_l_target = np.array([norm_target[c][2] for c in cids])

    # For state-blind: also track which pooled observations exist for this config
    # in the OTHER state. The surrogate trains on pooled (config_features, Q)
    # from both states. We simulate this by maintaining a full 2-state observation
    # set that grows in parallel (for every config revealed in the target state,
    # we also "know" its value in the other state — the generous interpretation
    # of state-blind: the algorithm has seen this config under some state).
    norm_other = norm_pooled  # the other state's normalized objectives
    all_q_other = np.array([norm_other[c][0] for c in cids])

    hv_curve = []
    for t in range(N_INIT, n + 1):
        pts = [pt for _, pt in D]
        hv = compute_hv(pts)
        hv_curve.append(hv / hv_star)
        if t == n:
            break
        unevaluated = [i for i in range(n) if i not in evaluated]
        if not unevaluated:
            break

        # Surrogate training data
        train_idx = [i for i, _ in D]
        if algo == 'state_aware':
            train_y = all_q_target[train_idx]
        else:
            # state-blind: augment with other-state observations (doubled data)
            train_y = np.concatenate([all_q_target[train_idx],
                                      all_q_other[train_idx]])
        # Features are the same for both arms (structural encoding of config)
        X_tr_single = np.array([features_pooled[i] for i in train_idx])
        X_tr = np.vstack([X_tr_single, X_tr_single]) if algo == 'state_blind' else X_tr_single
        X_te = np.array([features_pooled[i] for i in unevaluated])

        if len(train_idx) >= 2:
            mu, std = gp_predict(X_tr, train_y, X_te)
        else:
            mu = np.full(len(unevaluated), 0.5)
            std = np.full(len(unevaluated), 1.0)

        # Acquisition: EHVI (same for both arms — the only difference is the surrogate's
        # training data)
        current_pts = pts
        current_hv = compute_hv(current_pts)
        best_score = -1e9
        pick = 0
        for j in range(len(unevaluated)):
            q_samples = np.clip(rng.normal(mu[j], std[j] + 1e-6, N_MC), 0, 1)
            c_j, l_j = all_c_target[unevaluated[j]], all_l_target[unevaluated[j]]
            gains = []
            for qs in q_samples:
                cand = current_pts + [(qs, c_j, l_j)]
                gains.append(compute_hv(cand) - current_hv)
            e = np.mean(gains)
            score = e  # plain EHVI for both arms (not cost-aware, to isolate the state effect)
            if score > best_score:
                best_score = score
                pick = j

        chosen = unevaluated[pick]
        evaluated.add(chosen)
        D.append((chosen, norm_target[cids[chosen]]))
        D.sort(key=lambda x: x[0])

    return hv_curve


def run():
    clean_items, fault_items = load_all()
    cids = sorted(clean_items.keys())  # same config space
    norm_clean = normalize(clean_items)
    norm_fault = normalize(fault_items)

    # Build a combined feature encoding (same for both states; the config is the same)
    features = np.array([encode_config(c, cids) for c in cids])

    results = {}
    for state_name, norm_target, norm_other, other_name in [
            ('s_clean', norm_clean, norm_fault, 's_fault30'),
            ('s_fault30', norm_fault, norm_clean, 's_clean')]:
        for algo in ['state_aware', 'state_blind']:
            hv_traces = []
            t0 = time.time()
            for seed in range(N_SEEDS):
                hv_c = run_ablation_seed(norm_target, norm_other, cids, features, algo, seed)
                hv_traces.append(hv_c)
            hv_arr = np.array(hv_traces)
            n95 = []
            for s in range(N_SEEDS):
                idx = next((i for i, h in enumerate(hv_arr[s]) if h >= 0.95), len(hv_arr[s]) - 1)
                n95.append(idx + N_INIT)
            auc = float(np.mean([np.mean(hv_arr[s]) for s in range(N_SEEDS)]))
            results[f'{state_name}|{algo}'] = dict(
                hv_mean=hv_arr.mean(axis=0).tolist(),
                hv_std=hv_arr.std(axis=0).tolist(),
                n95_mean=float(np.mean(n95)),
                n95_std=float(np.std(n95)),
                auc_hv=auc,
                final_regret=float(1 - hv_arr[:, -1].mean()),
            )
            print(f'{state_name} {algo:14s} N95={np.mean(n95):.1f}±{np.std(n95):.1f} '
                  f'AUC={auc:.4f} R_final={1-hv_arr[:,-1].mean():.4f} ({time.time()-t0:.0f}s)',
                  flush=True)

    # paired permutation test on AUC-HV
    from itertools import combinations
    for state in ['s_clean', 's_fault30']:
        aware_auc = []
        blind_auc = []
        # re-derive per-seed AUC
        norm_t = norm_clean if state == 's_clean' else norm_fault
        norm_o = norm_fault if state == 's_clean' else norm_clean
        for seed in range(N_SEEDS):
            ha = run_ablation_seed(norm_t, norm_o, cids, features, 'state_aware', seed)
            hb = run_ablation_seed(norm_t, norm_o, cids, features, 'state_blind', seed)
            aware_auc.append(np.mean(ha))
            blind_auc.append(np.mean(hb))
        diff = np.array(aware_auc) - np.array(blind_auc)
        # paired sign permutation
        rng = np.random.default_rng(42)
        n_perm = 10000
        obs = np.mean(diff)
        cnt = 0
        for _ in range(n_perm):
            signs = rng.choice([-1, 1], len(diff))
            if np.mean(diff * signs) >= obs:
                cnt += 1
        p = cnt / n_perm
        results[f'{state}|pairwise_test'] = dict(
            auc_aware=float(np.mean(aware_auc)),
            auc_blind=float(np.mean(blind_auc)),
            mean_diff=float(obs),
            p_value=float(max(p, 1 / (n_perm + 1))),
        )
        print(f'{state} pairwise: aware={np.mean(aware_auc):.4f} blind={np.mean(blind_auc):.4f} '
              f'diff={obs:.4f} p={p:.4f}', flush=True)

    (OUT / 'ABLATION_STATE_AWARE.json').write_text(json.dumps(
        dict(results=results, n_seeds=N_SEEDS, note='zero LLM calls; state-blind has '
             '2x training data (both states pooled); state-aware has current state only; '
             'same EHVI acquisition, same initial design, same budget'),
        indent=1))
    print('done')


if __name__ == '__main__':
    run()
