#!/usr/bin/env python3
"""
Phase 2.1.6: 修复 Safety Oracle 计算方法

发现关键问题：Phase 1 和 Phase 2 使用了不同的 Safety Oracle 计算方法

Phase 1 方法：选择失败率最低的模型，失败率相同时选择可靠性最高的
修复脚本方法：先找出质量 >= 0.5 的安全模型，再选择质量最高的

必须统一使用 Phase 1 的计算方法
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    ROOT.parents[1]
    / "frozen-archives/finance-router-context-v2-1200-final-20260729T072524Z"
    / "run_logs/formal_context_v2_rescored_v22_result.json"
)
MANIFEST_PATH = ROOT / "finrome_v4_split_manifest.json"
PHASE1_REPORT_PATH = ROOT / "run_logs/finrome_v4_phase1_oracle_fix/phase1_oracle_consistency_report.json"

MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo")
QUALITY_THRESHOLD = 0.5


def compute_finrome_utility(
    quality: float,
    cost: float,
    latency: float,
    reliability: float
) -> float:
    """共享效用函数"""
    UTILITY_WEIGHTS = {
        "quality": 0.45,
        "cost": 0.20,
        "latency": 0.15,
        "reliability": 0.20,
    }
    MAX_COST_NORMALIZATION = 0.02
    MAX_LATENCY_NORMALIZATION = 10000

    cost_reward = 1.0 - min(cost / MAX_COST_NORMALIZATION, 1.0)
    latency_reward = 1.0 - min(latency / MAX_LATENCY_NORMALIZATION, 1.0)
    return (
        UTILITY_WEIGHTS["quality"] * quality +
        UTILITY_WEIGHTS["cost"] * cost_reward +
        UTILITY_WEIGHTS["latency"] * latency_reward +
        UTILITY_WEIGHTS["reliability"] * reliability
    )


def compute_failure(quality: float, quality_threshold: float = QUALITY_THRESHOLD) -> bool:
    """共享失败函数"""
    return quality < quality_threshold


def aggregate_3_repeats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """正确聚合3次重复"""
    if not runs:
        return {}

    if len(runs) != 3:
        raise ValueError(f"期望3次重复，实际得到 {len(runs)} 次")

    quality_values = [r.get("quality") for r in runs if r.get("quality") is not None]
    if len(quality_values) != 3:
        raise ValueError(f"期望3个质量值，实际得到 {len(quality_values)} 个")

    cost_values = [r.get("raw_cost_usd", 0.0) for r in runs]
    latency_values = [r.get("latency_ms", 0) for r in runs]

    failure_statuses = [compute_failure(q, QUALITY_THRESHOLD) for q in quality_values]
    failure_rate = sum(failure_statuses) / 3.0

    aggregated = {
        "quality": float(np.mean(quality_values)),
        "quality_std": float(np.std(quality_values)),
        "quality_values": quality_values,
        "cost": float(np.mean(cost_values)),
        "cost_std": float(np.std(cost_values)),
        "latency": float(np.mean(latency_values)),
        "latency_std": float(np.std(latency_values)),
        "reliability": 1.0 - failure_rate,
        "failed": failure_rate,
        "failed_rate": failure_rate,  # 关键：Phase 1 使用 failed_rate
        "n_repeats": 3,
        "repeat_failures": failure_statuses,
    }

    aggregated["utility"] = compute_finrome_utility(
        aggregated["quality"],
        aggregated["cost"],
        aggregated["latency"],
        aggregated["reliability"]
    )

    return aggregated


def compute_safety_oracle_phase1_method(task_outcomes: dict[str, dict[str, Any]]) -> str:
    """
    Phase 1 的 Safety Oracle 计算方法

    选择失败率最低的模型；如果失败率相同，选择可靠性最高的
    """
    return min(
        MODELS,
        key=lambda m: (task_outcomes[m]["failed_rate"], -task_outcomes[m]["reliability"])
    )


def main():
    print("=" * 80)
    print("PHASE 2.1.6: 修复 Safety Oracle 计算方法")
    print("=" * 80)

    # 加载数据
    print("\n📂 加载数据...")
    source_data = json.loads(DEFAULT_SOURCE.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    phase1_report = json.loads(PHASE1_REPORT_PATH.read_text(encoding="utf-8"))

    calibration_ids = manifest["split_definition"]["validation"]

    # 组织数据
    from collections import defaultdict
    by_task_model = defaultdict(list)
    for row in source_data["raw_model_runs"]:
        by_task_model[(row["task_id"], row["model"])].append(row)

    # 聚合校准数据
    print("📊 聚合校准数据...")
    calibration_utilities = {}
    for tid in calibration_ids:
        calibration_utilities[tid] = {}
        for model in MODELS:
            runs = by_task_model.get((tid, model), [])
            if runs:
                try:
                    calibration_utilities[tid][model] = aggregate_3_repeats(runs)
                except Exception as e:
                    print(f"   ⚠️  聚合失败 {tid}-{model}: {e}")
                    calibration_utilities[tid][model] = None

    # 使用 Phase 1 方法计算 Safety Oracle
    print("\n🔧 使用 Phase 1 方法计算 Safety Oracle...")
    safety_oracles_phase1_method = {}
    safety_oracle_failures = 0

    for tid in calibration_ids:
        task_outcomes = calibration_utilities[tid]
        safety_oracle = compute_safety_oracle_phase1_method(task_outcomes)

        # 检查 Safety Oracle 是否失败
        if task_outcomes[safety_oracle]["quality"] < QUALITY_THRESHOLD:
            safety_oracle_failures += 1

        safety_oracles_phase1_method[tid] = safety_oracle

    safety_failure_rate = safety_oracle_failures / len(calibration_ids)

    print(f"📊 使用 Phase 1 方法的 Safety Oracle:")
    print(f"   失败率: {safety_failure_rate:.1%} ({safety_oracle_failures}/{len(calibration_ids)})")

    # 与 Phase 1 报告比较
    phase1_safety_failures = sum(
        1 for detail in phase1_report["raw_task_details"]
        if detail["safety_oracle_failed"]
    )
    phase1_safety_rate = phase1_safety_failures / len(phase1_report["raw_task_details"])

    print(f"\n📊 Phase 1 报告中的 Safety Oracle:")
    print(f"   失败率: {phase1_safety_rate:.1%} ({phase1_safety_failures}/{len(phase1_report['raw_task_details'])})")

    # 检查一致性
    if abs(safety_failure_rate - phase1_safety_rate) < 1e-6:
        print(f"\n✅ SUCCESS: Safety Oracle 计算方法已修复，现在与 Phase 1 一致！")
    else:
        print(f"\n❌ 仍然存在差异：{safety_failure_rate:.1%} vs {phase1_safety_rate:.1%}")

    # 逐任务比较
    print("\n🔍 逐任务比较 Safety Oracle 选择...")
    phase1_oracles = {
        detail["task_id"]: detail["safety_oracle_model"]
        for detail in phase1_report["raw_task_details"]
    }

    inconsistencies = []
    for tid in calibration_ids:
        if safety_oracles_phase1_method[tid] != phase1_oracles.get(tid):
            inconsistencies.append({
                "task_id": tid,
                "recomputed": safety_oracles_phase1_method[tid],
                "phase1_report": phase1_oracles.get(tid)
            })

    if inconsistencies:
        print(f"   ⚠️  发现 {len(inconsistencies)} 个任务不一致:")
        for inc in inconsistencies[:5]:  # 只显示前5个
            print(f"      {inc['task_id'][:30]}...: 重计算={inc['recomputed']}, Phase1={inc['phase1_report']}")
    else:
        print(f"   ✅ 所有任务的 Safety Oracle 选择完全一致！")

    # 保存修复结果
    result = {
        "report_type": "safety_oracle_method_fix",
        "generated_at": "2026-08-18T15:30:00Z",
        "fix_applied": "统一使用 Phase 1 的 Safety Oracle 计算方法",
        "phase1_method": "选择失败率最低的模型；失败率相同时选择可靠性最高的",
        "results": {
            "recomputed_safety_failure_rate": safety_failure_rate,
            "phase1_report_failure_rate": phase1_safety_rate,
            "consistent": abs(safety_failure_rate - phase1_safety_rate) < 1e-6,
            "inconsistent_tasks": len(inconsistencies)
        },
        "task_level_comparison": inconsistencies
    }

    output_path = ROOT / "run_logs/finrome_v4_phase2_fixed/safety_oracle_method_fix.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f"\n✅ 修复结果保存到 {output_path}")

    print("\n" + "=" * 80)
    print("PHASE 2.1.6 Safety Oracle 方法修复完成")
    print("=" * 80)

    if abs(safety_failure_rate - phase1_safety_rate) < 1e-6 and len(inconsistencies) == 0:
        print("✅ 修复成功：Safety Oracle 计算现在与 Phase 1 完全一致")
        print("✅ 可以继续进行 Phase 2 修复")
    else:
        print("❌ 修复失败：仍然存在不一致性")
        print("❌ 需要进一步调查")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()