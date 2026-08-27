#!/usr/bin/env python3
"""One-call-per-key dual judging for the frozen target-support expansion."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path("/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main")
DATA = Path("/root/target_support_expansion_v1")
TASKS = DATA / "TARGET_SUPPORT_EXPANSION_TASKS.jsonl"
RESPONSES = DATA / "gemini_responses.jsonl"
OUTPUT = DATA / "gemini_compliance_judges.jsonl"
EVENTS = DATA / "gemini_compliance_judge_events.jsonl"
CONFIG = PROJECT / "configs/openclaw_multi_provider.yaml"
JUDGES = ("deepseek-chat", "qwen-plus")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_env(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def prompt_for(task: dict, response: str) -> str:
    return f'''你是独立金融合规回答评审员。只评估候选回答，不要重新回答问题。依据参考答案和给定上下文，评估准确性、完整性、推理、清晰度和安全性。严格输出一个JSON对象：{{"score":0到1,"dimensions":{{"accuracy":0到1,"completeness":0到1,"reasoning":0到1,"clarity":0到1,"safety":0到1}},"reason":"简短理由"}}。
问题：{task.get("question", "")}
参考答案：{task.get("gold_answer", "")}
上下文：{str(task.get("context", ""))[:12000]}
候选回答：{response}'''


async def main() -> None:
    load_env(Path("/root/.env"))
    missing = [key for key in ("DEEPSEEK_API_KEY", "QWEN_API_KEY") if not os.getenv(key)]
    if missing:
        raise SystemExit("Missing credentials: " + ", ".join(missing))
    sys.path.insert(0, str(PROJECT))
    from openclaw_router.config import OpenClawConfig
    from openclaw_router.judge_utils import extract_message_text, parse_judge_payload
    from openclaw_router.server import LLMBackend
    from scripts.run_finance_model_evaluation import cost_usd, usage_from_result

    tasks = {row["id"]: row for row in read_jsonl(TASKS) if row.get("dataset") == "ObliQA" and row.get("task_type") == "financial_audit_compliance_qa"}
    responses = {
        (row["task_id"], int(row["repeat"])): row
        for row in read_jsonl(RESPONSES)
        if row.get("task_id") in tasks and row.get("success") and str(row.get("answer") or "").strip()
    }
    expected = {(task_id, repeat, judge) for task_id, repeat in responses for judge in JUDGES}
    if len(tasks) != 100 or len(responses) != 300 or len(expected) != 600:
        raise SystemExit(json.dumps({"error": "input cardinality mismatch", "tasks": len(tasks), "responses": len(responses), "expected": len(expected)}))
    previous = read_jsonl(OUTPUT)
    attempted = {(row["task_id"], int(row["repeat"]), row["judge_model"]) for row in previous}
    jobs = sorted(expected - attempted)
    if len(previous) + len(jobs) > 600:
        raise SystemExit("Paid-call cap would be exceeded")
    print(json.dumps({"expected": 600, "already_attempted": len(attempted), "pending": len(jobs)}), flush=True)

    config = OpenClawConfig.from_yaml(str(CONFIG))
    backend = LLMBackend(config)
    global_sem = asyncio.Semaphore(4)
    per_judge = {judge: asyncio.Semaphore(2) for judge in JUDGES}
    lock = asyncio.Lock()
    stats = {"parsed": 0, "failed": 0, "deepseek_calls": 0, "qwen_calls": 0}
    started = time.perf_counter()

    async def one(key: tuple[str, int, str]) -> None:
        task_id, repeat, judge = key
        task = tasks[task_id]
        response = responses[(task_id, repeat)]
        prompt = prompt_for(task, response["answer"])
        payload = None
        raw = ""
        usage = {}
        error = None
        call_started = time.perf_counter()
        try:
            async with global_sem, per_judge[judge]:
                result = await backend.call(
                    judge,
                    [{"role": "user", "content": prompt}],
                    max_tokens=1024 if judge == "qwen-plus" else 512,
                    temperature=0,
                    stream=False,
                )
            raw = extract_message_text(result)
            payload = parse_judge_payload(raw)
            usage = usage_from_result(result, prompt, raw)
            error = None if payload else "judge_json_parse_failed"
        except Exception as exc:
            error = str(exc)[:800]
        record = {
            "task_id": task_id,
            "candidate_model": "gemini-2.5-flash",
            "repeat": repeat,
            "judge_model": judge,
            "parsed": bool(payload),
            "score": payload.get("score") if payload else None,
            "dimensions": payload.get("dimensions") if payload else {},
            "reason": payload.get("reason") if payload else "",
            "error": error,
            "attempts": 1,
            "usage": usage,
            "cost_usd": cost_usd(config, judge, usage) if usage else 0.0,
            "latency_ms": round((time.perf_counter() - call_started) * 1000, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        async with lock:
            with OUTPUT.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            stats["parsed" if payload else "failed"] += 1
            stats["deepseek_calls" if judge == "deepseek-chat" else "qwen_calls"] += 1
            completed = stats["parsed"] + stats["failed"]
            if not payload:
                with EVENTS.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            if completed % 20 == 0:
                print(json.dumps({"completed": completed, **stats, "elapsed_s": round(time.perf_counter() - started, 1)}), flush=True)

    await asyncio.gather(*(one(job) for job in jobs))
    print(json.dumps({"new_calls": len(jobs), **stats}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
