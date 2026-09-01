#!/usr/bin/env python3
"""C9.2 deterministic-only stability diagnostic; no API calls or training."""
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path("/root")
PHASE = ROOT / "phase_c9_0"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
SEED = 20260901


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


routes = {r["task_id"]: r for r in jsonl(PHASE / "C9_2_EVALUATION_ROUTE_MANIFEST.jsonl")}
task_ids = sorted(t for t, r in routes.items() if r["evaluation_route"].startswith("deterministic"))
rows = jsonl(PHASE / "C9_2_DETERMINISTIC_AND_FAILURE_REPEAT_LABELS.jsonl")
lookup = {(r["task_id"], r["model_id"], int(r["repeat_id"])): r for r in rows if r["task_id"] in task_ids}
assert len(task_ids) == 210
assert all((t, m, k) in lookup for t in task_ids for m in MODELS for k in range(3))


def cube_for(field, ids):
    return np.asarray([[[lookup[(t, m, k)][field] for k in range(3)] for m in MODELS] for t in ids], dtype=float)


complete_semantic = [t for t in task_ids if all(lookup[(t, m, k)]["semantic_quality"] is not None for m in MODELS for k in range(3))]


def diagnostic(cube, ids, label):
    n = len(ids)
    pos = np.arange(n)
    held_selected, held_single, reversals, held_ties = [], [], [], []
    fold_rows = []
    for held in range(3):
        train = [k for k in range(3) if k != held]
        selection = cube[:, :, train].mean(axis=2)
        order = np.argsort(-selection, axis=1, kind="stable")
        top1, top2 = order[:, 0], order[:, 1]
        selected_score = cube[pos, top1, held]
        runner_up_score = cube[pos, top2, held]
        best_single = int(cube[:, :, train].mean(axis=(0, 2)).argmax())
        single_score = cube[:, best_single, held]
        reversal = selected_score < runner_up_score
        tie = selected_score == runner_up_score
        held_selected.append(selected_score)
        held_single.append(single_score)
        reversals.append(reversal)
        held_ties.append(tie)
        fold_rows.append({
            "held_out_repeat": held,
            "best_single_model": MODELS[best_single],
            "stable_oracle_gap": float(np.mean(selected_score - single_score)),
            "top1_top2_reversal_rate": float(np.mean(reversal)),
            "top1_top2_held_out_tie_rate": float(np.mean(tie)),
        })
    selected = np.stack(held_selected, axis=1)
    single = np.stack(held_single, axis=1)
    reversal = np.stack(reversals, axis=1)
    held_tie = np.stack(held_ties, axis=1)
    aggregate = cube.mean(axis=2)
    sorted_values = np.sort(aggregate, axis=1)
    margin = sorted_values[:, -1] - sorted_values[:, -2]
    per_task_gap = (selected - single).mean(axis=1)
    rng = np.random.default_rng(SEED)
    boot_idx = rng.integers(0, n, size=(10000, n))
    boot_gap = per_task_gap[boot_idx].mean(axis=1)
    return {
        "label": label,
        "tasks": n,
        "stable_oracle_gap": float(per_task_gap.mean()),
        "stable_oracle_gap_ci95_task_bootstrap": [float(np.quantile(boot_gap, .025)), float(np.quantile(boot_gap, .975))],
        "probability_stable_oracle_gap_positive": float(np.mean(boot_gap > 0)),
        "stable_reversal_rate": float(reversal.mean()),
        "held_out_tie_rate": float(held_tie.mean()),
        "top1_top2_margin": {
            "mean": float(margin.mean()),
            "median": float(np.median(margin)),
            "quantiles": {str(q): float(np.quantile(margin, q)) for q in (0, .1, .25, .5, .75, .9, 1)},
        },
        "folds": fold_rows,
    }


semantic = diagnostic(cube_for("semantic_quality", complete_semantic), complete_semantic, "semantic_quality_complete_case")
delivered = diagnostic(cube_for("delivered_quality", task_ids), task_ids, "delivered_quality_all_deterministic_tasks")
route_counts = {}
for t in task_ids:
    route = routes[t]["evaluation_route"]
    route_counts[route] = route_counts.get(route, 0) + 1
report = {
    "status": "C9_2_DETERMINISTIC_ONLY_DIAGNOSTIC_COMPLETE",
    "decision_role": "early diagnostic only; final whole-query C9 decision requires all 480 task semantic labels",
    "definitions": {
        "stable_oracle_gap": "For each held-out repeat, select each task's top model using the other two repeats; subtract the held-out score of the globally best single model learned on those repeats; average over tasks and folds.",
        "stable_reversal_rate": "Across task x held-out-repeat folds, rate at which the top-1 model selected on the other two repeats scores strictly below that selection-time top-2 model on the held-out repeat.",
        "top1_top2_margin": "Difference between the highest and second-highest three-repeat mean score for each task.",
    },
    "integrity": {
        "deterministic_tasks": len(task_ids),
        "route_counts": route_counts,
        "models": len(MODELS),
        "repeats": 3,
        "semantic_complete_case_tasks": len(complete_semantic),
        "semantic_incomplete_tasks": len(task_ids) - len(complete_semantic),
        "semantic_complete_case_rate": len(complete_semantic) / len(task_ids),
        "judge_calls": 0,
        "router_training": False,
        "wave_2_access": False,
        "dag_run": False,
    },
    "primary_preliminary_semantic": semantic,
    "delivered_quality_sensitivity": delivered,
}
out = PHASE / "C9_2_DETERMINISTIC_ONLY_DIAGNOSTIC.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
sha = hashlib.sha256(out.read_bytes()).hexdigest()
(PHASE / "C9_2_DETERMINISTIC_ONLY_DIAGNOSTIC.sha256").write_text(f"{sha}  {out.name}\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
