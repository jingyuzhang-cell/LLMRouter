"""Run finance QA tasks against configured LLMs and fill model_results.

This script reads the standardized finance router JSONL file, calls each selected
model, records answer/usage/latency/cost/success, and writes an enriched JSONL.

Use --dry-run to validate prompts and output format without external API calls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openclaw_router.config import OpenClawConfig
from openclaw_router.server import LLMBackend

DEFAULT_CONFIG = ROOT / "configs" / "openclaw_multi_provider.yaml"
DEFAULT_INPUT = ROOT / "data" / "finance_router" / "standardized" / "finance_router_tasks.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "finance_router" / "standardized" / "finance_router_tasks.with_results.jsonl"


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def usage_from_result(result: Dict[str, Any], prompt: str, answer: str) -> Dict[str, int]:
    usage = result.get("usage") if isinstance(result, dict) else {}
    if not isinstance(usage, dict):
        usage = {}
    prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or estimate_tokens(prompt))
    completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or estimate_tokens(answer))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
    }


def cost_usd(config: OpenClawConfig, model_name: str, usage: Dict[str, int]) -> float:
    llm = config.llms.get(model_name)
    if not llm:
        return 0.0
    return round(
        (
            usage["prompt_tokens"] * float(llm.input_price or 0.0)
            + usage["completion_tokens"] * float(llm.output_price or 0.0)
        )
        / 1_000_000,
        10,
    )


def build_prompt(task: Dict[str, Any]) -> str:
    table = task.get("table") or []
    table_text = json.dumps(table, ensure_ascii=False) if table else "无"
    evidence = task.get("evidence") or []
    evidence_text = json.dumps(evidence, ensure_ascii=False) if evidence else "无"
    return (
        "你是金融问答与审计合规分析助手。请严格基于给定问题、上下文、表格和证据回答。\n"
        "如果需要计算，请写出关键计算过程；如果证据不足，请说明需要补充哪些证据。\n\n"
        f"任务类型：{task.get('task_type', 'financial_qa')}\n"
        f"风险等级：{task.get('risk_level', 'medium')}\n"
        f"问题：{task.get('question', '')}\n\n"
        f"上下文：{task.get('context', '')}\n\n"
        f"表格：{table_text}\n\n"
        f"证据：{evidence_text}\n\n"
        "请给出简洁、准确、可验证的回答。"
    )


def answer_from_result(result: Dict[str, Any]) -> str:
    try:
        return str(result["choices"][0]["message"].get("content") or "")
    except Exception:
        return ""


async def call_one(
    backend: LLMBackend,
    config: OpenClawConfig,
    task: Dict[str, Any],
    model_name: str,
    *,
    max_tokens: int,
    temperature: float,
    dry_run: bool,
) -> Dict[str, Any]:
    prompt = build_prompt(task)
    if dry_run:
        answer = f"[dry-run:{model_name}] {task.get('gold_answer') or '示例回答'}"
        usage = {
            "prompt_tokens": estimate_tokens(prompt),
            "completion_tokens": estimate_tokens(answer),
            "total_tokens": estimate_tokens(prompt) + estimate_tokens(answer),
        }
        return {
            "answer": answer,
            "success": True,
            "latency_ms": 0.0,
            "usage": usage,
            "cost_usd": cost_usd(config, model_name, usage),
            "error": None,
            "dry_run": True,
        }

    started = time.perf_counter()
    try:
        result = await backend.call(
            model_name,
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        answer = answer_from_result(result)
        usage = usage_from_result(result, prompt, answer)
        return {
            "answer": answer,
            "success": True,
            "latency_ms": latency_ms,
            "usage": usage,
            "cost_usd": cost_usd(config, model_name, usage),
            "error": None,
            "dry_run": False,
        }
    except Exception as error:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "answer": "",
            "success": False,
            "latency_ms": latency_ms,
            "usage": {"prompt_tokens": estimate_tokens(prompt), "completion_tokens": 0, "total_tokens": estimate_tokens(prompt)},
            "cost_usd": 0.0,
            "error": str(error)[:500],
            "dry_run": False,
        }


async def run(args: argparse.Namespace) -> None:
    config = OpenClawConfig.from_yaml(str(args.config))
    backend = LLMBackend(config)
    tasks = read_jsonl(args.input)
    if args.limit:
        tasks = tasks[: max(1, int(args.limit))]
    models = args.models or [
        name for name, llm in config.llms.items()
        if getattr(llm, "auto_routable", True)
    ]
    if not models:
        raise SystemExit("No models selected.")

    output_records: List[Dict[str, Any]] = []
    for index, task in enumerate(tasks, start=1):
        record = dict(task)
        results = dict(record.get("model_results") or {})
        print(f"[{index}/{len(tasks)}] {record.get('id')} -> {', '.join(models)}")
        for model_name in models:
            if model_name not in config.llms:
                print(f"  - skip unknown model: {model_name}")
                continue
            if model_name in results and not args.force:
                print(f"  - keep existing result: {model_name}")
                continue
            result = await call_one(
                backend,
                config,
                record,
                model_name,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                dry_run=args.dry_run,
            )
            results[model_name] = result
            status = "ok" if result.get("success") else "failed"
            print(f"  - {model_name}: {status}, {result.get('latency_ms')} ms")
            if args.sleep > 0 and not args.dry_run:
                await asyncio.sleep(args.sleep)
        record["model_results"] = results
        output_records.append(record)

    write_jsonl(args.output, output_records)
    print(f"Wrote evaluated records to {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run finance model evaluation.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
