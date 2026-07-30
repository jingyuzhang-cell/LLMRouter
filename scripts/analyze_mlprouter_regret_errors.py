"""Analyze high-regret ensemble routing errors and measurement noise priorities."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from evaluate_mlprouter_ensemble import probabilities
from llmrouter.utils import load_model


BASE = Path("data/example_data/routing_data")
GROUPED = BASE / "grouped"
MODEL_DIR = Path("llmrouter/saved_models/mlprouter")
OUT = Path("run_logs/mlprouter_regret_analysis")
MODELS = [
    MODEL_DIR / f"mlprouter_hparam_r10_b02_g3_s{seed}.pkl"
    for seed in (42, 123, 2026)
]


def model_sets(scores, model_names):
    maximum = scores.max(axis=1, keepdims=True)
    return [
        "|".join(np.asarray(model_names)[np.isclose(row, top, atol=1e-8)])
        for row, top in zip(scores, maximum[:, 0])
    ]


def aggregate_errors(rows, columns):
    return (
        rows.groupby(columns, dropna=False)
        .agg(
            queries=("query", "size"),
            errors=("is_error", "sum"),
            clear_gap_errors=("clear_gap_error", "sum"),
            mean_regret=("regret", "mean"),
            total_regret=("regret", "sum"),
            max_regret=("regret", "max"),
        )
        .assign(error_rate=lambda value: value.errors / value.queries)
        .sort_values(["total_regret", "errors"], ascending=False)
        .reset_index()
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    test = pd.read_json(GROUPED / "default_routing_test_data.jsonl", lines=True)
    train = pd.read_json(GROUPED / "default_routing_train_data.jsonl", lines=True)
    embeddings = torch.load(BASE / "query_embeddings_longformer.pt", map_location="cpu", weights_only=False)
    checkpoints = [load_model(str(path)) for path in MODELS]
    outputs = [probabilities(checkpoint, test, embeddings) for checkpoint in checkpoints]
    averaged = np.mean([output[0] for output in outputs], axis=0)
    scores = outputs[0][1]
    model_names = outputs[0][2]
    pivot = test.pivot(index="query", columns="model_name", values="performance").reindex(columns=model_names)
    metadata = test.drop_duplicates("query").set_index("query").loc[pivot.index]
    selected_index = averaged.argmax(axis=1)
    selected = np.asarray(model_names)[selected_index]
    order = np.sort(scores, axis=1)
    oracle = scores.max(axis=1)
    chosen = scores[np.arange(len(scores)), selected_index]
    gaps = order[:, -1] - order[:, -2]
    rows = pd.DataFrame({
        "query": pivot.index,
        "task_name": metadata["task_name"].to_numpy(),
        "embedding_id": metadata["embedding_id"].to_numpy(),
        "selected_model": selected,
        "optimal_models": model_sets(scores, model_names),
        "selected_performance": chosen,
        "optimal_performance": oracle,
        "regret": oracle - chosen,
        "top1_top2_gap": gaps,
    })
    rows["is_error"] = rows.regret > 1e-8
    rows["clear_gap_error"] = rows.is_error & (rows.top1_top2_gap >= 0.1)
    rows["priority_score"] = rows.regret * (1 + rows.top1_top2_gap)
    rows.sort_values(["priority_score", "regret"], ascending=False).to_csv(
        OUT / "query_priorities.csv", index=False
    )
    aggregate_errors(rows, ["task_name"]).to_csv(OUT / "by_task.csv", index=False)
    aggregate_errors(rows, ["selected_model"]).to_csv(OUT / "by_selected_model.csv", index=False)
    aggregate_errors(rows, ["optimal_models"]).to_csv(OUT / "by_optimal_models.csv", index=False)
    aggregate_errors(rows, ["task_name", "selected_model", "optimal_models"]).to_csv(
        OUT / "by_route_pattern.csv", index=False
    )

    train_scores = train.pivot(index="query", columns="model_name", values="performance").reindex(columns=model_names)
    train_values = train_scores.to_numpy()
    optimal_mask = np.isclose(train_values, train_values.max(axis=1, keepdims=True), atol=1e-8)
    unique_mask = optimal_mask.sum(axis=1) == 1
    unique_counts = {
        model: int((unique_mask & optimal_mask[:, index]).sum())
        for index, model in enumerate(model_names)
    }
    tied_counts = {model: int(optimal_mask[:, index].sum()) for index, model in enumerate(model_names)}
    rarity = pd.DataFrame({
        "model_name": model_names,
        "unique_optimum_train_queries": [unique_counts[m] for m in model_names],
        "optimal_set_train_queries": [tied_counts[m] for m in model_names],
    }).sort_values(["unique_optimum_train_queries", "optimal_set_train_queries"])
    rarity.to_csv(OUT / "model_rarity.csv", index=False)

    original_train = pd.read_json(BASE / "default_routing_train_data.jsonl", lines=True)
    duplicate_groups = original_train.groupby(["query", "model_name"]).filter(lambda group: len(group) > 1)
    duplicate_noise = (
        duplicate_groups.groupby(["query", "model_name"])
        .agg(
            evaluations=("performance", "size"),
            mean_performance=("performance", "mean"),
            performance_std=("performance", "std"),
            performance_min=("performance", "min"),
            performance_max=("performance", "max"),
            task_name=("task_name", "first"),
        )
        .assign(performance_range=lambda value: value.performance_max - value.performance_min)
        .sort_values("performance_range", ascending=False)
        .reset_index()
    )
    duplicate_noise.to_csv(OUT / "duplicate_measurement_noise.csv", index=False)

    high = rows[rows.is_error]
    report = {
        "ensemble_checkpoints": [str(path) for path in MODELS],
        "test_queries": len(rows),
        "error_queries": int(rows.is_error.sum()),
        "clear_gap_error_queries": int(rows.clear_gap_error.sum()),
        "mean_regret": float(rows.regret.mean()),
        "total_regret": float(rows.regret.sum()),
        "regret_concentration": {
            "top_10_error_share": float(high.nlargest(10, "regret").regret.sum() / high.regret.sum()),
            "top_50_error_share": float(high.nlargest(50, "regret").regret.sum() / high.regret.sum()),
            "queries_for_80pct_regret": int((high.sort_values("regret", ascending=False).regret.cumsum() < high.regret.sum() * .8).sum() + 1),
        },
        "duplicate_audit": {
            "original_train_query_model_pairs_with_repeats": len(duplicate_noise),
            "pairs_with_disagreement": int((duplicate_noise.performance_range > 0).sum()),
            "pairs_with_maximal_binary_disagreement": int((duplicate_noise.performance_range >= 1).sum()),
            "original_test_query_model_pairs_with_repeats": 0,
            "conclusion": "Test performance noise cannot be estimated without new repeated evaluations.",
        },
        "rare_unique_optimum_models": rarity.head(4).to_dict("records"),
        "artifacts": {path.name: str(path) for path in OUT.iterdir()},
    }
    (OUT / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
