#!/usr/bin/env python3
"""E5 nested-CV multi-task correctness router with a sealed final2 evaluation."""

import argparse
import json
import random
import sys
from pathlib import Path

import joblib
import numpy as np
import torch
import torch.nn as nn
from sklearn.model_selection import StratifiedKFold

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from kqapro_e4_generate import file_sha256, read_json, write_json
from train_safe_graphrouter import build_matrices, load_routing, parse_size
from train_safe_graphrouter_cv import enhanced_features, mean_std


class MultiTaskCorrectnessNet(nn.Module):
    def __init__(self, input_dim, output_dim):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 128),
            nn.ReLU(),
            nn.Dropout(0.15),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Dropout(0.10),
        )
        self.correctness_heads = nn.Linear(64, output_dim)

    def forward(self, features):
        return self.correctness_heads(self.encoder(features))


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def train_model(features, labels, seed, epochs=50):
    set_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    mean = features.mean(axis=0)
    std = features.std(axis=0)
    std[std < 1e-6] = 1.0
    normalized = (features - mean) / std
    x = torch.tensor(normalized, dtype=torch.float32, device=device)
    y = torch.tensor(labels, dtype=torch.float32, device=device)
    model = MultiTaskCorrectnessNet(features.shape[1], labels.shape[1]).to(device)
    positives = y.sum(dim=0)
    negatives = len(y) - positives
    pos_weight = (negatives / positives.clamp_min(1)).clamp(0.5, 4.0)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-4, weight_decay=1e-3)

    model.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        loss = criterion(model(x), y)
        loss.backward()
        optimizer.step()

    return {
        "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "mean": mean.astype(np.float32),
        "std": std.astype(np.float32),
        "input_dim": features.shape[1],
        "output_dim": labels.shape[1],
        "seed": seed,
    }


def predict_model(artifact, features):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = MultiTaskCorrectnessNet(
        artifact["input_dim"], artifact["output_dim"]
    ).to(device)
    model.load_state_dict(artifact["state_dict"])
    model.eval()
    normalized = (features - artifact["mean"]) / artifact["std"]
    x = torch.tensor(normalized, dtype=torch.float32, device=device)
    with torch.no_grad():
        return torch.sigmoid(model(x)).cpu().numpy()


def route_with_bounds(mean_probability, uncertainty, beta, margin, strong_idx, sizes):
    predictions = np.full(len(mean_probability), strong_idx, dtype=int)
    small_indices = [index for index in range(mean_probability.shape[1]) if index != strong_idx]
    small_lower = (
        mean_probability[:, small_indices] - beta * uncertainty[:, small_indices]
    )
    strong_upper = (
        mean_probability[:, strong_idx] + beta * uncertainty[:, strong_idx]
    )
    best_position = small_lower.argmax(axis=1)
    best_lower = small_lower[np.arange(len(small_lower)), best_position]
    eligible = best_lower >= strong_upper + margin
    predictions[eligible] = np.asarray(small_indices)[best_position[eligible]]
    return predictions


def routing_metrics(predictions, correct, performance, sizes, strong_idx):
    rows = np.arange(len(predictions))
    rescued = (
        (predictions != strong_idx)
        & (correct[rows, strong_idx] == 0)
        & (correct[rows, predictions] == 1)
    )
    harmed = (
        (predictions != strong_idx)
        & (correct[rows, strong_idx] == 1)
        & (correct[rows, predictions] == 0)
    )
    return {
        "answer_accuracy": float(correct[rows, predictions].mean()),
        "performance_score": float(performance[rows, predictions].mean()),
        "avg_size_b": float(sizes[predictions].mean()),
        "downgrade_count": int((predictions != strong_idx).sum()),
        "successful_rescues": int(rescued.sum()),
        "harmful_downgrades": int(harmed.sum()),
    }


def choose_policy(probabilities_by_seed, correct, performance, sizes, strong_idx):
    mean_probability = probabilities_by_seed.mean(axis=0)
    uncertainty = probabilities_by_seed.std(axis=0)
    strong_accuracy = float(correct[:, strong_idx].mean())
    candidates = []
    for beta in [0.0, 0.5, 1.0, 1.5, 2.0]:
        for margin in [0.0, 0.02, 0.05, 0.10, 0.15, 0.20]:
            predictions = route_with_bounds(
                mean_probability, uncertainty, beta, margin, strong_idx, sizes
            )
            metrics = routing_metrics(
                predictions, correct, performance, sizes, strong_idx
            )
            metrics.update({"beta": beta, "margin": margin})
            candidates.append(metrics)
    safe = [
        candidate
        for candidate in candidates
        if candidate["answer_accuracy"] >= strong_accuracy
        and candidate["successful_rescues"] >= candidate["harmful_downgrades"]
    ]
    pool = safe or candidates
    best = max(
        pool,
        key=lambda item: (
            item["answer_accuracy"],
            item["successful_rescues"] - item["harmful_downgrades"],
            -item["avg_size_b"],
            item["beta"],
            item["margin"],
        ),
    )
    return best, candidates


def stratification_labels(correct, strong_idx):
    pattern = sum(
        correct[:, index].astype(int) * (2 ** index)
        for index in range(correct.shape[1])
    )
    # Fall back to strong correctness if any joint pattern is too rare.
    counts = np.bincount(pattern)
    if np.any(counts[counts > 0] < 5):
        return correct[:, strong_idx].astype(int)
    return pattern


def nested_training(features, correct, performance, sizes, strong_idx, seeds,
                    outer_folds, inner_folds, epochs):
    labels = stratification_labels(correct, strong_idx)
    outer = StratifiedKFold(
        n_splits=outer_folds, shuffle=True, random_state=2026
    )
    oof_by_seed = np.zeros(
        (len(seeds), len(features), correct.shape[1]), dtype=np.float32
    )
    outer_models = {seed: [] for seed in seeds}
    fold_policies = []

    for outer_fold, (outer_train, outer_val) in enumerate(outer.split(features, labels)):
        inner_labels = stratification_labels(correct[outer_train], strong_idx)
        inner = StratifiedKFold(
            n_splits=inner_folds, shuffle=True, random_state=9000 + outer_fold
        )
        inner_oof = np.zeros(
            (len(seeds), len(outer_train), correct.shape[1]), dtype=np.float32
        )
        for inner_fold, (inner_fit_rel, inner_val_rel) in enumerate(
            inner.split(features[outer_train], inner_labels)
        ):
            inner_fit = outer_train[inner_fit_rel]
            for seed_position, seed in enumerate(seeds):
                artifact = train_model(
                    features[inner_fit],
                    correct[inner_fit],
                    seed + outer_fold * 100 + inner_fold,
                    epochs,
                )
                inner_oof[seed_position, inner_val_rel] = predict_model(
                    artifact, features[outer_train[inner_val_rel]]
                )

        selected, _ = choose_policy(
            inner_oof,
            correct[outer_train],
            performance[outer_train],
            sizes,
            strong_idx,
        )
        fold_policies.append(
            {
                "outer_fold": outer_fold,
                "beta": selected["beta"],
                "margin": selected["margin"],
                "inner_metrics": selected,
            }
        )

        for seed_position, seed in enumerate(seeds):
            artifact = train_model(
                features[outer_train],
                correct[outer_train],
                seed + outer_fold * 1000,
                epochs,
            )
            outer_models[seed].append(artifact)
            oof_by_seed[seed_position, outer_val] = predict_model(
                artifact, features[outer_val]
            )

    # A deterministic robust aggregation of independently selected inner-fold
    # policies. No dev/final outcomes participate.
    beta = float(np.median([item["beta"] for item in fold_policies]))
    margin = float(np.median([item["margin"] for item in fold_policies]))
    combined_mean = oof_by_seed.mean(axis=0)
    combined_std = oof_by_seed.std(axis=0)
    combined_predictions = route_with_bounds(
        combined_mean, combined_std, beta, margin, strong_idx, sizes
    )
    combined_oof = routing_metrics(
        combined_predictions, correct, performance, sizes, strong_idx
    )
    per_seed_oof = []
    for position, seed in enumerate(seeds):
        seed_uncertainty = np.zeros_like(oof_by_seed[position])
        predictions = route_with_bounds(
            oof_by_seed[position],
            seed_uncertainty,
            beta,
            margin,
            strong_idx,
            sizes,
        )
        metrics = routing_metrics(
            predictions, correct, performance, sizes, strong_idx
        )
        metrics["seed"] = seed
        per_seed_oof.append(metrics)
    return {
        "models": outer_models,
        "oof_by_seed": oof_by_seed,
        "beta": beta,
        "margin": margin,
        "fold_policies": fold_policies,
        "combined_oof": combined_oof,
        "per_seed_oof": per_seed_oof,
    }


def ensemble_predictions(models, features):
    predictions = np.stack(
        [predict_model(model, features) for model in models], axis=0
    )
    return predictions.mean(axis=0), predictions.std(axis=0)


def evaluate_frozen(training, features, correct, performance, sizes,
                    strong_idx, model_names, seeds):
    per_seed = []
    seed_means = []
    for seed in seeds:
        mean_probability, uncertainty = ensemble_predictions(
            training["models"][seed], features
        )
        predictions = route_with_bounds(
            mean_probability,
            uncertainty,
            training["beta"],
            training["margin"],
            strong_idx,
            sizes,
        )
        metrics = routing_metrics(
            predictions, correct, performance, sizes, strong_idx
        )
        metrics.update(
            {
                "seed": seed,
                "predicted_models": {
                    model_names[index]: int((predictions == index).sum())
                    for index in range(len(model_names))
                },
            }
        )
        per_seed.append(metrics)
        seed_means.append(mean_probability)

    seed_means = np.stack(seed_means, axis=0)
    combined_mean = seed_means.mean(axis=0)
    combined_uncertainty = seed_means.std(axis=0)
    combined_predictions = route_with_bounds(
        combined_mean,
        combined_uncertainty,
        training["beta"],
        training["margin"],
        strong_idx,
        sizes,
    )
    combined = routing_metrics(
        combined_predictions, correct, performance, sizes, strong_idx
    )
    combined["predicted_models"] = {
        model_names[index]: int((combined_predictions == index).sum())
        for index in range(len(model_names))
    }
    return per_seed, combined


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--train-routing",
        type=Path,
        default=PROJECT_ROOT / "data/kqapro/e4/routing_train.jsonl",
    )
    parser.add_argument(
        "--train-embeddings",
        type=Path,
        default=PROJECT_ROOT / "data/kqapro/e4/query_embeddings_longformer.pt",
    )
    parser.add_argument(
        "--final2-dir",
        type=Path,
        default=PROJECT_ROOT / "data/kqapro/e5_final2",
    )
    parser.add_argument(
        "--llm-data",
        type=Path,
        default=PROJECT_ROOT / "data/kqapro/e4/llm_candidates.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "run_logs/kqapro/e5",
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 43, 44])
    parser.add_argument("--outer-folds", type=int, default=5)
    parser.add_argument("--inner-folds", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=50)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    llm_data = read_json(args.llm_data)
    model_names = list(llm_data)
    sizes = np.asarray([parse_size(llm_data[name]["size"]) for name in model_names])
    strong_idx = int(sizes.argmax())

    train_frame = load_routing(args.train_routing)
    train_embeddings = torch.load(args.train_embeddings, map_location="cpu")
    queries, raw, correct, performance, _ = build_matrices(
        train_frame, train_embeddings, model_names
    )
    features = enhanced_features(queries, raw)
    training = nested_training(
        features,
        correct,
        performance,
        sizes,
        strong_idx,
        args.seeds,
        args.outer_folds,
        args.inner_folds,
        args.epochs,
    )
    frozen = {
        "experiment_id": "kqapro_e5_multitask",
        "seeds": args.seeds,
        "outer_folds": args.outer_folds,
        "inner_folds": args.inner_folds,
        "training_queries": len(queries),
        "shared_encoder": [128, 64],
        "correctness_heads": model_names,
        "beta": training["beta"],
        "margin": training["margin"],
        "threshold_source": "nested_training_cv_only",
        "fold_policies": training["fold_policies"],
        "combined_oof": training["combined_oof"],
        "per_seed_oof": training["per_seed_oof"],
    }
    write_json(args.output_dir / "frozen_policy.json", frozen)
    joblib.dump(
        {
            "models": training["models"],
            "beta": training["beta"],
            "margin": training["margin"],
            "seeds": args.seeds,
            "model_names": model_names,
            "strong_idx": strong_idx,
            "sizes": sizes,
        },
        args.output_dir / "multitask_ensemble.joblib",
    )

    # Only now, after all policies and artifacts are frozen, open final2.
    seal_path = args.final2_dir / "final2_seal.json"
    seal = read_json(seal_path)
    if seal["metrics_read"]:
        raise RuntimeError("final2 metrics were already read")
    if file_sha256(args.final2_dir / "routing_final2.jsonl") != seal["routing_sha256"]:
        raise RuntimeError("final2 routing hash mismatch")
    if file_sha256(args.final2_dir / "query_final2.jsonl") != seal["query_sha256"]:
        raise RuntimeError("final2 query hash mismatch")
    final_frame = load_routing(args.final2_dir / "routing_final2.jsonl")
    final_embeddings = torch.load(
        args.final2_dir / "query_embeddings_longformer.pt", map_location="cpu"
    )
    final_queries, final_raw, final_correct, final_performance, _ = build_matrices(
        final_frame, final_embeddings, model_names
    )
    final_features = enhanced_features(final_queries, final_raw)
    per_seed, combined = evaluate_frozen(
        training,
        final_features,
        final_correct,
        final_performance,
        sizes,
        strong_idx,
        model_names,
        args.seeds,
    )
    baseline = float(final_correct[:, strong_idx].mean())
    summary = {
        "experiment_id": "kqapro_e5_final2",
        "sealed_hash_verified": True,
        "final2_evaluated_once": True,
        "final2_queries": len(final_queries),
        "always_strong_accuracy": baseline,
        "oracle_accuracy": float(final_correct.max(axis=1).mean()),
        "beta": training["beta"],
        "margin": training["margin"],
        "per_seed": per_seed,
        "combined": combined,
        "per_seed_accuracy": mean_std(
            [item["answer_accuracy"] for item in per_seed]
        ),
        "pre_registered_goals": {
            "three_seed_mean_gt_strong": bool(
                np.mean([item["answer_accuracy"] for item in per_seed]) > baseline
            ),
            "every_seed_ge_strong": bool(all(
                item["answer_accuracy"] >= baseline for item in per_seed
            )),
            "combined_avg_size_lt_3b": combined["avg_size_b"] < 3.0,
            "combined_rescues_gt_harms": (
                combined["successful_rescues"] > combined["harmful_downgrades"]
            ),
            "threshold_from_oof_only": True,
            "final2_read_once": True,
        },
    }
    write_json(args.output_dir / "final2_summary.json", summary)
    seal["metrics_read"] = True
    seal["evaluation_output"] = str(
        (args.output_dir / "final2_summary.json").relative_to(PROJECT_ROOT)
    )
    write_json(seal_path, seal)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
