"""Nested development evaluation of four-model pairwise compatibility routing."""
import hashlib
import itertools
import json
import re
from pathlib import Path

import numpy as np
import torch
from sklearn.linear_model import Ridge
from torch import nn

from .data import sha
from .mmlu_learnability import group_ci


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "router_v2/knowledge_validation_400_results"
PANEL_DIR = ROOT / "router_v2/knowledge_validation_400"
EMBEDDINGS = ROOT / "data/embeddings_full_v2_recovery1/EMBEDDINGS.npz"
OUT = ROOT / "router_v2/experiment_pairwise_compatibility_400"
SLOTS = ["medium", "large", "coder", "reasoning"]
SEEDS = [42, 43, 44]
PAIRS = list(itertools.combinations(range(len(SLOTS)), 2))


def subject(text):
    match = re.match(r"Answer the following (.+?) question\.", text)
    return match.group(1).casefold() if match else "unknown"


def inner_split(indices, subjects, outer_fold):
    """Label-free deterministic 80/20 split within each MMLU-Pro subject."""
    train, validation = [], []
    for name in sorted(set(subjects[indices])):
        at = indices[subjects[indices] == name]
        ordered = sorted(at.tolist(), key=lambda i: hashlib.sha256(
            f"pairwise-v1:{outer_fold}:{i}".encode()).hexdigest())
        count = max(1, round(0.2 * len(ordered)))
        validation.extend(ordered[:count])
        train.extend(ordered[count:])
    train = np.array(sorted(train), dtype=int)
    validation = np.array(sorted(validation), dtype=int)
    if not len(train) or not len(validation) or set(train) & set(validation):
        raise ValueError("Invalid inner split")
    return train, validation


def pair_examples(y, indices):
    query_indices, left, right, labels, pair_ids = [], [], [], [], []
    for pair_id, (i, j) in enumerate(PAIRS):
        for q in indices:
            delta = y[q, i] - y[q, j]
            if delta == 0:
                continue
            query_indices.append(q)
            left.append(i)
            right.append(j)
            labels.append(float(delta > 0))
            pair_ids.append(pair_id)
    return tuple(np.asarray(v) for v in (query_indices, left, right, labels, pair_ids))


def balanced_weights(labels, pair_ids, reference_labels=None, reference_pairs=None):
    """Balance win/loss classes within each unordered model pair."""
    ref_y = labels if reference_labels is None else reference_labels
    ref_p = pair_ids if reference_pairs is None else reference_pairs
    result = np.ones(len(labels), dtype="float32")
    for pair_id in range(len(PAIRS)):
        ref = ref_y[ref_p == pair_id]
        for value in (0.0, 1.0):
            count = int((ref == value).sum())
            if count:
                result[(pair_ids == pair_id) & (labels == value)] = len(ref) / (2 * count)
    return result


class PairwiseMA(nn.Module):
    """Antisymmetric comparison from shared query-model compatibility scores."""

    def __init__(self, query_dim, model_dim=8):
        super().__init__()
        self.model_embedding = nn.Embedding(len(SLOTS), model_dim)
        self.score = nn.Sequential(
            nn.Linear(query_dim + model_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )

    def utilities(self, query):
        q = query[:, None, :].expand(-1, len(SLOTS), -1)
        m = self.model_embedding.weight[None, :, :].expand(len(query), -1, -1)
        return self.score(torch.cat([q, m], dim=-1)).squeeze(-1)

    def compare(self, query, left, right):
        scores = self.utilities(query)
        rows = torch.arange(len(query))
        return scores[rows, left] - scores[rows, right]


def run_epochs(model, x, examples, weights, epochs, seed):
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.01)
    q, left, right, labels, _ = examples
    tx = torch.tensor(x, dtype=torch.float32)
    tl = torch.tensor(left, dtype=torch.long)
    tr = torch.tensor(right, dtype=torch.long)
    ty = torch.tensor(labels, dtype=torch.float32)
    tw = torch.tensor(weights, dtype=torch.float32)
    rng = np.random.default_rng(seed)
    model.train()
    for _ in range(epochs):
        for batch in np.array_split(rng.permutation(len(q)), int(np.ceil(len(q) / 64))):
            logits = model.compare(tx[q[batch]], tl[batch], tr[batch])
            losses = nn.functional.binary_cross_entropy_with_logits(logits, ty[batch], reduction="none")
            loss = (losses * tw[batch]).sum() / tw[batch].sum()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()


def validation_loss(model, x, examples, weights):
    q, left, right, labels, _ = examples
    with torch.no_grad():
        logits = model.compare(torch.tensor(x[q], dtype=torch.float32),
                               torch.tensor(left, dtype=torch.long),
                               torch.tensor(right, dtype=torch.long))
        losses = nn.functional.binary_cross_entropy_with_logits(
            logits, torch.tensor(labels, dtype=torch.float32), reduction="none").numpy()
    return float(np.average(losses, weights=weights))


def fit_pairwise_ma(x, y, inner_train, inner_validation, development, evaluation, seed):
    train_examples = pair_examples(y, inner_train)
    validation_examples = pair_examples(y, inner_validation)
    if not len(train_examples[0]) or not len(validation_examples[0]):
        raise ValueError("No discordant inner pair examples")
    train_weights = balanced_weights(train_examples[3], train_examples[4])
    validation_weights = balanced_weights(validation_examples[3], validation_examples[4],
                                          train_examples[3], train_examples[4])
    torch.manual_seed(seed)
    probe = PairwiseMA(x.shape[1])
    optimizer = torch.optim.AdamW(probe.parameters(), lr=0.001, weight_decay=0.01)
    q, left, right, labels, _ = train_examples
    tx = torch.tensor(x, dtype=torch.float32)
    tl = torch.tensor(left, dtype=torch.long)
    tr = torch.tensor(right, dtype=torch.long)
    ty = torch.tensor(labels, dtype=torch.float32)
    tw = torch.tensor(train_weights, dtype=torch.float32)
    rng = np.random.default_rng(seed)
    best_epoch, best_loss = 1, float("inf")
    for epoch in range(1, 101):
        probe.train()
        for batch in np.array_split(rng.permutation(len(q)), int(np.ceil(len(q) / 64))):
            logits = probe.compare(tx[q[batch]], tl[batch], tr[batch])
            losses = nn.functional.binary_cross_entropy_with_logits(logits, ty[batch], reduction="none")
            loss = (losses * tw[batch]).sum() / tw[batch].sum()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        probe.eval()
        loss = validation_loss(probe, x, validation_examples, validation_weights)
        if loss < best_loss:
            best_loss, best_epoch = loss, epoch
    full_examples = pair_examples(y, development)
    full_weights = balanced_weights(full_examples[3], full_examples[4])
    torch.manual_seed(seed)
    final = PairwiseMA(x.shape[1])
    run_epochs(final, x, full_examples, full_weights, best_epoch, seed)
    final.eval()
    with torch.no_grad():
        scores = final.utilities(torch.tensor(x[evaluation], dtype=torch.float32)).numpy()
        reverse_check = final.compare(
            torch.tensor(x[evaluation], dtype=torch.float32),
            torch.full((len(evaluation),), 1, dtype=torch.long),
            torch.full((len(evaluation),), 3, dtype=torch.long),
        ).numpy()
    if not np.allclose(reverse_check, scores[:, 1] - scores[:, 3], atol=1e-6):
        raise AssertionError("Pairwise antisymmetry/index check failed")
    return scores, final.state_dict(), {"best_epoch": best_epoch, "validation_loss": best_loss,
                                        "inner_train_pairs": len(train_examples[0]),
                                        "inner_validation_pairs": len(validation_examples[0]),
                                        "full_development_pairs": len(full_examples[0])}


def pairwise_ridge(x, y, development, evaluation):
    aggregate = np.zeros((len(evaluation), len(SLOTS)), dtype="float32")
    trace = {}
    for pair_id, (i, j) in enumerate(PAIRS):
        delta = y[development, i] - y[development, j]
        keep = delta != 0
        labels = (delta[keep] > 0).astype(float)
        pair_ids = np.full(len(labels), pair_id)
        weights = balanced_weights(labels, pair_ids)
        model = Ridge(alpha=1.0).fit(x[development][keep], delta[keep], sample_weight=weights)
        prediction = np.clip(model.predict(x[evaluation]), -1, 1)
        aggregate[:, i] += prediction
        aggregate[:, j] -= prediction
        trace[f"{SLOTS[i]} / {SLOTS[j]}"] = {"train_discordant": int(keep.sum()),
                                                "left_wins": int((delta[keep] > 0).sum()),
                                                "right_wins": int((delta[keep] < 0).sum())}
    return aggregate, trace


def summarize(y, choices, groups):
    row = np.arange(len(y))
    baseline = y[row, choices["DatasetBest"]]
    oracle = y.max(1)
    gap = float((oracle - baseline).mean())
    methods = {}
    for name, choice in choices.items():
        actual = y[row, choice]
        gain = actual - baseline
        ci = group_ci(gain, groups)
        methods[name] = {"accuracy": float(actual.mean()), "gain_vs_datasetbest": float(gain.mean()),
                         "gain_ci95": ci, "gap_recovery": float(gain.mean() / gap),
                         "gap_recovery_ci95": [float(v / gap) for v in ci],
                         "rescued": int((gain > 0).sum()), "harmed": int((gain < 0).sum()),
                         "selection_counts": dict(zip(SLOTS, np.bincount(choice, minlength=4).tolist()))}
    seed_actual = np.array([y[row, choices[f"PairwiseMA_seed{s}"]] for s in SEEDS])
    mean_actual = seed_actual.mean(0)
    gain = mean_actual - baseline
    ci = group_ci(gain, groups)
    methods["PairwiseMA_seed_mean"] = {
        "accuracy": float(mean_actual.mean()), "gain_vs_datasetbest": float(gain.mean()),
        "gain_ci95": ci, "gap_recovery": float(gain.mean() / gap),
        "gap_recovery_ci95": [float(v / gap) for v in ci],
        "note": "Three fixed routers averaged; seed-query observations are not treated as independent."}
    return {"n": len(y), "oracle_accuracy": float(oracle.mean()),
            "datasetbest_accuracy": float(baseline.mean()), "oracle_gap": gap, "methods": methods}


def main():
    torch.set_num_threads(4)
    if OUT.exists():
        raise FileExistsError(OUT)
    prior = json.loads((SOURCE / "RESULTS.json").read_text())
    if not prior["gate"]["pass"]:
        raise ValueError("Routability gate did not pass")
    if sha(PANEL_DIR / "PANEL.jsonl") != prior["sources"]["panel"]:
        raise ValueError("Panel changed")
    with np.load(SOURCE / "DIAGNOSTIC.npz", allow_pickle=False) as saved:
        ids, folds, y = saved["ids"], saved["folds"].astype(int), saved["quality"].astype("float32")
    panel = {row["query_id"]: row for row in map(json.loads, (PANEL_DIR / "PANEL.jsonl").read_text().splitlines())}
    groups = np.array([panel[q]["prompt_group"] for q in ids])
    subjects = np.array([subject(panel[q]["query"]) for q in ids])
    with np.load(EMBEDDINGS, allow_pickle=False) as saved:
        index = {qid: i for i, qid in enumerate(saved["ids"].tolist())}
        x = saved["vectors"][[index[q] for q in ids]].astype("float32")
    if y.shape != (400, 4) or not np.isin(y, [0, 1]).all() or not np.isfinite(x).all():
        raise ValueError("Invalid input")
    names = ["BestSingle", "DatasetBest", "QueryOnlyRidge", "PairwiseRidge"] + [f"PairwiseMA_seed{s}" for s in SEEDS]
    choices = {name: np.empty(400, dtype=int) for name in names}
    scores = {name: np.empty_like(y) for name in names[2:]}
    folds_trace = []
    OUT.mkdir(parents=True)
    for fold in sorted(set(folds)):
        development = np.flatnonzero(folds != fold)
        test = np.flatnonzero(folds == fold)
        if set(groups[development]) & set(groups[test]):
            raise ValueError("Outer prompt-group leakage")
        inner_train, inner_validation = inner_split(development, subjects, int(fold))
        if set(groups[inner_train]) & set(groups[inner_validation]):
            raise ValueError("Inner prompt-group leakage")
        best = int(y[development].mean(0).argmax())
        choices["BestSingle"][test] = best
        choices["DatasetBest"][test] = best
        query_ridge = Ridge(alpha=1.0).fit(x[development], y[development]).predict(x[test])
        scores["QueryOnlyRidge"][test] = query_ridge
        choices["QueryOnlyRidge"][test] = query_ridge.argmax(1)
        pair_scores, ridge_trace = pairwise_ridge(x, y, development, test)
        scores["PairwiseRidge"][test] = pair_scores
        choices["PairwiseRidge"][test] = pair_scores.argmax(1)
        ma_trace = {}
        for seed in SEEDS:
            name = f"PairwiseMA_seed{seed}"
            prediction, state, detail = fit_pairwise_ma(
                x, y, inner_train, inner_validation, development, test, seed)
            scores[name][test] = prediction
            choices[name][test] = prediction.argmax(1)
            torch.save(state, OUT / f"model_fold{fold}_seed{seed}.pt")
            ma_trace[str(seed)] = detail
        folds_trace.append({"fold": int(fold), "development_ids": ids[development].tolist(),
                            "inner_train_ids": ids[inner_train].tolist(),
                            "inner_validation_ids": ids[inner_validation].tolist(),
                            "test_ids": ids[test].tolist(), "pairwise_ridge": ridge_trace,
                            "pairwise_ma": ma_trace})
        print(f"finished outer fold {fold}", flush=True)
    if not np.array_equal(choices["BestSingle"], choices["DatasetBest"]):
        raise AssertionError("Single-dataset baselines differ")
    report = summarize(y, choices, groups)
    protocol = {
        "role": "development-only nested pairwise compatibility experiment",
        "models": SLOTS,
        "target": "strict pair winner; tied model pairs excluded from pairwise loss, retained in routed accuracy evaluation",
        "pair_balance": "inverse win/loss frequency within each unordered pair, learned from the relevant training partition",
        "pairwise_ma": "shared s(e_q,e_m); logit(i>j)=s(q,i)-s(q,j), exactly antisymmetric",
        "router": "argmax model compatibility score",
        "inner_validation": "deterministic label-free subject-stratified 20%; choose epoch 1..100 by balanced pair BCE",
        "refit": "reinitialize and train on all outer development queries for selected epoch",
        "pairwise_ridge": "six independent alpha=1 delta regressions with pair-balanced weights; signed Borda aggregation",
        "query_ridge": "four-output alpha=1 utility regression",
        "seeds": SEEDS,
        "baselines": ["BestSingle", "DatasetBest", "QueryOnlyRidge", "PairwiseRidge", "PairwiseMA"],
        "source_sha256": {"diagnostic_results": sha(SOURCE / "RESULTS.json"),
                           "diagnostic_npz": sha(SOURCE / "DIAGNOSTIC.npz"),
                           "panel": sha(PANEL_DIR / "PANEL.jsonl"),
                           "embeddings": sha(EMBEDDINGS), "trainer": sha(Path(__file__))},
        "limits": ["This 400-query dataset was already inspected before this method was proposed; outer folds are development estimates, not untouched tests.",
                   "Single binary outcomes do not estimate expected utility or repeat stability.",
                   "Any subsequent method choice based on this result requires a new frozen confirmation panel."],
    }
    (OUT / "PROTOCOL.json").write_text(json.dumps(protocol, indent=2) + "\n")
    (OUT / "RESULTS.json").write_text(json.dumps(report, indent=2) + "\n")
    (OUT / "FOLDS.json").write_text(json.dumps(folds_trace, indent=2) + "\n")
    np.savez_compressed(OUT / "PREDICTIONS.npz", ids=ids, folds=folds, quality=y,
                        **{f"choice_{name}": value for name, value in choices.items()},
                        **{f"score_{name}": value for name, value in scores.items()})
    lines = ["# Pairwise Compatibility MA-v2", "",
             f"Oracle={report['oracle_accuracy']:.2%}；DatasetBest={report['datasetbest_accuracy']:.2%}；Gap={report['oracle_gap']:.2%}。", "",
             "| 方法 | Accuracy | 相对DatasetBest | Gap Recovery | Recovery CI95 |",
             "|---|---:|---:|---:|---|"]
    for name, value in report["methods"].items():
        lines.append(f"| {name} | {value['accuracy']:.2%} | {value['gain_vs_datasetbest']*100:+.2f} pp | "
                     f"{value['gap_recovery']:.2%} | {value['gap_recovery_ci95']} |")
    lines.extend(["", "Pairwise MA只训练非平局模型对；所有题和全部平局仍进入最终路由准确率。",
                  "内层验证只选训练轮数，外折不参与选择。但方法是在看过这400题的绝对MA结果后提出，因此本结果仍是开发估计。"])
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
