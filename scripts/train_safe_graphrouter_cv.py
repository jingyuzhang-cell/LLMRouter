#!/usr/bin/env python3
"""E3: five-fold OOF safety-gate ensemble with query-structure features."""

import argparse
import json
import re
from pathlib import Path

import joblib
import numpy as np
import torch
from sklearn.model_selection import StratifiedKFold

from train_safe_graphrouter import (
    build_matrices,
    choose_threshold,
    fit_rescue_models,
    load_json,
    load_routing,
    parse_size,
    policy_metrics,
    rescue_metrics,
    rescue_probabilities,
    select_models,
)


FEATURE_NAMES = [
    "char_count",
    "token_count",
    "digit_count",
    "capitalized_token_count",
    "conjunction_count",
    "count_question",
    "comparison_question",
    "verification_question",
    "relation_question",
    "set_operation_question",
    "temporal_question",
    "numeric_question",
    "url_question",
    "multi_hop_proxy",
]


def contains_any(text, phrases):
    return float(any(phrase in text for phrase in phrases))


def structural_features(queries):
    rows = []
    for query in queries:
        lower = query.lower()
        tokens = re.findall(r"[A-Za-z0-9]+", query)
        conjunctions = re.findall(r"\b(?:and|or|but|while|that|which|whose)\b", lower)
        count_flag = contains_any(
            lower, ["how many", "number of", "count of", "total number"]
        )
        comparison_flag = contains_any(
            lower,
            [
                "more ", "fewer ", "less ", "most ", "least ", "longer",
                "shorter", "largest", "smallest", "earlier", "later",
                "older", "younger", "higher", "lower", "same ",
            ],
        )
        verification_flag = float(
            bool(re.match(r"^(is|are|was|were|do|does|did|has|have|had|can|could)\b", lower))
        )
        relation_flag = contains_any(
            lower,
            [
                "relation", "related", "belongs to", "located in", "part of",
                "member of", "produced by", "written by", "directed by",
                "starring", "whose", "which has", "that has",
            ],
        )
        set_flag = contains_any(
            lower,
            [" both ", " either ", " or ", " and ", "not ", "all the", "among"],
        )
        temporal_flag = contains_any(
            lower,
            [
                "year", "date", "before", "after", "during", "ended",
                "started", "earlier", "later", "duration",
            ],
        )
        numeric_flag = float(bool(re.search(r"\d", query))) or count_flag
        url_flag = contains_any(lower, ["http://", "https://", "www.", "website"])
        multi_hop = float(
            len(conjunctions) >= 2
            or contains_any(lower, ["which has", "that has", "whose", "of the"])
        )
        rows.append(
            [
                len(query),
                len(tokens),
                len(re.findall(r"\d", query)),
                sum(token[:1].isupper() for token in tokens),
                len(conjunctions),
                count_flag,
                comparison_flag,
                verification_flag,
                relation_flag,
                set_flag,
                temporal_flag,
                numeric_flag,
                url_flag,
                multi_hop,
            ]
        )
    return np.asarray(rows, dtype=np.float32)


def enhanced_features(queries, embeddings):
    structure = structural_features(queries)
    return np.concatenate([embeddings.astype(np.float32), structure], axis=1)


def train_seed(features, correct, performance, latency, sizes, strong_idx,
               small_indices, seed, folds):
    rescue_any = (
        (correct[:, strong_idx] == 0)
        & (correct[:, small_indices].max(axis=1) == 1)
    ).astype(int)
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    oof = np.zeros((len(features), len(small_indices)), dtype=np.float64)
    fold_models = []
    fold_manifest = []

    for fold, (fit_idx, val_idx) in enumerate(splitter.split(features, rescue_any)):
        models = fit_rescue_models(
            features[fit_idx], correct[fit_idx], strong_idx, small_indices, seed + fold
        )
        oof[val_idx] = rescue_probabilities(models, features[val_idx])
        fold_models.append(models)
        fold_manifest.append(
            {
                "fold": fold,
                "fit_count": int(len(fit_idx)),
                "validation_count": int(len(val_idx)),
                "validation_indices": val_idx.tolist(),
            }
        )

    threshold_result, threshold_curve = choose_threshold(
        oof, correct, performance, latency, sizes, strong_idx, small_indices
    )
    threshold = threshold_result["threshold"]
    return {
        "seed": seed,
        "models": fold_models,
        "oof_probabilities": oof,
        "threshold": threshold,
        "threshold_result": threshold_result,
        "threshold_curve": threshold_curve,
        "fold_manifest": fold_manifest,
        "oof_rescue": rescue_metrics(
            oof, threshold, correct, strong_idx, small_indices
        ),
    }


def ensemble_probabilities(fold_models, features):
    per_fold = []
    for models in fold_models:
        per_fold.append(rescue_probabilities(models, features))
    return np.mean(np.stack(per_fold, axis=0), axis=0)


def mean_std(values):
    values = np.asarray(values, dtype=float)
    return {
        "mean": float(values.mean()),
        "std": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--routing-train", required=True)
    parser.add_argument("--routing-test", required=True)
    parser.add_argument("--embeddings", required=True)
    parser.add_argument("--llm-data", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 43, 44])
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    llm_data = load_json(args.llm_data)
    model_names = list(llm_data)
    sizes = np.asarray([parse_size(llm_data[name]["size"]) for name in model_names])
    strong_idx = int(sizes.argmax())
    small_indices = [idx for idx in range(len(model_names)) if idx != strong_idx]
    embeddings = torch.load(args.embeddings, map_location="cpu")

    # Phase 1: freeze every seed policy using training data and OOF predictions.
    train_frame = load_routing(args.routing_train)
    queries, raw_features, correct, performance, latency = build_matrices(
        train_frame, embeddings, model_names
    )
    features = enhanced_features(queries, raw_features)
    policies = []
    for seed in args.seeds:
        policy = train_seed(
            features, correct, performance, latency, sizes, strong_idx,
            small_indices, seed, args.folds
        )
        seed_dir = output_dir / f"seed{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        frozen = {
            "seed": seed,
            "folds": args.folds,
            "training_query_count": len(queries),
            "feature_dimension": int(features.shape[1]),
            "structure_features": FEATURE_NAMES,
            "strong_model": model_names[strong_idx],
            "small_models": [model_names[idx] for idx in small_indices],
            "threshold": policy["threshold"],
            "threshold_source": "training_oof_only",
            "oof": policy["threshold_result"],
            "oof_rescue": policy["oof_rescue"],
            "fold_manifest": policy["fold_manifest"],
        }
        with open(seed_dir / "frozen_policy.json", "w", encoding="utf-8") as handle:
            json.dump(frozen, handle, ensure_ascii=False, indent=2)
        with open(seed_dir / "oof_threshold_curve.json", "w", encoding="utf-8") as handle:
            json.dump(policy["threshold_curve"], handle, ensure_ascii=False, indent=2)
        joblib.dump(
            {
                "fold_models": policy["models"],
                "threshold": policy["threshold"],
                "model_names": model_names,
                "strong_idx": strong_idx,
                "small_indices": small_indices,
                "feature_names": FEATURE_NAMES,
            },
            seed_dir / "safe_gate_ensemble.joblib",
        )
        policies.append(policy)

    # Phase 2: after all policies are frozen, read the test set exactly once.
    test_frame = load_routing(args.routing_test)
    test_queries, test_raw, test_correct, test_performance, test_latency = build_matrices(
        test_frame, embeddings, model_names
    )
    test_features = enhanced_features(test_queries, test_raw)
    seed_results = []
    for policy in policies:
        probabilities = ensemble_probabilities(policy["models"], test_features)
        predictions = select_models(
            probabilities, policy["threshold"], strong_idx, small_indices
        )
        metrics = policy_metrics(
            predictions, test_correct, test_performance, test_latency, sizes
        )
        rows = np.arange(len(predictions))
        rescued = (
            (predictions != strong_idx)
            & (test_correct[rows, strong_idx] == 0)
            & (test_correct[rows, predictions] == 1)
        )
        harmed = (
            (predictions != strong_idx)
            & (test_correct[rows, strong_idx] == 1)
            & (test_correct[rows, predictions] == 0)
        )
        metrics.update(
            {
                "experiment_id": f"kqapro_graphrouter_e3_seed{policy['seed']}",
                "seed": policy["seed"],
                "threshold": policy["threshold"],
                "threshold_source": "training_oof_only",
                "test_queries": len(test_queries),
                "always_strong_accuracy": float(test_correct[:, strong_idx].mean()),
                "oracle_answer_accuracy": float(test_correct.max(axis=1).mean()),
                "successful_rescues": int(rescued.sum()),
                "harmful_downgrades": int(harmed.sum()),
                "predicted_models": {
                    model_names[idx]: int((predictions == idx).sum())
                    for idx in range(len(model_names))
                },
                "test_rescue_classifier": rescue_metrics(
                    probabilities, policy["threshold"], test_correct,
                    strong_idx, small_indices
                ),
            }
        )
        seed_dir = output_dir / f"seed{policy['seed']}"
        with open(seed_dir / "test_results.json", "w", encoding="utf-8") as handle:
            json.dump(metrics, handle, ensure_ascii=False, indent=2)
        seed_results.append(metrics)

    summary = {
        "experiment_id": "kqapro_graphrouter_e3",
        "seeds": args.seeds,
        "folds": args.folds,
        "test_was_loaded_after_all_policies_frozen": True,
        "answer_accuracy": mean_std([x["answer_accuracy"] for x in seed_results]),
        "performance_score": mean_std([x["performance_score"] for x in seed_results]),
        "avg_size_b": mean_std([x["avg_size_b"] for x in seed_results]),
        "successful_rescues": mean_std([x["successful_rescues"] for x in seed_results]),
        "harmful_downgrades": mean_std([x["harmful_downgrades"] for x in seed_results]),
        "pre_registered_goals": {
            "accuracy_gt_42pct": all(x["answer_accuracy"] > 0.42 for x in seed_results),
            "avg_size_le_3b": all(x["avg_size_b"] <= 3.0 for x in seed_results),
            "threshold_not_tuned_on_test": True,
            "at_least_one_successful_rescue": all(
                x["successful_rescues"] >= 1 for x in seed_results
            ),
        },
        "per_seed": seed_results,
    }
    with open(output_dir / "summary.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
