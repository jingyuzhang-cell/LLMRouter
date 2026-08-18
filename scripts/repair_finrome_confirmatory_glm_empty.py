#!/usr/bin/env python3
"""Repair truncated GLM answers in Fin-RoME confirmatory v3.

The original files are backed up once. Only latest successful records whose
answer is empty are recollected, using the same task/model/temperature and a
larger output allowance. Judge rows for repaired response keys are invalidated
only after every target has a non-empty replacement.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from openclaw_router.config import OpenClawConfig
from openclaw_router.server import LLMBackend
from scripts.run_finance_model_evaluation import call_one


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data/finance_router/finrome_300_confirmatory_v3"
CONFIG = ROOT / "configs/openclaw_multi_provider.yaml"
MAX_TOKENS = 2048
MODEL = "glm-5.2"


def rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl(path: Path, values: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def latest_responses(path: Path) -> dict[tuple[str, str, int], dict]:
    latest = {}
    for value in rows(path):
        latest[(value["task_id"], value["model"], value["repeat"])] = value
    return latest


def empty_success_keys(path: Path) -> set[tuple[str, str, int]]:
    return {
        key
        for key, value in latest_responses(path).items()
        if value.get("success") and not str(value.get("answer") or "").strip()
    }


def load_or_prepare(data: Path) -> tuple[dict, set[tuple[str, str, int]]]:
    response_path = data / "responses.jsonl"
    judge_path = data / "judges.jsonl"
    report_path = data / "glm_empty_repair_report.json"
    backup_dir = data / "pre_glm_empty_repair_backup"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        targets = {tuple(value) for value in report["target_keys"]}
        return report, targets

    targets = empty_success_keys(response_path)
    if not targets:
        raise SystemExit("No successful empty responses found; nothing to repair.")
    if any(key[1] != MODEL for key in targets):
        raise SystemExit("Refusing repair: successful empty responses include a non-GLM model.")
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(response_path, backup_dir / "responses.jsonl")
    shutil.copy2(judge_path, backup_dir / "judges.jsonl")
    report = {
        "repair": "GLM output-truncation data-quality repair",
        "status": "PREPARED",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(data),
        "model": MODEL,
        "original_max_tokens": 512,
        "repair_max_tokens": MAX_TOKENS,
        "target_count": len(targets),
        "target_keys": [list(key) for key in sorted(targets)],
        "backup_dir": str(backup_dir),
        "backup_sha256": {
            "responses.jsonl": sha256(backup_dir / "responses.jsonl"),
            "judges.jsonl": sha256(backup_dir / "judges.jsonl"),
        },
        "scope_contract": "tasks, models, temperature, scoring weights, and analysis methods unchanged",
        "human_review_contract": "all unresolved human review statuses remain PENDING",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report, targets


async def recollect(data: Path, targets: set[tuple[str, str, int]], workers: int, retries: int, max_tokens: int) -> dict:
    response_path = data / "responses.jsonl"
    latest = latest_responses(response_path)
    pending = [key for key in sorted(targets) if not (latest.get(key, {}).get("success") and str(latest[key].get("answer") or "").strip())]
    if not pending:
        return {"pending_start": 0, "ok": 0, "failed": 0, "retried": 0}
    if not os.getenv("ZHIPU_API_KEY"):
        raise SystemExit("Missing required API credential: ZHIPU_API_KEY")
    tasks = {value["id"]: value for value in rows(data / "tasks.jsonl")}
    config = OpenClawConfig.from_yaml(str(CONFIG))
    backend = LLMBackend(config)
    semaphore = asyncio.Semaphore(workers)
    lock = asyncio.Lock()
    stats = {"pending_start": len(pending), "ok": 0, "failed": 0, "retried": 0}

    async def one(key: tuple[str, str, int]) -> None:
        task_id, model, repeat = key
        result = None
        async with semaphore:
            for attempt in range(retries + 1):
                result = await call_one(
                    backend, config, tasks[task_id], model,
                    max_tokens=max_tokens, temperature=.2, dry_run=False,
                )
                answer = str(result.get("answer") or "").strip()
                if result.get("success") and answer:
                    break
                result["success"] = False
                result["error"] = result.get("error") or f"empty_response_after_{max_tokens}"
                if attempt < retries:
                    stats["retried"] += 1
        record = {
            "task_id": task_id,
            "dataset": tasks[task_id].get("dataset"),
            "task_type": tasks[task_id].get("task_type"),
            "risk_level": tasks[task_id].get("risk_level"),
            "model": model,
            "repeat": repeat,
            "attempts": attempt + 1,
            "repair": "glm_empty_512_to_2048",
            **result,
        }
        stats["ok" if record.get("success") else "failed"] += 1
        async with lock:
            with response_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            completed = stats["ok"] + stats["failed"]
            if completed % 20 == 0:
                print(json.dumps({"completed": completed, **stats}, ensure_ascii=False), flush=True)

    await asyncio.gather(*(one(key) for key in pending))
    return stats


def invalidate_judges(data: Path, targets: set[tuple[str, str, int]]) -> int:
    path = data / "judges.jsonl"
    values = rows(path)
    kept = [
        value for value in values
        if (value["task_id"], value["candidate_model"], value["repeat"]) not in targets
    ]
    removed = len(values) - len(kept)
    temporary = path.with_suffix(".jsonl.repair-tmp")
    write_jsonl(temporary, kept)
    os.replace(temporary, path)
    return removed


def finalize_report(data: Path, report: dict) -> None:
    matrix_report_path = data / "matrix_report.json"
    if not matrix_report_path.exists():
        raise SystemExit("matrix_report.json is not present; finish judge collection first.")
    matrix_report = json.loads(matrix_report_path.read_text(encoding="utf-8"))
    matrix_report["data_quality_repair"] = {
        "type": report["repair"],
        "target_count": report["target_count"],
        "max_tokens_change": [report["original_max_tokens"], report["repair_max_tokens"]],
        "max_tokens_escalations": report.get("max_tokens_escalations", []),
        "scope_contract": report["scope_contract"],
        "report": "glm_empty_repair_report.json",
    }
    matrix_report["human_review_contract"] = "all review_status values remain PENDING; no human conclusion is synthesized"
    matrix_report_path.write_text(json.dumps(matrix_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def main(args: argparse.Namespace) -> None:
    data = args.data_dir.resolve()
    report, targets = load_or_prepare(data)
    if args.dry_run:
        latest = latest_responses(data / "responses.jsonl")
        repaired = sum(bool(latest.get(key, {}).get("success") and str(latest[key].get("answer") or "").strip()) for key in targets)
        print(json.dumps({"targets": len(targets), "repaired": repaired, "pending": len(targets) - repaired, "status": report["status"]}, ensure_ascii=False))
        return
    
    if args.max_tokens != report["repair_max_tokens"]:
        escalation = {"max_tokens": args.max_tokens, "reason": "remaining responses exhausted 2048 tokens without final content"}
        if escalation not in report.setdefault("max_tokens_escalations", []):
            report["max_tokens_escalations"].append(escalation)
    stats = await recollect(data, targets, args.workers, args.retries, args.max_tokens)
    latest = latest_responses(data / "responses.jsonl")
    remaining = {
        key for key in targets
        if not (latest.get(key, {}).get("success") and str(latest[key].get("answer") or "").strip())
    }
    if remaining:
        report.update({"status": "RESPONSE_REPAIR_INCOMPLETE", "last_run": stats, "remaining_empty": len(remaining)})
    else:
        report.pop("remaining_empty", None)
        removed = invalidate_judges(data, targets) if report.get("status") != "RESPONSES_REPAIRED_JUDGES_INVALIDATED" else report.get("invalidated_judge_rows", 0)
        report.update({
            "status": "RESPONSES_REPAIRED_JUDGES_INVALIDATED",
            "responses_repaired": len(targets),
            "invalidated_judge_rows": removed,
            "last_run": stats,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    report_path = data / "glm_empty_repair_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("status", "target_count", "responses_repaired", "invalidated_judge_rows", "remaining_empty")}, ensure_ascii=False, indent=2))
    if report["status"] == "RESPONSES_REPAIRED_JUDGES_INVALIDATED":
        print("Next: PYTHONPATH=. bash scripts/run_finrome_confirmatory_v3.sh --execute")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        report = json.loads((args.data_dir / "glm_empty_repair_report.json").read_text(encoding="utf-8"))
        finalize_report(args.data_dir, report)
        print(json.dumps({"status": "MATRIX_REPORT_ANNOTATED", "matrix_report": str(args.data_dir / "matrix_report.json")}, ensure_ascii=False))
    else:
        asyncio.run(main(args))
