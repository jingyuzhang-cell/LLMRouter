"""Analyze routing-label noise and compare offline routing baselines."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, recall_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

BASE = Path("data/example_data/routing_data/grouped")
EMBEDDINGS = Path("data/example_data/routing_data/query_embeddings_longformer.pt")
OUTPUT = Path("run_logs/mlprouter_learnability.json")


def best_rows(frame):
    return frame.loc[frame.groupby("query")["performance"].idxmax()].reset_index(drop=True)


def query_frame(frame, embeddings):
    best = best_rows(frame)
    vectors = np.stack([embeddings[int(index)].numpy() for index in best["embedding_id"]])
    return best, vectors


def metrics(truth, predicted, labels):
    return {
        "accuracy": float(accuracy_score(truth, predicted)),
        "macro_f1": float(f1_score(truth, predicted, labels=labels, average="macro", zero_division=0)),
        "recall": {
            label: float(value)
            for label, value in zip(
                labels,
                recall_score(truth, predicted, labels=labels, average=None, zero_division=0),
            )
        },
    }


def main():
    frames = {
        split: pd.read_json(BASE / f"default_routing_{split}_data.jsonl", lines=True)
        for split in ("train", "validation", "test")
    }
    embeddings = torch.load(EMBEDDINGS, map_location="cpu", weights_only=False)
    train_best, train_x = query_frame(frames["train"], embeddings)
    test_best, test_x = query_frame(frames["test"], embeddings)
    labels = sorted(train_best["model_name"].unique())
    truth = test_best["model_name"].tolist()

    gaps = []
    ties = 0
    near_ties = {"0.00": 0, "0.01": 0, "0.05": 0, "0.10": 0}
    for _, group in pd.concat(frames.values()).groupby("query"):
        scores = np.sort(group["performance"].to_numpy())[::-1]
        gap = float(scores[0] - scores[1])
        gaps.append(gap)
        ties += int(gap == 0)
        for threshold in (0.00, 0.01, 0.05, 0.10):
            near_ties[f"{threshold:.2f}"] += int(gap <= threshold)

    train_majority = train_best["model_name"].mode().iloc[0]
    task_choice = train_best.groupby("task_name")["model_name"].agg(lambda x: x.mode().iloc[0])
    task_fallback = train_majority
    task_predictions = [task_choice.get(task, task_fallback) for task in test_best["task_name"]]

    logistic_embedding = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=500, class_weight="balanced", solver="lbfgs"),
    )
    logistic_embedding.fit(train_x, train_best["model_name"])

    tasks = sorted(train_best["task_name"].unique())
    task_to_idx = {task: index for index, task in enumerate(tasks)}
    def add_tasks(vectors, task_values):
        one_hot = np.zeros((len(vectors), len(tasks)), dtype=np.float32)
        for row, task in enumerate(task_values):
            if task in task_to_idx:
                one_hot[row, task_to_idx[task]] = 1.0
        return np.concatenate([vectors, one_hot], axis=1)

    train_structured = add_tasks(train_x, train_best["task_name"])
    test_structured = add_tasks(test_x, test_best["task_name"])
    logistic_structured = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=500, class_weight="balanced", solver="lbfgs"),
    )
    logistic_structured.fit(train_structured, train_best["model_name"])

    total = len(gaps)
    report = {
        "queries": total,
        "label_noise": {
            "gap_quantiles": {
                str(q): float(np.quantile(gaps, q)) for q in (0, 0.25, 0.5, 0.75, 0.9, 1.0)
            },
            "exact_tie_rate": ties / total,
            "near_tie_rates": {key: value / total for key, value in near_ties.items()},
        },
        "baselines": {
            "majority": metrics(truth, [train_majority] * len(truth), labels),
            "task_lookup": metrics(truth, task_predictions, labels),
            "logistic_embedding": metrics(truth, logistic_embedding.predict(test_x), labels),
            "logistic_embedding_task": metrics(
                truth, logistic_structured.predict(test_structured), labels
            ),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Report: {OUTPUT}")


if __name__ == "__main__":
    main()
