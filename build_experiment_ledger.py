#!/usr/bin/env python3
"""Build a fail-closed, machine-readable ledger for the paper experiments.

This script is read-only with respect to raw experimental artifacts.  Its only
outputs are EXPERIMENT_LEDGER.json and EXPERIMENT_LEDGER.md at repository root.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
E21 = ROOT / "e2_1_protocol"
MODELS = ("qwen-plus", "glm-5.2", "deepseek")
REPEATS = range(3)


def json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def key(row: dict[str, Any]) -> tuple[str, str, int]:
    return row["task_id"], row["model"], int(row["repeat"])


def eligible_success(row: dict[str, Any]) -> bool:
    if not row.get("provider_success"):
        return False
    return row.get("model") != "glm-5.2" or row.get("inference_profile") == "thinking_disabled"


def best_record(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose deterministically without allowing a later failed retry to erase success."""
    return max(
        enumerate(rows),
        key=lambda item: (
            eligible_success(item[1]),
            bool(item[1].get("format_valid")),
            item[1].get("timestamp", ""),
            item[0],
        ),
    )[1]


def e21_a_entry() -> dict[str, Any]:
    task_path = E21 / "E2_1_A_FRESH_360_TASKS.jsonl"
    response_path = E21 / "E2_1_A_RESPONSES.jsonl"
    event_path = E21 / "E2_1_A_EVENTS.jsonl"
    tasks = json_rows(task_path)
    responses = json_rows(response_path)
    events = json_rows(event_path)
    task_ids = {row["task_id"] for row in tasks}
    expected = {(tid, model, repeat) for tid in task_ids for model in MODELS for repeat in REPEATS}

    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    malformed = 0
    for row in responses:
        try:
            grouped.setdefault(key(row), []).append(row)
        except (KeyError, TypeError, ValueError):
            malformed += 1
    selected = {k: best_record(v) for k, v in grouped.items() if k in expected}
    recorded = set(selected)
    successful = {k for k, row in selected.items() if eligible_success(row)}
    format_valid = {k for k, row in selected.items() if eligible_success(row) and row.get("format_valid")}
    missing = expected - recorded
    unsuccessful = expected - successful
    counts_by_model = {}
    for model in MODELS:
        model_expected = {k for k in expected if k[1] == model}
        counts_by_model[model] = {
            "expected": len(model_expected),
            "recorded": len(model_expected & recorded),
            "eligible_provider_success": len(model_expected & successful),
            "format_valid": len(model_expected & format_valid),
            "unresolved": len(model_expected - successful),
        }

    errors = Counter()
    for row in responses:
        if not row.get("provider_success"):
            errors[str(row.get("error") or "unknown")[:160]] += 1

    complete = not unsuccessful
    result_exists = (E21 / "E2_1_A_RESULTS.json").exists()
    return {
        "status": "READY_FOR_FROZEN_ANALYSIS" if complete else "COLLECTION_INCOMPLETE",
        "claim_role": "confirmatory node-specialization gate",
        "protocol": {
            "path": "e2_1_PROTOCOL_FINAL.json",
            "sha256": sha256(ROOT / "e2_1_PROTOCOL_FINAL.json"),
        },
        "matrix": {
            "tasks": len(task_ids),
            "models": list(MODELS),
            "repeats": 3,
            "expected_cells": len(expected),
            "raw_response_rows": len(responses),
            "unique_expected_keys_recorded": len(recorded),
            "eligible_provider_success_keys": len(successful),
            "format_valid_keys": len(format_valid),
            "missing_record_keys": len(missing),
            "unresolved_success_keys": len(unsuccessful),
            "duplicate_or_retry_rows": max(0, len(responses) - len(grouped)),
            "out_of_matrix_keys": len(set(grouped) - expected),
            "malformed_rows": malformed,
            "by_model": counts_by_model,
        },
        "events": {"rows": len(events), "cost_usd": sum(float(x.get("cost_usd") or 0) for x in events)},
        "top_failure_reasons": errors.most_common(8),
        "analysis": {
            "result_exists": result_exists,
            "allowed_now": complete,
            "next_action": "run analyze_e2_1_a.py" if complete else "resume only unresolved frozen cells",
        },
        "artifacts": {
            "tasks_sha256": sha256(task_path),
            "responses_sha256": sha256(response_path),
            "events_sha256": sha256(event_path),
        },
    }


def c9_entry() -> dict[str, Any]:
    base_path = ROOT / "phase_c9_0/C9_2_MULTI_JUDGE_CALIBRATION_BASE_COLLECTION_RESULT.json"
    base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {}
    labels = int(base.get("formal_labels_created", 0))
    return {
        "status": "CALIBRATION_ONLY_NO_FORMAL_LABELS" if labels == 0 else "FORMAL_LABELING_STARTED",
        "formal_labels_created": labels,
        "gate_required_tasks": 480,
        "claim_allowed": False,
        "next_action": "do not use C9 as paper outcome until the frozen semantic label matrix is complete",
        "artifact_sha256": sha256(base_path),
    }


def e4_entry() -> dict[str, Any]:
    events_path = ROOT / "phase_e4_0_v2/E4_0_B_V2_EXPLORATION_EVENTS.jsonl"
    events = json_rows(events_path)
    failures = [x for x in events if not x.get("provider_success")]
    returned = Counter(
        (str(x.get("selected_model")), str(x.get("provider_returned_model")))
        for x in events if x.get("provider_success")
    )
    alias_mismatches = [
        {"selected_model": selected, "returned_model": actual, "count": count}
        for (selected, actual), count in returned.items()
        if actual not in {"None", selected}
    ]
    connect_failures = sum("connect" in str(x.get("provider_error", "")).lower() for x in failures)
    return {
        "status": "EXPLORATORY_COLLECTION_REQUIRES_FAILURE_AND_PROVENANCE_AUDIT",
        "event_rows": len(events),
        "provider_failures": len(failures),
        "connection_failures": connect_failures,
        "model_alias_mismatches": alias_mismatches,
        "confirmatory_claim_allowed": False,
        "next_action": "separate infrastructure failures and freeze actual model-version provenance before scoring",
        "artifact_sha256": sha256(events_path),
    }


def render_markdown(ledger: dict[str, Any]) -> str:
    e21 = ledger["experiments"]["E2.1-A"]
    c9 = ledger["experiments"]["C9"]
    e4 = ledger["experiments"]["E4.0-B-v2"]
    m = e21["matrix"]
    lines = [
        "# Experiment Ledger",
        "",
        f"Generated: `{ledger['generated_at']}`",
        "",
        "## Paper-critical path",
        "",
        f"1. **E2.1-A — {e21['status']}**: {m['eligible_provider_success_keys']}/{m['expected_cells']} frozen cells are provider-successful; {m['unresolved_success_keys']} remain unresolved.",
        "2. **E2.1-B — BLOCKED** until E2.1-A passes its frozen gate.",
        "3. **E2.2 Router — BLOCKED** until both E2.1-A and E2.1-B pass.",
        "",
        "## E2.1-A matrix",
        "",
        "| Model | Expected | Recorded | Provider success | Format valid | Unresolved |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model, row in m["by_model"].items():
        lines.append(f"| {model} | {row['expected']} | {row['recorded']} | {row['eligible_provider_success']} | {row['format_valid']} | {row['unresolved']} |")
    lines += [
        "",
        f"Raw rows: {m['raw_response_rows']}; duplicate/retry rows: {m['duplicate_or_retry_rows']}; missing keys: {m['missing_record_keys']}.",
        "",
        "## Other branches",
        "",
        f"- **C9 — {c9['status']}**: formal labels created = {c9['formal_labels_created']}; not eligible for a paper outcome claim.",
        f"- **E4.0-B-v2 — {e4['status']}**: {e4['provider_failures']} provider failures, including {e4['connection_failures']} connection failures; not yet eligible for confirmatory scoring.",
        "",
        "## Frozen next action",
        "",
        e21["analysis"]["next_action"] + ".",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ledger = {
        "version": "paper-experiment-ledger-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": "Raw artifacts are immutable; claims advance only through frozen gates.",
        "experiments": {"E2.1-A": e21_a_entry(), "C9": c9_entry(), "E4.0-B-v2": e4_entry()},
    }
    (ROOT / "EXPERIMENT_LEDGER.json").write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (ROOT / "EXPERIMENT_LEDGER.md").write_text(render_markdown(ledger), encoding="utf-8")
    print(json.dumps(ledger, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
