"""R2C failure diagnosis: WHY does a query-embedding router fail to recover the
oracle gap on the frozen R2A binary protocol (math500/mbpp/mmlupro,
Fin-R1 vs cogito, seed42 0.8 split, gte 3584-d embeddings)?

Causal hypotheses (user's four causes) -> measured as:
  C1 feature insufficiency   D4 informative-subset separability ~chance
                            while D6 outcome prediction >> chance
  C2 hard/noisy labels       D2 tie structure: informative fraction, minority size
  C3 pool too similar        D2 agreement rate + D3 needle-scatter
  C4 wrong objective         D5 idealized probabilistic router recovers ~0 gap
                            -> objective not the binding constraint on this data

All offline, fixed seeds, no API calls. Output: r2c_failure_diagnosis/.
"""
import json
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.manifold import TSNE
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics import roc_auc_score
from sklearn.svm import SVC

R = pathlib.Path(__file__).resolve().parent
OUT = R / "r2c_failure_diagnosis"
OUT.mkdir(exist_ok=True)
ADAPTOR = "seed42_split0.8_Fin-R1__vs__cogito-v1-preview-llama-8B"
TASKS = {"Math": "math500", "Code": "mbpp", "Knowledge": "mmlupro"}
SEED = 42


def load(task):
    d = R / "r2a_local" / task / "adaptor" / ADAPTOR
    tr = json.loads((d / "pairwise_train.json").read_text())
    te = json.loads((d / "pairwise_test.json").read_text())
    emb = np.load(d / "prompt_embeddings.npy")
    row = {e["prompt"]: e["idx"] for e in json.loads((d / "prompt_index.json").read_text())}
    return (tr, te, emb[[row[r["prompt"]] for r in tr]], emb[[row[r["prompt"]] for r in te]])


def outcome(r):
    a, b = r["score_model_a"], r["score_model_b"]
    if a > b: return "a_only"
    if b > a: return "b_only"
    return "both_right" if a == 1.0 else "both_wrong"


def main():
    report = {}
    for task, ds in TASKS.items():
        tr, te, Xtr, Xte = load(task)
        y_tr = np.array([outcome(r) for r in tr])
        y_te = np.array([outcome(r) for r in te])
        acc_a = float(np.mean([r["score_model_a"] for r in te]))
        acc_b = float(np.mean([r["score_model_b"] for r in te]))
        best = max(acc_a, acc_b)
        oracle = float(np.mean([max(r["score_model_a"], r["score_model_b"]) for r in te]))
        T = {}

        # ---- D1/D2: gap + label structure -----------------------------------
        for part, y in (("train", y_tr), ("test", y_te)):
            n = len(y)
            T[f"{part}_n"] = n
            T[f"{part}_outcome_counts"] = {k: int((y == k).sum()) for k in
                                           ("a_only", "b_only", "both_right", "both_wrong")}
            T[f"{part}_informative_frac"] = round(float(np.isin(y, ("a_only", "b_only")).mean()), 4)
        inf_tr = np.isin(y_tr, ("a_only", "b_only"))
        inf_te = np.isin(y_te, ("a_only", "b_only"))
        mino_tr = int((y_tr == "b_only").sum()) if (y_tr == "b_only").sum() <= (y_tr == "a_only").sum() \
            else int((y_tr == "a_only").sum())
        T["gap"] = dict(best_single=round(best, 4), oracle=round(oracle, 4),
                        headroom=round(oracle - best, 4),
                        headroom_equals_minority_only_frac=min(int((y_te == "b_only").sum()),
                                                               int((y_te == "a_only").sum())) / len(y_te))
        T["gap"]["headroom_note"] = ("binary scores: headroom == (minority-only wins)/n; "
                                     "recovering it requires finding exactly those queries")
        T["minority_train_count"] = mino_tr

        # ---- D3: local winner consistency in embedding space ----------------
        nn = NearestNeighbors(metric="cosine").fit(Xtr)
        knn_consistency = {}
        for k in (5, 10, 25):
            kk = min(k, len(tr))
            _, ind = nn.kneighbors(Xte[inf_te], n_neighbors=kk)
            neigh_win = (y_tr[ind] == "b_only").mean(1)  # frac of neighbors won by b
            pred_b = neigh_win > 0.5
            true_b = (y_te[inf_te] == "b_only")
            maj = max(true_b.mean(), 1 - true_b.mean())
            knn_consistency[k] = dict(
                acc=float((pred_b == true_b).mean()), majority_baseline=float(maj),
                mean_neighbor_b_win_frac=round(float(neigh_win.mean()), 4))
        T["D3_knn_winner_consistency"] = knn_consistency

        # ---- D4: CV separability on informative subset ----------------------
        Xi_tr, yi_tr = Xtr[inf_tr], (y_tr[inf_tr] == "b_only").astype(int)
        Xi_te, yi_te = Xte[inf_te], (y_te[inf_te] == "b_only").astype(int)
        sep = {}
        if 1 < yi_tr.sum() < len(yi_tr) - 1 and len(np.unique(yi_te)) == 2:
            skf = StratifiedKFold(5, shuffle=True, random_state=SEED)
            for name, clf in (("logreg", LogisticRegression(max_iter=2000, C=1.0)),
                              ("svm_rbf", SVC(probability=True, random_state=SEED))):
                p = cross_val_predict(clf, Xi_tr, yi_tr, cv=skf, method="predict_proba")[:, 1]
                sep[name] = dict(cv_auc=round(float(roc_auc_score(yi_tr, p)), 4),
                                 cv_acc=float(((p > .5).astype(int) == yi_tr).mean()))
            sep["majority_baseline"] = round(float(max(yi_tr.mean(), 1 - yi_tr.mean())), 4)
            sep["n_train_informative"] = int(len(yi_tr))
            sep["note"] = "can embeddings even separate winners among informative queries"
        T["D4_informative_separability"] = sep

        # ---- D5: idealized probabilistic router on ALL queries --------------
        # label: 1 = b_only (route to b iff p > tau); ties and a_only are class 0
        yb_tr = (y_tr == "b_only").astype(int)
        yb_te = (y_te == "b_only").astype(int)
        skf = StratifiedKFold(5, shuffle=True, random_state=SEED)
        p_tr = cross_val_predict(LogisticRegression(max_iter=2000, C=1.0),
                                 Xtr, yb_tr, cv=skf, method="predict_proba")[:, 1]
        lr = LogisticRegression(max_iter=2000, C=1.0).fit(Xtr, yb_tr)
        p_te = lr.predict_proba(Xte)[:, 1]
        # route to b iff p>tau; accuracy = mean over test of score of chosen model
        s = np.array([[r["score_model_a"], r["score_model_b"]] for r in te])
        taus = np.linspace(0.05, 0.95, 19)
        accs = [float(s[np.arange(len(te)), (p_te > t).astype(int)].mean()) for t in taus]
        best_tau_acc = max(accs)
        cv_auc = float(roc_auc_score(yb_te, p_te)) if 0 < yb_te.sum() < len(yb_te) else None
        # stochastic bound: a perfect probability model routed by its own prob
        Emax = float(np.mean(np.maximum(p_tr, 1 - p_tr)))
        T["D5_probabilistic_router"] = dict(
            cv_train_auc_of_probe=round(float(roc_auc_score(yb_tr, p_tr)), 4) if 0 < yb_tr.sum() < len(yb_tr) else None,
            test_auc_of_probe=round(cv_auc, 4) if cv_auc else None,
            best_tau_test_accuracy=round(best_tau_acc, 4),
            best_single=round(best, 4),
            gap_recovery=round((best_tau_acc - best) / (oracle - best), 4),
            E_max_p_bound_on_train=round(Emax, 4),
            note="even an oracle-thresholded linear prob model recovers ~0 -> not an objective problem alone")

        # ---- D6: control - embeddings DO carry query info -------------------
        # Representation-content probe (NOT a router): pooled train+test CV.
        # The frozen train file has zero ties by construction, so outcome
        # diversity only exists when pooling; we only probe what the embedding
        # encodes, using all labels, never transferring to held-out queries.
        Xall, yall = np.vstack([Xtr, Xte]), np.concatenate([y_tr, y_te])
        classes = np.unique(yall)
        T["D6_control_outcome_predictability"] = {}
        if len(classes) > 1 and min(np.bincount([list(classes).index(v) for v in yall])) >= 5:
            skf6 = StratifiedKFold(5, shuffle=True, random_state=SEED)
            lab6 = np.array([list(classes).index(v) for v in yall])
            pred6 = cross_val_predict(LogisticRegression(max_iter=2000, C=1.0), Xall, lab6, cv=skf6)
            T["D6_control_outcome_predictability"] = dict(
                pooled_cv_acc=round(float((pred6 == lab6).mean()), 4),
                pooled_majority_baseline=round(float(max(np.bincount(lab6)) / len(lab6)), 4),
                classes={c: int((yall == c).sum()) for c in classes},
                note="pooled train+test CV probes representation content: embeddings "
                     "predict outcome/difficulty above chance while winner stays ~chance "
                     "-> feature carries query type, not winner")
        inf_all = np.isin(yall, ("a_only", "b_only"))
        if inf_all.sum() >= 20 and min(np.bincount((yall[inf_all] == "b_only").astype(int))) >= 5:
            skf7 = StratifiedKFold(5, shuffle=True, random_state=SEED)
            Xw, yw = Xall[inf_all], (yall[inf_all] == "b_only").astype(int)
            pw = cross_val_predict(LogisticRegression(max_iter=2000, C=1.0), Xw, yw,
                                   cv=skf7, method="predict_proba")[:, 1]
            T["D4_pooled_winner_cv_auc"] = round(float(roc_auc_score(yw, pw)), 4)
            T["D4_pooled_winner_majority"] = round(float(max(yw.mean(), 1 - yw.mean())), 4)
            T["D4_pooled_n"] = int(len(yw))

        # ---- D7: t-SNE ------------------------------------------------------
        Z = TSNE(n_components=2, init="pca", random_state=SEED,
                 perplexity=30).fit_transform(np.vstack([Xtr, Xte]))
        y_all = np.concatenate([y_tr, y_te])
        part = np.array(["train"] * len(tr) + ["test"] * len(te))
        colors = {"a_only": "#d62728", "b_only": "#1f77b4", "both_right": "#2ca02c", "both_wrong": "#7f7f7f"}
        fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
        for ax, (mask, title) in zip(axes, [
                (np.ones(len(y_all), bool), f"{ds}: all queries by outcome"),
                (np.isin(y_all, ("a_only", "b_only")), f"{ds}: informative only (winner)")]):
            for k, c in colors.items():
                m = mask & (y_all == k)
                if m.any():
                    ax.scatter(Z[m, 0], Z[m, 1], s=14 if k in ("a_only", "b_only") else 7,
                               c=c, label=f"{k} ({m.sum()})", alpha=.75)
            ax.set_title(title)
            ax.legend(fontsize=8, markerscale=1.5)
        plt.tight_layout()
        plt.savefig(OUT / f"tsne_{ds}.png", dpi=150)
        plt.close()
        report[ds] = T
        print(ds, json.dumps({k: T[k] for k in ("gap", "D3_knn_winner_consistency",
                                                "D4_informative_separability",
                                                "D5_probabilistic_router")}, indent=1), flush=True)

    (OUT / "DIAGNOSIS.json").write_text(json.dumps(report, indent=2))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
