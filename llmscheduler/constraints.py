"""Constraint definitions for offline batch model scheduling."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

MetricGetter = Callable[[Dict[str, Any], str], Dict[str, float]]


@dataclass
class BatchConstraints:
    """Feasibility constraints for a batch assignment.

    Metrics follow the project convention:
    quality and reliability are larger-is-better, while cost and latency are
    normalized smaller-is-better values in ``[0, 1]``.
    """

    total_budget: Optional[float] = None
    total_latency: Optional[float] = None
    min_quality_per_task: Optional[float] = None
    min_reliability_per_task: Optional[float] = None
    max_cost_per_task: Optional[float] = None
    max_latency_per_task: Optional[float] = None
    max_calls_per_model: Optional[int] = None

    def violations(
        self,
        assignment: Sequence[int],
        tasks: Sequence[Dict[str, Any]],
        models: Sequence[str],
        metric_getter: MetricGetter,
    ) -> List[str]:
        """Return all violated constraints for an assignment."""

        if len(assignment) != len(tasks):
            return ["任务数量与模型分配数量不一致"]
        if not models and tasks:
            return ["没有可用候选模型"]

        violations: List[str] = []
        total_budget = 0.0
        total_latency = 0.0
        calls = Counter()

        for idx, (task, model_idx) in enumerate(zip(tasks, assignment)):
            if model_idx < 0 or model_idx >= len(models):
                violations.append(f"任务 {idx + 1} 的模型索引越界")
                continue

            model_name = models[model_idx]
            calls[model_name] += 1
            metrics = metric_getter(task, model_name)
            quality = float(metrics.get("quality", 0.0))
            cost = float(metrics.get("cost", 0.0))
            latency = float(metrics.get("latency", 0.0))
            reliability = float(metrics.get("reliability", 0.0))

            total_budget += cost
            total_latency += latency

            if self.min_quality_per_task is not None and quality < self.min_quality_per_task:
                violations.append(f"任务 {idx + 1} 质量低于下限")
            if self.min_reliability_per_task is not None and reliability < self.min_reliability_per_task:
                violations.append(f"任务 {idx + 1} 可靠性低于下限")
            if self.max_cost_per_task is not None and cost > self.max_cost_per_task:
                violations.append(f"任务 {idx + 1} 成本超过上限")
            if self.max_latency_per_task is not None and latency > self.max_latency_per_task:
                violations.append(f"任务 {idx + 1} 延迟超过上限")

        if self.total_budget is not None and total_budget > self.total_budget:
            violations.append("总预算超过上限")
        if self.total_latency is not None and total_latency > self.total_latency:
            violations.append("总延迟超过上限")
        if self.max_calls_per_model is not None:
            overloaded = [name for name, count in calls.items() if count > self.max_calls_per_model]
            if overloaded:
                violations.append("单模型调用次数超过上限：" + "、".join(overloaded))

        return violations

    def is_feasible(
        self,
        assignment: Sequence[int],
        tasks: Sequence[Dict[str, Any]],
        models: Sequence[str],
        metric_getter: MetricGetter,
    ) -> bool:
        """Whether an assignment satisfies every configured constraint."""

        return not self.violations(assignment, tasks, models, metric_getter)
