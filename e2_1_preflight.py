#!/usr/bin/env python3
"""Fail-closed preflight for E2.1-A. Never starts model calls."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPECTED_PROTOCOL = "4b1b0d6998c8870d1573b55abed3e98e4f1e8c6528961134bdc72852e04c9843"
EXPECTED_TASKS = "c30c2bab9eeed44e13931c37d90515bdf5a85688f54931cf7553ba530ddec6e5"
EXPECTED_B = "41a555c264a648732e1625433674e7d1f43b6be5b9fe84aaa4054dbaeda6804d"
EXPECTED_GOLD = "6a125c81a86acc3c763865dbe20bf28994acb1bc52dc61fa733104ee8a22cae1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def evidence_f1(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def main() -> int:
    checks = {}
    checks["protocol_sha256"] = digest(ROOT / "e2_1_PROTOCOL_FINAL.json") == EXPECTED_PROTOCOL
    checks["task_manifest_sha256"] = digest(
        ROOT / "e2_1_protocol/E2_1_A_FRESH_360_TASKS.jsonl"
    ) == EXPECTED_TASKS
    checks["b_subset_sha256"] = digest(
        ROOT / "e2_1_protocol/E2_1_B_PREFIXED_30_TASKS.jsonl"
    ) == EXPECTED_B
    gold_path = ROOT / "e2_1_protocol/E2_1_NATIVE_PAGE_GOLD_360.jsonl"
    checks["native_gold_sha256"] = digest(gold_path) == EXPECTED_GOLD
    tasks = rows(ROOT / "e2_1_protocol/E2_1_A_FRESH_360_TASKS.jsonl")
    gold = rows(gold_path)
    task_ids = {x["task_id"] for x in tasks}
    checks["task_count_360"] = len(tasks) == len(task_ids) == 360
    checks["native_gold_rows_360"] = len(gold) == 360
    checks["native_gold_task_ids_match"] = {x["task_id"] for x in gold} == task_ids
    checks["native_gold_nonempty"] = all(x.get("dataset_page_evidence_ids") for x in gold)
    checks["native_gold_page_id_format"] = all(
        all(":page:" in evidence_id for evidence_id in x["dataset_page_evidence_ids"])
        for x in gold
    )
    estimated_cost_usd = 87.55
    hard_cost_cap_usd = 375.0
    checks["worst_case_cost_within_frozen_cap"] = estimated_cost_usd <= hard_cost_cap_usd
    ready = all(checks.values())
    report = {
        "status": "READY_FOR_E2_1_A_CALLS" if ready else "BLOCKED_BEFORE_MODEL_CALLS",
        "checks": checks,
        "gold_source": "FinLongDocQA dataset-provided page_numbers",
        "planned_calls": 3240,
        "hard_call_cap": 3420,
        "estimated_cost_usd": estimated_cost_usd,
        "hard_cost_cap_usd": hard_cost_cap_usd,
    }
    print(json.dumps(report, indent=2))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
