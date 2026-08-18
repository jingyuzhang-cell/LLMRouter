"""RouterBench evaluation utilities.

RouterBench turns per-task router decisions into a comparable benchmark report:
quality, cost, latency, efficiency, robustness and statistical significance.
The implementation is dependency-free so it can run in the lightweight demo
environment and in real API experiments.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from statistics import mean
from typing import Any, Dict, List


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * percentile
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return round(ordered[low], 3)
    weight = rank - low
    return round(ordered[low] * (1.0 - weight) + ordered[high] * weight, 3)


def _dominates(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    lm = left["summary"]
    rm = right["summary"]
    better_or_equal = (
        lm["quality"] >= rm["quality"]
        and lm["reliability"] >= rm["reliability"]
        and lm["cost"] <= rm["cost"]
        and lm["latency"] <= rm["latency"]
    )
    strictly_better = (
        lm["quality"] > rm["quality"]
        or lm["reliability"] > rm["reliability"]
        or lm["cost"] < rm["cost"]
        or lm["latency"] < rm["latency"]
    )
    return bool(better_or_equal and strictly_better)


def _paired_by_task(
    rows_by_strategy: Dict[str, List[Dict[str, Any]]],
    left: str,
    right: str,
) -> List[float]:
    left_scores = {
        str(item.get("task_id")): _safe_float(item.get("score"))
        for item in rows_by_strategy.get(left, [])
    }
    right_scores = {
        str(item.get("task_id")): _safe_float(item.get("score"))
        for item in rows_by_strategy.get(right, [])
    }
    common = sorted(set(left_scores) & set(right_scores))
    return [left_scores[task_id] - right_scores[task_id] for task_id in common]


def _bootstrap_ci(differences: List[float], samples: int = 600) -> Dict[str, float]:
    if not differences:
        return {"mean": 0.0, "low": 0.0, "high": 0.0}
    rng = random.Random(20260702)
    boot = []
    for _ in range(samples):
        draw = [rng.choice(differences) for _ in differences]
        boot.append(mean(draw))
    boot.sort()
    return {
        "mean": round(mean(differences), 5),
        "low": round(boot[int(0.025 * (samples - 1))], 5),
        "high": round(boot[int(0.975 * (samples - 1))], 5),
    }


def _mean_bootstrap_ci(values: List[float], samples: int = 1000, seed: int = 20260727) -> List[float]:
    """Deterministic percentile CI for a strategy mean."""
    if not values:
        return [0.0, 0.0]
    if len(values) == 1:
        value = round(values[0], 5)
        return [value, value]
    rng = random.Random(seed)
    boot = sorted(mean([rng.choice(values) for _ in values]) for _ in range(samples))
    return [round(boot[int(0.025 * (samples - 1))], 5), round(boot[int(0.975 * (samples - 1))], 5)]


def _utility(metrics: Dict[str, Any], weights: Dict[str, float]) -> float:
    return (
        _safe_float(metrics.get("quality")) * weights["quality"]
        + (1.0 - _safe_float(metrics.get("cost"), 1.0)) * weights["cost"]
        + (1.0 - _safe_float(metrics.get("latency"), 1.0)) * weights["latency"]
        + _safe_float(metrics.get("reliability")) * weights["reliability"]
    )


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _paired_t_test(differences: List[float]) -> Dict[str, float]:
    n = len(differences)
    if n < 2:
        return {"t": 0.0, "p": 1.0}
    avg = mean(differences)
    variance = sum((item - avg) ** 2 for item in differences) / (n - 1)
    stderr = math.sqrt(variance / n) if variance > 0 else 0.0
    if stderr <= 0:
        return {"t": 0.0, "p": 1.0 if abs(avg) < 1e-12 else 0.0}
    t_value = avg / stderr
    p_value = 2.0 * (1.0 - _normal_cdf(abs(t_value)))
    return {"t": round(t_value, 5), "p": round(max(0.0, min(1.0, p_value)), 6)}


def _wilcoxon_signed_rank(differences: List[float]) -> Dict[str, float]:
    nonzero = [item for item in differences if abs(item) > 1e-12]
    n = len(nonzero)
    if n < 2:
        return {"w": 0.0, "p": 1.0}
    ranked = sorted((abs(item), item) for item in nonzero)
    rank_sum_positive = 0.0
    rank_sum_negative = 0.0
    index = 0
    while index < n:
        j = index
        while j + 1 < n and abs(ranked[j + 1][0] - ranked[index][0]) < 1e-12:
            j += 1
        avg_rank = (index + 1 + j + 1) / 2.0
        for k in range(index, j + 1):
            if ranked[k][1] > 0:
                rank_sum_positive += avg_rank
            else:
                rank_sum_negative += avg_rank
        index = j + 1
    w_stat = min(rank_sum_positive, rank_sum_negative)
    expected = n * (n + 1) / 4.0
    variance = n * (n + 1) * (2 * n + 1) / 24.0
    if variance <= 0:
        return {"w": round(w_stat, 5), "p": 1.0}
    z_value = (w_stat - expected) / math.sqrt(variance)
    p_value = 2.0 * min(_normal_cdf(z_value), 1.0 - _normal_cdf(z_value))
    return {"w": round(w_stat, 5), "p": round(max(0.0, min(1.0, p_value)), 6)}


def _row_latency_ms(row: Dict[str, Any]) -> float:
    latency_ms = _safe_float(row.get("latency_ms"), -1.0)
    if latency_ms >= 0:
        return latency_ms
    metrics = row.get("metrics") or {}
    return _safe_float(metrics.get("latency")) * 60000.0


def _row_cost_usd(row: Dict[str, Any]) -> float:
    raw = _safe_float(row.get("raw_cost_usd"), -1.0)
    if raw >= 0:
        return raw
    metrics = row.get("metrics") or {}
    return _safe_float(metrics.get("cost")) * 0.01


def _row_router_overhead_ms(row: Dict[str, Any]) -> float:
    direct = _safe_float(row.get("router_overhead_ms"), -1.0)
    if direct >= 0:
        return direct
    details = row.get("routing_overhead") or {}
    if isinstance(details, dict):
        nested = _safe_float(details.get("total_ms"), -1.0)
        if nested >= 0:
            return nested
    return 0.0


def build_routerbench(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build a RouterBench report from an experiment payload."""
    rows = payload.get("routerbench_rows") or payload.get("case_results") or []
    strategies = payload.get("strategies") or []
    rows_by_strategy: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strategy = str(row.get("strategy_id") or row.get("strategy") or "unknown")
        rows_by_strategy[strategy].append(row)
    task_risks = {
        str(task.get("id")): max(0.0, min(1.0, _safe_float(task.get("risk"))))
        for task in (payload.get("sampled_task_set") or payload.get("task_set") or [])
    }
    weights = {
        "quality": _safe_float((payload.get("weights") or {}).get("quality"), 0.45),
        "cost": _safe_float((payload.get("weights") or {}).get("cost"), 0.20),
        "latency": _safe_float((payload.get("weights") or {}).get("latency"), 0.15),
        "reliability": _safe_float((payload.get("weights") or {}).get("reliability"), 0.20),
    }
    risk_lambda = max(0.0, _safe_float((payload.get("scoring") or {}).get("risk_lambda"), 1.0))

    benchmark_rows = []
    for strategy in strategies:
        strategy_id = str(strategy.get("id") or strategy.get("name"))
        strategy_rows = rows_by_strategy.get(strategy_id) or rows_by_strategy.get(str(strategy.get("name"))) or []
        summary = dict(strategy.get("summary") or {})
        if strategy_rows:
            qualities = [_safe_float((row.get("metrics") or {}).get("quality")) for row in strategy_rows]
            costs = [_safe_float((row.get("metrics") or {}).get("cost")) for row in strategy_rows]
            latencies = [_safe_float((row.get("metrics") or {}).get("latency")) for row in strategy_rows]
            reliabilities = [_safe_float((row.get("metrics") or {}).get("reliability")) for row in strategy_rows]
            scores = [_safe_float(row.get("score")) for row in strategy_rows]
            summary = {
                "quality": round(mean(qualities), 4),
                "cost": round(mean(costs), 4),
                "latency": round(mean(latencies), 4),
                "reliability": round(mean(reliabilities), 4),
                "utility": round(mean(scores), 5),
            }
        latency_ms = [_row_latency_ms(row) for row in strategy_rows]
        overhead_ms = [_row_router_overhead_ms(row) for row in strategy_rows]
        raw_costs = [_row_cost_usd(row) for row in strategy_rows]
        overhead_ratios = [
            overhead / max(1.0, latency)
            for overhead, latency in zip(overhead_ms, latency_ms)
        ]
        grouped_scores: Dict[str, List[float]] = defaultdict(list)
        for row in strategy_rows:
            grouped_scores[str(row.get("task_type") or "unknown")].append(_safe_float(row.get("score")))
        group_means = {
            key: round(mean(values), 5)
            for key, values in grouped_scores.items()
            if values
        }
        group_values = list(group_means.values())
        robustness_gap = max(group_values) - min(group_values) if len(group_values) >= 2 else 0.0
        quality = _safe_float(summary.get("quality"))
        reliability = _safe_float(summary.get("reliability"))
        cost = _safe_float(summary.get("cost"))
        latency = _safe_float(summary.get("latency"))
        utility = _safe_float(summary.get("utility"))
        row_utilities = [_utility(row.get("metrics") or {}, weights) for row in strategy_rows]
        risk_weights = [1.0 + risk_lambda * task_risks.get(str(row.get("task_id")), 0.0) for row in strategy_rows]
        risk_utility = (sum(value * weight for value, weight in zip(row_utilities, risk_weights)) / sum(risk_weights) if risk_weights else utility)
        success_observations = [
            _safe_float((row.get("metrics") or {}).get("api_availability"), _safe_float((row.get("metrics") or {}).get("reliability")))
            for row in strategy_rows
        ]
        benchmark_rows.append({
            "id": strategy_id,
            "name": strategy.get("name", strategy_id),
            "category": strategy.get("category", "-"),
            "summary": {
                "quality": round(quality, 4),
                "accuracy": round(quality, 4),
                "f1_proxy": round(quality * reliability, 4),
                "bertscore_proxy": round(min(1.0, 0.72 + 0.28 * quality), 4),
                "llm_judge": round(quality, 4),
                "cost": round(cost, 4),
                "avg_cost_usd": round(mean(raw_costs), 8) if raw_costs else 0.0,
                "total_cost_usd": round(sum(raw_costs), 8),
                "latency": round(latency, 4),
                "p50_latency_ms": _percentile(latency_ms, 0.50),
                "p95_latency_ms": _percentile(latency_ms, 0.95),
                "p99_latency_ms": _percentile(latency_ms, 0.99),
                "router_overhead_avg_ms": round(mean(overhead_ms), 3) if overhead_ms else 0.0,
                "router_overhead_p95_ms": _percentile(overhead_ms, 0.95),
                "router_overhead_ratio": round(mean(overhead_ratios), 5) if overhead_ratios else 0.0,
                "reliability": round(reliability, 4),
                "utility": round(utility, 5),
                "risk_weighted_utility": round(risk_utility, 5),
                "utility_ci95": _mean_bootstrap_ci(row_utilities, seed=20260727 + len(benchmark_rows)),
                "failure_rate": round(1.0 - mean(success_observations), 5) if success_observations else 0.0,
                "fallback_rate": round(sum(bool(row.get("fallback_used") or row.get("service_fallback")) for row in strategy_rows) / len(strategy_rows), 5) if strategy_rows else 0.0,
                "quality_per_dollar": round(
                    quality / max(1e-8, mean(raw_costs) if raw_costs else cost * 0.01),
                    4,
                ),
                "robustness_gap": round(robustness_gap, 5),
                "robustness_score": round(max(0.0, 1.0 - robustness_gap), 5),
                "task_count": len(strategy_rows),
                "group_scores": group_means,
            },
        })

    pareto_front = [
        item for item in benchmark_rows
        if not any(_dominates(other, item) for other in benchmark_rows if other is not item)
    ]
    pareto_ids = {item["id"] for item in pareto_front}
    for item in benchmark_rows:
        item["pareto_efficient"] = item["id"] in pareto_ids

    best = max(benchmark_rows, key=lambda item: item["summary"]["utility"], default=None)
    significance = []
    if best:
        best_id = best["id"]
        for item in benchmark_rows:
            if item["id"] == best_id:
                continue
            differences = _paired_by_task(rows_by_strategy, best_id, item["id"])
            if not differences:
                continue
            ci = _bootstrap_ci(differences)
            significance.append({
                "baseline": item["name"],
                "baseline_id": item["id"],
                "n": len(differences),
                "mean_delta": ci["mean"],
                "bootstrap_ci95": [ci["low"], ci["high"]],
                "paired_t": _paired_t_test(differences),
                "wilcoxon": _wilcoxon_signed_rank(differences),
                "significant": bool(ci["low"] > 0 or ci["high"] < 0),
            })

    active_learning = []
    for row in rows:
        scores = sorted(
            (_safe_float(score) for score in (row.get("candidate_scores") or {}).values()),
            reverse=True,
        )
        margin = scores[0] - scores[1] if len(scores) >= 2 else 1.0
        uncertainty = _safe_float(row.get("uncertainty"), max(0.0, 1.0 - margin / 0.25))
        if uncertainty >= 0.65 or margin <= 0.04 or _safe_float(row.get("score")) <= 0.45:
            active_learning.append({
                "task_id": row.get("task_id"),
                "strategy": row.get("strategy"),
                "strategy_id": row.get("strategy_id"),
                "query": row.get("query"),
                "selected_model": row.get("selected_model"),
                "uncertainty": round(uncertainty, 4),
                "score_margin": round(margin, 4),
                "reason": "候选分数接近或路由不确定，建议优先做人工标注或真实多模型评估。",
            })
    active_learning = sorted(
        active_learning,
        key=lambda item: (-item["uncertainty"], item["score_margin"]),
    )[:30]

    sensitivity_profiles = {
        "当前偏好": weights,
        "质量优先": {"quality": 0.60, "cost": 0.10, "latency": 0.10, "reliability": 0.20},
        "成本优先": {"quality": 0.30, "cost": 0.40, "latency": 0.15, "reliability": 0.15},
        "低延迟优先": {"quality": 0.30, "cost": 0.15, "latency": 0.40, "reliability": 0.15},
        "可靠性优先": {"quality": 0.30, "cost": 0.10, "latency": 0.10, "reliability": 0.50},
    }
    sensitivity = []
    for profile_name, profile_weights in sensitivity_profiles.items():
        ranked = []
        for strategy in strategies:
            strategy_id = str(strategy.get("id") or strategy.get("name"))
            strategy_rows = rows_by_strategy.get(strategy_id) or rows_by_strategy.get(str(strategy.get("name"))) or []
            values = [_utility(row.get("metrics") or {}, profile_weights) for row in strategy_rows]
            ranked.append({"id": strategy_id, "name": strategy.get("name", strategy_id), "utility": round(mean(values), 5) if values else 0.0})
        ranked.sort(key=lambda item: item["utility"], reverse=True)
        sensitivity.append({"profile": profile_name, "weights": profile_weights, "winner": ranked[0]["name"] if ranked else "-", "ranking": ranked})

    return {
        "name": "RouterBench",
        "version": "0.1",
        "metric_note": (
            "route-only 模式中的准确率、F1、BERTScore 和 LLM-as-Judge 为可复现实验代理指标；"
            "real-sample 模式会优先使用真实回答、LLM 裁判、真实耗时和真实 token 成本。"
        ),
        "dataset_count": len({str(task.get("dataset") or task.get("type") or "unknown") for task in payload.get("task_set", [])}),
        "task_count": len(payload.get("sampled_task_set") or payload.get("task_set") or []),
        "strategy_count": len(benchmark_rows),
        "best_strategy": best["name"] if best else "-",
        "pareto_front": [{"id": item["id"], "name": item["name"]} for item in pareto_front],
        "strategies": sorted(benchmark_rows, key=lambda item: item["summary"]["utility"], reverse=True),
        "significance": sorted(significance, key=lambda item: item["mean_delta"], reverse=True),
        "risk_lambda": risk_lambda,
        "sensitivity": sensitivity,
        "active_learning": active_learning,
    }


def render_routerbench_markdown(routerbench: Dict[str, Any]) -> List[str]:
    lines = [
        "## RouterBench 统一评估",
        "",
        f"- 任务数：{routerbench.get('task_count', 0)}",
        f"- 策略数：{routerbench.get('strategy_count', 0)}",
        f"- 最优策略：{routerbench.get('best_strategy', '-')}",
        f"- 指标说明：{routerbench.get('metric_note', '-')}",
        "",
        "### RouterBench 指标表",
        "",
        "| 策略 | Pareto | Acc/质量 | F1代理 | BERTScore代理 | 成本$ | P50 ms | P95 ms | 鲁棒性 | 综合效用 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in routerbench.get("strategies", []):
        summary = item.get("summary", {})
        lines.append(
            f"| {item.get('name', '-')} | {'是' if item.get('pareto_efficient') else '否'} | "
            f"{summary.get('accuracy', 0):.3f} | {summary.get('f1_proxy', 0):.3f} | "
            f"{summary.get('bertscore_proxy', 0):.3f} | {summary.get('avg_cost_usd', 0):.8f} | "
            f"{summary.get('p50_latency_ms', 0):.1f} | {summary.get('p95_latency_ms', 0):.1f} | "
            f"{summary.get('robustness_score', 0):.3f} | {summary.get('utility', 0):.4f} |"
        )
    lines.extend([
        "",
        "### 路由器自身开销",
        "",
        "| 策略 | 平均路由开销 ms | P95 路由开销 ms | 路由开销/响应耗时 |",
        "|---|---:|---:|---:|",
    ])
    for item in routerbench.get("strategies", []):
        summary = item.get("summary", {})
        lines.append(
            f"| {item.get('name', '-')} | {summary.get('router_overhead_avg_ms', 0):.2f} | "
            f"{summary.get('router_overhead_p95_ms', 0):.2f} | "
            f"{summary.get('router_overhead_ratio', 0) * 100:.2f}% |"
        )
    lines.extend(["", "### 统计显著性检验", ""])
    if not routerbench.get("significance"):
        lines.append("暂无可配对的逐任务样本，无法进行统计检验。")
    else:
        lines.extend([
            "| 对比基线 | n | 平均提升 | Bootstrap 95% CI | paired t p | Wilcoxon p | 显著 |",
            "|---|---:|---:|---|---:|---:|---|",
        ])
        for item in routerbench.get("significance", [])[:20]:
            ci = item.get("bootstrap_ci95", [0, 0])
            lines.append(
                f"| {item.get('baseline', '-')} | {item.get('n', 0)} | {item.get('mean_delta', 0):.5f} | "
                f"[{ci[0]:.5f}, {ci[1]:.5f}] | "
                f"{item.get('paired_t', {}).get('p', 1):.6f} | "
                f"{item.get('wilcoxon', {}).get('p', 1):.6f} | "
                f"{'是' if item.get('significant') else '否'} |"
            )
    lines.extend(["", "### 主动学习样本池", ""])
    if not routerbench.get("active_learning"):
        lines.append("暂无高不确定性样本。")
    else:
        lines.extend([
            "| 任务 | 策略 | 当前模型 | 不确定性 | 分差 | 说明 |",
            "|---|---|---|---:|---:|---|",
        ])
        for item in routerbench.get("active_learning", [])[:12]:
            lines.append(
                f"| {item.get('task_id', '-')} | {item.get('strategy', '-')} | {item.get('selected_model', '-')} | "
                f"{item.get('uncertainty', 0):.3f} | {item.get('score_margin', 0):.3f} | {item.get('reason', '-')} |"
            )
    return lines
