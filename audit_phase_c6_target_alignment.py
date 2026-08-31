#!/usr/bin/env python3
"""Diagnostic-only C6 target-alignment ceiling; does not alter the frozen method."""
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path("/root")
EXP = ROOT / "target_support_expansion_v1"
OUT = ROOT / "phase_c6"
ANCHOR = "qwen-plus"
SPECIALISTS = ("deepseek-chat", "gemini-2.5-flash")


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def utility(row):
    q = float(row["quality"])
    c = float(row.get("cost_usd") or 0)
    l = float(row.get("latency_ms") or 0)
    r = float(row.get("reliability", 1))
    return 0.45 * q + 0.20 * (1 - min(c / 0.02, 1)) + 0.15 * (1 - min(l / 10000, 1)) + 0.20 * r


old = json.loads((ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text())
new = json.loads((EXP / "EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
ids = sorted(set(old["train_task_ids"] + old["validation_task_ids"] + new["train_task_ids"]))
rows = read_jsonl(ROOT / "five_model_routability_audit/five_model_training_repeats_frozen.jsonl")
rows += read_jsonl(EXP / "expanded_five_model_repeats_frozen.jsonl")
outcomes = {}
for row in rows:
    if row["task_id"] in ids and row["model"] in (ANCHOR,) + SPECIALISTS:
        outcomes[(row["task_id"], row["model"], int(row["repeat"]))] = {
            "utility": utility(row),
            "failure": bool(float(row.get("reliability", 1)) < 1 or float(row["quality"]) < 0.6),
        }

records = []
for task_id in ids:
    for repeat in range(3):
        anchor = outcomes[(task_id, ANCHOR, repeat)]
        specialist_values = {model: outcomes[(task_id, model, repeat)] for model in SPECIALISTS}
        best_model = max(SPECIALISTS, key=lambda model: specialist_values[model]["utility"])
        best = specialist_values[best_model]
        records.append({
            "anchor_failure": anchor["failure"],
            "best_specialist": best_model,
            "gain": best["utility"] - anchor["utility"],
            "anchor_utility": anchor["utility"],
            "best_specialist_utility": best["utility"],
            "anchor_failure_value": anchor["failure"],
            "best_specialist_failure": best["failure"],
        })

failed = [row for row in records if row["anchor_failure"]]
safe = [row for row in records if not row["anchor_failure"]]
oracle_cascade_utility = np.asarray([max(row["anchor_utility"], row["best_specialist_utility"]) for row in records])
anchor_utility = np.asarray([row["anchor_utility"] for row in records])
oracle_cascade_failure = np.asarray([
    row["anchor_failure_value"] if row["anchor_utility"] >= row["best_specialist_utility"] else row["best_specialist_failure"]
    for row in records
], dtype=bool)
audit = {
    "status": "DIAGNOSTIC_ONLY_AFTER_C6",
    "samples": len(records),
    "anchor_failure_samples": len(failed),
    "target_alignment": {
        "p_any_specialist_improves_given_anchor_failure": float(np.mean([row["gain"] > 0 for row in failed])),
        "mean_best_specialist_gain_given_anchor_failure": float(np.mean([row["gain"] for row in failed])),
        "p_any_specialist_reduces_failure_given_anchor_failure": float(np.mean([not row["best_specialist_failure"] for row in failed])),
        "p_any_specialist_improves_given_anchor_nonfailure": float(np.mean([row["gain"] > 0 for row in safe])),
        "failure_label_is_sufficient_escalation_target": False,
    },
    "perfect_information_accept_escalate_ceiling": {
        "anchor_utility": float(anchor_utility.mean()),
        "cascade_utility": float(oracle_cascade_utility.mean()),
        "utility_gain": float((oracle_cascade_utility - anchor_utility).mean()),
        "anchor_failure": float(np.mean([row["anchor_failure_value"] for row in records])),
        "cascade_failure": float(oracle_cascade_failure.mean()),
        "interpretation": "Upper bound only: chooses the better realized utility between anchor and the best specialist on the same repeat.",
    },
    "conclusion": "Response-aware routing retains theoretical headroom, but anchor-failure classification is misaligned with beneficial escalation. A future method must predict safe specialist improvement, not failure alone.",
}
path = OUT / "C6_TARGET_ALIGNMENT_AUDIT.json"
path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
(OUT / "C6_TARGET_ALIGNMENT_AUDIT.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
print(json.dumps(audit, ensure_ascii=False, indent=2))
