#!/usr/bin/env python3
"""Freeze an outcome-blind stratified split for target-support expansion v1."""
import hashlib, json, random
from collections import defaultdict
from pathlib import Path

DATA = Path("/root/target_support_expansion_v1")
TASKS = DATA / "TARGET_SUPPORT_EXPANSION_TASKS.jsonl"
OUT = DATA / "EXPANSION_DEV_VALIDATION_SPLIT.json"
SEED = 20260827
QUOTAS = {"TAT-QA:medium": 45, "TAT-QA:low": 15, "ObliQA:high": 30}

tasks = [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()]
groups = defaultdict(list)
for task in tasks:
    groups[f'{task["dataset"]}:{task["risk_level"]}'].append(task["id"])
rng = random.Random(SEED)
validation = []
for group, quota in QUOTAS.items():
    ids = sorted(groups[group]); rng.shuffle(ids); validation.extend(ids[:quota])
validation = sorted(validation)
train = sorted(set(task["id"] for task in tasks) - set(validation))
assert len(train) == 210 and len(validation) == 90 and not set(train) & set(validation)
manifest = {
    "version": "target-support-expansion-dev-validation-v1",
    "created_outcome_blind": True,
    "selection_features": ["dataset", "risk_level", "task_id", "seed"],
    "forbidden_selection_features": ["quality", "utility", "failure", "winner", "model response", "judge score"],
    "seed": SEED,
    "validation_quota": QUOTAS,
    "train_task_ids": train,
    "validation_task_ids": validation,
    "counts": {"total": 300, "train": 210, "validation": 90},
}
OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
(OUT.with_suffix(OUT.suffix + ".sha256")).write_text(f'{hashlib.sha256(OUT.read_bytes()).hexdigest()}  {OUT.name}\n')
print(json.dumps(manifest["counts"]))
