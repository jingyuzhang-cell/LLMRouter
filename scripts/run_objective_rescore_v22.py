#!/usr/bin/env python3
"""Offline rescore of the frozen 1200 responses with objective scorer v2.2."""
from __future__ import annotations

import copy
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openclaw_router.experiment_protocol import (
    OBJECTIVE_FEASIBILITY_THRESHOLD,
    OBJECTIVE_SCORER_VERSION,
    objective_feasible,
    objective_score,
)

SOURCE = ROOT / "run_logs/formal_context_v2_resumed_result.json"
OUT = ROOT / "run_logs/formal_context_v2_rescored_v22_result.json"
W = {"quality": .45, "cost": .20, "latency": .15, "reliability": .20}


def utility(metrics):
    return round(
        W["quality"] * float(metrics.get("quality") or 0)
        + W["cost"] * (1 - float(metrics.get("cost") or 0))
        + W["latency"] * (1 - float(metrics.get("latency") or 0))
        + W["reliability"] * float(metrics.get("reliability") or 0),
        6,
    )


def main():
    source = json.loads(SOURCE.read_text())
    result = copy.deepcopy(source)
    tasks = {str(task["id"]): task for task in source["sampled_task_set"]}
    raw = result["raw_model_runs"]
    changes = []
    for row in raw:
        task = tasks[str(row["task_id"])]
        old_objective = row.get("objective_score")
        new_objective = objective_score(task, str(row.get("response") or ""))
        scores = [float(item["score"]) for item in row.get("judge_scores") or [] if item.get("score") is not None]
        judge_mean = statistics.mean(scores) if scores else None
        if new_objective is None:
            quality = judge_mean if judge_mean is not None else float(row.get("quality") or 0)
        elif new_objective < OBJECTIVE_FEASIBILITY_THRESHOLD:
            quality = new_objective
        else:
            quality = .7 * new_objective + .3 * (judge_mean if judge_mean is not None else new_objective)
        compared = scores + ([] if new_objective is None else [float(new_objective)])
        disagreement = max(compared) - min(compared) if len(compared) > 1 else 0.0
        row["objective_score"] = new_objective
        row["objective_feasible"] = objective_feasible(new_objective)
        row["quality"] = round(quality, 3)
        row["answer_correctness"] = new_objective if new_objective is not None else row["quality"]
        row["judge_disagreement"] = round(disagreement, 3)
        row["manual_review_required"] = disagreement >= .20
        row["objective_scorer_version"] = OBJECTIVE_SCORER_VERSION
        if old_objective != new_objective:
            changes.append({"task_id": row["task_id"], "model": row["model"], "repeat": row["repeat"], "old": old_objective, "new": new_objective})

    groups = defaultdict(list)
    for row in raw:
        groups[(str(row["task_id"]), str(row["model"]))].append(row)
    aggregated = {}
    for key, rows in groups.items():
        objective_values = [float(row["objective_score"]) for row in rows if row.get("objective_score") is not None]
        avg_objective = round(statistics.mean(objective_values), 3) if objective_values else None
        aggregated[key] = {
            "quality": round(statistics.mean(float(row.get("quality") or 0) for row in rows), 3),
            "objective_score": avg_objective,
            "answer_correctness": avg_objective if avg_objective is not None else round(statistics.mean(float(row.get("quality") or 0) for row in rows), 3),
            "objective_feasible": objective_feasible(avg_objective),
            "reliability": round(avg_objective if avg_objective is not None else statistics.mean(float(row.get("quality") or 0) for row in rows), 3),
            "manual_review_required": any(bool(row.get("manual_review_required")) for row in rows),
        }
    for row in result["routerbench_rows"]:
        values = aggregated[(str(row["task_id"]), str(row["selected_model"]))]
        metrics = row["metrics"]
        metrics.update({name: values[name] for name in ("quality", "answer_correctness", "objective_feasible", "reliability")})
        row["objective_score"] = values["objective_score"]
        row["manual_review_required"] = values["manual_review_required"]
        row["score"] = utility(metrics)

    result["score_source"] = "offline_rescore_dataset_aware_objective_v2.2"
    result["posthoc_rescoring"] = {
        "scorer_version": OBJECTIVE_SCORER_VERSION,
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_calls": 0,
        "raw_responses_modified": False,
        "rescored_records": len(raw),
        "changed_records": len(changes),
        "up": sum(float(item["new"]) > float(item["old"]) for item in changes),
        "down": sum(float(item["new"]) < float(item["old"]) for item in changes),
        "changes": changes,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(OUT), **result["posthoc_rescoring"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
