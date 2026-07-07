"""Shared fitness functions for PSO and GA batch schedulers."""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Sequence

from .constraints import BatchConstraints, MetricGetter

UtilityFn = Callable[[Dict[str, float]], float]


def default_utility(metrics: Dict[str, float]) -> float:
    """Project default quality-cost-latency-reliability utility."""

    return round(
        float(metrics.get("quality", 0.0)) * 0.45
        + (1.0 - float(metrics.get("cost", 0.0))) * 0.20
        + (1.0 - float(metrics.get("latency", 0.0))) * 0.15
        + float(metrics.get("reliability", 0.0)) * 0.20,
        5,
    )


def batch_fitness(
    tasks: Sequence[Dict[str, Any]],
    assignment: Sequence[int],
    models: Sequence[str],
    constraints: Optional[BatchConstraints],
    metric_getter: MetricGetter,
    utility_fn: UtilityFn = default_utility,
    fairness_weight: float = 0.15,
    violation_penalty: float = 0.08,
) -> float:
    """Compute global utility for a batch assignment.

    The score is intentionally not a plain sum. It combines task-level utility,
    constraint penalties, and a fairness/load-balance penalty so the scheduler
    avoids spending the best model on every task when the batch has constraints.
    """

    if not tasks or not models or len(assignment) != len(tasks):
        return 0.0

    utilities: List[float] = []
    usage_counter = Counter()
    for task, model_idx in zip(tasks, assignment):
        model_name = models[model_idx % len(models)]
        usage_counter[model_name] += 1
        metrics = metric_getter(task, model_name)
        score = float(utility_fn(metrics))
        risk = float(task.get("risk", 0.0))
        if risk >= 0.75 and float(metrics.get("reliability", 0.0)) < 0.70:
            score = max(0.0, score - 0.10)
        utilities.append(score)

    avg_utility = sum(utilities) / len(utilities)
    spread_penalty = (max(utilities) - min(utilities)) * fairness_weight if utilities else 0.0
    ideal_load = len(tasks) / len(models)
    load_penalty = (
        sum(abs(usage_counter.get(model, 0) - ideal_load) for model in models)
        / max(1, len(tasks))
        * 0.025
    )

    violations = []
    if constraints is not None:
        violations = constraints.violations(assignment, tasks, models, metric_getter)
    penalty = min(0.45, len(violations) * violation_penalty)
    return round(max(0.0, avg_utility - spread_penalty - load_penalty - penalty), 5)


def summarize_assignment(
    tasks: Sequence[Dict[str, Any]],
    assignment: Sequence[int],
    models: Sequence[str],
    metric_getter: MetricGetter,
    utility_fn: UtilityFn = default_utility,
) -> Dict[str, Any]:
    """Build aggregate metrics for a solved assignment."""

    totals = Counter()
    usage = Counter()
    rows = []
    for task, model_idx in zip(tasks, assignment):
        model_name = models[model_idx % len(models)]
        usage[model_name] += 1
        metrics = metric_getter(task, model_name)
        score = float(utility_fn(metrics))
        for key in ("quality", "cost", "latency", "reliability"):
            totals[key] += float(metrics.get(key, 0.0))
        totals["score"] += score
        rows.append({
            "task_id": task.get("id"),
            "task_type": task.get("type"),
            "selected_model": model_name,
            "metrics": metrics,
            "score": round(score, 5),
        })

    count = max(1, len(tasks))
    return {
        "avg_quality": round(totals["quality"] / count, 5),
        "avg_cost": round(totals["cost"] / count, 5),
        "avg_latency": round(totals["latency"] / count, 5),
        "avg_reliability": round(totals["reliability"] / count, 5),
        "avg_utility": round(totals["score"] / count, 5),
        "model_usage": dict(usage),
        "task_details": rows,
    }
