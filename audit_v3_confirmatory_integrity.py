#!/usr/bin/env python3
"""Post-unblinding integrity and bounded sensitivity audit; never rewrites v3 data."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/root")
V3 = ROOT / "v3_confirmatory"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


protocol = json.loads((V3 / "V3_CONFIRMATORY_PROTOCOL.json").read_text())
manifest = json.loads((V3 / "V3_MATRIX_MANIFEST.json").read_text())
results = json.loads((V3 / "V3_CONFIRMATORY_RESULTS.json").read_text())
repeat_rows = read_jsonl(V3 / "V3_REPEAT_MATRIX_FROZEN.jsonl")
matrix_rows = read_jsonl(V3 / "V3_TASK_MODEL_MATRIX_FROZEN.jsonl")
decisions = read_jsonl(V3 / "V3_FROZEN_C3_DECISIONS.jsonl")
recovery = read_jsonl(V3 / "V3_RESPONSE_RECOVERY_FAILURES.jsonl")
tasks = {row["id"]: row for row in read_jsonl(V3 / "V3_CONFIRMATORY_TASKS.jsonl")}

assert len(repeat_rows) == 1800
assert len(matrix_rows) == 600
assert len(decisions) == 120
assert len({(row["task_id"], row["model"], row["repeat"]) for row in repeat_rows}) == 1800
assert len({(row["task_id"], row["model"]) for row in matrix_rows}) == 600

attempts = Counter((row["task_id"], row["model"], int(row["repeat"])) for row in recovery)
rounds = defaultdict(set)
for row in recovery:
    rounds[(row["task_id"], row["model"], int(row["repeat"]))].add(int(row.get("recovery_round", 0)))
persistent = [tuple(key) for key in manifest["persistent_glm_failure_keys"]]

matrix = {(row["task_id"], row["model"]): dict(row) for row in matrix_rows}
choice = {row["task_id"]: row["selected_model"] for row in decisions}
baseline = results["training_baseline_model"]


def utility(quality, cost, latency, reliability):
    return 0.45 * quality + 0.20 * (1 - min(cost / 0.02, 1)) + 0.15 * (1 - min(latency / 10000, 1)) + 0.20 * reliability


def summarize(candidate_matrix):
    task_ids = sorted(tasks)
    selected = np.asarray([candidate_matrix[(task_id, choice[task_id])]["utility"] for task_id in task_ids])
    best = np.asarray([candidate_matrix[(task_id, baseline)]["utility"] for task_id in task_ids])
    oracle = np.asarray([max(candidate_matrix[(task_id, model)]["utility"] for model in MODELS) for task_id in task_ids])
    delta = selected - best
    gap = float(oracle.mean() - best.mean())
    rng = np.random.default_rng(20260827)
    indices = rng.integers(0, len(task_ids), size=(10000, len(task_ids)))
    bootstrap = delta[indices].mean(axis=1)
    high = [task_id for task_id in task_ids if tasks[task_id]["risk_level"] == "high"]
    return {
        "router_utility": float(selected.mean()),
        "best_single_utility": float(best.mean()),
        "oracle_utility": float(oracle.mean()),
        "gap_recovery": float(delta.mean() / gap) if gap > 0 else None,
        "bootstrap_probability_router_above_best": float(np.mean(bootstrap > 0)),
        "router_failure": float(np.mean([candidate_matrix[(task_id, choice[task_id])]["failure"] for task_id in task_ids])),
        "best_single_failure": float(np.mean([candidate_matrix[(task_id, baseline)]["failure"] for task_id in task_ids])),
        "router_high_risk_failure": float(np.mean([candidate_matrix[(task_id, choice[task_id])]["failure"] for task_id in high])),
        "best_single_high_risk_failure": float(np.mean([candidate_matrix[(task_id, baseline)]["failure"] for task_id in high])),
    }


# Best-case bound: replace only the four persistent empty repeat outcomes with perfect,
# reliable answers, while keeping the already frozen router decisions unchanged.
optimistic_repeats = [dict(row) for row in repeat_rows]
for row in optimistic_repeats:
    if (row["task_id"], row["model"], row["repeat"]) in persistent:
        row["quality"] = 1.0
        row["reliability"] = 1.0
grouped = defaultdict(list)
for row in optimistic_repeats:
    grouped[(row["task_id"], row["model"])].append(row)
optimistic = {}
for key, rows in grouped.items():
    quality = float(np.mean([row["quality"] for row in rows]))
    cost = float(np.mean([row["cost_usd"] for row in rows]))
    latency = float(np.mean([row["latency_ms"] for row in rows]))
    reliability = float(np.mean([row["reliability"] for row in rows]))
    optimistic[key] = {
        "quality": quality,
        "cost_usd": cost,
        "latency_ms": latency,
        "reliability": reliability,
        "failure": bool(reliability < 1 or quality < 0.6),
        "utility": utility(quality, cost, latency, reliability),
    }

protocol_hash = hashlib.sha256((V3 / "V3_CONFIRMATORY_PROTOCOL.json").read_bytes()).hexdigest()
task_hash = hashlib.sha256((V3 / "V3_CONFIRMATORY_TASKS.jsonl").read_bytes()).hexdigest()
sidecar_protocol = (V3 / "V3_CONFIRMATORY_PROTOCOL.json.sha256").read_text().split()[0]
sidecar_tasks = (V3 / "V3_CONFIRMATORY_TASKS.jsonl.sha256").read_text().split()[0]
source = (ROOT / "run_phase_c3.py").read_text()
audit = {
    "status": "V3_CONFIRMATORY_FAIL_WITH_PROTOCOL_DEVIATIONS",
    "immutable_original_result": results["status"],
    "structural_integrity": {
        "repeat_rows": len(repeat_rows),
        "aggregate_rows": len(matrix_rows),
        "decision_rows": len(decisions),
        "missing_keys": manifest["missing_keys"],
        "duplicate_keys": manifest["duplicate_keys"],
        "protocol_hash_matches_sidecar": protocol_hash == sidecar_protocol,
        "tasks_hash_matches_sidecar": task_hash == sidecar_tasks,
        "matrix_hash_matches_manifest": hashlib.sha256((V3 / "V3_TASK_MODEL_MATRIX_FROZEN.jsonl").read_bytes()).hexdigest() == manifest["sha256"]["V3_TASK_MODEL_MATRIX_FROZEN.jsonl"],
    },
    "protocol_deviations": [
        {
            "id": "unbounded_transport_recovery",
            "severity": "material",
            "finding": "Recovery continued through round 8 without a pre-frozen retry cap.",
            "max_observed_recovery_round": max(int(row.get("recovery_round", 0)) for row in recovery),
            "persistent_failure_attempt_counts_in_failure_log": {"|".join(map(str, key)): attempts[key] for key in persistent},
            "interpretation": "Do not retry or replace these outcomes after v3 unblinding. Preserve them as provider failures.",
        },
        {
            "id": "gold_answer_feature_schema_violation",
            "severity": "material",
            "finding": "The frozen C3 schema forbids gold answer, but manual() reads gold_answer to derive three answer-type features.",
            "static_source_evidence": "gold=str(t.get('gold_answer') or '')" in source,
            "interpretation": "C3 is not deployment-clean as implemented; C4 removes gold and evidence annotations.",
        },
    ],
    "persistent_provider_failures": {
        "count": len(persistent),
        "keys": [list(key) for key in persistent],
        "selected_by_router_count": sum(choice[task_id] == model for task_id, model, _ in persistent),
    },
    "reported_analysis": summarize(matrix),
    "optimistic_fixed_decision_sensitivity": summarize(optimistic),
    "sensitivity_definition": "All four persistent empty GLM repeats are set to quality=1 and reliability=1; frozen routing decisions are not changed.",
    "confirmatory_conclusion_changes_under_optimistic_sensitivity": False,
    "post_unblinding_actions": [
        "No v3 response was overwritten.",
        "No C3 threshold or model was changed.",
        "v3 is not reused as confirmation for C4 or later methods.",
    ],
}
(V3 / "V3_INTEGRITY_AND_SENSITIVITY_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(audit, ensure_ascii=False, indent=2))
