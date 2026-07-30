"""Collect resumable repeated evaluations for high-regret MLP routing pairs."""

import argparse
import ast
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from llmrouter.data.api_calling_evaluation import eval_perf
from llmrouter.utils import call_api, generate_task_query


MODEL_API_NAMES = {
    "qwen2.5-7b-instruct": "qwen/qwen2.5-7b-instruct",
    "llama-3.1-8b-instruct": "meta/llama-3.1-8b-instruct",
    "mistral-small-4-119b-2603": "mistralai/mistral-small-4-119b-2603",
    "gemma-2-9b-it": "google/gemma-2-9b-it",
    "llama-3.2-3b-instruct": "meta/llama-3.2-3b-instruct",
    "llama3-chatqa-1.5-8b": "nvidia/llama3-chatqa-1.5-8b",
    "llama3-chatqa-1.5-70b": "nvidia/llama3-chatqa-1.5-70b",
    "llama-3.1-nemotron-51b-instruct": "nvidia/llama-3.1-nemotron-51b-instruct",
    "llama-3.3-nemotron-super-49b-v1": "nvidia/llama-3.3-nemotron-super-49b-v1",
    "llama-3.3-70b-instruct": "meta/llama-3.3-70b-instruct",
    "qwen3-next-80b-a3b-instruct": "qwen/qwen3-next-80b-a3b-instruct",
}
WRITE_LOCK = threading.Lock()


def parse_value(value):
    if not isinstance(value, str):
        return value
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def prompt_for(row):
    sample = row.to_dict()
    sample["query"] = row.name
    choices = parse_value(sample.get("choices"))
    if isinstance(choices, dict) and "labels" in choices and "label" not in choices:
        choices["label"] = choices.pop("labels")
    sample["choices"] = choices
    try:
        return generate_task_query(row.task_name, sample)
    except ValueError:
        return {"system": None, "user": str(row.name)}


def key(record):
    return (record["query"], record["model_name"], int(record["repeat_index"]))


def collect(job, endpoint, output):
    request = {
        "api_endpoint": endpoint,
        "service": "NVIDIA",
        "query": job["user_prompt"],
        "system_prompt": job["system_prompt"],
        "model_name": job["model_name"],
        "api_name": MODEL_API_NAMES[job["model_name"]],
    }
    result = None
    for attempt in range(1, 4):
        result = call_api(request, max_tokens=1024, temperature=0.01, timeout=90, max_retries=1)
        if not result.get("error"):
            break
    record = {**job, "attempt_count": attempt, **{name: result.get(name) for name in (
        "response", "token_num", "prompt_tokens", "completion_tokens", "response_time", "error"
    )}}
    if not record.get("error"):
        try:
            record["performance"] = eval_perf(
                job["metric"], record["response"], job["ground_truth"], job["task_name"], job.get("task_id")
            )
            record["success"] = True
        except Exception as exc:
            record["performance"] = None
            record["success"] = False
            record["scoring_error"] = str(exc)
    else:
        record["performance"] = None
        record["success"] = False
    with WRITE_LOCK, output.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="run_logs/mlprouter_regret_analysis/reevaluation_manifest.jsonl")
    parser.add_argument("--data", default="data/example_data/routing_data/grouped/default_routing_test_data.jsonl")
    parser.add_argument("--output", default="run_logs/mlprouter_regret_analysis/reevaluation_results.jsonl")
    parser.add_argument("--endpoint", default="https://integrate.api.nvidia.com/v1")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--models", help="comma-separated canonical model names to run")
    args = parser.parse_args()

    manifest = pd.read_json(args.manifest, lines=True)
    data = pd.read_json(args.data, lines=True).drop_duplicates("query").set_index("query")
    jobs = []
    for row in manifest.itertuples(index=False):
        source = data.loc[row.query]
        prompt = prompt_for(source)
        repeat_indices = [int(row.repeat_index)] if hasattr(row, "repeat_index") else range(1, int(row.requested_repeats) + 1)
        for repeat in repeat_indices:
            jobs.append({
                "query": row.query, "task_name": source.task_name, "model_name": row.model_name,
                "repeat_index": repeat, "metric": source.metric, "ground_truth": source.ground_truth,
                "task_id": None if pd.isna(source.task_id) else source.task_id,
                "system_prompt": prompt.get("system"), "user_prompt": prompt["user"],
            })
    output = Path(args.output)
    completed = set()
    if output.exists():
        completed = {key(row) for row in pd.read_json(output, lines=True).to_dict("records") if row.get("success")}
    allowed = set(args.models.split(",")) if args.models else None
    jobs = [job for job in jobs if key(job) not in completed and (allowed is None or job["model_name"] in allowed)]
    if args.limit is not None:
        jobs = jobs[:args.limit]
    summary = {"total_planned": len(jobs) + len(completed), "already_completed": len(completed), "remaining_selected": len(jobs)}
    if args.dry_run:
        summary["models"] = pd.Series([job["model_name"] for job in jobs]).value_counts().to_dict()
        summary["api_keys_configured"] = bool(os.environ.get("API_KEYS"))
        print(json.dumps(summary, indent=2))
        return
    if not os.environ.get("API_KEYS"):
        raise SystemExit("API_KEYS is not configured; no external calls were made.")
    successes = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(collect, job, args.endpoint, output) for job in jobs]
        for future in as_completed(futures):
            successes += int(future.result()["success"])
    print(json.dumps({**summary, "successes": successes, "failures": len(jobs) - successes}, indent=2))


if __name__ == "__main__":
    main()
