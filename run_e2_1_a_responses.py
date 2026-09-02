#!/usr/bin/env python3
"""Resume-safe frozen E2.1-A response collection."""

import argparse
import asyncio
import json
import os
import re
import sys
import time
import httpx
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "e2_1_protocol"
PROJECT = ROOT / "autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main"
CONFIG = PROJECT / "configs/openclaw_multi_provider.yaml"
TASKS = DATA / "E2_1_A_FRESH_360_TASKS.jsonl"
RESPONSES = DATA / "E2_1_A_RESPONSES.jsonl"
EVENTS = DATA / "E2_1_A_EVENTS.jsonl"
SMOKE_RESPONSES = DATA / "E2_1_A_SMOKE_RESPONSES.jsonl"
SMOKE_EVENTS = DATA / "E2_1_A_SMOKE_EVENTS.jsonl"
MODELS = ("qwen-plus", "glm-5.2", "deepseek")
API_MODEL = {"qwen-plus": "qwen-plus", "glm-5.2": "glm-5.2", "deepseek": "deepseek-chat"}
REPEATS = range(3)
MAX_CALLS = 5000
MAX_COST = 375.0
PAGE_PATTERN = re.compile(r"(?m)^# Page (\d+)\s*$")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x] if path.exists() else []


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def document_pages(path: Path) -> dict[int, str]:
    text = path.read_text(encoding="utf-8")
    matches = list(PAGE_PATTERN.finditer(text))
    return {
        int(match.group(1)): text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        for i, match in enumerate(matches)
    }


def build_prompt(task: dict, page_cache: dict[Path, dict[int, str]]) -> str:
    path = ROOT / task["document_path"]
    pages = page_cache.setdefault(path, document_pages(path))
    blocks = []
    for evidence_id in task["candidate_page_ids"]:
        page = int(evidence_id.rsplit(":", 1)[1])
        blocks.append(f"\n<<<EVIDENCE_ID {evidence_id}>>>\n{pages[page]}\n<<<END_EVIDENCE_ID>>>")
    return (
        "Select every and only candidate evidence page needed to answer the financial question. "
        "Return exactly one JSON object and no prose: "
        '{"evidence_ids":["FinLongDocQA:COMPANY:YEAR:page:NUMBER"]}. '
        "Use only IDs shown below. Do not answer the question.\n\n"
        f"QUESTION:\n{task['question']}\n\nCANDIDATE PAGES:\n" + "".join(blocks)
    )


def parse_ids(answer: str, allowed: set[str]) -> tuple[list[str], bool]:
    text = str(answer).strip()
    try:
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
        obj = json.loads(text)
        ids = obj["evidence_ids"]
        if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
            raise ValueError("evidence_ids must be a string list")
        if any(x not in allowed for x in ids):
            raise ValueError("unknown evidence ID")
        return sorted(set(ids)), True
    except Exception:
        return [], False


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--smoke-task-index", type=int, default=0)
    parser.add_argument("--models", nargs="+", choices=MODELS, default=list(MODELS))
    args = parser.parse_args()
    if os.system(f"{sys.executable} {ROOT / 'e2_1_preflight.py'} >/dev/null") != 0:
        raise SystemExit("E2.1 preflight failed")
    load_env()
    sys.path.insert(0, str(PROJECT))
    from openclaw_router.config import OpenClawConfig
    from openclaw_router.server import LLMBackend
    import openclaw_router.server as backend_module
    from openclaw_router.server import _build_chat_url, clean_response, normalize_messages
    from scripts.run_finance_model_evaluation import answer_from_result, cost_usd, usage_from_result

    cfg = OpenClawConfig.from_yaml(str(CONFIG))
    for api_model in API_MODEL.values():
        model_config = cfg.llms[api_model]
        backend_module.MODEL_CONTEXT_LIMITS[model_config.model_id] = model_config.context_limit
    backend = LLMBackend(cfg)
    out = SMOKE_RESPONSES if args.smoke else RESPONSES
    event_out = SMOKE_EVENTS if args.smoke else EVENTS
    tasks = read_jsonl(TASKS)
    if args.smoke:
        tasks = tasks[args.smoke_task_index:args.smoke_task_index + 1]
    all_events = read_jsonl(EVENTS) + read_jsonl(SMOKE_EVENTS)
    spent = sum(float(x.get("cost_usd") or 0) for x in all_events)
    calls = len(all_events)
    previous = read_jsonl(out)
    complete = set()
    for x in previous:
        if not x.get("provider_success"):
            continue
        if x["model"] == "glm-5.2" and x.get("inference_profile") != "thinking_disabled":
            continue
        complete.add((x["task_id"], x["model"], int(x["repeat"])))
    page_cache = {}
    global_sem = asyncio.Semaphore(6)
    model_sem = {model: asyncio.Semaphore(1 if model == "glm-5.2" else 2) for model in MODELS}

    async def invoke(model: str, prompt: str):
        if model != "glm-5.2":
            return await backend.call(
                API_MODEL[model], [{"role": "user", "content": prompt}],
                max_tokens=128, temperature=0, stream=False,
            )
        llm = cfg.llms[API_MODEL[model]]
        api_key = cfg.get_api_key(llm.provider, llm)
        body = {
            "model": llm.model_id,
            "messages": normalize_messages([{"role": "user", "content": prompt}], llm.model_id),
            "max_tokens": 128,
            "temperature": 0,
            "thinking": {"type": "disabled"},
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _build_chat_url(llm.base_url, llm.chat_path),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                json=body, timeout=120.0,
            )
        response.raise_for_status()
        return clean_response(response.json())

    async def call_one(task: dict, model: str, repeat: int) -> None:
        nonlocal spent, calls
        key = (task["task_id"], model, repeat)
        if key in complete:
            return
        if calls >= MAX_CALLS or spent >= MAX_COST:
            raise RuntimeError(f"Hard cap reached before {key}: calls={calls}, cost={spent:.4f}")
        prompt = build_prompt(task, page_cache)
        started = time.perf_counter()
        answer, usage, error = "", {}, None
        calls += 1
        for attempt, delay in enumerate((0, 5, 15, 30)):
            if delay:
                await asyncio.sleep(delay)
            try:
                async with global_sem, model_sem[model]:
                    result = await invoke(model, prompt)
                answer = answer_from_result(result)
                usage = usage_from_result(result, prompt, answer)
                if not answer.strip():
                    raise RuntimeError("empty answer")
                error = None
                break
            except Exception as exc:
                error = str(exc)[:1000]
                transient = "429" in error or "disconnected" in error.lower() or "timeout" in error.lower()
                if not transient or attempt == 3:
                    break
        billed = float(cost_usd(cfg, API_MODEL[model], usage)) if usage else 0.0
        spent += billed
        event = {
            "task_id": task["task_id"], "model": model, "api_model": API_MODEL[model],
            "inference_profile": "thinking_disabled" if model == "glm-5.2" else "default_nonreasoning",
            "repeat": repeat, "success": error is None, "error": error, "usage": usage,
            "cost_usd": billed, "cumulative_cost_usd": spent, "cumulative_calls": calls,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with event_out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n"); handle.flush(); os.fsync(handle.fileno())
        if spent > MAX_COST:
            raise RuntimeError(f"Hard cost cap exceeded: {spent:.4f}")
        predicted, valid = parse_ids(answer, set(task["candidate_page_ids"])) if error is None else ([], False)
        row = {
            "task_id": task["task_id"], "model": model, "repeat": repeat,
            "inference_profile": "thinking_disabled" if model == "glm-5.2" else "default_nonreasoning",
            "predicted_evidence_ids": predicted, "format_valid": valid,
            "provider_success": error is None, "error": error,
            "raw_answer": answer,
            "cost_usd": billed, "timestamp": event["timestamp"],
        }
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n"); handle.flush(); os.fsync(handle.fileno())
        complete.add(key)

    repeats = (0,) if args.smoke else REPEATS
    units = [(task, repeat) for task in tasks for repeat in repeats]
    for start in range(0, len(units), 4):
        batch = units[start:start + 4]
        await asyncio.gather(*(
            call_one(task, model, repeat)
            for task, repeat in batch for model in args.models
        ))
        completed_units = min(start + len(batch), len(units))
        if completed_units % 30 < 4 or args.smoke:
            print(json.dumps({"task_repeat_units": completed_units, "calls": calls, "cost_usd": round(spent, 4)}), flush=True)
    print(json.dumps({"status": "SMOKE_COMPLETE" if args.smoke else "E2_1_A_COLLECTION_COMPLETE",
                      "calls": calls, "cost_usd": round(spent, 4)}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
