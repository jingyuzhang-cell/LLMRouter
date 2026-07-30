"""Merge successful repeated measurements, rebuild splits, and report uncertainty."""

import argparse
import json
import subprocess
from pathlib import Path

import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="run_logs/mlprouter_regret_analysis/reevaluation_results.jsonl")
    parser.add_argument("--base", default="data/example_data/routing_data/default_routing_test_data.jsonl")
    parser.add_argument("--output", default="data/example_data/routing_data/default_routing_test_data_remeasured.jsonl")
    parser.add_argument("--min-repeats", type=int, default=3)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    results = pd.read_json(args.results, lines=True)
    successful = results[results.success & results.performance.notna()].copy()
    stats = (
        successful.groupby(["query", "model_name"])
        .performance.agg(["count", "mean", "std", "min", "max"])
        .reset_index()
    )
    incomplete = stats[stats["count"] < args.min_repeats]
    if len(incomplete):
        raise SystemExit(f"{len(incomplete)} query/model pairs have fewer than {args.min_repeats} successful repeats")

    base = pd.read_json(args.base, lines=True)
    means = stats.set_index(["query", "model_name"])["mean"]
    index = pd.MultiIndex.from_frame(base[["query", "model_name"]])
    replacement = means.reindex(index).to_numpy()
    selected = pd.notna(replacement)
    base.loc[selected, "performance"] = replacement[selected]
    base.loc[selected, "evaluation_count"] = args.min_repeats
    base.to_json(args.output, orient="records", lines=True, force_ascii=False)

    report = {
        "successful_evaluations": len(successful),
        "updated_query_model_pairs": len(stats),
        "mean_within_pair_std": float(stats["std"].mean()),
        "disagreement_pairs": int((stats["min"] != stats["max"]).sum()),
        "output": args.output,
    }
    report_path = Path("run_logs/mlprouter_regret_analysis/reevaluation_variance.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if args.rebuild:
        subprocess.run([
            "python", "scripts/split_mlprouter_grouped.py",
            "--test", args.output,
        ], check=True)


if __name__ == "__main__":
    main()
