"""Canonical scoring and normalization functions used by experiments and offline validation."""
from __future__ import annotations
from typing import Mapping

WEIGHTS = {"quality": 0.45, "cost": 0.20, "latency": 0.15, "reliability": 0.20}
COST_BUDGET_USD = 0.02
TOKEN_BUDGET = 3000
LATENCY_SLA_MS = 10000

def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))

def normalized_cost(cost_usd: float | None, total_tokens: int = 0, priced: bool = True) -> float:
    raw = float(cost_usd or 0.0) / COST_BUDGET_USD if priced else float(total_tokens) / TOKEN_BUDGET
    return round(clamp01(raw), 3)

def normalized_latency(latency_ms: float) -> float:
    return round(clamp01(float(latency_ms) / LATENCY_SLA_MS), 3)

def utility(metrics: Mapping[str, float], weights: Mapping[str, float] = WEIGHTS) -> float:
    # Objective tasks that fail the correctness threshold are infeasible: cost/latency cannot rescue them.
    if metrics.get("objective_feasible") is False:
        return 0.0
    return round(
        clamp01(metrics["quality"]) * weights["quality"]
        + (1.0 - clamp01(metrics["cost"])) * weights["cost"]
        + (1.0 - clamp01(metrics["latency"])) * weights["latency"]
        + clamp01(metrics["reliability"]) * weights["reliability"], 4
    )

def risk_weighted_mean(utilities: list[float], risks: list[float], risk_lambda: float = 1.0) -> float:
    weights = [1.0 + risk_lambda * clamp01(risk) for risk in risks]
    return sum(u * w for u, w in zip(utilities, weights)) / max(1e-12, sum(weights))
