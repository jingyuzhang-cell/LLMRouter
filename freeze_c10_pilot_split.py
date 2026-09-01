#!/usr/bin/env python3
"""Freeze an outcome-blind 60/60 split of the C10 complex-120 manifest."""
import hashlib
import json
from pathlib import Path

ROOT = Path("/root")
OUT = ROOT / "c10_prep"
SOURCE = OUT / "C10_PREP_COMPLEX_SUBSET.jsonl"
SEED = "C10-PILOT-SPLIT-v1|20260901"

rows = [json.loads(x) for x in SOURCE.read_text().splitlines() if x.strip()]
assert len(rows) == 120 == len({x["task_id"] for x in rows})

def split_hash(row):
    return hashlib.sha256(f"{SEED}|{row['task_id']}".encode()).hexdigest()

ranked = sorted(rows, key=lambda row: (split_hash(row), row["task_id"]))
pilot, remaining = ranked[:60], ranked[60:]

def public_row(row, rank):
    return {
        "task_id": row["task_id"],
        "split_rank": rank,
        "split_hash": split_hash(row),
        "source_complexity_score": row["complexity_score"],
    }

pilot_rows = [public_row(row, i + 1) for i, row in enumerate(pilot)]
remaining_rows = [public_row(row, i + 61) for i, row in enumerate(remaining)]
protocol = {
    "version": "C10-pilot-split-v1",
    "status": "FROZEN_BEFORE_C9_3_AND_BEFORE_DECOMPOSITION",
    "source_manifest": SOURCE.name,
    "source_manifest_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "population": 120,
    "pilot_tasks": 60,
    "reserved_tasks": 60,
    "ranking": "SHA-256(seed + '|' + task_id), ascending",
    "seed": SEED,
    "outcome_inputs_used": False,
    "judge_inputs_used": False,
    "c9_results_used": False,
    "reserved_policy": "C10_REMAINING_60 is inaccessible for method or decomposition-rule development until C10-P1 pilot analysis is frozen.",
}
files = {
    "C10_PILOT_60.jsonl": pilot_rows,
    "C10_REMAINING_60.jsonl": remaining_rows,
}
for name, data in files.items():
    (OUT / name).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in data))
(OUT / "C10_PILOT_SPLIT_PROTOCOL.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
for name in (*files, "C10_PILOT_SPLIT_PROTOCOL.json"):
    path = OUT / name
    print(hashlib.sha256(path.read_bytes()).hexdigest(), name)
