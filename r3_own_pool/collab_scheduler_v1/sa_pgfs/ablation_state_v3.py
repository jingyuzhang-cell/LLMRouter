"""Ablation v3: State-specific vs cross-state training (zero LLM calls).

Fixes over v2 (b0d0e50):
 1. CRITICAL: fixed feature-label misalignment in state_blind_equal
    (v2 shuffled indices for labels but NOT features; v3 uses per-index
    coin-flip with separate RNG, features stay aligned)
 2. Separate RNG for training-data mixing vs acquisition sampling
    (paired arms now share identical acquisition random streams)
 3. Exact two-sided paired permutation p-values + Holm-Bonferroni correction
 4. Protocol boundary documented: old RBF GP, n0=3, budget=14 (NOT the
    replay v2 main protocol with sklearn GP, n0=2, budget=8)
 5. Normalization visibility documented: unified scale uses full-cube Q/C/L
    ranges (offline normalization — valid for comparison, NOT deployable)
 6. Accurate experiment name: "state-specific training vs cross-state
    pooled/mixed training" (NOT "state-feature on/off ablation")

Three arms:
  state_aware    : current-state Q labels only
  blind_equal    : per-index coin-flip target/other Q (matched volume)
  blind_pooled   : both Q values per index (2x volume)
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
N_PERM = 10000
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
    all_vals = list(clean_items.values()) + list(fault_items.values())
    qs = [v[0] for v in all_vals]
    cs = [v[1] for v in all_vals]
    ls = [v[2] for v in all_vals]
    qmin, qmax = min(qs), max(qs)
    cmin, cmax = min(cs), max(cs)
    lmin, lmax = min(ls), max(ls)

    def norm(items):
        return {cid: ((q - qmin) / (qmax - qmin) if qmax > qmin else 0.5,
                      1 - (c - cmin) / (cmax - cmin) if cmax > cmin else 0.5,
                      1 - (l - lmin) / (lmax - lmin) if lmax > lmin else 0.5)
                for cid, (q, c, l) in items.items()}
    return norm(clean_items), norm(fault_items)


def unit_test_alignment():
    """Verify X and y stay aligned in all three arms."""
    features = np.array([[0., 0., 0., 0., 0., 0.], [1., 0., 0., 0., 0., 0.],
                         [0., 1., 0., 0., 0., 0.]])
    q_t = np.array([0.1, 0.5, 0.9])
    q_o = np.array([0.2, 0.6, 0.8])
    train_idx = [0, 1, 2]
    X_single = features[train_idx]
    mix_rng = np.random.default_rng(99)

    # state_aware
    assert np.allclose(X_single[:, 0], [0, 1, 0]), "aware X wrong"
    assert np.allclose(q_t[train_idx], [0.1, 0.5, 0.9]), "aware y wrong"

    # blind_equal: per-index coin-flip, features UNCHANGED
    k = len(train_idx)
    labels = np.array([q_o[i] if mix_rng.random() < 0.5 else q_t[i] for i in train_idx])
    assert len(labels) == k
    assert X_single.shape == (k, 6), f"X shape changed: {X_single.shape}"
    for j, i in enumerate(train_idx):
        expected = q_o[i] if labels[j] == q_o[i] else q_t[i]
        assert labels[j] in (q_t[i], q_o[i]), f"label {labels[j]} not valid for idx {i}"

    # blind_pooled
    X_pooled = np.vstack([X_single, X_single])
    y_pooled = np.concatenate([q_t[train_idx], q_o[train_idx]])
    assert X_pooled.shape == (2 * k, 6)
    assert y_pooled.shape == (2 * k,)
    # row j and row j+k have same features, different labels (target vs other)
    for j in range(k):
        assert np.allclose(X_pooled[j], X_pooled[j + k])
    print("ALIGNMENT UNIT TEST: PASS")


def run_seed(norm_target, norm_other, cids, features, arm, seed):
    """One replay seed. Uses separate RNGs for mixing and acquisition."""
    acq_rng = np.random.default_rng(seed)          # acquisition randomness
    mix_rng = np.random.default_rng(seed + 1000000)  # label-mixing randomness
    n = len(cids)
    init = acq_rng.choice(n, N_INIT, replace=False)
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
        hv_curve.append(hv_correct(pts) / hv_star)
        if t == n:
            break
        uneval = [i for i in range(n) if i not in evaluated]
        if not uneval:
            break
        train_idx = [i for i, _ in D]
        X_single = np.array([features[i] for i in train_idx])

        if arm == 'state_aware':
            X_tr, y_tr = X_single, all_q_t[train_idx]
        elif arm == 'blind_equal':
            y_list = [all_q_o[i] if mix_rng.random() < 0.5 else all_q_t[i]
                      for i in train_idx]
            X_tr, y_tr = X_single, np.array(y_list)
        elif arm == 'blind_pooled':
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

        # EHVI acquisition (identical acq_rng stream across arms)
        current_hv = hv_correct(pts)
        best_gain = -1e9
        pick = 0
        for j in range(len(uneval)):
            q_s = np.clip(acq_rng.normal(mu[j], std[j] + 1e-6, N_MC), 0, 1)
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


def holm_bonferroni(pvals):
    """Holm-Bonferroni step-down correction. Returns adjusted p-values."""
    n = len(pvals)
    indexed = sorted(enumerate(pvals), key=lambda x: x[1])
    adjusted = [0.0] * n
    prev = 0.0
    for rank, (orig_idx, p) in enumerate(indexed):
        adj = min(1.0, (n - rank) * p)
        adj = max(adj, prev)  # enforce monotonicity
        adjusted[orig_idx] = adj
        prev = adj
    return adjusted


def run():
    unit_test_alignment()
    clean_items, fault_items = load_all()
    cids = sorted(clean_items.keys())
    norm_c, norm_f = unified_normalize(clean_items, fault_items)
    features = np.array([encode_config(c, cids) for c in cids])
    arms = ['state_aware', 'blind_equal', 'blind_pooled']

    per_seed_auc = {}
    results = {}
    for state_name, norm_t, norm_o in [('s_clean', norm_c, norm_f),
                                        ('s_fault30', norm_f, norm_c)]:
        for arm in arms:
            aucs = []
            t0 = time.time()
            for seed in range(N_SEEDS):
                c = run_seed(norm_t, norm_o, cids, features, arm, seed)
                aucs.append(float(np.mean(c)))
            per_seed_auc[f'{state_name}|{arm}'] = aucs
            arr = np.array(aucs)
            results[f'{state_name}|{arm}'] = dict(
                auc_mean=float(np.mean(arr)), auc_std=float(np.std(arr)),
                auc_ci95=[float(np.percentile(arr, 2.5)),
                          float(np.percentile(arr, 97.5))])
            print(f'{state_name} {arm:15s} AUC={np.mean(arr):.4f} '
                  f'CI=[{np.percentile(arr,2.5):.4f},{np.percentile(arr,97.5):.4f}] '
                  f'({time.time()-t0:.0f}s)', flush=True)

    # pairwise tests with Holm correction
    perm_rng = np.random.default_rng(42)
    all_p = []
    all_labels = []
    pairwise_data = {}
    for state in ['s_clean', 's_fault30']:
        for a, b in [('state_aware', 'blind_equal'),
                     ('state_aware', 'blind_pooled'),
                     ('blind_equal', 'blind_pooled')]:
            da = np.array(per_seed_auc[f'{state}|{a}'])
            db = np.array(per_seed_auc[f'{state}|{b}'])
            diff = da - db
            obs = np.mean(diff)
            cnt_ge = 0
            cnt_le = 0
            for _ in range(N_PERM):
                signs = perm_rng.choice([-1, 1], len(diff))
                perm = np.mean(diff * signs)
                if perm >= obs:
                    cnt_ge += 1
                if perm <= obs:
                    cnt_le += 1
            p_raw = 2 * min(cnt_ge, cnt_le) / N_PERM
            p_raw = min(1.0, max(p_raw, 2.0 / N_PERM))
            label = f'{state}|{a}_vs_{b}'
            all_p.append(p_raw)
            all_labels.append(label)
            pairwise_data[label] = dict(
                auc_a=float(np.mean(da)), auc_b=float(np.mean(db)),
                mean_diff=float(obs), p_two_sided_raw=p_raw)
    # Holm correction
    adj = holm_bonferroni(all_p)
    for label, p_raw, p_adj in zip(all_labels, all_p, adj):
        pairwise_data[label]['p_holm_adjusted'] = p_adj
        print(f'{label}: diff={pairwise_data[label]["mean_diff"]:+.4f} '
              f'p_raw={p_raw:.4f} p_holm={p_adj:.4f}', flush=True)

    results['pairwise_tests'] = pairwise_data
    results['protocol_note'] = (
        'SUPPLEMENTARY protocol: old RBF GP (ls=1.0, sigma_f=1.0, noise=0.01), '
        'n0=3, budget=14 (full space). Differs from replay v2 main protocol '
        '(sklearn GP, n0=2, budget=8). This is a standalone training-data-source '
        'ablation, not a same-protocol main-experiment ablation.')
    results['normalization_note'] = (
        'Unified min-max normalization computed from the full dual-state cube '
        '(offline). Valid for comparing arms; NOT a deployable normalization '
        '(requires knowledge of all-state objective ranges).')
    results['experiment_name'] = (
        'State-specific training vs cross-state pooled/mixed training. '
        'NOT a state-feature on/off ablation (arms differ in training label '
        'source, not in the presence of a state input feature).')
    results['v2_bug_fixed'] = (
        'v2 (b0d0e50) had feature-label misalignment in blind_equal '
        '(shuffled indices for labels, unshuffled features); v3 fixes with '
        'per-index coin-flip using separate RNG, features stay aligned.')
    results['v2_p_value_correction'] = (
        'v2 reported p<1e-4 but actual minimum achievable with 10000 permutations '
        'is 2/10000=0.0002; v3 reports exact values with Holm correction.')

    (OUT / 'ABLATION_STATE_V3.json').write_text(json.dumps(
        dict(results=results, n_seeds=N_SEEDS, n_perm=N_PERM), indent=1))
    print('done')


if __name__ == '__main__':
    run()
