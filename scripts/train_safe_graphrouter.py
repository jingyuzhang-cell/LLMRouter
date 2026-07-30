#!/usr/bin/env python3
"""Train and evaluate an accuracy-first safety gate for GraphRouter.

The gate defaults to the strongest candidate model. It routes to a smaller
model only when a rescue classifier predicts that the strong model will fail
and the smaller model will succeed. The confidence threshold is selected on a
validation split; test data is evaluated only after the policy is frozen.
"""

import argparse
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_routing(path):
    frame = pd.read_json(path, lines=True)
    required = {"query", "embedding_id", "model_name", "correct", "performance"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")
    return frame


def parse_size(value):
    text = str(value)
    number = "".join(char for char in text if char.isdigit() or char == ".")
    if not number:
        raise ValueError(f"Cannot parse model size from {value!r}")
    return float(number)


def build_matrices(frame, embeddings, model_names):
    queries = frame["query"].drop_duplicates().tolist()
    model_to_idx = {name: idx for idx, name in enumerate(model_names)}
    features = []
    correct = np.zeros((len(queries), len(model_names)), dtype=np.float32)
    performance = np.zeros_like(correct)
    latency = np.zeros_like(correct)

    for query_idx, query in enumerate(queries):
        rows = frame[frame["query"] == query]
        embedding_id = int(rows["embedding_id"].iloc[0])
        vector = embeddings[embedding_id]
        if isinstance(vector, torch.Tensor):
            vector = vector.cpu().numpy()
        features.append(np.asarray(vector, dtype=np.float32))

        for _, row in rows.iterrows():
            model_idx = model_to_idx[row["model_name"]]
            correct[query_idx, model_idx] = float(row["correct"])
            performance[query_idx, model_idx] = float(row["performance"])
            latency[query_idx, model_idx] = float(row.get("response_time", 0) or 0)

    return queries, np.asarray(features), correct, performance, latency


def fit_rescue_models(features, correct, strong_idx, small_indices, seed):
    models = []
    strong_wrong = correct[:, strong_idx] == 0
    for small_idx in small_indices:
        rescue = ((correct[:, small_idx] == 1) & strong_wrong).astype(int)
        pipeline = Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        C=0.1,
                        class_weight="balanced",
                        max_iter=2000,
                        random_state=seed,
                    ),
                ),
            ]
        )
        pipeline.fit(features, rescue)
        models.append(pipeline)
    return models


def rescue_probabilities(models, features):
    return np.column_stack(
        [model.predict_proba(features)[:, 1] for model in models]
    )


def select_models(probabilities, threshold, strong_idx, small_indices):
    predictions = np.full(len(probabilities), strong_idx, dtype=int)
    best_small_position = probabilities.argmax(axis=1)
    best_probability = probabilities.max(axis=1)
    downgrade = best_probability >= threshold
    small_array = np.asarray(small_indices)
    predictions[downgrade] = small_array[best_small_position[downgrade]]
    return predictions


def policy_metrics(predictions, correct, performance, latency, sizes):
    rows = np.arange(len(predictions))
    return {
        "answer_accuracy": float(correct[rows, predictions].mean()),
        "performance_score": float(performance[rows, predictions].mean()),
        "avg_size_b": float(sizes[predictions].mean()),
        "avg_latency_s": float(latency[rows, predictions].mean()),
        "downgrade_count": int((predictions != sizes.argmax()).sum()),
    }


def choose_threshold(probabilities, correct, performance, latency, sizes,
                     strong_idx, small_indices):
    candidates = np.concatenate(
        [np.linspace(0.0, 1.0, 201), np.array([1.000001])]
    )
    records = []
    for threshold in candidates:
        predictions = select_models(
            probabilities, threshold, strong_idx, small_indices
        )
        metrics = policy_metrics(
            predictions, correct, performance, latency, sizes
        )
        metrics["threshold"] = float(threshold)
        records.append(metrics)

    # Accuracy is primary. On ties, prefer fewer risky downgrades, then the
    # higher cost-aware performance score.
    best = max(
        records,
        key=lambda item: (
            item["answer_accuracy"],
            -item["downgrade_count"],
            item["performance_score"],
        ),
    )
    return best, records


def rescue_metrics(probabilities, threshold, correct, strong_idx, small_indices):
    actual = np.column_stack(
        [
            ((correct[:, idx] == 1) & (correct[:, strong_idx] == 0)).astype(int)
            for idx in small_indices
        ]
    )
    predicted = probabilities >= threshold
    precision, recall, f1, _ = precision_recall_fscore_support(
        actual.ravel(), predicted.ravel(), average="binary", zero_division=0
    )
    return {
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "actual_rescue_labels": int(actual.sum()),
        "predicted_rescue_labels": int(predicted.sum()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--routing-train", required=True)
    parser.add_argument("--routing-test", required=True)
    parser.add_argument("--embeddings", required=True)
    parser.add_argument("--llm-data", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    args = parser.parse_args()

    np.random.seed(args.seed)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    llm_data = load_json(args.llm_data)
    model_names = list(llm_data)
    sizes = np.asarray([parse_size(llm_data[name]["size"]) for name in model_names])
    strong_idx = int(sizes.argmax())
    small_indices = [idx for idx in range(len(model_names)) if idx != strong_idx]
    embeddings = torch.load(args.embeddings, map_location="cpu")

    train_frame = load_routing(args.routing_train)
    train_queries, features, correct, performance, latency = build_matrices(
        train_frame, embeddings, model_names
    )
    rescue_any = (
        (correct[:, strong_idx] == 0)
        & (correct[:, small_indices].max(axis=1) == 1)
    ).astype(int)
    fit_idx, val_idx = train_test_split(
        np.arange(len(features)),
        test_size=args.val_ratio,
        random_state=args.seed,
        stratify=rescue_any,
    )

    models = fit_rescue_models(
        features[fit_idx], correct[fit_idx], strong_idx, small_indices, args.seed
    )
    val_probabilities = rescue_probabilities(models, features[val_idx])
    threshold_result, threshold_curve = choose_threshold(
        val_probabilities,
        correct[val_idx],
        performance[val_idx],
        latency[val_idx],
        sizes,
        strong_idx,
        small_indices,
    )
    threshold = threshold_result["threshold"]
    val_predictions = select_models(
        val_probabilities, threshold, strong_idx, small_indices
    )

    frozen_policy = {
        "seed": args.seed,
        "fit_query_count": int(len(fit_idx)),
        "validation_query_count": int(len(val_idx)),
        "strong_model": model_names[strong_idx],
        "small_models": [model_names[idx] for idx in small_indices],
        "threshold": threshold,
        "validation": threshold_result,
        "validation_rescue": rescue_metrics(
            val_probabilities, threshold, correct[val_idx], strong_idx, small_indices
        ),
    }
    joblib.dump(
        {
            "models": models,
            "model_names": model_names,
            "strong_idx": strong_idx,
            "small_indices": small_indices,
            "threshold": threshold,
        },
        output_dir / "safe_gate.joblib",
    )
    with open(output_dir / "frozen_policy.json", "w", encoding="utf-8") as handle:
        json.dump(frozen_policy, handle, ensure_ascii=False, indent=2)
    with open(output_dir / "validation_threshold_curve.json", "w", encoding="utf-8") as handle:
        json.dump(threshold_curve, handle, ensure_ascii=False, indent=2)

    # The test set is loaded only after the model and threshold are frozen.
    test_frame = load_routing(args.routing_test)
    test_queries, test_features, test_correct, test_performance, test_latency = build_matrices(
        test_frame, embeddings, model_names
    )
    test_probabilities = rescue_probabilities(models, test_features)
    test_predictions = select_models(
        test_probabilities, threshold, strong_idx, small_indices
    )
    test_metrics = policy_metrics(
        test_predictions, test_correct, test_performance, test_latency, sizes
    )
    test_metrics.update(
        {
            "experiment_id": f"kqapro_graphrouter_e2_seed{args.seed}",
            "dataset": "KQAPro",
            "router": "graphrouter_safe_gate",
            "seed": args.seed,
            "test_queries": len(test_queries),
            "threshold_source": "validation_only",
            "threshold": threshold,
            "strong_model": model_names[strong_idx],
            "always_strong_accuracy": float(test_correct[:, strong_idx].mean()),
            "oracle_answer_accuracy": float(test_correct.max(axis=1).mean()),
            "predicted_models": {
                model_names[idx]: int((test_predictions == idx).sum())
                for idx in range(len(model_names))
            },
            "test_rescue": rescue_metrics(
                test_probabilities,
                threshold,
                test_correct,
                strong_idx,
                small_indices,
            ),
        }
    )
    with open(output_dir / "test_results.json", "w", encoding="utf-8") as handle:
        json.dump(test_metrics, handle, ensure_ascii=False, indent=2)

    print(json.dumps({"policy": frozen_policy, "test": test_metrics}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
