"""R2B / user-Phase-1: neural router baselines on the frozen R2A binary protocol.

Question: can a simple neural router beat Best Single?

Data/tasks/split/embeddings: frozen by R2_PROTOCOL + AMENDMENT_001/002 + R2A closure
  - tasks: math500 / mbpp / mmlupro, binary pool Fin-R1 (model_a) vs cogito (model_b)
  - split: seed42 ratio 0.8, pairwise_train/test from R2A adaptor dirs
  - embeddings: gte-Qwen2-7B-instruct 3584-dim, L2-normalized (R2A global cache rows)
No inference API calls; no new embeddings.

Methods:
  Random        uniform coin, seed 0
  Best Single   train-mean-score selected single model
  KNN           official RouterBench KNNRouter algorithm ported to this schema:
                cosine NearestNeighbors k=50 -> neighbor mean score per model -> argmax
  MLP           official RouterBench MLPRouter algorithm ported to this schema:
                per-model MLPRegressor((100,100,100), relu, lr .001, max_iter 200,
                random_state 1234) on embeddings -> predicted score -> argmax
  Oracle        per-query max score (hindsight)

Metrics: Accuracy (mean score of routed model), Cost (mean USD of routed model),
Latency (NOT RECORDED in the frozen official data -> N/A; collection planned for the
own-pool dataset). Operating point: pure argmax predicted score (lambda=0).

Validation gate: Best Single and Oracle must reproduce the frozen R2A closure numbers
(math .68/.74, mbpp .6667/.7026, mmlupro .54/.64) exactly.
"""
import json
import pathlib
import time

import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.neighbors import NearestNeighbors

R = pathlib.Path(__file__).resolve().parent
OUT = R / "r2b_neural_baselines"
OUT.mkdir(exist_ok=True)

TASKS = {
    "Math": "math500",
    "Code": "mbpp",
    "Knowledge": "mmlupro",
}
ADAPTOR = "seed42_split0.8_Fin-R1__vs__cogito-v1-preview-llama-8B"
FROZEN_CLOSURE = {  # from r2a_local/STATIC_VS_DYNAMIC.json (R2A closure PASS)
    ("math500", "best_single"): 0.68, ("math500", "oracle"): 0.74,
    ("mbpp", "best_single"): 0.6666666666666666, ("mbpp", "oracle"): 0.7025641025641025,
    ("mmlupro", "best_single"): 0.54, ("mmlupro", "oracle"): 0.64,
}
KNN_K = 50  # official RouterBench default; all train sets (126/231/227) >= 50


def load_task(task):
    d = R / "r2a_local" / task / "adaptor" / ADAPTOR
    tr = json.loads((d / "pairwise_train.json").read_text())
    te = json.loads((d / "pairwise_test.json").read_text())
    emb = np.load(d / "prompt_embeddings.npy")
    idx = json.loads((d / "prompt_index.json").read_text())
    assert len(idx) == emb.shape[0]
    row_of = {e["prompt"]: e["idx"] for e in idx}
    def X(rows):
        return emb[[row_of[r["prompt"]] for r in rows]]
    return tr, te, X(tr), X(te)


def routed_metrics(rows, choice):
    """choice: list of 'model_a'/'model_b' per row -> (accuracy, cost)."""
    acc = np.mean([r["score_" + c] for r, c in zip(rows, choice)])
    cost = np.mean([r["cost_" + c] for r, c in zip(rows, choice)])
    return float(acc), float(cost)


def main():
    rows_out, started = [], time.time()
    for task, ds in TASKS.items():
        tr, te, Xtr, Xte = load_task(task)
        ya = np.array([r["score_model_a"] for r in tr])
        yb = np.array([r["score_model_b"] for r in tr])

        def add(method, acc, cost, note=""):
            rows_out.append(dict(task=task, dataset=ds, method=method, accuracy=acc,
                                 cost=cost, latency=None, note=note))

        # Random (seed 0)
        rng = np.random.RandomState(0)
        choice = ["model_a" if u < .5 else "model_b" for u in rng.rand(len(te))]
        add("Random", *routed_metrics(te, choice), "uniform coin seed 0")

        # Best Single (train selected)
        best = "model_a" if ya.mean() >= yb.mean() else "model_b"
        add("Best Single", *routed_metrics(te, [best] * len(te)),
            f"train-selected: {tr[0][best]}")

        # KNN (official algorithm, cosine k=50)
        nn = NearestNeighbors(n_neighbors=KNN_K, metric="cosine").fit(Xtr)
        _, ind = nn.kneighbors(Xte)
        pred = np.column_stack([ya[ind].mean(1), yb[ind].mean(1)])
        knn_choice = np.argmax(pred, axis=1)
        choice = ["model_a" if i == 0 else "model_b" for i in knn_choice]
        _, nn_tr = NearestNeighbors(n_neighbors=KNN_K, metric="cosine").fit(Xtr).kneighbors(Xtr)
        tr_pred = np.column_stack([ya[nn_tr].mean(1), yb[nn_tr].mean(1)])
        tr_choice = ["model_a" if i == 0 else "model_b" for i in np.argmax(tr_pred, axis=1)]
        add("KNNRouter", *routed_metrics(te, choice),
            f"k={KNN_K} cosine; train acc {routed_metrics(tr, tr_choice)[0]:.4f}")

        # MLP (official algorithm: per-model MLPRegressor)
        mlps = {}
        for name, y in (("model_a", ya), ("model_b", yb)):
            m = MLPRegressor(hidden_layer_sizes=(100, 100, 100), activation="relu",
                             learning_rate_init=0.001, max_iter=200, random_state=1234)
            m.fit(Xtr, y)
            mlps[name] = m
        pred = np.column_stack([mlps["model_a"].predict(Xte), mlps["model_b"].predict(Xte)])
        choice = ["model_a" if i == 0 else "model_b" for i in np.argmax(pred, axis=1)]
        tr_pred = np.column_stack([mlps["model_a"].predict(Xtr), mlps["model_b"].predict(Xtr)])
        tr_choice = ["model_a" if i == 0 else "model_b" for i in np.argmax(tr_pred, axis=1)]
        add("MLPRouter", *routed_metrics(te, choice),
            f"official defaults; train acc {routed_metrics(tr, tr_choice)[0]:.4f}")

        # Oracle (hindsight)
        acc = float(np.mean([max(r["score_model_a"], r["score_model_b"]) for r in te]))
        add("Oracle", acc, None, "per-query max score")

        # Step-1 context: where does oracle headroom live (test winner stats)
        a_only = sum(1 for r in te if r["score_model_a"] > r["score_model_b"])
        b_only = sum(1 for r in te if r["score_model_b"] > r["score_model_a"])
        both = sum(1 for r in te if r["score_model_a"] == r["score_model_b"] == 1.0)
        none = sum(1 for r in te if r["score_model_a"] == r["score_model_b"] == 0.0)
        print(f"{ds}: a_only={a_only} b_only={b_only} both_right={both} both_wrong={none} "
              f"n={len(te)}", flush=True)

        # validation gate vs frozen closure
        got = {(r["method"]): r for r in rows_out if r["dataset"] == ds}
        for m, key in (("Best Single", "best_single"), ("Oracle", "oracle")):
            assert np.isclose(got[m]["accuracy"], FROZEN_CLOSURE[(ds, key)]), \
                f"GATE FAIL {ds} {m}: {got[m]['accuracy']} != {FROZEN_CLOSURE[(ds, key)]}"
        print(f"{ds}: gate PASS (best_single/oracle reproduce frozen closure)", flush=True)

    # results
    import csv
    with open(OUT / "RESULTS.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    audit = dict(
        status="PASS",
        elapsed_seconds=round(time.time() - started, 1),
        protocol="frozen R2A binary protocol (R2_PROTOCOL + AMENDMENT_001/002); no API calls, no new embeddings",
        pool="Fin-R1 (model_a) vs cogito-v1-preview-llama-8B (model_b)",
        methods=dict(
            random="uniform coin, np.random.RandomState(0)",
            best_single="train-mean-score selected",
            knn=f"RouterBench KNNRouter algorithm, cosine k={KNN_K}",
            mlp="RouterBench MLPRouter algorithm, per-model MLPRegressor (100,100,100) relu lr .001 max_iter 200 rs 1234",
            oracle="per-query max score",
        ),
        metrics="accuracy=mean routed score; cost=mean routed USD; latency NOT RECORDED in frozen data -> None",
        validation_gate="best_single and oracle reproduce r2a_local/STATIC_VS_DYNAMIC.json exactly (all 3 tasks)",
        winner_stats_note="printed a_only/b_only/both_right/both_wrong per task (Step-1 oracle-gap context)",
    )
    (OUT / "RUN.json").write_text(json.dumps(audit, indent=2))
    for r in rows_out:
        print({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items() if v is not None}, flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
