"""Unified entry point for offline batch schedulers."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional, Sequence

from .constraints import BatchConstraints, MetricGetter
from .fitness import UtilityFn, default_utility, summarize_assignment
from .ga import GAOptimizer
from .pso import PSOOptimizer


class SchedulerType(Enum):
    PSO = "pso"
    GA = "ga"


def solve_batch_assignment(
    tasks: Sequence[Dict[str, Any]],
    models: Sequence[str],
    constraints: Optional[BatchConstraints],
    method: SchedulerType | str = SchedulerType.PSO,
    metric_getter: Optional[MetricGetter] = None,
    utility_fn: UtilityFn = default_utility,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Solve a batch model-assignment problem.

    PPO is intentionally not included here. In this project, PSO/GA are offline
    schedulers, while PPO belongs to future online feedback routing where a
    policy can learn from user ratings and long-term logs.
    """

    if metric_getter is None:
        raise ValueError("metric_getter is required")

    scheduler_type = method if isinstance(method, SchedulerType) else SchedulerType(str(method).lower())
    if scheduler_type == SchedulerType.PSO:
        optimizer = PSOOptimizer(**kwargs)
    elif scheduler_type == SchedulerType.GA:
        optimizer = GAOptimizer(**kwargs)
    else:
        raise ValueError(f"Unsupported scheduler: {method}")

    result = optimizer.solve(tasks, models, constraints, metric_getter, utility_fn)
    assignment = result.get("assignment", [])
    result["assignment_by_task"] = {
        str(task.get("id", idx)): models[model_idx % len(models)]
        for idx, (task, model_idx) in enumerate(zip(tasks, assignment))
    }
    result["summary"] = summarize_assignment(tasks, assignment, models, metric_getter, utility_fn)
    if constraints is not None:
        result["constraint_violations"] = constraints.violations(assignment, tasks, models, metric_getter)
        result["feasible"] = not result["constraint_violations"]
    else:
        result["constraint_violations"] = []
        result["feasible"] = True
    return result
