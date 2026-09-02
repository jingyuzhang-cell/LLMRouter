#!/usr/bin/env python3
"""Resume-safe, budget-capped candidate execution for E2 Stage 1."""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/root")
OUT = ROOT / "e2_targeted_decomposition"
PROJECT = ROOT / "autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main"
CONFIG = PROJECT / "configs/openclaw_multi_provider.yaml"
MODELS = ("qwen-plus", "glm-5.2")
REPEATS = (0, 1)
MAX_TOTAL_COST_USD = 5.0
MAX_EXTERNAL_CALLS = 520


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()] if Path(path).exists() else []


def load_env():
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def prompt(node, task, upstream):
    declared = []
    if "source_question" in node["declared_inputs"]:
        declared.append("SOURCE QUESTION:\n" + task["source_question"])
    if "source_context" in node["declared_inputs"]:
        declared.append("SOURCE CONTEXT:\n" + task["source_context"])
    if "source_table" in node["declared_inputs"]:
        table = task["source_table"]
        declared.append("SOURCE TABLE:\n" + "\n".join(" | ".join(map(str, row)) for row in table if isinstance(row, list)))
    for dependency in node["depends_on"]:
        declared.append(f"UPSTREAM {dependency}:\n{upstream[dependency]}")
    return (
        "You are executing one frozen atomic node in a financial QA DAG. Follow only the node instruction.\n\n"
        f"NODE TYPE: {node['node_type']}\nINSTRUCTION: {node['instruction']}\n"
        f"EXPECTED OUTPUT: {node['expected_output_type']}\nVERIFICATION: {node['verification_rule']}\n\n"
        + "\n\n".join(declared)
    )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Run only n1 of the first task once per provider")
    args = parser.parse_args()
    load_env()
    sys.path.insert(0, str(PROJECT))
    from openclaw_router.config import OpenClawConfig
    from openclaw_router.server import LLMBackend
    from scripts.run_finance_model_evaluation import answer_from_result, cost_usd, usage_from_result

    cfg = OpenClawConfig.from_yaml(str(CONFIG))
    backend = LLMBackend(cfg)
    tasks = {x["task_id"]: x for x in read_jsonl(OUT / "E2_STAGE1_30.jsonl")}
    nodes = read_jsonl(OUT / "E2_SUBTASK_MANIFEST.jsonl")
    by_task = {tid: sorted([x for x in nodes if x["task_id"] == tid], key=lambda x: x["node_id"]) for tid in tasks}
    response_path = OUT / ("E2_PROVIDER_SMOKE.jsonl" if args.smoke else "E2_STAGE1_RESPONSES.jsonl")
    event_path = OUT / ("E2_PROVIDER_SMOKE_EVENTS.jsonl" if args.smoke else "E2_STAGE1_RESPONSE_EVENTS.jsonl")
    previous = read_jsonl(response_path)
    prior_events = read_jsonl(event_path)
    completed = {(x["task_id"], x["model"], int(x["repeat"]), x["node_id"]) for x in previous if x.get("success")}
    spent = sum(float(x.get("total_billed_cost_usd") or 0) for x in prior_events)
    smoke_events = read_jsonl(OUT / "E2_PROVIDER_SMOKE_EVENTS.jsonl")
    total_external_calls = len(prior_events) + len(smoke_events)
    if spent >= MAX_TOTAL_COST_USD:
        raise SystemExit(f"Budget already exhausted: ${spent:.4f}")

    task_ids = sorted(tasks)
    if args.smoke:
        task_ids = task_ids[:1]
    jobs_done = 0
    for tid in task_ids:
        for model in MODELS:
            repeats = (0,) if args.smoke else REPEATS
            for repeat in repeats:
                upstream = {}
                task_nodes = by_task[tid][:1] if args.smoke else by_task[tid]
                for node in task_nodes:
                    key = (tid, model, repeat, node["node_id"])
                    prior = next((x for x in previous if (x["task_id"], x["model"], int(x["repeat"]), x["node_id"]) == key and x.get("success")), None)
                    if prior:
                        upstream[node["node_id"]] = prior["answer"]
                        continue
                    text = prompt(node, tasks[tid], upstream)
                    answer, final_error, attempts, total_cost = "", None, [], 0.0
                    prior_attempts = sum(1 for x in prior_events if (x["task_id"], x["model"], int(x["repeat"]), x["node_id"]) == key)
                    if prior_attempts >= 4:
                        raise RuntimeError(f"Per-key attempt cap exhausted for {key}: {prior_attempts}")
                    for attempt in range(prior_attempts + 1, min(4, prior_attempts + 2) + 1):
                        started = time.perf_counter()
                        result = None
                        usage = {}
                        error = None
                        if total_external_calls >= MAX_EXTERNAL_CALLS:
                            raise RuntimeError(f"Hard external-call cap exhausted: {total_external_calls}")
                        total_external_calls += 1
                        try:
                            max_tokens = 1536 if model == "glm-5.2" else 384
                            result = await backend.call(model, [{"role": "user", "content": text}], max_tokens=max_tokens, temperature=0, stream=False)
                            answer = answer_from_result(result)
                            usage = usage_from_result(result, text, answer)
                            if not answer.strip():
                                raise RuntimeError("empty answer")
                        except Exception as exc:
                            error = str(exc)[:1000]
                        billed = float(cost_usd(cfg, model, usage)) if usage else 0.0
                        total_cost += billed
                        event = {"task_id": tid, "model": model, "repeat": repeat, "node_id": node["node_id"],
                                 "attempt": attempt, "success": error is None, "error": error,
                                 "service_latency_ms": round((time.perf_counter() - started) * 1000, 2),
                                 "usage": usage, "total_billed_cost_usd": billed,
                                 "timestamp": datetime.now(timezone.utc).isoformat()}
                        with event_path.open("a", encoding="utf-8") as f:
                            f.write(json.dumps(event, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
                        attempts.append(event); spent += billed
                        if spent > MAX_TOTAL_COST_USD:
                            raise RuntimeError(f"Hard budget cap exceeded: ${spent:.4f}")
                        if error is None:
                            final_error = None
                            break
                        final_error = error
                        await asyncio.sleep(2 * attempt)
                    row = {"task_id": tid, "selection_stratum": tasks[tid]["selection_stratum"], "model": model,
                           "repeat": repeat, "node_id": node["node_id"], "node_type": node["node_type"],
                           "answer": answer, "success": final_error is None, "error": final_error,
                           "attempts": len(attempts), "total_billed_cost_usd": total_cost,
                           "timestamp": datetime.now(timezone.utc).isoformat()}
                    with response_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
                    if final_error is not None:
                        raise RuntimeError(f"Provider failure for {key}: {final_error}")
                    upstream[node["node_id"]] = answer
                    jobs_done += 1
                    if jobs_done % 20 == 0:
                        print(json.dumps({"new_nodes": jobs_done, "spent_usd": round(spent, 6), "external_calls": total_external_calls}), flush=True)
    print(json.dumps({"status": "SMOKE_PASS" if args.smoke else "STAGE1_RESPONSES_COMPLETE",
                      "new_nodes": jobs_done, "spent_usd": round(spent, 6), "external_calls": total_external_calls}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
