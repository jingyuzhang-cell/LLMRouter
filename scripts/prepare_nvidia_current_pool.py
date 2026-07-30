"""Create a clean pilot query set and manifest for the current NVIDIA model pool."""

import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split


CURRENT_POOL = {
    "llama-3.1-8b-instruct": "meta/llama-3.1-8b-instruct",
    "llama-3.3-70b-instruct": "meta/llama-3.3-70b-instruct",
    "mistral-small-4-119b-2603": "mistralai/mistral-small-4-119b-2603",
    "llama-3.2-3b-instruct": "meta/llama-3.2-3b-instruct",
    "llama-3.3-nemotron-super-49b-v1": "nvidia/llama-3.3-nemotron-super-49b-v1",
    "qwen3-next-80b-a3b-instruct": "qwen/qwen3-next-80b-a3b-instruct",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="data/example_data/routing_data/grouped/default_routing_test_data.jsonl")
    parser.add_argument("--output-dir", default="data/nvidia_current_v1")
    parser.add_argument("--queries", type=int, default=300)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    supported_tasks = {"math", "gsm8k", "gpqa", "mmlu", "commonsense_qa", "openbook_qa", "arc_challenge", "natural_qa", "trivia_qa"}
    source = pd.read_json(args.source, lines=True).drop_duplicates("query")
    source = source[source["task_name"].isin(supported_tasks)].copy()
    if args.queries > len(source):
        raise ValueError(f"Requested {args.queries} queries but only {len(source)} are available")
    selected, _ = train_test_split(
        source,
        test_size=len(source) - args.queries,
        random_state=args.seed,
        stratify=source["task_name"],
    )
    selected = selected.sort_values(["task_name", "query"]).copy()
    selected["source_split"] = "historical_test_query_only"
    # Keep no old model performance or model response in the new experiment input.
    keep = ["task_name", "query", "ground_truth", "metric", "choices", "task_id", "embedding_id", "source_split"]
    selected[keep].to_json(output / "queries.jsonl", orient="records", lines=True, force_ascii=False)

    jobs = []
    for row in selected.itertuples(index=False):
        for model_name, api_name in CURRENT_POOL.items():
            for repeat_index in range(1, args.repeats + 1):
                jobs.append({
                    "query": row.query,
                    "task_name": row.task_name,
                    "model_name": model_name,
                    "api_name": api_name,
                    "repeat_index": repeat_index,
                    "requested_repeats": args.repeats,
                })
    pd.DataFrame(jobs).to_json(output / "manifest.jsonl", orient="records", lines=True, force_ascii=False)
    summary = {
        "experiment": "nvidia_current_v1",
        "queries": len(selected),
        "tasks": selected["task_name"].value_counts().to_dict(),
        "models": CURRENT_POOL,
        "repeats": args.repeats,
        "planned_calls": len(jobs),
        "labels_reused": False,
        "source_performance_reused": False,
    }
    (output / "experiment.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
