from llmscheduler import BatchConstraints, SchedulerType, solve_batch_assignment


TASKS = [
    {"id": "t1", "type": "通用问答", "risk": 0.2},
    {"id": "t2", "type": "代码生成", "risk": 0.45},
    {"id": "t3", "type": "专业问答", "risk": 0.86},
]

MODELS = ["light", "balanced", "strong"]

METRICS = {
    ("t1", "light"): {"quality": 0.72, "cost": 0.15, "latency": 0.18, "reliability": 0.82},
    ("t1", "balanced"): {"quality": 0.80, "cost": 0.35, "latency": 0.30, "reliability": 0.86},
    ("t1", "strong"): {"quality": 0.92, "cost": 0.75, "latency": 0.65, "reliability": 0.93},
    ("t2", "light"): {"quality": 0.52, "cost": 0.15, "latency": 0.18, "reliability": 0.78},
    ("t2", "balanced"): {"quality": 0.86, "cost": 0.35, "latency": 0.30, "reliability": 0.87},
    ("t2", "strong"): {"quality": 0.90, "cost": 0.75, "latency": 0.65, "reliability": 0.92},
    ("t3", "light"): {"quality": 0.50, "cost": 0.15, "latency": 0.18, "reliability": 0.58},
    ("t3", "balanced"): {"quality": 0.78, "cost": 0.35, "latency": 0.30, "reliability": 0.82},
    ("t3", "strong"): {"quality": 0.93, "cost": 0.75, "latency": 0.65, "reliability": 0.95},
}


def metric_getter(task, model_name):
    return METRICS[(task["id"], model_name)]


def test_pso_scheduler_returns_assignment_with_trace():
    result = solve_batch_assignment(
        TASKS,
        MODELS,
        BatchConstraints(min_quality_per_task=0.50, min_reliability_per_task=0.55),
        method=SchedulerType.PSO,
        metric_getter=metric_getter,
        iterations=4,
        particle_count=8,
    )

    assert result["scheduler_used"] == "pso"
    assert len(result["assignment"]) == len(TASKS)
    assert result["trace"]
    assert result["fitness"] > 0


def test_ga_scheduler_returns_assignment_with_summary():
    result = solve_batch_assignment(
        TASKS,
        MODELS,
        BatchConstraints(min_quality_per_task=0.50, min_reliability_per_task=0.55),
        method="ga",
        metric_getter=metric_getter,
        generations=4,
        population_size=8,
    )

    assert result["scheduler_used"] == "ga"
    assert len(result["assignment_by_task"]) == len(TASKS)
    assert result["summary"]["avg_utility"] > 0
