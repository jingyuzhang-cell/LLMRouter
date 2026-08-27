#!/usr/bin/env python3
"""Run FRAR-v2 with frozen v2 response telemetry joined for every model."""

from __future__ import annotations

from collections import defaultdict

import numpy as np

import frar_v2_five_model_experiment as experiment


def load_test_outcomes() -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    tasks = {x["id"]: x for x in experiment.read_jsonl(experiment.V2 / "tasks.jsonl")}
    matrix = experiment.read_jsonl(experiment.PILOT / "five_model_task_matrix.jsonl")
    telemetry: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for response in experiment.read_jsonl(experiment.V2 / "responses.jsonl"):
        if response.get("success") and response.get("model") in experiment.MODELS:
            telemetry[(response["task_id"], response["model"])].append(response)

    outcomes = {}
    for row in matrix:
        observed = telemetry.get((row["task_id"], row["model"]), [])
        cost = (float(np.mean([float(x.get("cost_usd") or 0) for x in observed]))
                if observed else float(row.get("cost_usd") or 0))
        latency = (float(np.mean([float(x.get("latency_ms") or 0) for x in observed]))
                   if observed else float(row.get("latency_ms") or 0))
        reliability = (float(np.mean([float(x.get("error") is None) for x in observed]))
                       if observed else 1.0)
        outcomes[(row["task_id"], row["model"])] = {
            "quality": float(row["quality"]),
            "failure": float(row["repeat_failure_rate"]),
            "cost_usd": cost,
            "latency_ms": latency,
            "reliability": reliability,
        }
    assert len(outcomes) == len(tasks) * len(experiment.MODELS)
    return tasks, outcomes


experiment.load_test_outcomes = load_test_outcomes
experiment.main()
