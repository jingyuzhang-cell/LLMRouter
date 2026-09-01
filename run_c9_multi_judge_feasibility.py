#!/usr/bin/env python3
"""Stage-0 feasibility for three replacement judges; never creates formal labels."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import string
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/root")
DATA = ROOT / "phase_c9_0"
PROJECT = ROOT / "autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main"
SEED = "20260831|C9_2_QUALITY_EVALUATION_V1"
JUDGES = ("doubao-seed-2.1-turbo", "qwen-max", "glm-4-flash")
TIMEOUT = 90
EVENTS = DATA / "C9_2_MULTI_JUDGE_FEASIBILITY_EVENTS.jsonl"
RESULT = DATA / "C9_2_MULTI_JUDGE_FEASIBILITY_RESULT.json"


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


for line in (ROOT / ".env").read_text().splitlines():
    value = line.strip()
    if value and not value.startswith("#") and "=" in value:
        key, secret = value.split("=", 1)
        os.environ.setdefault(key.strip(), secret.strip().strip('"').strip("'"))

sys.path.insert(0, str(PROJECT))
from openclaw_router.config import OpenClawConfig
from openclaw_router.judge_utils import extract_message_text
from openclaw_router.server import LLMBackend

tasks = {row["task_id"]: row for row in read_jsonl(DATA / "C9_DEV_TASKS.jsonl") if row.get("split") == "development_train"}
routes = {row["task_id"]: row for row in read_jsonl(DATA / "C9_2_EVALUATION_ROUTE_MANIFEST.jsonl")}
groups = defaultdict(list)
for row in read_jsonl(DATA / "C9_TRAIN_RESPONSES.jsonl"):
    if row.get("success") and routes[row["task_id"]]["evaluation_route"] == "independent_judge_0_4":
        groups[(row["task_id"], int(row["repeat"]))].append(row)
manifest = json.loads((DATA / "C9_2_REPLACEMENT_JUDGE_PROBE_MANIFEST.json").read_text())
selected = [(row["task_id"], int(row["repeat_id"])) for row in manifest["groups"][:3]]
assert len(selected) == 3 and len(groups) == 810


def prompt_for(key):
    tid, repeat = key
    answers = sorted(groups[key], key=lambda row: row["model"])
    labels = list(string.ascii_uppercase[: len(answers)])
    order = list(range(len(answers)))
    digest = hashlib.sha256(f"{SEED}|primary|{tid}|{repeat}".encode()).hexdigest()
    random.Random(int(digest, 16)).shuffle(order)
    mapping = {labels[index]: answers[index]["model"] for index in range(len(answers))}
    displayed = "\n\n".join(f"Answer {labels[index]}:\n{answers[index].get('answer', '')}" for index in order)
    task = tasks[tid]
    reference = str(task.get("reference_answer") or "").strip()
    refpart = f"\nReference answer:\n{reference}" if reference else "\nNo reference answer is available. Judge only whether each answer is correct and supported by the supplied context/table."
    prompt = f'''You are an independent evaluator. Score every blinded candidate answer independently; do not rank candidates or infer model identity. Use only the question, supplied context/table, and reference answer when present.
Rubric: 4=fully correct and supported; 3=mostly correct with only minor omission; 2=partly correct with a material omission or local error; 1=little correct content and main conclusion wrong; 0=incorrect, irrelevant, unsupported, or no valid answer.
Return only JSON exactly shaped as {{"scores":[{{"label":"A","score":4,"reason":"brief reason"}}]}}. Include every supplied label exactly once; score must be an integer 0..4.
Question:
{task.get("question", "")}
Context:
{task.get("context", "")}
Table:
{json.dumps(task.get("table") or [], ensure_ascii=False)}{refpart}

{displayed}'''
    return mapping, prompt


def parse(raw, mapping):
    try:
        match = re.search(r"\{.*\}", raw, re.S)
        obj = json.loads(match.group(0) if match else raw)
        rows = obj["scores"]
        got = {str(row["label"]): row for row in rows}
        if set(got) != set(mapping):
            return None
        if any(not isinstance(row.get("score"), int) or isinstance(row.get("score"), bool) or not 0 <= row["score"] <= 4 for row in rows):
            return None
        return {mapping[label]: int(got[label]["score"]) for label in sorted(mapping)}
    except Exception:
        return None


async def evaluate(backend, judge, key):
    mapping, prompt = prompt_for(key)
    start = time.perf_counter()
    parsed, error, error_type = None, None, None
    try:
        response = await asyncio.wait_for(
            backend.call(judge, [{"role": "user", "content": prompt}], max_tokens=1500, temperature=0, stream=False),
            timeout=TIMEOUT,
        )
        parsed = parse(extract_message_text(response), mapping)
        if parsed is None:
            raise ValueError("judge_json_schema_invalid")
    except Exception as exc:
        error, error_type = str(exc)[:1000], type(exc).__name__
    return {
        "group_id": f"{key[0]}:{key[1]}",
        "judge_model": judge,
        "success": parsed is not None,
        "scores_by_model": parsed,
        "error_type": error_type,
        "error": error,
        "latency_ms": round((time.perf_counter() - start) * 1000, 2),
        "formal_label": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def main():
    backend = LLMBackend(OpenClawConfig.from_yaml(str(PROJECT / "configs/openclaw_multi_provider.yaml")))
    completed = {(row["group_id"], row["judge_model"]): row for row in read_jsonl(EVENTS)} if EVENTS.exists() else {}
    for key in selected:
        for judge in JUDGES:
            event_key = (f"{key[0]}:{key[1]}", judge)
            if event_key in completed:
                continue
            row = await evaluate(backend, judge, key)
            with EVENTS.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush(); os.fsync(handle.fileno())
            completed[event_key] = row
            print(json.dumps({"group_id": row["group_id"], "judge": judge, "success": row["success"], "error_type": row["error_type"]}, ensure_ascii=False), flush=True)
    counts = Counter()
    for row in completed.values():
        if row["success"]:
            counts[row["judge_model"]] += 1
    passes = {judge: counts[judge] >= 2 for judge in JUDGES}
    result = {
        "status": "PASS_ADVANCE_TO_15_GROUP_CALIBRATION" if all(passes.values()) else "FAIL_STOP_BEFORE_FORMAL_LABELS",
        "groups": 3,
        "success_counts": {judge: counts[judge] for judge in JUDGES},
        "judge_pass": passes,
        "all_judges_pass": all(passes.values()),
        "formal_labels_created": 0,
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


asyncio.run(main())
