"""Rebuild MLP routing splits with query-level isolation and label stratification."""

import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split


def best_label_by_query(frame):
    best = frame.loc[frame.groupby("query")["performance"].idxmax()]
    return best.set_index("query")["model_name"]


def aggregate_repeated_evaluations(frame):
    """Keep metadata from the first run while averaging repeated quality measurements."""
    keys = ["query", "model_name"]
    counts = frame.groupby(keys)["performance"].size().rename("evaluation_count")
    means = frame.groupby(keys)["performance"].mean().rename("performance_mean")
    result = frame.drop_duplicates(keys, keep="first").set_index(keys)
    result["performance"] = means
    result["evaluation_count"] = counts
    return result.reset_index()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", default="data/example_data/routing_data/default_routing_train_data.jsonl")
    parser.add_argument("--test", default="data/example_data/routing_data/default_routing_test_data.jsonl")
    parser.add_argument("--output-dir", default="data/example_data/routing_data/grouped")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    original_train = pd.read_json(args.train, lines=True)
    original_test = pd.read_json(args.test, lines=True)
    combined_raw = pd.concat([original_train, original_test], ignore_index=True)
    # Preserve the established query assignment for comparable held-out evaluation.
    split_source = combined_raw.drop_duplicates(["query", "model_name"], keep="first")
    labels = best_label_by_query(split_source)
    combined = aggregate_repeated_evaluations(combined_raw)
    queries = labels.index.to_series()
    train_queries, holdout_queries = train_test_split(
        queries,
        test_size=0.20,
        random_state=args.seed,
        stratify=labels.loc[queries],
    )
    validation_queries, test_queries = train_test_split(
        holdout_queries,
        test_size=0.50,
        random_state=args.seed,
        stratify=labels.loc[holdout_queries],
    )

    split_queries = {
        "train": set(train_queries),
        "validation": set(validation_queries),
        "test": set(test_queries),
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {}
    for split, selected in split_queries.items():
        frame = combined[combined["query"].isin(selected)].copy()
        path = output_dir / f"default_routing_{split}_data.jsonl"
        frame.to_json(path, orient="records", lines=True, force_ascii=False)
        split_labels = labels.loc[list(selected)].value_counts().sort_index()
        summary[split] = {
            "queries": len(selected),
            "rows": len(frame),
            "labels": {str(key): int(value) for key, value in split_labels.items()},
        }

    overlaps = {
        "train_validation": len(split_queries["train"] & split_queries["validation"]),
        "train_test": len(split_queries["train"] & split_queries["test"]),
        "validation_test": len(split_queries["validation"] & split_queries["test"]),
    }
    if any(overlaps.values()):
        raise RuntimeError(f"Query leakage detected: {overlaps}")
    summary["overlaps"] = overlaps
    (output_dir / "split_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
