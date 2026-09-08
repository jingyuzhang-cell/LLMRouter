"""R3 pilot experiment: is the reward learnable? (user Step 2)

Input:  data/frozen/pilot_v1.jsonl + data/frozen/split.json (from freeze.py)
        embeddings: gte-Qwen2-7B-instruct fp16 (R2A-compatible, cosine-validated)
Models: MLP reward predictor 3584 -> 1024 -> 512 -> 4 (user spec, seed 1234)
        + official-default control (100,100,100)
Targets per slot: quality.final
Eval on pilot test split:
  - regression: per-slot MAE / R^2 vs. predicting the train mean (learnability gate)
  - routing (lambda=0): argmax predicted quality -> accuracy vs Random / Best Single / Oracle
  - reward routing over frozen (lambda, mu): accuracy / cost / latency Pareto points
Output: PILOT_RESULT.json + PILOT_TABLE.md
"""
import json
import pathlib
import sys

import numpy as np
import torch
from sklearn.neural_network import MLPRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import Ridge
from sklearn.neighbors import KNeighborsRegressor

R = pathlib.Path(__file__).resolve().parent
GTE = "/root/autodl-tmp/models/gte-Qwen2-7B-instruct-fp16"
SLOTS = ["small", "medium", "large", "reasoning"]
SLOT_NAME = {"small": "Qwen/Qwen2.5-3B-Instruct", "medium": "Qwen/Qwen2.5-7B-Instruct",
             "large": "Qwen/Qwen2.5-14B-Instruct",
             "reasoning": "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B"}
LAMS = (0, 0.1, 0.5, 1, 2, 5)
MUS = (0, 0.1, 0.5, 1)


def embed(prompts):
    from sentence_transformers import SentenceTransformer
    enc = SentenceTransformer(GTE, trust_remote_code=False, device="cuda",
                              model_kwargs={"torch_dtype": torch.float16})
    enc.max_seq_length = 32768
    v = enc.encode(prompts, batch_size=8, convert_to_numpy=True,
                   normalize_embeddings=True, show_progress_bar=False)
    del enc
    torch.cuda.empty_cache()
    return v


def main():
    recs = [json.loads(l) for l in (R / "data/frozen/pilot_v1.jsonl").read_text().splitlines() if l.strip()]
    split = json.loads((R / "data/frozen/split.json").read_text())
    by_slot = {r["query_id"]: {s["slot"]: s for s in r["responses"]} for r in recs}

    emb_path = R / "data/frozen/pilot_emb.npy"
    if emb_path.exists():
        X = np.load(emb_path)
    else:
        X = embed([r["query"] for r in recs])
        np.save(emb_path, X)

    ids = [r["query_id"] for r in recs]
    tr_i = [i for i, q in enumerate(ids) if q in set(split["train"])]
    te_i = [i for i, q in enumerate(ids) if q in set(split["test"])]
    Y = np.full((len(recs), 4), np.nan)
    for i, r in enumerate(recs):
        for j, s in enumerate(SLOTS):
            v = by_slot[r["query_id"]][s]["quality"]["final"]
            if v is not None:
                Y[i, j] = v
    keep_tr = tr_i  # rows with any NaN target are dropped per-fit inside loop below
    Xtr, Xte = X[tr_i], X[te_i]
    Ytr, Yte = Y[tr_i], Y[te_i]

    results = {"n_train": len(tr_i), "n_test": len(te_i), "slot": SLOT_NAME,
               "regression": {}, "routing": {}, "pareto": []}

    for arch, tag in (((1024, 512), "user_spec"), ((100, 100, 100), "official_default")):
        preds = np.zeros_like(Yte)
        train_preds = np.zeros_like(Ytr)
        for j, s in enumerate(SLOTS):
            m = (Ytr[:, j] == Ytr[:, j])
            mlp = MLPRegressor(hidden_layer_sizes=arch, activation="relu",
                               learning_rate_init=1e-3, max_iter=800, random_state=1234,
                               early_stopping=True, validation_fraction=0.2, n_iter_no_change=30)
            mlp.fit(Xtr[m], Ytr[m, j])
            preds[:, j] = mlp.predict(Xte)
            train_preds[:, j] = mlp.predict(Xtr)
        reg = {}
        for j, s in enumerate(SLOTS):
            ok = Yte[:, j] == Yte[:, j]
            if ok.sum() == 0:
                continue
            mae = float(mean_absolute_error(Yte[ok, j], preds[ok, j]))
            base = float(mean_absolute_error(Yte[ok, j], np.full(ok.sum(), np.nanmean(Ytr[:, j]))))
            ss_res = float(((Yte[ok, j] - preds[ok, j]) ** 2).sum())
            ss_tot = float(((Yte[ok, j] - Yte[ok, j].mean()) ** 2).sum())
            reg[s] = dict(mae=round(mae, 4), mae_mean_baseline=round(base, 4),
                          r2=round(1 - ss_res / ss_tot, 4) if ss_tot > 0 else None)
        results["regression"][tag] = reg
        if tag == "user_spec":
            P = preds

    # routing metrics on test (lambda=0: argmax predicted quality)
    S = Yte.copy()  # final quality
    C = np.array([[by_slot[ids[i]][s]["cost"].get("usd") or 0.0 for s in SLOTS] for i in te_i])
    T = np.array([[by_slot[ids[i]][s]["latency"].get("total_ms") or 1.0 for s in SLOTS] for i in te_i])
    valid = ~np.isnan(S).any(1)
    S_, C_, T_, P_ = S[valid], C[valid], T[valid], P[valid]
    n = len(S_)
    rng = np.random.RandomState(0)

    def acc_cost(choice):
        return dict(accuracy=round(float(S_[np.arange(n), choice].mean()), 4),
                    cost_usd=round(float(C_[np.arange(n), choice].mean()), 7),
                    latency_ms=round(float(T_[np.arange(n), choice].mean()), 1))

    results["routing"]["Random"] = acc_cost(rng.randint(0, 4, n))
    best = int(np.nanmean(Ytr, 0).argmax())
    results["routing"]["Best Single"] = {**acc_cost(np.full(n, best)), "model": SLOTS[best]}
    results["routing"]["Oracle"] = dict(accuracy=round(float(S_.max(1).mean()), 4))
    results["routing"]["MLP reward (lam=0)"] = acc_cost(P_.argmax(1))

    # Predict resource use from training observations only. Test C/T are evaluation
    # outcomes, never decision inputs. Scales are frozen from the training split.
    resource_predictions = []
    resource_scales = []
    for field, key in (("cost", "usd"), ("latency", "total_ms")):
        targets = np.array([[by_slot[ids[i]][slot][field].get(key, np.nan)
                             for slot in SLOTS] for i in tr_i], dtype=float)
        if not np.isfinite(targets).all() or (targets < 0).any():
            raise ValueError(f"Missing/invalid training {field}; cannot fit resource predictor")
        resource_predictions.append(np.maximum(0, Ridge(alpha=20).fit(Xtr, targets).predict(Xte))[valid])
        positive = targets[targets > 0]
        resource_scales.append(float(np.median(positive)) if positive.size else 1.0)
    C_hat, T_hat = resource_predictions
    c_scale, t_scale = resource_scales
    complete = np.isfinite(Ytr).all(axis=1)
    if not complete.any():
        raise ValueError("No complete training rows for kNN quality baseline")
    knn = KNeighborsRegressor(n_neighbors=min(20, int(complete.sum())), metric="cosine", algorithm="brute")
    knn_pred = knn.fit(Xtr[complete], Ytr[complete]).predict(Xte)[valid]
    results["routing"]["kNN quality (lam=0)"] = acc_cost(knn_pred.argmax(1))
    results["resource_prediction"] = dict(method="Ridge alpha=20, training only", cost_scale=c_scale,
                                           latency_scale=t_scale, mixed_deployment="exploratory only")
    # Frozen (lam, mu) sweep; do not choose weights on the test split.
    for lam in LAMS:
        for mu in MUS:
            ch = (P_ - lam * C_hat / c_scale - mu * T_hat / t_scale).argmax(1)
            results["pareto"].append(dict(lam=lam, mu=mu, **acc_cost(ch)))

    (R / "PILOT_RESULT.json").write_text(json.dumps(results, indent=2, allow_nan=False))
    print(json.dumps(results, indent=2)[:3500])


if __name__ == "__main__":
    main()
