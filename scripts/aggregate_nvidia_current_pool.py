"""Aggregate current-pool repeats and create grouped train/validation/test data."""

import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", default="data/nvidia_current_v1/queries.jsonl")
    parser.add_argument("--results", default="data/nvidia_current_v1/results.jsonl")
    parser.add_argument("--output-dir", default="data/nvidia_current_v1/grouped")
    parser.add_argument("--min-repeats", type=int, default=2)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    queries = pd.read_json(args.queries, lines=True)
    results = pd.read_json(args.results, lines=True)
    successful = results[results.success & results.performance.notna()].copy()
    stats = successful.groupby(["query", "model_name"]).performance.agg(
        evaluation_count="count", performance="mean", performance_std="std"
    ).reset_index()
    expected = len(queries) * stats.model_name.nunique()
    incomplete = stats[stats.evaluation_count < args.min_repeats]
    if len(stats) != expected or len(incomplete):
        raise SystemExit(
            f"incomplete current-pool data: pairs={len(stats)}/{expected}, "
            f"pairs below repeats={len(incomplete)}"
        )

    full = queries.merge(stats, on="query", how="inner", validate="many_to_one")
    labels = (
        full.loc[full.groupby("query").performance.idxmax()]
        .set_index("query")["model_name"]
    )
    query_values = labels.index.to_series()
    train_queries, holdout = train_test_split(
        query_values, test_size=0.30, random_state=args.seed, stratify=labels.loc[query_values]
    )
    validation_queries, test_queries = train_test_split(
        holdout, test_size=0.50, random_state=args.seed, stratify=labels.loc[holdout]
    )
    groups = {"train": set(train_queries), "validation": set(validation_queries), "test": set(test_queries)}
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary = {"models": sorted(stats.model_name.unique()), "repeats": args.min_repeats}
    for split, selected in groups.items():
        frame = full[full.query.isin(selected)].copy()
        frame.to_json(output / f"default_routing_{split}_data.jsonl", orient="records", lines=True, force_ascii=False)
        summary[split] = {"queries": len(selected), "rows": len(frame)}
    summary["overlaps"] = {
        "train_validation": len(groups["train"] & groups["validation"]),
        "train_test": len(groups["train"] & groups["test"]),
        "validation_test": len(groups["validation"] & groups["test"]),
    }
    (output / "split_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    variance = stats.groupby("model_name").performance_std.agg(["count", "mean", "median"]).reset_index()
    variance.to_csv(output / "repeat_variance_by_model.csv", index=False)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
