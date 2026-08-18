"""Particle swarm optimizer for batch LLM model assignment."""

from __future__ import annotations

import random
from typing import Any, Dict, Optional, Sequence

from .constraints import BatchConstraints, MetricGetter
from .fitness import UtilityFn, batch_fitness, default_utility


class PSOOptimizer:
    """Discrete PSO variant for assigning each task to one model."""

    def __init__(
        self,
        particle_count: Optional[int] = None,
        iterations: int = 36,
        seed: int = 20260629,
        fairness_weight: float = 0.15,
    ) -> None:
        self.particle_count = particle_count
        self.iterations = iterations
        self.seed = seed
        self.fairness_weight = fairness_weight

    def solve(
        self,
        tasks: Sequence[Dict[str, Any]],
        models: Sequence[str],
        constraints: Optional[BatchConstraints],
        metric_getter: MetricGetter,
        utility_fn: UtilityFn = default_utility,
    ) -> Dict[str, Any]:
        rng = random.Random(self.seed)
        if not tasks or not models:
            return {"assignment": [], "fitness": 0.0, "iterations": 0}

        particle_count = self.particle_count or min(24, max(10, len(tasks)))
        particles = [[rng.randrange(len(models)) for _ in tasks] for _ in range(particle_count)]
        best_by_task = [
            max(
                range(len(models)),
                key=lambda model_idx: utility_fn(metric_getter(task, models[model_idx])),
            )
            for task in tasks
        ]
        particles.append(best_by_task)

        personal_best = [particle[:] for particle in particles]
        personal_scores = [
            batch_fitness(
                tasks,
                particle,
                models,
                constraints,
                metric_getter,
                utility_fn,
                fairness_weight=self.fairness_weight,
            )
            for particle in particles
        ]
        best_idx = max(range(len(particles)), key=lambda idx: personal_scores[idx])
        global_best = personal_best[best_idx][:]
        global_score = personal_scores[best_idx]
        trace = [{"iteration": 0, "best_fitness": global_score}]

        for iteration in range(1, self.iterations + 1):
            for idx, particle in enumerate(particles):
                for task_idx, task in enumerate(tasks):
                    roll = rng.random()
                    if roll < 0.40:
                        particle[task_idx] = personal_best[idx][task_idx]
                    elif roll < 0.75:
                        particle[task_idx] = global_best[task_idx]
                    elif roll < 0.90:
                        particle[task_idx] = max(
                            range(len(models)),
                            key=lambda model_idx: utility_fn(metric_getter(task, models[model_idx])),
                        )
                    else:
                        particle[task_idx] = rng.randrange(len(models))

                score = batch_fitness(
                    tasks,
                    particle,
                    models,
                    constraints,
                    metric_getter,
                    utility_fn,
                    fairness_weight=self.fairness_weight,
                )
                if score > personal_scores[idx]:
                    personal_scores[idx] = score
                    personal_best[idx] = particle[:]
                    if score > global_score:
                        global_score = score
                        global_best = particle[:]
            if iteration in {1, self.iterations} or iteration % 6 == 0:
                trace.append({"iteration": iteration, "best_fitness": global_score})

        return {
            "assignment": global_best,
            "fitness": round(global_score, 5),
            "iterations": self.iterations,
            "scheduler_used": "pso",
            "trace": trace,
        }
