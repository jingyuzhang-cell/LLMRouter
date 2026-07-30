#!/usr/bin/env python3
"""Deduplicate and rescore KQA routing JSONL files without API calls."""
import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from generate_kqa_multi_model_routing import extract_choice_label


def repair(path: Path, apply: bool) -> dict:
    rows, malformed = [], 0
    with path.open() as source:
        for line in source:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                malformed += 1
    selected, refusals, unresolved = {}, {}, set()
    for row in reversed(rows):
        task_id = row.get("task_id")
        if not task_id or task_id in selected:
            continue
        if row.get("status") in {"provider_refusal", "invalid_response"}:
            if row.get("status") == "provider_refusal":
                row["response"] = None
            row["predicted_label"] = None
            row["correct"] = 0.0
            row["performance"] = 0.0
            row.setdefault("error_type", "content_filter")
            refusals.setdefault(task_id, row)
            continue
        choices = row.get("choices", {}).get("text", [])
        label = extract_choice_label(str(row.get("response", "")), choices)
        if label is None:
            unresolved.add(task_id)
            continue
        try:
            gold = chr(65 + choices.index(row["ground_truth"]))
        except (KeyError, ValueError):
            unresolved.add(task_id)
            continue
        row["predicted_label"] = label
        row["correct"] = float(label == gold)
        row["performance"] = row["correct"]
        selected[task_id] = row
        refusals.pop(task_id, None)
        unresolved.discard(task_id)
    for task_id, row in refusals.items():
        if task_id not in selected:
            selected[task_id] = row
            unresolved.discard(task_id)
    unique_ids = {row.get("task_id") for row in rows if row.get("task_id")}
    result = {
        "input_lines": len(rows), "valid_unique": len(selected),
        "duplicates_removed": len(rows) - len(unique_ids),
        "unresolved_unique": len(unresolved), "malformed_lines": malformed,
        "correct": int(sum(row["correct"] for row in selected.values())),
        "provider_refusals": sum(
            row.get("status") == "provider_refusal" for row in selected.values()
        ),
        "invalid_responses": sum(
            row.get("status") == "invalid_response" for row in selected.values()
        ),
    }
    if apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_suffix(path.suffix + f".bak-{stamp}")
        shutil.copy2(path, backup)
        temp = path.with_suffix(path.suffix + ".repairing")
        with temp.open("w") as target:
            for task_id in sorted(selected):
                target.write(json.dumps(selected[task_id], ensure_ascii=False) + "\n")
        temp.replace(path)
        result["backup"] = str(backup)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="write repaired files; originals are backed up")
    args = parser.parse_args()
    for path in args.files:
        print(json.dumps({"file": str(path), **repair(path, args.apply)},
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
