#!/usr/bin/env python3
"""Export dual-review packets without model or automated-score identities."""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/finance_router/finrome_legacy_v2_confirmatory"
OUT = ROOT / "run_logs/finrome_legacy_v2_confirmatory/human_review"
SEED = 20260824


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in values))


def main() -> None:
    pending = rows(DATA / "manual_review_pending.jsonl")
    if len(pending) != 1752 or any(row.get("review_status") != "PENDING" for row in pending):
        raise SystemExit("Expected exactly 1752 PENDING review items")
    tasks = {row["id"]: row for row in rows(DATA / "tasks.jsonl")}
    responses = {}
    for row in rows(DATA / "responses.jsonl"):
        responses[(row["task_id"], row["model"], row["repeat"])] = row

    mapping = []
    packet = []
    seen = set()
    for row in pending:
        key = (row["task_id"], row["model"], row["repeat"])
        if key in seen:
            raise SystemExit(f"Duplicate review key: {key}")
        seen.add(key)
        task = tasks[row["task_id"]]
        response = responses[key]
        review_id = "R-" + hashlib.sha256(
            f"{SEED}|{key[0]}|{key[1]}|{key[2]}".encode()
        ).hexdigest()[:16]
        mapping.append(
            {
                "review_id": review_id,
                "task_id": key[0],
                "model": key[1],
                "repeat": key[2],
            }
        )
        packet.append(
            {
                "review_id": review_id,
                "dataset": task.get("dataset"),
                "risk_level": task.get("risk_level"),
                "task_type": task.get("task_type"),
                "question": task.get("question", ""),
                "context": task.get("context", ""),
                "reference_answer": task.get("gold_answer", ""),
                "candidate_answer": response.get("answer", ""),
                "accuracy": "",
                "completeness": "",
                "reasoning": "",
                "clarity": "",
                "safety": "",
                "overall_decision": "",
                "reviewer_confidence": "",
                "reviewer_notes": "",
                "review_status": "PENDING",
            }
        )

    OUT.mkdir(parents=True, exist_ok=True)
    for reviewer, offset in (("reviewer_a", 0), ("reviewer_b", 1)):
        ordered = list(packet)
        random.Random(SEED + offset).shuffle(ordered)
        write_jsonl(OUT / f"{reviewer}_packet.jsonl", ordered)
    write_jsonl(OUT / "identity_mapping_RESTRICTED.jsonl", mapping)
    arbitration = [
        {
            "review_id": row["review_id"],
            "reviewer_a_decision": "",
            "reviewer_b_decision": "",
            "agreement": "",
            "adjudicator_decision": "",
            "adjudicator_notes": "",
            "review_status": "PENDING",
        }
        for row in packet
    ]
    write_jsonl(OUT / "arbitration_template.jsonl", arbitration)
    manifest = {
        "status": "PENDING_ONLY_NO_HUMAN_CONCLUSIONS_SYNTHESIZED",
        "items": len(packet),
        "reviewers": 2,
        "blind_fields_removed": ["model", "repeat", "objective_score", "judge_scores", "judge_disagreement"],
        "decision_fields": ["accuracy", "completeness", "reasoning", "clarity", "safety", "overall_decision"],
        "identity_mapping": "identity_mapping_RESTRICTED.jsonl",
        "seed": SEED,
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"out": str(OUT), **manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
