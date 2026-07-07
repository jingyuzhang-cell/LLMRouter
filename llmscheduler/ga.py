"""Genetic optimizer for batch LLM model assignment."""

from __future__ import annotations

import random
from typing import Any, Dict, Optional, Sequence

from .constraints import BatchConstraints, MetricGetter
from .fitness import UtilityFn, batch_fitness, default_utility


class GAOptimizer:
    """Simple GA baseline for offline scheduling experiments."""

    def __init__(
        self,
        population_size: Optional[int] = None,
        generations: int = 42,
        mutation_rate: float = 0.12,
        seed: int = 20260630,
        fairness_weight: float = 0.15,
    ) -> None:
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
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

        population_size = self.population_size or min(28, max(12, len(tasks)))
        population = [[rng.randrange(len(models)) for _ in tasks] for _ in range(population_size)]
        greedy = [
            max(
                range(len(models)),
                key=lambda model_idx: utility_fn(metric_getter(task, models[model_idx])),
            )
            for task in tasks
        ]
        population.append(greedy)

        def score(item: Sequence[int]) -> float:
            return batch_fitness(
                tasks,
                item,
                models,
                constraints,
                metric_getter,
                utility_fn,
                fairness_weight=self.fairness_weight,
            )

        trace = [{"generation": 0, "best_fitness": max(score(item) for item in population)}]
        for generation in range(1, self.generations + 1):
            ranked = sorted(population, key=score, reverse=True)
            survivors = ranked[: max(4, population_size // 3)]
            next_population = [item[:] for item in survivors[:2]]

            while len(next_population) < population_size:
                parent_a = rng.choice(survivors)
                parent_b = rng.choice(survivors)
                if len(tasks) > 1:
                    cut = rng.randrange(1, len(tasks))
                    child = parent_a[:cut] + parent_b[cut:]
                else:
                    child = parent_a[:]
                for task_idx in range(len(child)):
                    if rng.random() < self.mutation_rate:
                        child[task_idx] = rng.randrange(len(models))
                next_population.append(child)

            population = next_population
            if generation in {1, self.generations} or generation % 7 == 0:
                trace.append({"generation": generation, "best_fitness": max(score(item) for item in population)})

        best = max(population, key=score)
        best_score = score(best)
        return {
            "assignment": list(best),
            "fitness": round(best_score, 5),
            "iterations": self.generations,
            "scheduler_used": "ga",
            "trace": trace,
        }
