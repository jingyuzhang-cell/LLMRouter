#!/usr/bin/env python3
"""
Phase 2.1.8: 完全正确的 Safety Oracle 修复

关键发现：
Phase 1 的 failed 定义 = (failed_rate > 0)，即只要有一次重复失败就算失败
不是 = (平均质量 < 0.5)

所以：
- glm-5.2: 质量=0.644, failed_rate=0.33 → failed=True (因为有1/3次重复失败)
- all_failed = 所有模型的 failed_rate > 0
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
from collections import defaultdict

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


def compute_finrome_utility(quality: float, cost: float, latency: float, reliability: float) -> float:
    """共享效用函数"""
    UTILITY_WEIGHTS = {"quality": 0.45, "cost": 0.20, "latency": 0.15, "reliability": 0.20}
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


def aggregate_3_repeats_phase1_logic(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """
    完全按照 Phase 1 逻辑聚合3次重复
    """
    if not runs:
        return {}

    if len(runs) != 3:
        raise ValueError(f"期望3次重复，实际得到 {len(runs)} 次")

    quality_values = [r.get("quality") for r in runs if r.get("quality") is not None]
    if len(quality_values) != 3:
        raise ValueError(f"期望3个质量值，实际得到 {len(quality_values)} 个")

    cost_values = [r.get("raw_cost_usd", 0.0) for r in runs]
    latency_values = [r.get("latency_ms", 0) for r in runs]

    # 计算每次重复的失败状态
    failure_statuses = [q < QUALITY_THRESHOLD for q in quality_values]
    failure_rate = sum(failure_statuses) / 3.0

    return {
        "quality": float(np.mean(quality_values)),
        "quality_std": float(np.std(quality_values)),
        "quality_values": quality_values,
        "cost": float(np.mean(cost_values)),
        "latency": float(np.mean(latency_values)),
        "reliability": 1.0 - failure_rate,
        "failed": failure_rate,  # 关键：这是 failed_rate，不是布尔值
        "failed_rate": failure_rate,
        "n_repeats": 3,
        "repeat_failures": failure_statuses,
    }


def main():
    print("=" * 80)
    print("PHASE 2.1.8: 完全正确的 Safety Oracle 修复")
    print("=" * 80)

    # 加载数据
    print("\n📂 加载数据...")
    source_data = json.loads(DEFAULT_SOURCE.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    phase1_report = json.loads(PHASE1_REPORT_PATH.read_text(encoding="utf-8"))

    calibration_ids = manifest["split_definition"]["validation"]

    # 组织数据
    by_task_model = defaultdict(list)
    for row in source_data["raw_model_runs"]:
        by_task_model[(row["task_id"], row["model"])].append(row)

    # 使用 Phase 1 逻辑聚合
    print("📊 使用 Phase 1 逻辑聚合校准数据...")
    calibration_utilities = {}
    for tid in calibration_ids:
        calibration_utilities[tid] = {}
        for model in MODELS:
            runs = by_task_model.get((tid, model), [])
            if runs:
                try:
                    aggregated = aggregate_3_repeats_phase1_logic(runs)
                    # 计算效用
                    aggregated["utility"] = compute_finrome_utility(
                        aggregated["quality"],
                        aggregated["cost"],
                        aggregated["latency"],
                        aggregated["reliability"]
                    )
                    calibration_utilities[tid][model] = aggregated
                except Exception as e:
                    print(f"   ⚠️  聚合失败 {tid}-{model}: {e}")

    # 使用 Phase 1 完整逻辑计算 Safety Oracle
    print("\n🔧 使用 Phase 1 完整逻辑计算 Safety Oracle...")
    safety_oracle_results = []
    safety_oracle_failures = 0

    for tid in calibration_ids:
        task_outcomes = calibration_utilities[tid]

        # Phase 1 的 Safety Oracle 选择逻辑
        safety_oracle = min(
            MODELS,
            key=lambda m: (task_outcomes[m]["failed_rate"], -task_outcomes[m]["reliability"])
        )

        # Phase 1 的 all_failed 逻辑
        all_failed = all(task_outcomes[m]["failed"] > 0 for m in MODELS)

        # Phase 1 的 safety_oracle_failed 逻辑
        # 如果所有模型都失败，Safety Oracle 也失败
        # 或者 Safety Oracle 的 failed_rate > 0
        safety_oracle_failed = all_failed or (task_outcomes[safety_oracle]["failed"] > 0)

        if safety_oracle_failed:
            safety_oracle_failures += 1

        safety_oracle_results.append({
            "task_id": tid,
            "safety_oracle": safety_oracle,
            "safety_oracle_failed": safety_oracle_failed,
            "all_models_failed": all_failed,
            "safety_oracle_quality": task_outcomes[safety_oracle]["quality"],
            "safety_oracle_failed_rate": task_outcomes[safety_oracle]["failed_rate"]
        })

    safety_failure_rate = safety_oracle_failures / len(calibration_ids)

    print(f"📊 使用 Phase 1 完整逻辑的 Safety Oracle:")
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
        print(f"\n✅✅✅ SUCCESS: Safety Oracle 失败率现在与 Phase 1 完全一致！")
    else:
        print(f"\n❌ 仍然存在差异：{safety_failure_rate:.1%} vs {phase1_safety_rate:.1%}")

    # 逐任务比较
    print("\n🔍 逐任务比较 Safety Oracle...")
    phase1_oracles = {
        detail["task_id"]: {
            "model": detail["safety_oracle_model"],
            "failed": detail["safety_oracle_failed"]
        }
        for detail in phase1_report["raw_task_details"]
    }

    inconsistencies = []
    for result in safety_oracle_results:
        tid = result["task_id"]
        phase1_data = phase1_oracles.get(tid)

        if phase1_data:
            if result["safety_oracle"] != phase1_data["model"] or result["safety_oracle_failed"] != phase1_data["failed"]:
                inconsistencies.append({
                    "task_id": tid,
                    "recomputed_model": result["safety_oracle"],
                    "phase1_model": phase1_data["model"],
                    "recomputed_failed": result["safety_oracle_failed"],
                    "phase1_failed": phase1_data["failed"],
                    "recomputed_quality": result["safety_oracle_quality"],
                    "recomputed_failed_rate": result["safety_oracle_failed_rate"],
                    "all_models_failed": result["all_models_failed"]
                })

    if inconsistencies:
        print(f"   ⚠️  发现 {len(inconsistencies)} 个任务不一致:")
        for inc in inconsistencies:
            print(f"      {inc['task_id'][:30]}...")
            print(f"         模型: 重计算={inc['recomputed_model']}, Phase1={inc['phase1_model']}")
            print(f"         失败: 重计算={inc['recomputed_failed']}, Phase1={inc['phase1_failed']}")
            print(f"         质量: {inc['recomputed_quality']:.6f}, 失败率: {inc['recomputed_failed_rate']:.2f}")
            print(f"         所有失败: {inc['all_models_failed']}")
    else:
        print(f"   ✅ 所有任务的 Safety Oracle 完全一致！")

    # 分析关键发现
    print(f"\n🔍 关键发现:")
    print(f"   Phase 1 的 failed 定义 = (failed_rate > 0)")
    print(f"   即：只要有一次重复失败就算失败，不是基于平均质量")
    print(f"   这解释了为什么 glm-5.2 (质量=0.644, 失败率=0.33) 被标记为 failed=True")

    # 保存最终正确结果
    final_result = {
        "report_type": "safety_oracle_correct_fix",
        "generated_at": "2026-08-18T15:40:00Z",
        "key_discovery": "Phase 1 的 failed 定义 = (failed_rate > 0)，不是 (quality < 0.5)",
        "phase1_logic": {
            "failed_definition": "failed_rate > 0 (只要有一次重复失败就算失败)",
            "all_failed_definition": "所有模型的 failed_rate > 0",
            "safety_oracle_failed": "all_failed OR (safety_oracle.failed_rate > 0)"
        },
        "results": {
            "recomputed_safety_failure_rate": safety_failure_rate,
            "phase1_report_failure_rate": phase1_safety_rate,
            "consistent": abs(safety_failure_rate - phase1_safety_rate) < 1e-6,
            "inconsistent_tasks": len(inconsistencies)
        },
        "task_level_comparison": inconsistencies
    }

    output_path = ROOT / "run_logs/finrome_v4_phase2_fixed/safety_oracle_correct_fix.json"
    output_path.write_text(json.dumps(final_result, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f"\n✅ 最终正确修复结果保存到 {output_path}")

    print("\n" + "=" * 80)
    print("PHASE 2.1.8 最终正确修复完成")
    print("=" * 80)

    if abs(safety_failure_rate - phase1_safety_rate) < 1e-6 and len(inconsistencies) == 0:
        print("✅✅✅ 完全成功！Safety Oracle 现在与 Phase 1 完全一致")
        print("✅ 关键发现：Phase 1 的 failed 定义基于 failed_rate > 0")
        print("✅ 现在可以基于此正确逻辑重新运行完整的 Phase 2")
        print("✅ 这将解决 Safety Oracle 15% vs 5% 的矛盾")
    else:
        print("❌ 修复失败：仍然存在不一致性")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()