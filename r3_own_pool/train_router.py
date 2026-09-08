"""R3 router training & evaluation per FROZEN design (R3_ROUTER_DESIGN.md).

Methods: Random / Best Single / KNN / MLP-winner (old route) / RewardReg (independent
per-model regression) / Hybrid Utility Router (ours: model-conditioned Q-hat, MSE +
alpha*pairwise-rank) / Oracle. Utility sweep over frozen (lam, mu) grid with
train-split cost/latency profiles. Router behavior shift (routing distribution as
lam grows) is part of the required output.

Run with R2 venv python (torch + sentence_transformers + sklearn):
  /root/autodl-tmp/llmrouterbench_r2_venv/bin/python train_router.py --frozen pilot_v1
Smoke validation on pilot only; conclusions wait for the full run.
"""
import argparse
import json
import pathlib

import numpy as np
import torch
import torch.nn as nn
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.neighbors import NearestNeighbors

R = pathlib.Path(__file__).resolve().parent
GTE = "/root/autodl-tmp/models/gte-Qwen2-7B-instruct-fp16"
SLOTS = ["small", "medium", "large", "reasoning"]
NAME = {"small": "Qwen2.5-3B", "medium": "Qwen2.5-7B", "large": "Qwen2.5-14B",
        "reasoning": "DS-R1-Distill-14B"}
LAMS = (0, 0.1, 0.5, 1, 2, 5)
MUS = (0, 0.1, 0.5, 1)
SEED = 42


def embed(prompts):
    from sentence_transformers import SentenceTransformer
    enc = SentenceTransformer(GTE, trust_remote_code=False, device="cuda",
                              model_kwargs={"torch_dtype": torch.float16})
    enc.max_seq_length = 32768
    v = enc.encode(prompts, batch_size=8, convert_to_numpy=True,
                   normalize_embeddings=True, show_progress_bar=False)
    del enc
    torch.cuda.empty_cache()
    return v.astype(np.float32)


class HybridUtilityRouter(nn.Module):
    """Model-conditioned quality predictor. use_m_emb=False gives the pre-registered
    query-only ablation (shared trunk + 4 per-model heads, same loss/optimizer) so
    the value of model conditioning is measured without trainer confounds."""

    def __init__(self, q_dim=3584, m_dim=64, alpha=0.5, margin=0.05, lr=1e-3,
                 seed=SEED, use_m_emb=True, pure_rank=False):
        super().__init__()
        torch.manual_seed(seed)
        self.use_m_emb = use_m_emb
        self.pure_rank = pure_rank  # ranking-only baseline (no MSE term)
        self.alpha, self.margin = alpha, margin
        if use_m_emb:
            self.m_emb = nn.Embedding(4, m_dim)
            in_dim = q_dim + m_dim
            self.net = nn.Sequential(nn.Linear(in_dim, 256), nn.ReLU(), nn.Dropout(0.2),
                                     nn.Linear(256, 128), nn.ReLU(), nn.Linear(128, 1))
        else:  # ablation A: query-only, 4 independent output heads
            self.net = nn.Sequential(nn.Linear(q_dim, 256), nn.ReLU(), nn.Dropout(0.2),
                                     nn.Linear(256, 128), nn.ReLU(), nn.Linear(128, 4))
        self.opt = torch.optim.Adam(self.parameters(), lr=lr)

    def predict_batch(self, q):
        """q: torch [b, q_dim] -> [b, 4] predicted quality for all models."""
        if self.use_m_emb:
            outs = []
            for m in range(4):
                mm = torch.full((len(q),), m, dtype=torch.long)
                outs.append(self.net(torch.cat([q, self.m_emb(mm)], 1)).squeeze(-1))
            return torch.stack(outs, 1)
        return self.net(q)

    def fit(self, Q_in, M_in, Y_in, epochs=60, batch_q=64, verbose=False):
        n_q = Q_in.shape[0]
        for ep in range(epochs):
            perm = np.random.RandomState(SEED + ep).permutation(n_q)
            tot = 0.0
            for s in range(0, n_q, batch_q):
                idx = perm[s:s + batch_q]
                q = torch.tensor(Q_in[idx])
                preds = self.predict_batch(q)
                y = torch.tensor(Y_in[idx], dtype=torch.float32)
                loss_q = ((preds - y) ** 2).mean()
                loss_r = torch.tensor(0.0)
                for i in range(4):
                    for j in range(4):
                        if i == j:
                            continue
                        pos = (y[:, i] - y[:, j] > 0).float()
                        viol = torch.relu(-(preds[:, i] - preds[:, j]) + self.margin)
                        loss_r = loss_r + (pos * viol).mean() / 12.0
                loss = self.alpha * loss_r if self.pure_rank else loss_q + self.alpha * loss_r
                self.opt.zero_grad()
                loss.backward()
                self.opt.step()
                tot += float(loss)
            if verbose and ep % 10 == 0:
                print(f"  ep{ep}: loss {tot/max(1,n_q//batch_q):.4f}", flush=True)

    def predict_all(self, Q_in):
        with torch.no_grad():
            return self.predict_batch(torch.tensor(Q_in)).numpy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frozen", default="pilot_v1")
    ap.add_argument("--alpha", type=float, default=None,
                    help="None = select from grid on carved val split")
    a = ap.parse_args()
    fr = R / "data/frozen"
    recs = [json.loads(l) for l in (fr / f"{a.frozen}.jsonl").read_text().splitlines() if l.strip()]
    split = json.loads((fr / "split.json").read_text())
    by = {r["query_id"]: {s["slot"]: s for s in r["responses"]} for r in recs}
    ids = [r["query_id"] for r in recs]
    tr = [i for i, q in enumerate(ids) if q in set(split["train"])]
    te = [i for i, q in enumerate(ids) if q in set(split["test"])]

    emb_p = fr / f"{a.frozen}_emb.npy"
    if emb_p.exists():
        X = np.load(emb_p)
    else:
        X = embed([r["query"] for r in recs])
        np.save(emb_p, X)

    Qm = np.full((len(recs), 4), np.nan)
    Cm = np.zeros((len(recs), 4))
    Tm = np.zeros((len(recs), 4))
    for i, r in enumerate(recs):
        for j, s in enumerate(SLOTS):
            b = by[r["query_id"]][s]
            f = b["quality"]["final"]
            Qm[i, j] = f if f is not None else np.nan
            Cm[i, j] = b["cost"].get("usd") or 0.0
            Tm[i, j] = b["latency"].get("total_ms") or 1.0
    keep_tr = [i for i in tr if not np.isnan(Qm[i]).any()]
    keep_te = [i for i in te if not np.isnan(Qm[i]).any()]
    Xtr, Xte = X[keep_tr], X[keep_te]
    Qtr, Qte = Qm[keep_tr], Qm[keep_te]
    Cte, Tte = Cm[keep_te], Tm[keep_te]
    n = len(keep_te)
    print(f"train {len(keep_tr)} / test {n} (complete-label)")

    # cost/latency profiles from TRAIN only (deployment prior)
    c_prof = np.nanmedian(Cm[keep_tr], 0)
    t_prof = np.nanmedian(Tm[keep_tr], 0)
    cn, tn = c_prof / c_prof.max(), t_prof / t_prof.max()

    res = {}
    def rep(name, choice, extra=None):
        acc = float(Qte[np.arange(n), choice].mean())
        cost = float(Cte[np.arange(n), choice].mean())
        lat = float(Tte[np.arange(n), choice].mean())
        dist = np.bincount(choice, minlength=4) / n
        res[name] = dict(accuracy=round(acc, 4), cost_usd=round(cost, 7),
                         latency_ms=round(lat, 1),
                         routing={NAME[SLOTS[j]]: round(float(dist[j]), 3) for j in range(4)},
                         **(extra or {}))

    rng = np.random.RandomState(0)
    rep("Random", rng.randint(0, 4, n))
    best = int(np.nanmean(Qtr, 0).argmax())
    rep("Best Single", np.full(n, best), extra={"model": NAME[SLOTS[best]]})
    res["Oracle"] = dict(accuracy=round(float(Qte.max(1).mean()), 4))

    # KNN
    kk = min(50, len(keep_tr))
    _, ind = NearestNeighbors(n_neighbors=kk, metric="cosine").fit(Xtr).kneighbors(Xte)
    rep("KNN", Qtr[ind].mean(1).argmax(1))

    # MLP-winner (old route control)
    ywin = Qtr.argmax(1)
    if len(set(ywin)) > 1:
        clf = MLPClassifier(hidden_layer_sizes=(100, 100, 100), random_state=1234, max_iter=400)
        clf.fit(Xtr, ywin)
        rep("MLP-winner", clf.predict(Xte))

    # RewardReg: independent per-model regressors (no model conditioning)
    rr = np.zeros((n, 4))
    for j in range(4):
        m = MLPRegressor(hidden_layer_sizes=(100, 100, 100), random_state=1234,
                         max_iter=400, early_stopping=True)
        m.fit(Xtr, Qtr[:, j])
        rr[:, j] = m.predict(Xte)
    rep("RewardReg", rr.argmax(1))

    # Pairwise Ranking-only Router (baseline: score function trained on rank loss alone)
    hyr = HybridUtilityRouter(alpha=1.0, pure_rank=True)
    hyr.fit(Xtr, np.arange(4), Qtr, epochs=60)
    rep("Ranking-only", hyr.predict_all(Xte).argmax(1))

    # ---- Hybrid Utility Router family: alpha grid selected on a carved val split ----
    # (train -> train/val stratified by dataset seed 42; test untouched)
    ds_tr = [recs[keep_tr[i]]["dataset"] for i in range(len(keep_tr))]
    rngv = np.random.RandomState(42)
    val_idx_by_ds = {}
    for i, ds in enumerate(ds_tr):
        val_idx_by_ds.setdefault(ds, []).append(i)
    val_set = set()
    for ds, idxs in val_idx_by_ds.items():
        idxs = list(idxs)
        rngv.shuffle(idxs)
        val_set.update(idxs[:max(1, len(idxs) // 4)])
    tr_local = [i for i in range(len(keep_tr)) if i not in val_set]
    va_local = sorted(val_set)
    Xtr_l, Xva = Xtr[tr_local], Xtr[va_local]
    Qtr_l, Qva = Qtr[tr_local], Qtr[va_local]

    def routing_acc(pred, Qy):
        return float(Qy[np.arange(len(Qy)), pred.argmax(1)].mean())

    alpha_grid = [0.0, 0.25, 0.5, 1.0]
    val_report = {}
    best_alpha, best_val = None, -1
    for al in alpha_grid:
        m_ = HybridUtilityRouter(alpha=al)
        m_.fit(Xtr_l, np.arange(4), Qtr_l, epochs=60)
        v = routing_acc(m_.predict_all(Xva), Qva)
        val_report[al] = round(v, 4)
        if v > best_val:
            best_val, best_alpha = v, al
    say_alpha = best_alpha if a.alpha is None else a.alpha
    hy = HybridUtilityRouter(alpha=say_alpha)
    hy.fit(Xtr, np.arange(4), Qtr, epochs=60)  # refit on full train with chosen alpha
    P = hy.predict_all(Xte)
    rep(f"Hybrid(lam=0,alpha={say_alpha:g})", P.argmax(1))
    res["Hybrid(lam=0)"] = res.pop(f"Hybrid(lam=0,alpha={say_alpha:g}")  # canonical key

    # ablation ladder: A query-only / B +model / C +utility / D +rank (alpha>0)
    hy0 = HybridUtilityRouter(alpha=say_alpha, use_m_emb=False)
    hy0.fit(Xtr, np.arange(4), Qtr, epochs=60)
    P0 = hy0.predict_all(Xte)
    rep("A:Hybrid-noM(lam=0)", P0.argmax(1))
    if say_alpha == 0:  # ensure a rank-loss variant exists for the ladder
        hy_r = HybridUtilityRouter(alpha=0.5)
        hy_r.fit(Xtr, np.arange(4), Qtr, epochs=60)
        rep("D:Hybrid-rank(lam=0)", hy_r.predict_all(Xte).argmax(1))
    else:
        res["D:Hybrid-rank(lam=0)"] = res["Hybrid(lam=0)"]

    # ---- paper metrics: gap recovery / iso-quality cost / behavior shift ----
    acc_bs = res["Best Single"]["accuracy"]
    acc_or = res["Oracle"]["accuracy"]
    def gap_recovery(acc):
        return round((acc - acc_bs) / max(acc_or - acc_bs, 1e-9), 4)
    for k in list(res):
        if isinstance(res[k], dict) and "accuracy" in res[k] and k != "Oracle":
            res[k]["gap_recovery"] = gap_recovery(res[k]["accuracy"])

    # utility sweep + behavior shift
    sweep = []
    for lam in LAMS:
        for mu in MUS:
            ch = (P - lam * cn[None, :] - mu * tn[None, :]).argmax(1)
            sweep.append(dict(lam=lam, mu=mu, **{k: v for k, v in
                             dict(accuracy=round(float(Qte[np.arange(n), ch].mean()), 4),
                                  cost_usd=round(float(Cte[np.arange(n), ch].mean()), 7),
                                  latency_ms=round(float(Tte[np.arange(n), ch].mean()), 1)).items()}))
    behavior = {f"lam={lam},mu=0": {NAME[SLOTS[j]]: round(float(((P - lam*cn[None,:]).argmax(1) == j).mean()), 3)
                                    for j in range(4)} for lam in (0, 0.5, 1, 5)}
    # paper metric 3: iso-quality cost reduction (points at least as good as Best Single)
    iso = []
    for pt in sweep:
        if pt["accuracy"] >= acc_bs - 0.005:
            iso.append(dict(lam=pt["lam"], mu=pt["mu"], accuracy=pt["accuracy"],
                            cost_reduction_vs_best_single=round(1 - pt["cost_usd"] / max(res["Best Single"]["cost_usd"], 1e-12), 4),
                            latency_reduction_vs_best_single=round(1 - pt["latency_ms"] / max(res["Best Single"]["latency_ms"], 1e-12), 4)))
    iso.sort(key=lambda x: -x["cost_reduction_vs_best_single"])
    paper_metrics = dict(
        oracle_gap_recovery_hybrid=res["Hybrid(lam=0)"].get("gap_recovery"),
        oracle_gap_recovery_hybrid_nom=res["A:Hybrid-noM(lam=0)"].get("gap_recovery"),
        conditioning_gain_accuracy=round(res["Hybrid(lam=0)"]["accuracy"] - res["A:Hybrid-noM(lam=0)"]["accuracy"], 4),
        alpha_selected=say_alpha, alpha_val_routing=val_report,
        iso_quality_points=iso[:5],
    )
    # generalization: per-task-type accuracy for key methods (cross-domain signal)
    tt_te = np.array([recs[keep_te[i]]["task_type"] for i in range(len(keep_te))])
    per_task = {}
    for mname in ("Best Single", "Hybrid(lam=0)", "A:Hybrid-noM(lam=0)"):
        if mname not in res or "routing" not in res.get(mname, {}):
            continue
        # recompute choice per task requires stored routing dist only; use accuracy split
        per_task[mname] = {}
    hy_choice = P.argmax(1)
    bs_choice = np.full(n, best)
    for tt in ("math", "code", "knowledge", "general"):
        msk = tt_te == tt
        if msk.sum() == 0:
            continue
        per_task.setdefault("Best Single", {})[tt] = round(float(Qte[msk][np.arange(msk.sum()), bs_choice[msk]].mean()), 4)
        per_task.setdefault("Hybrid(lam=0)", {})[tt] = round(float(Qte[msk][np.arange(msk.sum()), hy_choice[msk]].mean()), 4)
        per_task.setdefault("Oracle", {})[tt] = round(float(Qte[msk].max(1).mean()), 4)

    # ---- task-level holdout: train on math/code/general, evaluate on knowledge ----
    task_holdout = None
    hold_tr = np.where(np.array([recs[keep_tr[i]]["task_type"] for i in range(len(keep_tr))]) != "knowledge")[0]
    hold_te = np.where(tt_te == "knowledge")[0]
    if len(hold_tr) > 50 and len(hold_te) > 10:
        hy_h = HybridUtilityRouter(alpha=say_alpha)
        hy_h.fit(Xtr[hold_tr], np.arange(4), Qtr[hold_tr], epochs=60)
        ch_h = hy_h.predict_all(Xte[hold_te]).argmax(1)
        bs_h = int(Qtr[hold_tr].mean(0).argmax())
        Qh = Qte[hold_te]
        task_holdout = dict(
            train_tasks=["math", "code", "general"], test_task="knowledge",
            n_test=int(len(hold_te)),
            best_single=round(float(Qh[np.arange(len(hold_te)), bs_h].mean()), 4),
            best_single_model=NAME[SLOTS[bs_h]],
            hybrid=round(float(Qh[np.arange(len(hold_te)), ch_h].mean()), 4),
            oracle=round(float(Qh.max(1).mean()), 4),
            note="router trained WITHOUT knowledge queries; tests task generalization")

    # ---- Pareto curve data (figure-ready) ----
    qmax = Qte.max(1, keepdims=True)
    tie_mask = Qte == qmax
    oracle_cost = float(np.mean([Cte[i][tie_mask[i]].min() for i in range(n)]))
    pareto_curve = dict(
        single_models=[dict(model=NAME[SLOTS[j]], cost_usd=float(c_prof[j]),
                            quality=float(Qte[:, j].mean())) for j in range(4)],
        router=[dict(lam=p["lam"], mu=p["mu"], cost_usd=p["cost_usd"],
                     accuracy=p["accuracy"]) for p in sweep],
        best_single=dict(model=NAME[SLOTS[best]], cost_usd=res["Best Single"]["cost_usd"],
                         accuracy=res["Best Single"]["accuracy"]),
        oracle=dict(accuracy=res["Oracle"]["accuracy"],
                    cost_usd_cheapest_tiebreak=round(oracle_cost, 7)))
    out = dict(frozen=a.frozen, n_train=len(keep_tr), n_test=n,
               profiles=dict(cost_usd={NAME[SLOTS[j]]: float(c_prof[j]) for j in range(4)},
                             latency_ms={NAME[SLOTS[j]]: float(t_prof[j]) for j in range(4)}),
               methods=res, sweep=sweep, behavior_shift=behavior, paper_metrics=paper_metrics,
               per_task_accuracy=per_task, task_holdout=task_holdout, pareto_curve=pareto_curve,
               alpha=a.alpha, note="pipeline smoke on pilot; conclusions await full 5000x4")
    (R / f"ROUTER_RESULT_{a.frozen}.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(res, indent=1))
    print("behavior_shift:", json.dumps(behavior, indent=1))
    print(f"written ROUTER_RESULT_{a.frozen}.json")


if __name__ == "__main__":
    main()
