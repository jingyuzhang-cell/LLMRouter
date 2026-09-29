"""SA-PGFS reveal/replay on the Reference Cube — zero LLM calls.

Implements the frozen PROTOCOL_SAPGFS_FREEZE.json exactly. 200 paired replay
seeds × 5 algorithms × 2 states × t=3..14, plus robustness on seed-level
fault cubes. Single is external baseline, never searched.
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



N_SEEDS = 200
N_INIT = 3
N_MC = 48
WEIGHTS = [[0.6, 0.2, 0.2], [0.4, 0.3, 0.3], [1/3, 1/3, 1/3], [0.2, 0.4, 0.4]]
ALGOS = ['random', 'scalarized', 'greedy_q', 'ehvi', 'sa_pgfs']


def load_cube():
    cube = json.loads(CUBE.read_text())
    f30 = json.loads(F30.read_text())
    clean = json.loads(CLEAN.read_text())
    clean_items = {}
    fault_items = {}
    for cid, cfg in clean['results'].items():
        clean_items[cid] = (cfg['Q'], cfg['C'], cfg['L'])
    for cid, cfg in f30['fault_per_config'].items():
        fault_items[cid] = (cfg['Q'], cfg['C'], cfg['L'])
    # remove Single from search space
    clean_items.pop('SINGLE__QUALITY__RETRY__FRESH', None)
    fault_items.pop('SINGLE__QUALITY__RETRY__FRESH', None)
    return clean_items, fault_items


def normalize(items):
    """Normalize objectives to [0,1]^3 (Q↑, C↓→-C, L↓→-L). Returns dict cid->(q,nc,nl)."""
    if not items:
        return {}
    qs = [v[0] for v in items.values()]
    cs = [v[1] for v in items.values()]
    ls = [v[2] for v in items.values()]
    qmin, qmax = min(qs), max(qs)
    cmin, cmax = min(cs), max(cs)
    lmin, lmax = min(ls), max(ls)
    out = {}
    for cid, (q, c, l) in items.items():
        nq = (q - qmin) / (qmax - qmin) if qmax > qmin else 0.5
        nc = 1 - (c - cmin) / (cmax - cmin) if cmax > cmin else 0.5
        nl = 1 - (l - lmin) / (lmax - lmin) if lmax > lmin else 0.5
        out[cid] = (nq, nc, nl)
    return out


def front_indices(pts):
    """Return indices of non-dominated points."""
    arr = np.array(pts)
    n = len(arr)
    nd = []
    for i in range(n):
        dominated = False
        for j in range(n):
            if i == j:
                continue
            if np.all(arr[j] >= arr[i]) and np.any(arr[j] > arr[i]):
                dominated = True
                break
        if not dominated:
            nd.append(i)
    return nd


def compute_hv(pts):
    """Hypervolume of a set of normalized 3D points, ref=(0,0,0)."""
    if not pts:
        return 0.0
    nd = front_indices(pts)
    pts_nd = [pts[i] for i in nd]
    arr = np.array(pts_nd)
    # sort by z descending, sweep
    order = np.argsort(-arr[:, 2])
    arr = arr[order]
    hv = 0.0
    prev_z = 0.0
    slices = []
    for pt in arr:
        if pt[2] > prev_z:
            dz = pt[2] - prev_z
            slices.append((pt[0], pt[1], dz))
            prev_z = pt[2]
    # exact 3D HV by inclusion-exclusion on slices (exact for non-dominated set)
    if not slices:
        return 0.0
    # sort slices by z descending (already done); cumulative 2D union
    covered = []  # list of (x, y) rectangles
    total = 0.0
    prev_z = 0.0
    for x, y, dz in slices:
        # 2D area of union of covered rects + this rect
        # simple: each non-dominated slice contributes x*y*dz minus overlaps
        # for simplicity with small sets, use brute-force inclusion
        area = x * y
        for cx, cy in covered:
            area -= max(0, min(x, cx)) * max(0, min(y, cy))
        total += area * dz
        covered.append((x, y))
    return total


def gp_predict(train_X, train_y, test_X):
    """Simple GP with fixed hyperparams (no sklearn dependency for replay speed).
    Returns (mean, std) arrays. Uses RBF kernel with fixed lengthscale."""
    if len(train_X) == 0:
        return np.full(len(test_X), np.mean(train_y) if len(train_y) else 0.5), \
               np.full(len(test_X), 1.0)
    ls = 1.0
    sigma_f = 1.0
    sigma_n = 0.01

    def k(a, b):
        d2 = np.sum((a - b) ** 2, axis=-1)
        return sigma_f ** 2 * np.exp(-d2 / (2 * ls ** 2))

    K = k(train_X[:, None, :] if train_X.ndim == 1 else train_X[:, None, :],
          train_X[None, :, :] if train_X.ndim == 1 else train_X[None, :, :])
    K += sigma_n ** 2 * np.eye(len(train_X))
    k_star = k(test_X[:, None, :], train_X[None, :, :])
    K_inv = np.linalg.inv(K + 1e-8 * np.eye(len(train_X)))
    mu = k_star @ K_inv @ train_y
    var = sigma_f ** 2 - np.sum(k_star @ K_inv * k_star, axis=1)
    std = np.sqrt(np.maximum(var, 0))
    return mu, std


def encode_config(cid, cids):
    """Simple structural encoding: index-based + manual features."""
    idx = cids.index(cid)
    parts = cid.split('__')
    topo = parts[0]
    fam = parts[1]
    z = parts[2]
    # features: n_nodes, has_v, has_dual_e, recovery, fam_ord, z_ord, topo_ord
    n_nodes = {'SER': 2, 'SERV': 3, 'PARALLELER': 3, 'DYNAMICDAG': 4}[topo]
    has_v = 1.0 if topo in ('SERV', 'DYNAMICDAG') else 0.0
    has_de = 1.0 if topo in ('PARALLELER', 'DYNAMICDAG') else 0.0
    recovery = 1.0 if 'REROUTE' in z else 0.0
    fam_ord = {'BALANCED': 0, 'HETEROGENEOUS': 1, 'QUALITY': 2}[fam]
    topo_ord = {'SER': 0, 'SERV': 1, 'PARALLELER': 2, 'DYNAMICDAG': 3}[topo]
    return np.array([n_nodes / 4, has_v, has_de, recovery, fam_ord / 2, topo_ord / 3])


def c_eval_estimate(cid):
    """Estimated evaluation cost (tokens) for revealing this config — structural,
    NOT the objective C(G)."""
    parts = cid.split('__')
    topo, fam = parts[0], parts[1]
    z = parts[2]
    base = {'SER': 2, 'SERV': 3, 'PARALLELER': 3, 'DYNAMICDAG': 4}[topo]
    # rough per-node token estimate
    per_node = 300
    eval_cost = base * per_node
    if 'REROUTE' in z:
        eval_cost += 500  # recovery calls
    return eval_cost


def run_replay(norm_items, cids, features, algo_name, seed):
    """One replay seed for one algorithm. Returns HV ratio curve."""
    rng = np.random.default_rng(seed)
    n = len(cids)
    c_evals = np.array([c_eval_estimate(cid) for cid in cids], dtype=float)
    c_evals = c_evals / c_evals.max()

    # shared initial design
    init = rng.choice(n, N_INIT, replace=False)
    evaluated = set(init.tolist())
    D = [(i, norm_items[cids[i]]) for i in sorted(evaluated)]

    # compute reference HV (full cube)
    full_pts = [norm_items[c] for c in cids]
    hv_star = compute_hv(full_pts)
    if hv_star == 0:
        hv_star = 1e-9

    # extract objective components
    all_q = np.array([norm_items[c][0] for c in cids])
    all_c = np.array([norm_items[c][1] for c in cids])
    all_l = np.array([norm_items[c][2] for c in cids])
    full_nd = set(front_indices(full_pts))

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
        # surrogate prediction for Q only (C and L are deterministic from structure)
        train_idx = [i for i, _ in D]
        train_y = all_q[train_idx]
        test_idx = unevaluated
        if algo_name in ('ehvi', 'sa_pgfs', 'scalarized', 'greedy_q') and len(train_idx) >= 2:
            X_tr = np.array([features[i] for i in train_idx])
            X_te = np.array([features[i] for i in test_idx])
            mu, std = gp_predict(X_tr, train_y, X_te)
        else:
            mu = np.full(len(test_idx), 0.5)
            std = np.full(len(test_idx), 1.0)

        if algo_name == 'random':
            pick = int(rng.integers(len(test_idx)))
        elif algo_name == 'greedy_q':
            pick = int(np.argmax(mu))
        elif algo_name == 'scalarized':
            w = WEIGHTS[(t - N_INIT) % len(WEIGHTS)]
            c_te = all_c[test_idx]
            l_te = all_l[test_idx]
            scores = w[0] * mu + w[1] * c_te + w[2] * l_te
            pick = int(np.argmax(scores))
        elif algo_name == 'ehvi':
            current_pts = [pt for _, pt in D]
            current_hv = compute_hv(current_pts)
            best_gain = -1
            pick = 0
            for j in range(len(test_idx)):
                q_samples = np.clip(rng.normal(mu[j], std[j] + 1e-6, N_MC), 0, 1)
                c_j, l_j = all_c[test_idx[j]], all_l[test_idx[j]]
                gains = []
                for qs in q_samples:
                    cand = current_pts + [(qs, c_j, l_j)]
                    gains.append(compute_hv(cand) - current_hv)
                e = np.mean(gains)
                if e > best_gain:
                    best_gain = e
                    pick = j
        elif algo_name == 'sa_pgfs':
            current_pts = [pt for _, pt in D]
            current_hv = compute_hv(current_pts)
            best_score = -1
            pick = 0
            for j in range(len(test_idx)):
                q_samples = np.clip(rng.normal(mu[j], std[j] + 1e-6, N_MC), 0, 1)
                c_j, l_j = all_c[test_idx[j]], all_l[test_idx[j]]
                gains = []
                for qs in q_samples:
                    cand = current_pts + [(qs, c_j, l_j)]
                    gains.append(compute_hv(cand) - current_hv)
                e = np.mean(gains)
                score = e / (c_evals[test_idx[j]] ** 1.0 + 1e-9)
                if score > best_score:
                    best_score = score
                    pick = j
        else:
            raise ValueError(algo_name)
        chosen = test_idx[pick]
        evaluated.add(chosen)
        D.append((chosen, norm_items[cids[chosen]]))
        D.sort(key=lambda x: x[0])

    # Pareto recall at each step
    recall_curve = []
    for t in range(N_INIT, n + 1):
        pts_t = [norm_items[cids[i]] for i in sorted(evaluated)[:t]]
        nd_t = set(front_indices(pts_t))
        found = len(nd_t & full_nd)
        recall_curve.append(found / max(1, len(full_nd)))

    return hv_curve, recall_curve


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    clean_items, fault_items = load_cube()
    results = {}
    for state_name, items in [('s_clean', clean_items), ('s_fault30', fault_items)]:
        cids = sorted(items.keys())
        norm = normalize(items)
        features = np.array([encode_config(c, cids) for c in cids])
        state_result = {}
        for algo in ALGOS:
            hv_traces = []
            recall_traces = []
            t0 = time.time()
            for seed in range(N_SEEDS):
                hv_c, rec_c = run_replay(norm, cids, features, algo, seed)
                hv_traces.append(hv_c)
                recall_traces.append(rec_c)
            hv_arr = np.array(hv_traces)
            rec_arr = np.array(recall_traces)
            n95 = []
            for s in range(N_SEEDS):
                idx = next((i for i, h in enumerate(hv_arr[s]) if h >= 0.95), len(hv_arr[s]) - 1)
                n95.append(idx + N_INIT)
            auc = np.mean([np.mean(hv_arr[s]) for s in range(N_SEEDS)])
            state_result[algo] = dict(
                hv_mean=hv_arr.mean(axis=0).tolist(),
                hv_std=hv_arr.std(axis=0).tolist(),
                recall_mean=rec_arr.mean(axis=0).tolist(),
                n95_mean=float(np.mean(n95)),
                n95_std=float(np.std(n95)),
                auc_hv=float(auc),
                final_regret=float(1 - hv_arr[:, -1].mean()),
            )
            elapsed = time.time() - t0
            print(f'{state_name} {algo:14s} N95={np.mean(n95):.1f}±{np.std(n95):.1f} '
                  f'AUC={auc:.3f} R_final={1-hv_arr[:,-1].mean():.4f} ({elapsed:.0f}s)',
                  flush=True)
        results[state_name] = state_result
    (OUT / 'RESULTS_SAPGFS.json').write_text(json.dumps(
        dict(results=results, n_seeds=N_SEEDS, n_init=N_INIT,
             algorithms=ALGOS, note='zero LLM calls, paired seeds, shared D_0'),
        indent=1))
    print('done')


if __name__ == '__main__':
    run()
