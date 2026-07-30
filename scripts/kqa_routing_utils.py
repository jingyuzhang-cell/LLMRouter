#!/usr/bin/env python3
"""Shared validation and schema helpers for KQAPro routing artifacts."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

EXPECTED_COUNT = 11797
EXPECTED_IDS = {f"kqapro-val-{i:05d}" for i in range(EXPECTED_COUNT)}
TERMINAL_STATUSES = {"provider_refusal", "invalid_response"}
MODEL_SPECS = {
    "deepseek": {"file": "routing_train_deepseek.jsonl", "display": "DeepSeek", "input_price": 0.14, "output_price": 0.28, "currency": "CNY"},
    "qwen": {"file": "routing_train_qwen.jsonl", "display": "Qwen", "input_price": 0.40, "output_price": 2.00, "currency": "CNY"},
    "zhipu": {"file": "routing_train_zhipu.jsonl", "display": "Zhipu", "input_price": 0.15, "output_price": 0.60, "currency": "CNY"},
    "gemini": {"file": "routing_train_gemini-3.5-flash.jsonl", "display": "Gemini 3.5 Flash", "input_price": 0.075, "output_price": 0.30, "currency": "USD"},
    "qwen-3b-local": {"file": "routing_train_qwen-3b-local.jsonl", "display": "Qwen 3B Local", "input_price": 0.0, "output_price": 0.0, "currency": "LOCAL"},
    "llama": {"file": "routing_train_llama-3.3-70b-instruct.jsonl", "display": "Llama 3.3 70B", "input_price": 0.0, "output_price": 0.0, "currency": "NVIDIA_FREE_TIER"},
}

def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, malformed = [], []
    with path.open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            if not line.strip():
                malformed.append({"line": number, "error": "blank_line"}); continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict): raise TypeError("JSON value is not an object")
                rows.append(row)
            except (json.JSONDecodeError, TypeError) as exc:
                malformed.append({"line": number, "error": str(exc)})
    return rows, malformed

def normalized_status(row: dict[str, Any]) -> str:
    status = row.get("status")
    if status in TERMINAL_STATUSES: return status
    return "ok"

def validate_file(path: Path, expected_ids: set[str] = EXPECTED_IDS) -> dict[str, Any]:
    rows, malformed = load_jsonl(path)
    by_id: dict[str, list[dict[str, Any]]] = {}
    invalid = []
    status_counts: dict[str, int] = {}
    for row in rows:
        task_id = row.get("task_id")
        if isinstance(task_id, str): by_id.setdefault(task_id, []).append(row)
        status = normalized_status(row); status_counts[status] = status_counts.get(status, 0) + 1
        predicted = row.get("predicted_label")
        correct = row.get("correct")
        response = row.get("response")
        reasons = []
        if not isinstance(task_id, str): reasons.append("missing_task_id")
        if status == "provider_refusal":
            if response not in (None, ""): reasons.append("refusal_has_response")
            if predicted is not None: reasons.append("refusal_has_label")
            if correct not in (0, 0.0): reasons.append("refusal_not_incorrect")
            if row.get("error_type") != "content_filter": reasons.append("refusal_error_type")
        elif status == "invalid_response":
            if predicted is not None: reasons.append("invalid_response_has_label")
            if correct not in (0, 0.0): reasons.append("invalid_response_not_incorrect")
            if not isinstance(response, str) or not response.strip(): reasons.append("invalid_response_empty")
        else:
            if not isinstance(response, str) or not response.strip(): reasons.append("empty_response")
            if predicted not in list("ABCDEFGHIJ"): reasons.append("invalid_label")
            choices = row.get("choices", {}).get("text", [])
            truth = row.get("ground_truth")
            if predicted in list("ABCDEFGHIJ") and truth in choices:
                expected_correct = float(predicted == chr(65 + choices.index(truth)))
                if correct not in (expected_correct, int(expected_correct)): reasons.append("incorrect_score_mismatch")
            else:
                reasons.append("invalid_ground_truth")
        if reasons: invalid.append({"task_id": task_id, "reasons": reasons})
    ids = set(by_id)
    duplicates = sorted(task_id for task_id, items in by_id.items() if len(items) > 1)
    missing = sorted(expected_ids - ids)
    unexpected = sorted(ids - expected_ids)
    result = {
        "file": str(path), "lines": len(rows) + len(malformed), "json_objects": len(rows),
        "unique_task_ids": len(ids), "duplicates": len(duplicates), "duplicate_task_ids": duplicates,
        "malformed_json": len(malformed), "malformed_details": malformed,
        "missing": len(missing), "missing_task_ids": missing,
        "unexpected": len(unexpected), "unexpected_task_ids": unexpected,
        "invalid_records": len(invalid), "invalid_details": invalid,
        "status_counts": status_counts,
    }
    result["passed"] = all(result[key] == 0 for key in ("duplicates", "malformed_json", "missing", "unexpected", "invalid_records")) and len(ids) == len(expected_ids)
    return result

def question_type(item: dict[str, Any]) -> str:
    program = item.get("program") or []
    if not program: return "unknown"
    function = str(program[-1].get("function", "unknown"))
    if function == "Count": return "count"
    if function.startswith("Verify"): return "verification"
    if function in {"SelectAmong", "SelectBetween"}: return "comparison"
    if function in {"And", "Or"}: return "set_operation"
    if function == "QueryRelation": return "relation"
    if "Qualifier" in function: return "qualifier_query"
    if function.startswith("QueryAttr"): return "attribute_query"
    if function.startswith("QueryName"): return "name_query"
    return function
