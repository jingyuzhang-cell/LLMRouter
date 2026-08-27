#!/usr/bin/env python3
"""Create an outcome-blind target-support development/validation split."""

import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


SEED = 20260827
PILOT = Path("/root/gemini_frar_pilot/five_model_v1")
V2_TASKS = Path("/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/data/finance_router/safety_expansion_v2_counterexample_enrichment/tasks.jsonl")
OUT = Path("/root/target_support_dev_split")
VALIDATION_QUOTA = {("TAT-QA", "medium"): 36, ("TAT-QA", "low"): 14, ("ObliQA", "high"): 20}


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


tasks = read(PILOT / "gemini_training_pilot_tasks.jsonl")
v2_ids = {row["id"] for row in read(V2_TASKS)}
groups = defaultdict(list)
for task in tasks:
    key = (str(task.get("dataset")), str(task.get("risk_level")).lower())
    if key in VALIDATION_QUOTA:
        groups[key].append(task["id"])

rng = random.Random(SEED)
validation = []
for key, quota in VALIDATION_QUOTA.items():
    values = sorted(groups[key]); rng.shuffle(values)
    assert len(values) > quota, (key, len(values), quota)
    validation.extend(values[:quota])

eligible = sorted(task_id for values in groups.values() for task_id in values)
validation = sorted(validation)
train = sorted(set(eligible) - set(validation))
assert not set(train) & set(validation)
assert not (set(eligible) & v2_ids)

task_map = {task["id"]: task for task in tasks}
def distribution(ids):
    return {
        "dataset": dict(Counter(str(task_map[x].get("dataset")) for x in ids)),
        "risk": dict(Counter(str(task_map[x].get("risk_level")).lower() for x in ids)),
        "task_type": dict(Counter(str(task_map[x].get("task_type")) for x in ids)),
    }

manifest = {
    "version": "target-support-dev-split-v1",
    "created_outcome_blind": True,
    "selection_features": ["dataset", "risk_level", "task_type", "task_id", "seed"],
    "forbidden_selection_features": ["quality", "utility", "failure", "winner", "any model response"],
    "seed": SEED,
    "target_support": ["TAT-QA/table reasoning/medium+low", "ObliQA/compliance/high"],
    "validation_quota": {f"{key[0]}:{key[1]}": value for key, value in VALIDATION_QUOTA.items()},
    "train_task_ids": train,
    "validation_task_ids": validation,
    "train_distribution": distribution(train),
    "validation_distribution": distribution(validation),
    "eligible_tasks": len(eligible),
    "train_tasks": len(train),
    "validation_tasks": len(validation),
    "v2_overlap": 0,
}
OUT.mkdir(parents=True, exist_ok=True)
path = OUT / "TARGET_SUPPORT_DEV_SPLIT.json"
path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
(OUT / "TARGET_SUPPORT_DEV_SPLIT.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "  TARGET_SUPPORT_DEV_SPLIT.json\n")
print(json.dumps({key: value for key, value in manifest.items() if not key.endswith("task_ids")}, ensure_ascii=False, indent=2))
