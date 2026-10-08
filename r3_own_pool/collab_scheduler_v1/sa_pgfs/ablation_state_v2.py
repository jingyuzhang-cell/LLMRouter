"""CORRECTED ablation: State-aware vs State-blind SA-PGFS (zero LLM calls).

Fixes vs the invalid v1 (ablation_state.py):
 1. Uses sa_pgfs_v1.pareto.hypervolume (regression-tested correct 3D HV)
 2. Unified normalization: single min-max scale computed from the FULL
    dual-state cube (pre-determined, not per-state)
 3. Three arms:
    a) state_aware: surrogate trained on current-state observations only
    b) state_blind_equal: surrogate trained on SAME NUMBER of observations
       from BOTH states (no state label, matched data volume)
    c) state_blind_pooled: surrogate trained on ALL observations from both
       states (generous, 2x data volume)
 4. Two-sided paired permutation test
 5. Does NOT overwrite the v1 results (writes ABLATION_STATE_V2.json)
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/sa_pgfs'

from sa_pgfs_v1.pareto import hypervolume as hv_correct
from collab_scheduler_v1.sa_pgfs.replay import gp_predict, encode_config, c_eval_estimate

N_SEEDS = 200
N_INIT = 3
N_MC = 48
F30 = ROOT / 'collab_scheduler_v1/FAULT30_ANALYSIS.json'
CLEAN = ROOT / 'collab_scheduler_v1/cube_clean/CUBE_CLEAN.json'


def load_all():
    f30 = json.loads(F30.read_text())
    clean = json.loads(CLEAN.read_text())
    ci = {cid: (c['Q'], c['C'], c['L']) for cid, c in clean['results'].items()}
    fi = {cid: (c['Q'], c['C'], c['L']) for cid, c in f30['fault_per_config'].items()}
    ci.pop('SINGLE__QUALITY__RETRY__FRESH', None)
    fi.pop('SINGLE__QUALITY__RETRY__FRESH', None)
    return ci, fi


def unified_normalize(clean_items, fault_items):
    """Single min-max scale across BOTH states; returns two normalized dicts."""
    all_vals = list(clean_items.values()) + list(fault_items.values())
    qs = [v[0] for v in all_vals]
    cs = [v[1] for v in all_vals]
    ls = [v[2] for v in all_vals]
    qmin, qmax = min(qs), max(qs)
    cmin, cmax = min(cs), max(cs)
    lmin, lmax = min(ls), max(ls)

    def norm(items):
        out = {}
        for cid, (q, c, l) in items.items():
            nq = (q - qmin) / (qmax - qmin) if qmax > qmin else 0.5
            nc = 1 - (c - cmin) / (cmax - cmin) if cmax > cmin else 0.5
            nl = 1 - (l - lmin) / (lmax - lmin) if lmax > lmin else 0.5
            out[cid] = (nq, nc, nl)
        return out
    return norm(clean_items), norm(fault_items)


def run_seed(norm_target, norm_other, cids, features, arm, seed):
    """One replay seed for one arm. Returns HV curve using correct HV."""
    rng = np.random.default_rng(seed)
    n = len(cids)
    init = rng.choice(n, N_INIT, replace=False)
    evaluated = set(init.tolist())
    D = [(i, norm_target[cids[i]]) for i in sorted(evaluated)]

    full_pts = [norm_target[c] for c in cids]
    hv_star = hv_correct(full_pts)
    if hv_star <= 0:
        hv_star = 1e-9

    all_q_t = np.array([norm_target[c][0] for c in cids])
    all_c_t = np.array([norm_target[c][1] for c in cids])
    all_l_t = np.array([norm_target[c][2] for c in cids])
    all_q_o = np.array([norm_other[c][0] for c in cids])

    hv_curve = []
    for t in range(N_INIT, n + 1):
        pts = [pt for _, pt in D]
        hv = hv_correct(pts)
        hv_curve.append(hv / hv_star)
        if t == n:
            break
        uneval = [i for i in range(n) if i not in evaluated]
        if not uneval:
            break
        train_idx = [i for i, _ in D]
        X_single = np.array([features[i] for i in train_idx])
        if arm == 'state_aware':
            X_tr, y_tr = X_single, all_q_t[train_idx]
        elif arm == 'state_blind_equal':
            # same obs count, but half from other state (no state label)
            k = len(train_idx)
            half = max(1, k // 2)
            idx_shuffled = list(train_idx)
            rng.shuffle(idx_shuffled)
            mixed_y = np.concatenate([all_q_t[idx_shuffled[:k - half]],
                                      all_q_o[idx_shuffled[k - half:]]])
            X_tr, y_tr = X_single, mixed_y
        elif arm == 'state_blind_pooled':
            X_tr = np.vstack([X_single, X_single])
            y_tr = np.concatenate([all_q_t[train_idx], all_q_o[train_idx]])
        else:
            raise ValueError(arm)

        X_te = np.array([features[i] for i in uneval])
        if len(train_idx) >= 2:
            mu, std = gp_predict(X_tr, y_tr, X_te)
        else:
            mu = np.full(len(uneval), 0.5)
            std = np.full(len(uneval), 1.0)

        # EHVI acquisition (same for all arms)
        current_hv = hv_correct(pts)
        best_gain = -1e9
        pick = 0
        for j in range(len(uneval)):
            q_s = np.clip(rng.normal(mu[j], std[j] + 1e-6, N_MC), 0, 1)
            cj, lj = all_c_t[uneval[j]], all_l_t[uneval[j]]
            gains = [hv_correct(pts + [(qs, cj, lj)]) - current_hv for qs in q_s]
            e = np.mean(gains)
            if e > best_gain:
                best_gain = e
                pick = j
        chosen = uneval[pick]
        evaluated.add(chosen)
        D.append((chosen, norm_target[cids[chosen]]))
        D.sort(key=lambda x: x[0])
    return hv_curve


def run():
    clean_items, fault_items = load_all()
    cids = sorted(clean_items.keys())
    norm_c, norm_f = unified_normalize(clean_items, fault_items)
    features = np.array([encode_config(c, cids) for c in cids])
    arms = ['state_aware', 'state_blind_equal', 'state_blind_pooled']
    results = {}
    per_seed_auc = {}  # for pairwise tests

    for state_name, norm_t, norm_o in [('s_clean', norm_c, norm_f),
                                        ('s_fault30', norm_f, norm_c)]:
        for arm in arms:
            traces = []
            aucs = []
            t0 = time.time()
            for seed in range(N_SEEDS):
                c = run_seed(norm_t, norm_o, cids, features, arm, seed)
                traces.append(c)
                aucs.append(float(np.mean(c)))
            arr = np.array(traces)
            n95 = [next((i for i, h in enumerate(arr[s]) if h >= 0.95), len(arr[s]) - 1) + N_INIT
                   for s in range(N_SEEDS)]
            results[f'{state_name}|{arm}'] = dict(
                auc_hv=float(np.mean(aucs)), n95_mean=float(np.mean(n95)),
                n95_std=float(np.std(n95)),
                final_regret=float(1 - arr[:, -1].mean()),
                hv_mean=arr.mean(axis=0).tolist())
            per_seed_auc[f'{state_name}|{arm}'] = aucs
            print(f'{state_name} {arm:20s} AUC={np.mean(aucs):.4f} '
                  f'N95={np.mean(n95):.1f}±{np.std(n95):.1f} ({time.time()-t0:.0f}s)',
                  flush=True)

    # two-sided paired permutation tests
    rng = np.random.default_rng(42)
    n_perm = 10000
    for state in ['s_clean', 's_fault30']:
        for a, b in [('state_aware', 'state_blind_equal'),
                     ('state_aware', 'state_blind_pooled'),
                     ('state_blind_equal', 'state_blind_pooled')]:
            da = np.array(per_seed_auc[f'{state}|{a}'])
            db = np.array(per_seed_auc[f'{state}|{b}'])
            diff = da - db
            obs = np.mean(diff)
            cnt_ge = 0
            cnt_le = 0
            for _ in range(n_perm):
                signs = rng.choice([-1, 1], len(diff))
                perm = np.mean(diff * signs)
                if perm >= obs:
                    cnt_ge += 1
                if perm <= obs:
                    cnt_le += 1
            p_two = 2 * min(cnt_ge, cnt_le) / n_perm
            results[f'{state}|{a}_vs_{b}'] = dict(
                auc_a=float(np.mean(da)), auc_b=float(np.mean(db)),
                mean_diff=float(obs), p_two_sided=float(min(1.0, max(p_two, 2 / n_perm))))
            print(f'{state} {a} vs {b}: diff={obs:+.4f} p={p_two:.4f}', flush=True)

    (OUT / 'ABLATION_STATE_V2.json').write_text(json.dumps(
        dict(results=results, n_seeds=N_SEEDS,
             hv_source='sa_pgfs_v1.pareto.hypervolume (regression-tested)',
             normalization='unified across both states (pre-determined)',
             note='corrected version; v1 (ablation_state.py) used broken HV and '
                  'per-state normalization — see ABLATION_REPORT.md supersede note'),
        indent=1))
    print('done')


if __name__ == '__main__':
    run()
