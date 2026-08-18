"""Small CLI for offline scheduler smoke tests.

This CLI intentionally uses task-provided metrics when available, so it can run
without provider API keys. A task may contain:
{"id": "t1", "metrics": {"model-a": {"quality": 0.9, ...}}}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from .constraints import BatchConstraints
from .solver import SchedulerType, solve_batch_assignment


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    tasks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            tasks.append(json.loads(line))
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PSO/GA batch model scheduling.")
    parser.add_argument("--input", required=True, help="Path to a JSONL task file.")
    parser.add_argument("--models", required=True, help="Comma-separated model ids.")
    parser.add_argument("--scheduler", choices=[item.value for item in SchedulerType], default="pso")
    parser.add_argument("--budget", type=float, default=None)
    parser.add_argument("--max-time", type=float, default=None)
    parser.add_argument("--min-quality", type=float, default=None)
    parser.add_argument("--min-reliability", type=float, default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    tasks = load_jsonl(Path(args.input))
    models = [item.strip() for item in args.models.split(",") if item.strip()]
    constraints = BatchConstraints(
        total_budget=args.budget,
        total_latency=args.max_time,
        min_quality_per_task=args.min_quality,
        min_reliability_per_task=args.min_reliability,
    )

    def metric_getter(task: Dict[str, Any], model_name: str) -> Dict[str, float]:
        metrics = task.get("metrics", {}).get(model_name)
        if metrics:
            return metrics
        return {"quality": 0.6, "cost": 0.5, "latency": 0.5, "reliability": 0.7}

    result = solve_batch_assignment(
        tasks,
        models,
        constraints,
        method=args.scheduler,
        metric_getter=metric_getter,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
