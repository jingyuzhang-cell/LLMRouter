#!/usr/bin/env python3
"""Run a resumable grounded pilot on the count questions in the sealed KQA subset."""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
BASELINES = ROOT / "data/kqapro/KQAPro_Baselines"
sys.path[:0] = [str(ROOT / "scripts"), str(BASELINES)]

from Program.executor_rule import RuleExecutor
from generate_kqa_multi_model_routing import load_env
from run_kqa_reasoning_pilot import complete, label, mapper

VAL = BASELINES / "dataset/val.json"
KB = BASELINES / "dataset/kb.json"
PILOT = ROOT / "data/kqapro/reasoning_pilot_v1"
LOCK = Lock()


def execute_raw(executor: RuleExecutor, program: list[dict]):
    """Execute dataset-native functions using their explicit dependencies."""
    memory = []
    for step in program:
        dependencies = [memory[i] for i in step["dependencies"]]
        memory.append(
            getattr(executor, step["function"])(dependencies, step["inputs"])
        )
    return memory[-1]


def entity_name(executor: RuleExecutor, entity_id: str) -> str:
    info = executor.entities.get(entity_id) or executor.concepts.get(entity_id) or {}
    return str(info.get("name", entity_id))


def grounded_prompt(item: dict, entity_ids: list[str]) -> str:
    options = "\n".join(f"{chr(65 + i)}. {x}" for i, x in enumerate(item["choices"]))
    # One record per line preserves the executor's Count semantics, including duplicates.
    records = "\n".join(f"- record {i + 1}: {name}" for i, name in enumerate(entity_ids))
    return (
        "Answer using only the retrieved knowledge-base records below. Each bullet is "
        "one result record; count the bullets exactly, including repeated names if any. "
        "Do not use outside knowledge. End with a separate line exactly FINAL: <A-J>.\n\n"
        f"Question: {item['question']}\n\nRetrieved records:\n{records or '(no records)'}\n\n"
        f"Options:\n{options}"
    )


def run_one(env: dict, executor: RuleExecutor, item: dict, source_index: int) -> dict:
    prefix = execute_raw(executor, item["program"][:-1])
    entity_ids = list(prefix[0])
    names = [entity_name(executor, entity_id) for entity_id in entity_ids]
    prompt = grounded_prompt(item, names)
    messages = [
        {"role": "system", "content": "Use the supplied records exactly and return the matching option."},
        {"role": "user", "content": prompt},
    ]
    started = time.time()
    result = complete(env, "deepseek", messages, 0.0, 256)
    predicted = label(result.get("text"))
    mapped = None
    if result["status"] == "ok" and predicted is None:
        mapped = mapper(env, "deepseek", item, result["text"] or "")
        predicted = mapped.get("label")
    elapsed = time.time() - started
    gold = chr(65 + item["choices"].index(item["answer"]))
    status = "ok" if predicted else result["status"] if result["status"] != "ok" else "invalid_response"
    input_tokens = int(result.get("input_tokens", 0)) + int((mapped or {}).get("input_tokens", 0))
    output_tokens = int(result.get("output_tokens", 0)) + int((mapped or {}).get("output_tokens", 0))
    return {
        "task_id": f"kqapro-val-{source_index:05d}",
        "source_index": source_index,
        "query": item["question"],
        "ground_truth": item["answer"],
        "choices": {"text": item["choices"], "labels": list("ABCDEFGHIJ")},
        "question_type": "count",
        "program_operations": [step["function"] for step in item["program"]],
        "model": "deepseek",
        "variant": "count_grounded_gold_program",
        "retrieved_record_count_audit": len(entity_ids),
        "response": result.get("text"),
        "predicted_label": predicted,
        "correct": float(predicted == gold),
        "performance": float(predicted == gold),
        "status": status,
        "response_time": elapsed,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost": 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=PILOT / "manifest.json")
    parser.add_argument("--output", type=Path, default=PILOT / "deepseek__count_grounded_gold_program.jsonl")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()

    data = json.loads(VAL.read_text())
    selected = set(json.loads(args.manifest.read_text())["task_ids"])
    jobs = [
        (idx, item)
        for idx, item in enumerate(data)
        if f"kqapro-val-{idx:05d}" in selected and item["program"][-1]["function"] == "Count"
    ]
    executor = RuleExecutor({"function_idx_to_token": {}, "word_idx_to_token": {}}, str(KB))
    for idx, item in jobs:
        prefix = execute_raw(executor, item["program"][:-1])
        full = execute_raw(executor, item["program"])
        if int(full) != len(prefix[0]) or str(full) != str(item["answer"]):
            raise SystemExit(f"executor/gold mismatch for kqapro-val-{idx:05d}")
    print(json.dumps({"selected_count_tasks": len(jobs), "executor_validation": "passed"}), flush=True)
    if args.prepare_only:
        return

    done = set()
    if args.output.exists():
        for line in args.output.open():
            try:
                done.add(json.loads(line)["task_id"])
            except Exception:
                pass
    pending = [(idx, item) for idx, item in jobs if f"kqapro-val-{idx:05d}" not in done]
    print(f"pending grounded tasks: {len(pending)}", flush=True)
    env = load_env(["deepseek"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a") as handle, ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(run_one, env, executor, item, idx): idx for idx, item in pending}
        for n, future in enumerate(as_completed(futures), 1):
            row = future.result()
            with LOCK:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
            if n % 20 == 0 or n == len(pending):
                print(f"completed this run: {n}/{len(pending)}", flush=True)


if __name__ == "__main__":
    main()
