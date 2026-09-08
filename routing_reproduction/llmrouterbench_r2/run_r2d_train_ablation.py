"""R2D train-construction ablation: the frozen R2A train file (pairwise_train.json)
drops ALL ties (routellm_adaptor.py:151 include_ties=False) while 68-73% of test
queries are ties. This script rebuilds the FULL train split (ties included) with the
SAME loader/split (baseline.yaml config, train_ratio .8, seed 42) and reruns:

  - KNNRouter algorithm (k=50 cosine neighbor-mean argmax)
  - MLPRouter algorithm (per-model MLPRegressor, official defaults)
  - Reward-router prototype: per-model predicted score - lambda*cost, lambda sweep

Gates: (1) test prompt set identical to frozen pairwise_test; (2) Best Single and
Oracle reproduce the frozen closure numbers. All offline; embeddings from the R2A
global cache (no API calls).
"""
import json
import pathlib
import sys

import numpy as np
import yaml
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPRegressor
from sklearn.neighbors import NearestNeighbors

R = pathlib.Path(__file__).resolve().parent
U = R / "LLMRouterBench"
sys.path.insert(0, str(U))
from baselines import BaselineDataLoader  # noqa: E402

OUT = R / "r2d_train_ablation"
OUT.mkdir(exist_ok=True)
TASKS = {"Math": "math500", "Code": "mbpp", "Knowledge": "mmlupro"}
ADAPTOR = "seed42_split0.8_Fin-R1__vs__cogito-v1-preview-llama-8B"
FROZEN = {("math500", "bs"): 0.68, ("math500", "orc"): 0.74,
          ("mbpp", "bs"): 0.6666666666666666, ("mbpp", "orc"): 0.7025641025641025,
          ("mmlupro", "bs"): 0.54, ("mmlupro", "orc"): 0.64}
KNN_K = 50
EMB = np.load(R / "r2a_local" / "global_embeddings.npy")
PROMPTS = json.loads((R / "r2a_local" / "global_prompts.json").read_text())
ROW = {p: i for i, p in enumerate(PROMPTS)}


def build(task):
    """Full split (ties included) via the frozen baseline.yaml loader config."""
    cfg = yaml.safe_load((R / "r2a_local" / task / "baseline.yaml").read_text())["baseline"]
    l = BaselineDataLoader(config=cfg)
    rr = l.load_all_records()
    tr, te = l.split_by_dataset_then_prompt(rr, train_ratio=0.8, random_seed=42)
    def tabulate(recs):
        d = {}
        for r in recs:
            d.setdefault(r.prompt, {})[r.model_name] = (float(r.score), float(r.cost))
        return d
    return tabulate(tr), tabulate(te)


def main():
    rows = []
    for task, ds in TASKS.items():
        tr, te = build(task)
        ad = R / "r2a_local" / task / "adaptor" / ADAPTOR
        pw_tr = json.loads((ad / "pairwise_train.json").read_text())
        pw_te = json.loads((ad / "pairwise_test.json").read_text())

        # gate: frozen test == our test (prompt sets)
        assert {r["prompt"] for r in pw_te} == set(te), f"{task}: test set mismatch"
        # full train superset of frozen informative train
        assert {r["prompt"] for r in pw_tr} <= set(tr), f"{task}: train superset failed"
        n_ties_added = len(tr) - len({r["prompt"] for r in pw_tr})
        print(f"{task}: full train {len(tr)} prompts (frozen pairwise_train "
              f"{len(pw_tr)} + {n_ties_added} tie prompts recovered), test {len(te)}", flush=True)

        pool = sorted(next(iter(te.values())).keys())
        strong, weak = "Fin-R1", "cogito-v1-preview-llama-8B"
        te_prompts = sorted(te)
        Xte = EMB[[ROW[p] for p in te_prompts]]
        s_te = np.array([[te[p][m][0] for m in pool] for p in te_prompts])  # scores
        c_te = np.array([[te[p][m][1] for m in pool] for p in te_prompts])  # costs

        tr_prompts = sorted(tr)
        Xtr = EMB[[ROW[p] for p in tr_prompts]]
        y_tr = np.array([[tr[p][m][0] for m in pool] for p in tr_prompts])
        cost_tr = np.array([[tr[p][m][1] for m in pool] for p in tr_prompts])
        i_strong, i_weak = pool.index(strong), pool.index(weak)

        def add(method, acc, cost, note=""):
            rows.append(dict(dataset=ds, method=method, accuracy=round(float(acc), 4),
                             cost=None if cost is None else round(float(cost), 7), note=note))

        # Best Single (train selected, full train) + Oracle: gates
        tr_mean = y_tr.mean(0)
        bs_i = int(np.argmax(tr_mean))
        acc_bs = float(s_te[:, bs_i].mean())
        orc = float(s_te.max(1).mean())
        assert np.isclose(acc_bs, FROZEN[(ds, "bs")]) and np.isclose(orc, FROZEN[(ds, "orc")]), \
            f"GATE FAIL {ds}: bs {acc_bs} orc {orc}"
        add("Best Single", acc_bs, float(c_te[:, bs_i].mean()), f"full-train selected: {pool[bs_i]}")
        add("Oracle", orc, None)

        # Random seed 0 for reference
        rng = np.random.RandomState(0)
        rc = rng.randint(0, 2, len(te_prompts))
        add("Random", float(s_te[np.arange(len(rc)), rc].mean()),
            float(c_te[np.arange(len(rc)), rc].mean()), "seed 0")

        # ---- official KNN algorithm on FULL train --------------------------
        kk = min(KNN_K, len(tr_prompts))
        nn = NearestNeighbors(n_neighbors=kk, metric="cosine").fit(Xtr)
        _, ind = nn.kneighbors(Xte)
        pred_knn = y_tr[ind].mean(1)  # neighbor mean score per model
        knn_choice = pred_knn.argmax(1)
        add("KNN (full train)", float(s_te[np.arange(len(te)), knn_choice].mean()),
            float(c_te[np.arange(len(te)), knn_choice].mean()),
            f"k={kk}; predicted-score argmax")

        # ---- official MLP algorithm (per-model regression) on FULL train ---
        mlps = []
        for j in range(len(pool)):
            m = MLPRegressor(hidden_layer_sizes=(100, 100, 100), activation="relu",
                             learning_rate_init=0.001, max_iter=200, random_state=1234)
            m.fit(Xtr, y_tr[:, j])
            mlps.append(m)
        pred_mlp = np.column_stack([m.predict(Xte) for m in mlps])
        mlp_choice = pred_mlp.argmax(1)
        acc_mlp = float(s_te[np.arange(len(te)), mlp_choice].mean())
        cost_mlp = float(c_te[np.arange(len(te)), mlp_choice].mean())
        add("MLP (full train)", acc_mlp, cost_mlp, "per-model score regression, official defaults")

        # ---- reward router prototype: reward = pred_score - lambda * cost --
        lam_grid = [0.0, 1.0, 10.0, 100.0, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8]
        scale = c_te.mean()  # costs are ~1e-4 USD; sweep lambda relative to score scale
        for lam in lam_grid:
            rew = pred_mlp - lam * scale * c_te  # tie queries: equal scores -> free model wins
            ch = rew.argmax(1)
            acc = float(s_te[np.arange(len(te)), ch].mean())
            cost = float(c_te[np.arange(len(te)), ch].mean())
            rows.append(dict(dataset=ds, method=f"RewardMLP lam={lam:g}", accuracy=round(acc, 4),
                             cost=round(cost, 7),
                             note="pred score - lam*scale*cost; prototype of Multi-objective Router"))

        # ---- logreg P(strong wins) reference on full train ------------------
        lab = (y_tr[:, i_strong] > y_tr[:, i_weak]).astype(int)
        if 0 < lab.sum() < len(lab):
            lg = LogisticRegression(max_iter=2000).fit(Xtr, lab)
            p = lg.predict_proba(Xte)[:, 1]
            ch = np.where(p > .5, i_strong, i_weak)
            add("LogReg P(strong>weak)", float(s_te[np.arange(len(te)), ch].mean()),
                float(c_te[np.arange(len(te)), ch].mean()), "threshold .5, full train")
        print(f"{task}: gates PASS; MLP(full)={acc_mlp:.4f} vs BestSingle={acc_bs:.4f}", flush=True)

    import csv
    with open(OUT / "RESULTS.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (OUT / "RUN.json").write_text(json.dumps(dict(
        status="PASS", train="FULL split (ties included) rebuilt from frozen baseline.yaml "
        "loader config, train_ratio .8 seed 42; test identical to frozen pairwise_test "
        "(gated)", embeddings="R2A global cache (2474x3584, sha-audited), 0 API calls",
        cause_under_test="pairwise_train.json dropped all train ties (adaptor include_ties=False)",
    ), indent=2))
    for r in rows:
        print(r, flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
