#!/usr/bin/env python3
"""Resume-safe dual judging for the frozen Gemini compatibility-training pilot."""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT = Path("/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main")
DATA = Path("/root/gemini_frar_pilot/five_model_v1")
TASKS = DATA / "gemini_training_pilot_tasks.jsonl"
RESPONSES = DATA / "gemini_training_pilot_responses.jsonl"
OUTPUT = DATA / "gemini_training_pilot_judges.jsonl"
EVENTS = DATA / "gemini_training_pilot_judge_events.jsonl"
CONFIG = PROJECT / "configs/openclaw_multi_provider.yaml"
JUDGES = ("deepseek-chat", "qwen-plus")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_env(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def judge_prompt(task: dict, response: str) -> str:
    return f'''你是独立金融合规回答评审员。只评估候选回答，不要重新回答问题。依据参考答案和给定上下文，评估准确性、完整性、推理、清晰度和安全性。严格输出一个JSON对象：{{"score":0到1,"dimensions":{{"accuracy":0到1,"completeness":0到1,"reasoning":0到1,"clarity":0到1,"safety":0到1}},"reason":"简短理由"}}。
问题：{task.get("question", "")}
参考答案：{task.get("gold_answer", "")}
上下文：{str(task.get("context", ""))[:12000]}
候选回答：{response}'''


def transient(error: str | None) -> bool:
    value = str(error or "").lower()
    return value.startswith(("429", "500", "502", "503", "504")) or any(
        token in value for token in ("timeout", "temporar", "connection", "disconnect")
    )


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

    tasks = {row["id"]: row for row in read_jsonl(TASKS)}
    responses = {
        (row["task_id"], int(row["repeat"])): row
        for row in read_jsonl(RESPONSES)
        if row.get("success") and str(row.get("answer") or "").strip()
    }
    latest = {}
    for row in read_jsonl(OUTPUT):
        latest[(row["task_id"], int(row["repeat"]), row["judge_model"])] = row
    done = {key for key, row in latest.items() if row.get("parsed") and row.get("score") is not None}
    expected = {(task_id, repeat, judge) for task_id, repeat in responses for judge in JUDGES}
    jobs = sorted(expected - done)
    print(json.dumps({"expected": len(expected), "done": len(done), "pending": len(jobs)}), flush=True)
    if not jobs:
        return

    config = OpenClawConfig.from_yaml(str(CONFIG))
    backend = LLMBackend(config)
    global_sem = asyncio.Semaphore(4)
    per_judge = {judge: asyncio.Semaphore(2) for judge in JUDGES}
    lock = asyncio.Lock()
    stats = {"ok": 0, "failed": 0, "retried": 0}
    started = time.perf_counter()

    async def one(key: tuple[str, int, str]) -> None:
        task_id, repeat, judge = key
        task = tasks[task_id]
        response = responses[(task_id, repeat)]
        prompt = judge_prompt(task, response["answer"])
        payload = None
        error = None
        usage = {}
        attempt = 0
        call_started = time.perf_counter()
        async with global_sem, per_judge[judge]:
            while attempt < 6:
                attempt += 1
                try:
                    result = await backend.call(
                        judge,
                        [{"role": "user", "content": prompt}],
                        max_tokens=512,
                        temperature=0,
                        stream=False,
                    )
                    raw = extract_message_text(result)
                    payload = parse_judge_payload(raw)
                    usage = usage_from_result(result, prompt, raw)
                    error = None if payload else "judge_json_parse_failed"
                except Exception as exc:
                    error = str(exc)[:800]
                if payload or not transient(error):
                    break
                stats["retried"] += 1
                await asyncio.sleep(min(35, 2**attempt + random.random()))

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
            "attempts": attempt,
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
            stats["ok" if payload else "failed"] += 1
            completed = stats["ok"] + stats["failed"]
            if not payload:
                with EVENTS.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            if completed % 20 == 0:
                print(json.dumps({
                    "completed": completed,
                    "pending_start": len(jobs),
                    **stats,
                    "elapsed_s": round(time.perf_counter() - started, 1),
                }), flush=True)

    await asyncio.gather(*(one(job) for job in jobs))
    print(json.dumps({"pending_start": len(jobs), **stats}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
