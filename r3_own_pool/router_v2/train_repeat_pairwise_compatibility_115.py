"""Nested pairwise compatibility on five-repeat empirical utility labels."""
import hashlib
import itertools
import json
import re
from pathlib import Path

import numpy as np
import torch
from sklearn.linear_model import Ridge
from torch import nn

from .data import read_rows, sha
from .mmlu_learnability import group_ci


ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = ROOT / "router_v2/repeat_compatibility_115"
DATA = ROOT / "data/repeat_compatibility_115"
EMBEDDINGS = ROOT / "data/embeddings_full_v2_recovery1/EMBEDDINGS.npz"
OUT = ROOT / "router_v2/experiment_repeat_pairwise_compatibility_115"
SLOTS = ["medium", "large", "coder", "reasoning"]
SEEDS = [42, 43, 44]
PAIRS = list(itertools.combinations(range(4), 2))


def subject(text):
    match = re.match(r"Answer the following (.+?) question\.", text)
    return match.group(1).casefold() if match else "unknown"


def inner_split(indices, subjects, outer_fold):
    train, validation = [], []
    for name in sorted(set(subjects[indices])):
        values = indices[subjects[indices] == name]
        ordered = sorted(values.tolist(), key=lambda i: hashlib.sha256(
            f"repeat-pairwise-v1:{outer_fold}:{i}".encode()).hexdigest())
        count = max(1, round(0.2 * len(ordered)))
        validation.extend(ordered[:count])
        train.extend(ordered[count:])
    return np.array(sorted(train)), np.array(sorted(validation))


def examples(y, indices):
    queries, left, right, target = [], [], [], []
    for i, j in PAIRS:
        for q in indices:
            queries.append(q)
            left.append(i)
            right.append(j)
            # Random independent draws with ties split equally.
            target.append(0.5 + 0.5 * float(y[q, i] - y[q, j]))
    return tuple(np.asarray(v) for v in (queries, left, right, target))


class PairwiseMA(nn.Module):
    def __init__(self, query_dim):
        super().__init__()
        self.model_embedding = nn.Embedding(4, 8)
        self.score = nn.Sequential(nn.Linear(query_dim + 8, 64), nn.ReLU(), nn.Linear(64, 1))

    def utilities(self, query):
        q = query[:, None, :].expand(-1, 4, -1)
        m = self.model_embedding.weight[None, :, :].expand(len(query), -1, -1)
        return self.score(torch.cat([q, m], -1)).squeeze(-1)

    def compare(self, query, left, right):
        score = self.utilities(query)
        rows = torch.arange(len(query))
        return score[rows, left] - score[rows, right]


def epoch(model, optimizer, x, data, rng):
    queries, left, right, target = data
    tx = torch.tensor(x, dtype=torch.float32)
    tl = torch.tensor(left, dtype=torch.long)
    tr = torch.tensor(right, dtype=torch.long)
    tt = torch.tensor(target, dtype=torch.float32)
    model.train()
    for batch in np.array_split(rng.permutation(len(queries)), int(np.ceil(len(queries) / 64))):
        logits = model.compare(tx[queries[batch]], tl[batch], tr[batch])
        loss = nn.functional.binary_cross_entropy_with_logits(logits, tt[batch])
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()


def loss(model, x, data):
    queries, left, right, target = data
    model.eval()
    with torch.no_grad():
        logits = model.compare(torch.tensor(x[queries], dtype=torch.float32),
                               torch.tensor(left, dtype=torch.long),
                               torch.tensor(right, dtype=torch.long))
        return float(nn.functional.binary_cross_entropy_with_logits(
            logits, torch.tensor(target, dtype=torch.float32)))


def fit(x, y, train, validation, development, test, seed):
    torch.manual_seed(seed)
    probe = PairwiseMA(x.shape[1])
    optimizer = torch.optim.AdamW(probe.parameters(), lr=0.001, weight_decay=0.01)
    train_data, validation_data = examples(y, train), examples(y, validation)
    rng = np.random.default_rng(seed)
    best_epoch, best_loss = 1, float("inf")
    for number in range(1, 101):
        epoch(probe, optimizer, x, train_data, rng)
        current = loss(probe, x, validation_data)
        if current < best_loss:
            best_epoch, best_loss = number, current
    torch.manual_seed(seed)
    final = PairwiseMA(x.shape[1])
    optimizer = torch.optim.AdamW(final.parameters(), lr=0.001, weight_decay=0.01)
    full = examples(y, development)
    rng = np.random.default_rng(seed)
    for _ in range(best_epoch):
        epoch(final, optimizer, x, full, rng)
    final.eval()
    with torch.no_grad():
        scores = final.utilities(torch.tensor(x[test], dtype=torch.float32)).numpy()
    return scores, final.state_dict(), {"best_epoch": best_epoch, "validation_loss": best_loss,
                                         "train_queries": len(train), "validation_queries": len(validation)}


def pairwise_ridge(x, y, train, test):
    scores = np.zeros((len(test), 4), dtype="float32")
    for i, j in PAIRS:
        target = y[train, i] - y[train, j]
        prediction = np.clip(Ridge(alpha=1.0).fit(x[train], target).predict(x[test]), -1, 1)
        scores[:, i] += prediction
        scores[:, j] -= prediction
    return scores


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
        methods[name] = {"expected_quality": float(actual.mean()), "gain": float(gain.mean()),
                         "gain_ci95": ci, "gap_recovery": float(gain.mean() / gap),
                         "gap_recovery_ci95": [float(v / gap) for v in ci],
                         "selection_counts": dict(zip(SLOTS, np.bincount(choice, minlength=4).tolist()))}
    seed_actual = np.array([y[row, choices[f"RepeatPairwiseMA_seed{s}"]] for s in SEEDS])
    gain = seed_actual.mean(0) - baseline
    ci = group_ci(gain, groups)
    methods["RepeatPairwiseMA_seed_mean"] = {
        "expected_quality": float(seed_actual.mean()), "gain": float(gain.mean()),
        "gain_ci95": ci, "gap_recovery": float(gain.mean() / gap),
        "gap_recovery_ci95": [float(v / gap) for v in ci]}
    return {"n": len(y), "oracle_expected_quality": float(oracle.mean()),
            "datasetbest_expected_quality": float(baseline.mean()), "oracle_gap": gap, "methods": methods}


def main():
    torch.set_num_threads(4)
    if OUT.exists():
        raise FileExistsError(OUT)
    status = json.loads((DATA / "STATUS.json").read_text())
    labels_path = DATA / "EXPECTED_UTILITY_LABELS.jsonl"
    if status.get("phase") != "REPEAT_LABELS_COMPLETE" or sha(labels_path) != status["labels_sha256"]:
        raise ValueError("Repeat labels incomplete or changed")
    protocol = json.loads((PANEL_DIR / "PROTOCOL.json").read_text())
    if sha(PANEL_DIR / "PANEL.jsonl") != protocol["panel_sha256"]:
        raise ValueError("Panel changed")
    panel_rows = read_rows(PANEL_DIR / "PANEL.jsonl")
    labels = {r["query_id"]: r for r in read_rows(labels_path)}
    ids = np.array([r["query_id"] for r in panel_rows])
    folds = np.array([r["fold"] for r in panel_rows])
    groups = np.array([r["prompt_group"] for r in panel_rows])
    subjects = np.array([subject(r["query"]) for r in panel_rows])
    y = np.array([[labels[q]["models"][slot]["mean"] for slot in SLOTS] for q in ids], dtype="float32")
    with np.load(EMBEDDINGS, allow_pickle=False) as saved:
        index = {qid: i for i, qid in enumerate(saved["ids"].tolist())}
        x = saved["vectors"][[index[q] for q in ids]].astype("float32")
    names = ["BestSingle", "DatasetBest", "QueryOnlyRidge", "PairwiseRidge"] + [f"RepeatPairwiseMA_seed{s}" for s in SEEDS]
    choices = {name: np.empty(len(ids), dtype=int) for name in names}
    scores = {name: np.empty_like(y) for name in names[2:]}
    trace = []
    OUT.mkdir(parents=True)
    for fold in sorted(set(folds)):
        development = np.flatnonzero(folds != fold)
        test = np.flatnonzero(folds == fold)
        train, validation = inner_split(development, subjects, int(fold))
        if set(groups[development]) & set(groups[test]) or set(groups[train]) & set(groups[validation]):
            raise ValueError("Group leakage")
        best = int(y[development].mean(0).argmax())
        choices["BestSingle"][test] = choices["DatasetBest"][test] = best
        prediction = Ridge(alpha=1.0).fit(x[development], y[development]).predict(x[test])
        scores["QueryOnlyRidge"][test] = prediction
        choices["QueryOnlyRidge"][test] = prediction.argmax(1)
        prediction = pairwise_ridge(x, y, development, test)
        scores["PairwiseRidge"][test] = prediction
        choices["PairwiseRidge"][test] = prediction.argmax(1)
        detail = {}
        for seed in SEEDS:
            name = f"RepeatPairwiseMA_seed{seed}"
            prediction, state, fit_detail = fit(x, y, train, validation, development, test, seed)
            scores[name][test] = prediction
            choices[name][test] = prediction.argmax(1)
            torch.save(state, OUT / f"model_fold{fold}_seed{seed}.pt")
            detail[str(seed)] = fit_detail
        trace.append({"fold": int(fold), "development_ids": ids[development].tolist(),
                      "inner_train_ids": ids[train].tolist(), "inner_validation_ids": ids[validation].tolist(),
                      "test_ids": ids[test].tolist(), "fit": detail})
        print(f"finished fold {fold}", flush=True)
    report = summarize(y, choices, groups)
    metadata = {"role": "outcome-enriched repeat-label nested development experiment",
                "pair_target": "P(i preferred to j)=0.5+(mean_i-mean_j)/2; ties split equally",
                "architecture": "shared s(e_q,e_m), antisymmetric logit difference, soft-label BCE",
                "inner_validation": "label-free subject-stratified 20%, epoch 1..100",
                "refit": "all outer development queries for selected epoch",
                "seeds": SEEDS, "ridge_alpha": 1.0,
                "source_sha256": {"labels": sha(labels_path), "panel": sha(PANEL_DIR / "PANEL.jsonl"),
                                  "embeddings": sha(EMBEDDINGS), "trainer": sha(Path(__file__))},
                "limits": ["115 queries selected using observed disagreement and prior-panel overlap; not representative evaluation.",
                           "Five stochastic repeats reduce label noise but do not add query diversity.",
                           "A new frozen panel is required for confirmation after method selection."]}
    (OUT / "PROTOCOL.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (OUT / "RESULTS.json").write_text(json.dumps(report, indent=2) + "\n")
    (OUT / "FOLDS.json").write_text(json.dumps(trace, indent=2) + "\n")
    np.savez_compressed(OUT / "PREDICTIONS.npz", ids=ids, folds=folds, quality=y,
                        **{f"choice_{k}": v for k, v in choices.items()}, **{f"score_{k}": v for k, v in scores.items()})
    lines = ["# 五次重复标签 Pairwise Compatibility", "",
             f"Oracle={report['oracle_expected_quality']:.2%}；DatasetBest={report['datasetbest_expected_quality']:.2%}；Gap={report['oracle_gap']:.2%}。", "",
             "| 方法 | Expected quality | Gap Recovery | 95%区间 |", "|---|---:|---:|---|"]
    for name, value in report["methods"].items():
        lines.append(f"| {name} | {value['expected_quality']:.2%} | {value['gap_recovery']:.2%} | {value['gap_recovery_ci95']} |")
    lines.extend(["", "这是按单次分歧富集的115题训练诊断，不是代表性测试或论文主结果。"])
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
