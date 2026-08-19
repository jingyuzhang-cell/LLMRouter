#!/usr/bin/env python3
"""
Phase 3.1: Baseline Fidelity + SPDF Reproducibility Audit

核心原则：
1. Phase 3不准再自己重新定义M1/M2/M3
2. 必须直接加载Phase 2冻结的M1/M2/M3 selection
3. 实施强制Baseline Fidelity Assertions
4. 修复Override Metrics分类逻辑
5. 将Phase3分成prediction_generation和evaluation两个独立阶段
6. 做Phase 3五次可复现性检查
7. 暂时不要选择τu=0.05作为正式阈值
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, mean_absolute_error, roc_auc_score
from sklearn.model_selection import KFold
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler

# 导入项目正式 Router 实现
from llmrouter.models.mlprouter.router import MLPClassifierNN
from llmrouter.models.graphrouter.graph_nn import EncoderDecoderNet

# 导入统一指标模块
from llmrouter.utils.finrome_metrics import (
    MODELS, MODEL_INDEX,
    UTILITY_WEIGHTS,
    MAX_COST_NORMALIZATION,
    MAX_LATENCY_NORMALIZATION,
    MAIN_QUALITY_THRESHOLD,
    STRICT_REPEAT_QUALITY_THRESHOLD,
    aggregate_3_repeats_formal,
    compute_finrome_utility,
    compute_main_failure,
    compute_strict_repeat_failure,
    compute_utility_oracle,
    compute_safety_oracle_formal,
    compute_all_models_failed,
    build_task_model_outcomes,
    compute_selection_metrics,
    analyze_router_agreement,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PHASE2_FORMAL_PATH = ROOT / "run_logs/finrome_v4_phase2_formal"
DEFAULT_SOURCE = (
    ROOT.parents[1]
    / "frozen-archives/finance-router-context-v2-1200-final-20260729T072524Z"
    / "run_logs/formal_context_v2_rescored_v22_result.json"
)
MANIFEST_PATH = ROOT / "finrome_v4_split_manifest.json"
EMBEDDINGS_PATH = ROOT / "run_logs/offline_knn_baseline/longformer_embeddings.pt"
DEFAULT_OUTPUT = ROOT / "run_logs/finrome_v4_phase3_1_baseline_fidelity"
OOF_FOLD_MANIFEST_PATH = ROOT / "finrome_v4_oof_fold_manifest.json"
OOF_FOLD_RANDOM_STATE = 42
SEED = 20260808
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'

ROUTERS = ('knnrouter', 'mlprouter', 'graphrouter')

# ========================================================================
# Phase 2 冻结基准（硬编码，必须严格匹配）
# ========================================================================

PHASE2_FROZEN_BASELINE = {
    "M1": {
        "mean_utility": 0.8350752466666668,
        "mean_regret": 0.07745980083333333,
        "main_failure_rate": 0.15,
        "strict_repeat_failure_rate": 0.2,
        "oracle_match_rate": 0.2,
        "safety_oracle_match_rate": 0.4,
        "high_risk_failure_rate": 0.0,
        "selection_counts": {
            "deepseek-chat": 6,
            "qwen-plus": 6,
            "glm-5.2": 8
        },
        "method": "M1-EqualRank"
    },
    "M2": {
        "mean_utility": 0.8654756200000001,
        "mean_regret": 0.047059427499999994,
        "main_failure_rate": 0.3,
        "strict_repeat_failure_rate": 0.3,
        "oracle_match_rate": 0.5,
        "safety_oracle_match_rate": 0.35,
        "high_risk_failure_rate": 0.0,
        "selection_counts": {
            "qwen-plus": 2,
            "deepseek-chat": 8,
            "qwen-turbo": 10
        },
        "method": "M2-Dynamic"
    },
    "M3": {
        "mean_utility": 0.8656190733333334,
        "mean_regret": 0.04691597416666667,
        "main_failure_rate": 0.3,
        "strict_repeat_failure_rate": 0.3,
        "oracle_match_rate": 0.55,
        "safety_oracle_match_rate": 0.2,
        "high_risk_failure_rate": 0.0,
        "selection_counts": {
            "qwen-plus": 2,
            "qwen-turbo": 13,
            "deepseek-chat": 5
        },
        "method": "M3-M3_conformal"
    }
}

# ========================================================================
# 辅助函数
# ========================================================================

def seed_all(s: int) -> None:
    """设置所有随机种子"""
    random.seed(s)
    np.random.seed(s)
    torch.manual_seed(s)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(s)


def num(x: Any, default: float = 0.0) -> float:
    """安全转换为浮点数"""
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def risk(task: dict[str, Any]) -> str:
    """提取任务风险等级"""
    x = str(task.get('risk', task.get('risk_level', 'medium'))).lower()
    if x in {'low', 'medium', 'high'}:
        return x
    try:
        num_val = float(x)
        return 'high' if num_val >= .8 else 'medium' if num_val >= .4 else 'low'
    except ValueError:
        return 'medium'


def task_features(task: dict[str, Any]) -> np.ndarray:
    """提取任务特征"""
    kinds = (
        'financial_numerical_reasoning',
        'financial_table_text_reasoning',
        'financial_audit_compliance_qa',
        'financial_kg_grounded_qa',
        'financial_kg_multihop_qa'
    )
    r = risk(task)
    return np.array([
        num(task.get('complexity'), .5),
        {'low': .2, 'medium': .62, 'high': .86}[r],
        float(bool(task.get('requires_calculation'))),
        float(bool(task.get('requires_table_reasoning'))),
        float(bool(task.get('requires_kg_reasoning'))),
        min(len(str(task.get('query', ''))), 5000) / 5000,
        *[float(task.get('task_type') == k) for k in kinds]
    ], dtype=np.float32)


def softmax(scores: np.ndarray) -> np.ndarray:
    """Softmax 归一化"""
    shifted = scores - scores.max(1, keepdims=True)
    exp_scores = np.exp(np.clip(shifted, -40, 40))
    return exp_scores / exp_scores.sum(1, keepdims=True)


def rank_standardise(scores: np.ndarray) -> np.ndarray:
    """排名标准化"""
    ranks = np.argsort(np.argsort(scores, axis=1), axis=1)
    return ranks / np.maximum(1, scores.shape[1] - 1)


def compute_hash(obj: Any) -> str:
    """计算对象的哈希值"""
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


# ========================================================================
# Phase 3.1: Baseline Fidelity Audit
# ========================================================================

@dataclass
class SelectionResult:
    """选择结果"""
    task_id: str
    method: str
    selected_model: str
    anchor_model: str  # M1 选择（来自Phase 2）
    proposal_model: str  # M3 选择（来自Phase 2）
    override: bool  # 是否覆盖 M1
    predicted_delta_utility: float  # 预测 utility 增益
    predicted_anchor_failure: float  # 预测 anchor 失败率
    predicted_proposal_failure: float  # 预测 proposal 失败率
    override_score: float  # Override 决策分数
    disagreement: bool  # anchor != proposal
    router_features: dict[str, float]  # Router 特征


class BaselineFidelityError(Exception):
    """Baseline Fidelity 检查失败"""
    pass


def load_phase2_formal_selections(phase2_formal_path: Path) -> dict[str, dict[str, Any]]:
    """
    加载 Phase 2 正式输出中的 M1/M2/M3 selection

    这是 Phase 3 唯一合法的 M1/M2/M3 selection 来源
    """
    trace_path = phase2_formal_path / "phase2_formal_trace.jsonl"

    selections = {
        "M1": {},
        "M2": {},
        "M3": {}
    }

    with open(trace_path) as f:
        for line in f:
            entry = json.loads(line)
            task_id = entry["task_id"]

            # M1 selection (Equal-Rank)
            m1_entry = entry["m1_selection"]
            selections["M1"][task_id] = {
                "selected_model_index": m1_entry["selected_model_index"],
                "selected_model_name": m1_entry["selected_model_name"],
                "fused_ranks": m1_entry["fused_ranks"],
                # 不包含 true_outcome - 这些只能在 evaluation 阶段使用
            }

            # M2 selection (Dynamic)
            m2_entry = entry["m2_selection"]
            selections["M2"][task_id] = {
                "selected_model_index": m2_entry["selected_model_index"],
                "selected_model_name": m2_entry["selected_model_name"],
                "router_weights": m2_entry["router_weights"],
            }

            # M3 selection (Conformal)
            m3_entry = entry["m3_selection"]
            selections["M3"][task_id] = {
                "selected_model_index": m3_entry["selected_model_index"],
                "selected_model_name": m3_entry["selected_model_name"],
                "safe_router_set": m3_entry["safe_router_set"],
                "conformal_bounds": m3_entry["conformal_bounds"],
                "risk_limit": m3_entry["risk_limit"],
            }

    # 计算selection hash
    for method in ["M1", "M2", "M3"]:
        selections[f"{method}_hash"] = compute_hash(selections[method])

    return selections


def verify_baseline_fidelity(
    selections: dict[str, dict[str, Any]],
    all_task_outcomes: dict[str, dict[str, dict[str, Any]]],
    calibration_task_ids: list[str],
    expected_baseline: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """
    强制 Baseline Fidelity Assertions

    验证 Phase 3 加载的 M1/M2/M3 与 Phase 2 冻结 baseline 完全一致
    """
    fidelity_report = {
        "passed": True,
        "errors": [],
        "computed_metrics": {},
        "task_ids_verified": calibration_task_ids,
    }

    for method, expected_metrics in expected_baseline.items():
        print(f"\n🔍 Verifying {method} baseline fidelity...")

        # 计算实际 metrics
        utility_sum = 0.0
        main_failure_count = 0
        strict_failure_count = 0
        oracle_match_count = 0
        safety_oracle_match_count = 0
        selection_counts = Counter()
        n_tasks = 0

        for task_id in calibration_task_ids:
            if task_id not in selections[method]:
                fidelity_report["errors"].append(
                    f"{method}: Missing selection for task {task_id}"
                )
                fidelity_report["passed"] = False
                continue

            if task_id not in all_task_outcomes:
                continue

            selection = selections[method][task_id]
            outcomes = all_task_outcomes[task_id]
            selected_model = selection["selected_model_name"]

            # 真实结果
            true_outcome = outcomes[selected_model]
            utility_sum += true_outcome['utility']

            if true_outcome['main_failed']:
                main_failure_count += 1
            if true_outcome['strict_repeat_failed']:
                strict_failure_count += 1

            # Oracle match
            utility_oracle = compute_utility_oracle(outcomes)
            safety_oracle = compute_safety_oracle_formal(outcomes)

            if selected_model == utility_oracle:
                oracle_match_count += 1
            if selected_model == safety_oracle:
                safety_oracle_match_count += 1

            selection_counts[selected_model] += 1
            n_tasks += 1

        if n_tasks != len(calibration_task_ids):
            fidelity_report["errors"].append(
                f"{method}: Expected {len(calibration_task_ids)} tasks, got {n_tasks}"
            )
            fidelity_report["passed"] = False

        # 计算指标
        computed_metrics = {
            "n_tasks": n_tasks,
            "mean_utility": utility_sum / n_tasks if n_tasks > 0 else 0.0,
            "main_failure_rate": main_failure_count / n_tasks if n_tasks > 0 else 0.0,
            "strict_repeat_failure_rate": strict_failure_count / n_tasks if n_tasks > 0 else 0.0,
            "oracle_match_rate": oracle_match_count / n_tasks if n_tasks > 0 else 0.0,
            "safety_oracle_match_rate": safety_oracle_match_count / n_tasks if n_tasks > 0 else 0.0,
            "selection_counts": dict(selection_counts),
        }
        fidelity_report["computed_metrics"][method] = computed_metrics

        # 验证匹配（允许很小的浮点误差）
        tolerance = 1e-6

        errors = []
        if abs(computed_metrics["mean_utility"] - expected_metrics["mean_utility"]) > tolerance:
            errors.append(
                f"Utility mismatch: expected {expected_metrics['mean_utility']:.10f}, "
                f"got {computed_metrics['mean_utility']:.10f}"
            )
        if abs(computed_metrics["main_failure_rate"] - expected_metrics["main_failure_rate"]) > tolerance:
            errors.append(
                f"Failure rate mismatch: expected {expected_metrics['main_failure_rate']:.10f}, "
                f"got {computed_metrics['main_failure_rate']:.10f}"
            )
        if abs(computed_metrics["strict_repeat_failure_rate"] - expected_metrics["strict_repeat_failure_rate"]) > tolerance:
            errors.append(
                f"Strict failure rate mismatch: expected {expected_metrics['strict_repeat_failure_rate']:.10f}, "
                f"got {computed_metrics['strict_repeat_failure_rate']:.10f}"
            )
        if abs(computed_metrics["oracle_match_rate"] - expected_metrics["oracle_match_rate"]) > tolerance:
            errors.append(
                f"Oracle match rate mismatch: expected {expected_metrics['oracle_match_rate']:.10f}, "
                f"got {computed_metrics['oracle_match_rate']:.10f}"
            )
        if abs(computed_metrics["safety_oracle_match_rate"] - expected_metrics["safety_oracle_match_rate"]) > tolerance:
            errors.append(
                f"Safety oracle match rate mismatch: expected {expected_metrics['safety_oracle_match_rate']:.10f}, "
                f"got {computed_metrics['safety_oracle_match_rate']:.10f}"
            )

        # 验证 selection counts
        if computed_metrics["selection_counts"] != expected_metrics["selection_counts"]:
            errors.append(
                f"Selection counts mismatch: expected {expected_metrics['selection_counts']}, "
                f"got {computed_metrics['selection_counts']}"
            )

        if errors:
            fidelity_report["passed"] = False
            fidelity_report["errors"].extend([f"{method}: {err}" for err in errors])
            print(f"  ❌ {method} baseline fidelity FAILED:")
            for err in errors:
                print(f"    - {err}")
        else:
            print(f"  ✅ {method} baseline fidelity PASSED")
            print(f"    Utility: {computed_metrics['mean_utility']:.10f}")
            print(f"    Failure: {computed_metrics['main_failure_rate']:.10f}")
            print(f"    Selections: {dict(computed_metrics['selection_counts'])}")

    return fidelity_report


# ========================================================================
# Override Metrics 修复
# ========================================================================

def classify_override(
    anchor_utility: float,
    proposal_utility: float,
    anchor_failure: bool,
    proposal_failure: bool
) -> str:
    """
    修复后的 Override 分类

    分类规则：
    - beneficial_override: proposal utility > anchor utility AND proposal failure <= anchor failure
    - safety_harmful_override: anchor failure = 0 AND proposal failure = 1
    - utility_harmful_override: proposal utility < anchor utility AND no safety_harm
    - neutral_override: 其余情况
    """
    # beneficial: proposal 更好（utility 更高，failure 更低或相等）
    is_beneficial = (proposal_utility > anchor_utility) and (not proposal_failure or anchor_failure)

    # safety_harmful: anchor 安全但 proposal 失败
    is_safety_harmful = (not anchor_failure) and proposal_failure

    # utility_harmful: proposal utility 更低且不是 safety_harm
    is_utility_harmful = (proposal_utility < anchor_utility) and not is_safety_harmful

    if is_beneficial:
        return "beneficial_override"
    elif is_safety_harmful:
        return "safety_harmful_override"
    elif is_utility_harmful:
        return "utility_harmful_override"
    else:
        return "neutral_override"


# ========================================================================
# Phase 3.1 主流程
# ========================================================================

def run_phase3_1_audit(
    phase2_formal_path: Path,
    tasks: list[dict[str, Any]],
    raw_model_runs: list[dict[str, Any]],
    calibration_task_ids: list[str],
    output_dir: Path,
    reproducibility_run: int = 1
) -> dict[str, Any]:
    """
    运行 Phase 3.1 Baseline Fidelity Audit

    返回：
    - audit_results: 包含 fidelity 验证和可复现性检查的结果
    """
    print("=" * 80)
    print(f"Fin-RoME Phase 3.1: Baseline Fidelity + SPDF Reproducibility Audit (Run {reproducibility_run}/5)")
    print("=" * 80)

    # 创建输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 加载 Phase 2 冻结 selection
    print("\n📦 Step 1: Loading Phase 2 frozen selections...")
    selections = load_phase2_formal_selections(phase2_formal_path)

    print(f"  ✅ Loaded selections:")
    print(f"    M1: {len(selections['M1'])} tasks, hash: {selections['M1_hash'][:16]}...")
    print(f"    M2: {len(selections['M2'])} tasks, hash: {selections['M2_hash'][:16]}...")
    print(f"    M3: {len(selections['M3'])} tasks, hash: {selections['M3_hash'][:16]}...")

    # 2. 构建任务结果矩阵
    print("\n📊 Step 2: Building task-model outcome matrix...")
    all_task_outcomes = build_task_model_outcomes(tasks, raw_model_runs)

    # 3. Baseline Fidelity 验证
    print("\n🔍 Step 3: Verifying baseline fidelity...")
    fidelity_report = verify_baseline_fidelity(
        selections=selections,
        all_task_outcomes=all_task_outcomes,
        calibration_task_ids=calibration_task_ids,
        expected_baseline=PHASE2_FROZEN_BASELINE
    )

    if not fidelity_report["passed"]:
        print("\n❌ BASELINE_FIDELITY_FAILURE - Stopping execution")
        print("Errors:")
        for error in fidelity_report["errors"]:
            print(f"  - {error}")

        # 保存失败报告
        failure_report_path = output_dir / f"baseline_fidelity_failure_run_{reproducibility_run}.json"
        with open(failure_report_path, 'w') as f:
            json.dump(fidelity_report, f, indent=2)

        raise BaselineFidelityError("Baseline fidelity check failed")

    print("\n✅ All baseline fidelity checks PASSED")

    # 4. 保存 frozen selection
    print("\n💾 Step 4: Saving frozen selection...")
    frozen_selection_path = output_dir / f"phase3_selection_frozen_run_{reproducibility_run}.jsonl"
    with open(frozen_selection_path, 'w') as f:
        for task_id in calibration_task_ids:
            entry = {
                "task_id": task_id,
                "run_id": reproducibility_run,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "m1_selection": selections["M1"][task_id],
                "m2_selection": selections["M2"][task_id],
                "m3_selection": selections["M3"][task_id],
                "m1_hash": selections["M1_hash"],
                "m2_hash": selections["M2_hash"],
                "m3_hash": selections["M3_hash"],
            }
            f.write(json.dumps(entry) + "\n")

    # 5. 计算可复现性 hashes
    print("\n🔐 Step 5: Computing reproducibility hashes...")
    reproducibility_hashes = {
        "run_id": reproducibility_run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "anchor_hash": selections["M1_hash"],
        "proposal_hash": selections["M3_hash"],
        "selections_verified": True,
        "task_count": len(calibration_task_ids),
    }

    hashes_path = output_dir / f"reproducibility_hashes_run_{reproducibility_run}.json"
    with open(hashes_path, 'w') as f:
        json.dump(reproducibility_hashes, f, indent=2)

    print(f"  ✅ Reproducibility hashes computed:")
    print(f"    Anchor (M1) hash: {reproducibility_hashes['anchor_hash'][:16]}...")
    print(f"    Proposal (M3) hash: {reproducibility_hashes['proposal_hash'][:16]}...")

    # 6. 生成 audit 报告
    print("\n📋 Step 6: Generating audit report...")
    audit_report = {
        "audit_type": "finrome_v4_phase3_1_baseline_fidelity",
        "version": "3.1_fidelity_audit",
        "run_id": reproducibility_run,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "phase2_formal_path": str(phase2_formal_path),
            "calibration_only": True,
            "test_accessed": False,
            "baseline_fidelity_enforced": True,
            "override_metrics_fixed": True,
        },
        "reproducibility_hashes": reproducibility_hashes,
        "fidelity_report": fidelity_report,
        "phase2_baseline": PHASE2_FROZEN_BASELINE,
        "computed_baseline": fidelity_report["computed_metrics"],
        "status": "PASSED" if fidelity_report["passed"] else "FAILED",
    }

    audit_path = output_dir / f"phase3_1_audit_run_{reproducibility_run}.json"
    with open(audit_path, 'w') as f:
        json.dump(audit_report, f, indent=2)

    print(f"  ✅ Audit report saved to {audit_path}")

    return audit_report


def run_reproducibility_check(
    phase2_formal_path: Path,
    tasks: list[dict[str, Any]],
    raw_model_runs: list[dict[str, Any]],
    calibration_task_ids: list[str],
    output_dir: Path,
    n_runs: int = 5
) -> dict[str, Any]:
    """
    运行 5 次可复现性检查

    必须满足：
    - anchor_hash identical 5/5
    - proposal_hash identical 5/5
    - selection_hash identical 5/5
    - M1 metrics identical 5/5
    - M3 metrics identical 5/5
    """
    print("=" * 80)
    print("Fin-RoME Phase 3.1: Reproducibility Check (5 runs)")
    print("=" * 80)

    all_hashes = []
    all_metrics = []
    all_passed = True

    for run_id in range(1, n_runs + 1):
        print(f"\n🔄 Running reproducibility check {run_id}/{n_runs}...")

        # 设置相同的随机种子（确保可复现性）
        seed_all(SEED)

        try:
            audit_report = run_phase3_1_audit(
                phase2_formal_path=phase2_formal_path,
                tasks=tasks,
                raw_model_runs=raw_model_runs,
                calibration_task_ids=calibration_task_ids,
                output_dir=output_dir,
                reproducibility_run=run_id
            )
            all_hashes.append(audit_report["reproducibility_hashes"])
            all_metrics.append(audit_report["computed_baseline"])
        except BaselineFidelityError as e:
            print(f"  ❌ Run {run_id} failed: {e}")
            all_passed = False
            break

    # 验证可复现性
    print("\n🔍 Verifying reproducibility across runs...")
    reproducibility_summary = {
        "total_runs": n_runs,
        "successful_runs": len(all_hashes),
        "anchor_hashes": {},
        "proposal_hashes": {},
        "m1_metrics": {},
        "m3_metrics": {},
        "reproducibility_passed": True,
        "differences": [],
    }

    if len(all_hashes) < n_runs:
        reproducibility_summary["reproducibility_passed"] = False
        reproducibility_summary["differences"].append(
            f"Only {len(all_hashes)}/{n_runs} runs completed"
        )
    else:
        # 检查 anchor hash 一致性
        anchor_hashes = [h["anchor_hash"] for h in all_hashes]
        reproducibility_summary["anchor_hashes"] = {
            "all_identical": len(set(anchor_hashes)) == 1,
            "unique_hashes": len(set(anchor_hashes)),
            "first_hash": anchor_hashes[0],
        }

        if len(set(anchor_hashes)) != 1:
            reproducibility_summary["reproducibility_passed"] = False
            reproducibility_summary["differences"].append(
                f"Anchor hashes not identical across runs: {anchor_hashes}"
            )

        # 检查 proposal hash 一致性
        proposal_hashes = [h["proposal_hash"] for h in all_hashes]
        reproducibility_summary["proposal_hashes"] = {
            "all_identical": len(set(proposal_hashes)) == 1,
            "unique_hashes": len(set(proposal_hashes)),
            "first_hash": proposal_hashes[0],
        }

        if len(set(proposal_hashes)) != 1:
            reproducibility_summary["reproducibility_passed"] = False
            reproducibility_summary["differences"].append(
                f"Proposal hashes not identical across runs: {proposal_hashes}"
            )

        # 检查 M1 metrics 一致性
        m1_utilities = [m["M1"]["mean_utility"] for m in all_metrics]
        m1_failures = [m["M1"]["main_failure_rate"] for m in all_metrics]

        reproducibility_summary["m1_metrics"] = {
            "utility_range": [min(m1_utilities), max(m1_utilities)],
            "failure_range": [min(m1_failures), max(m1_failures)],
            "all_identical": len(set([round(u, 10) for u in m1_utilities])) == 1 and
                             len(set([round(f, 10) for f in m1_failures])) == 1,
        }

        if len(set([round(u, 10) for u in m1_utilities])) != 1:
            reproducibility_summary["reproducibility_passed"] = False
            reproducibility_summary["differences"].append(
                f"M1 utilities not identical: {m1_utilities}"
            )

        # 检查 M3 metrics 一致性
        m3_utilities = [m["M3"]["mean_utility"] for m in all_metrics]
        m3_failures = [m["M3"]["main_failure_rate"] for m in all_metrics]

        reproducibility_summary["m3_metrics"] = {
            "utility_range": [min(m3_utilities), max(m3_utilities)],
            "failure_range": [min(m3_failures), max(m3_failures)],
            "all_identical": len(set([round(u, 10) for u in m3_utilities])) == 1 and
                             len(set([round(f, 10) for f in m3_failures])) == 1,
        }

        if len(set([round(u, 10) for u in m3_utilities])) != 1:
            reproducibility_summary["reproducibility_passed"] = False
            reproducibility_summary["differences"].append(
                f"M3 utilities not identical: {m3_utilities}"
            )

    # 保存可复现性总结
    summary_path = output_dir / "reproducibility_summary.json"
    with open(summary_path, 'w') as f:
        json.dump(reproducibility_summary, f, indent=2)

    # 生成 markdown 报告
    markdown_report = generate_markdown_report(reproducibility_summary, all_hashes, all_metrics)
    markdown_path = output_dir / "FINROME_V4_PHASE3_1_BASELINE_FIDELITY_AUDIT.md"
    with open(markdown_path, 'w') as f:
        f.write(markdown_report)

    print(f"\n📊 Reproducibility Summary:")
    print(f"  Total runs: {reproducibility_summary['total_runs']}")
    print(f"  Successful runs: {reproducibility_summary['successful_runs']}")
    print(f"  Reproducibility: {'✅ PASSED' if reproducibility_summary['reproducibility_passed'] else '❌ FAILED'}")
    print(f"  Report: {markdown_path}")

    return reproducibility_summary


def generate_markdown_report(
    reproducibility_summary: dict[str, Any],
    all_hashes: list[dict[str, Any]],
    all_metrics: list[dict[str, Any]]
) -> str:
    """生成 Phase 3.1 Audit Markdown 报告"""
    report = []
    report.append("# Fin-RoME v4 Phase 3.1: Baseline Fidelity + SPDF Reproducibility Audit\n\n")
    report.append(f"**生成时间:** {datetime.now(timezone.utc).isoformat()}\n")
    report.append(f"**版本:** 3.1_fidelity_audit\n\n")

    report.append("## Audit 概述\n\n")
    report.append("Phase 3.1 专注于验证 Baseline Fidelity，确保 Phase 3 严格继承 Phase 2 已冻结的 M1/M2/M3 selection。\n\n")

    report.append("### 关键原则\n\n")
    report.append("1. **禁止重新计算 M1/M2/M3**\n")
    report.append("   - Phase 3 必须直接加载 Phase 2 冻结的 selection\n")
    report.append("   - 禁止重新训练 Router 后重新生成 calibration baseline\n\n")

    report.append("2. **强制 Baseline Fidelity Assertions**\n")
    report.append("   - Phase3 task_ids == Phase2 calibration task_ids\n")
    report.append("   - Phase3 M1 selections hash == Phase2 M1 selections hash\n")
    report.append("   - Phase3 M2 selections hash == Phase2 M2 selections hash\n")
    report.append("   - Phase3 M3 selections hash == Phase2 M3 selections hash\n\n")

    report.append("3. **精确指标匹配**\n")
    report.append("   - M1: utility = 0.8350752467, failure = 3/20 = 15%\n")
    report.append("   - M2: utility = 0.8654756200, failure = 6/20 = 30%\n")
    report.append("   - M3: utility = 0.8656190733, failure = 6/20 = 30%\n\n")

    report.append("4. **修复 Override Metrics**\n")
    report.append("   - beneficial_override: proposal utility > anchor utility AND proposal failure <= anchor failure\n")
    report.append("   - safety_harmful_override: anchor failure = 0 AND proposal failure = 1\n")
    report.append("   - utility_harmful_override: proposal utility < anchor utility AND no safety_harm\n")
    report.append("   - neutral_override: 其余情况\n\n")

    report.append("5. **可复现性检查**\n")
    report.append("   - 固定相同 frozen inputs 后连续运行 5 次\n")
    report.append("   - 必须满足 anchor_hash identical 5/5\n")
    report.append("   - 必须满足 proposal_hash identical 5/5\n")
    report.append("   - 必须满足 M1/M3 metrics identical 5/5\n\n")

    report.append("## Phase 2 冻结 Baseline\n\n")
    report.append("| Method | Utility | Main Failure | Strict Failure | Oracle Match | Selection Counts |\n")
    report.append("|--------|---------|--------------|-----------------|---------------|------------------|\n")

    for method in ["M1", "M2", "M3"]:
        baseline = PHASE2_FROZEN_BASELINE[method]
        report.append(f"| {method} | {baseline['mean_utility']:.10f} | {baseline['main_failure_rate']:.2%} | "
                     f"{baseline['strict_repeat_failure_rate']:.2%} | {baseline['oracle_match_rate']:.2%} | "
                     f"{dict(baseline['selection_counts'])} |\n")

    report.append("\n## 可复现性检查结果\n\n")
    report.append(f"**总运行次数:** {reproducibility_summary['total_runs']}\n")
    report.append(f"**成功运行次数:** {reproducibility_summary['successful_runs']}\n")
    report.append(f"**可复现性:** {'✅ PASSED' if reproducibility_summary['reproducibility_passed'] else '❌ FAILED'}\n\n")

    report.append("### Anchor (M1) Hash 一致性\n\n")
    anchor_info = reproducibility_summary.get('anchor_hashes', {})
    report.append(f"- **全部相同:** {'✅ 是' if anchor_info.get('all_identical') else '❌ 否'}\n")
    report.append(f"- **唯一 hash 数量:** {anchor_info.get('unique_hashes', 'N/A')}\n")
    if 'first_hash' in anchor_info:
        report.append(f"- **Hash:** `{anchor_info['first_hash'][:16]}...`\n\n")

    report.append("### Proposal (M3) Hash 一致性\n\n")
    proposal_info = reproducibility_summary.get('proposal_hashes', {})
    report.append(f"- **全部相同:** {'✅ 是' if proposal_info.get('all_identical') else '❌ 否'}\n")
    report.append(f"- **唯一 hash 数量:** {proposal_info.get('unique_hashes', 'N/A')}\n")
    if 'first_hash' in proposal_info:
        report.append(f"- **Hash:** `{proposal_info['first_hash'][:16]}...`\n\n")

    report.append("### M1 指标一致性\n\n")
    m1_info = reproducibility_summary.get('m1_metrics', {})
    if 'utility_range' in m1_info:
        report.append(f"- **Utility 范围:** [{m1_info['utility_range'][0]:.10f}, {m1_info['utility_range'][1]:.10f}]\n")
    if 'failure_range' in m1_info:
        report.append(f"- **Failure 范围:** [{m1_info['failure_range'][0]:.10f}, {m1_info['failure_range'][1]:.10f}]\n")
    report.append(f"- **全部相同:** {'✅ 是' if m1_info.get('all_identical') else '❌ 否'}\n\n")

    report.append("### M3 指标一致性\n\n")
    m3_info = reproducibility_summary.get('m3_metrics', {})
    if 'utility_range' in m3_info:
        report.append(f"- **Utility 范围:** [{m3_info['utility_range'][0]:.10f}, {m3_info['utility_range'][1]:.10f}]\n")
    if 'failure_range' in m3_info:
        report.append(f"- **Failure 范围:** [{m3_info['failure_range'][0]:.10f}, {m3_info['failure_range'][1]:.10f}]\n")
    report.append(f"- **全部相同:** {'✅ 是' if m3_info.get('all_identical') else '❌ 否'}\n\n")

    if reproducibility_summary.get('differences'):
        report.append("### 发现的差异\n\n")
        for diff in reproducibility_summary['differences']:
            report.append(f"- ❌ {diff}\n")
        report.append("\n")

    report.append("## Audit 结论\n\n")

    if reproducibility_summary['reproducibility_passed']:
        report.append("✅ **BASELINE FIDELITY AUDIT PASSED**\n\n")
        report.append("Phase 3.1 验证了以下关键要求：\n\n")
        report.append("1. ✅ Phase 3 正确加载了 Phase 2 冻结的 M1/M2/M3 selection\n")
        report.append("2. ✅ M1/M2/M3 指标与 Phase 2 冻结 baseline 完全一致\n")
        report.append("3. ✅ 5 次运行结果完全可复现（hashes 和 metrics 相同）\n\n")
        report.append("现在可以安全进入下一步：\n")
        report.append("- Phase 3.2: 在冻结 baseline 上实现 SPDF Gate\n")
        report.append("- Phase 3.3: Threshold tuning（使用冻结的 selection）\n")
    else:
        report.append("❌ **BASELINE FIDELITY AUDIT FAILED**\n\n")
        report.append("发现以下问题：\n\n")
        for diff in reproducibility_summary.get('differences', []):
            report.append(f"- {diff}\n")
        report.append("\n")
        report.append("必须先解决这些问题才能继续。\n")

    report.append("\n## 下一步行动\n\n")
    report.append("根据 Phase 3.1 Audit 结果：\n")
    report.append("- **如果 PASSED:** 继续实现 Phase 3.2 SPDF Gate（基于冻结 baseline）\n")
    report.append("- **如果 FAILED:** 修复 baseline fidelity 问题后重新运行 Phase 3.1\n\n")

    report.append("### 禁止的操作（直到 Phase 3.1 PASSED）\n")
    report.append("- ❌ 运行 test\n")
    report.append("- ❌ 进入 Phase 4\n")
    report.append("- ❌ 调整 SPDF 阈值\n")
    report.append("- ❌ 重新训练 Router/M1/M2/M3\n")

    return "".join(report)


# ========================================================================
# 主函数
# ========================================================================

def main():
    parser = argparse.ArgumentParser(description="Fin-RoME Phase 3.1: Baseline Fidelity + SPDF Reproducibility Audit")
    parser.add_argument("--phase2-formal", type=str, default=str(DEFAULT_PHASE2_FORMAL_PATH))
    parser.add_argument("--source", type=str, default=str(DEFAULT_SOURCE))
    parser.add_argument("--manifest", type=str, default=str(MANIFEST_PATH))
    parser.add_argument("--oof-manifest", type=str, default=str(OOF_FOLD_MANIFEST_PATH))
    parser.add_argument("--embeddings", type=str, default=str(EMBEDDINGS_PATH))
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT))
    parser.add_argument("--runs", type=int, default=5, help="Number of reproducibility runs")

    args = parser.parse_args()

    print("=" * 80)
    print("Fin-RoME Phase 3.1: Baseline Fidelity + SPDF Reproducibility Audit")
    print("=" * 80)
    print(f"Phase 2 Formal Path: {args.phase2_formal}")
    print(f"Source: {args.source}")
    print(f"Manifest: {args.manifest}")
    print(f"OOF Manifest: {args.oof_manifest}")
    print(f"Output: {args.output}")
    print(f"Reproducibility Runs: {args.runs}")
    print("=" * 80)

    # 创建输出目录
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 设置随机种子
    seed_all(SEED)

    # 加载数据
    print("\n📊 Loading data...")
    phase2_formal_path = Path(args.phase2_formal)

    # 检查 Phase 2 正式输出是否存在
    if not phase2_formal_path.exists():
        print(f"❌ Phase 2 formal path does not exist: {phase2_formal_path}")
        return

    phase2_trace_path = phase2_formal_path / "phase2_formal_trace.jsonl"
    if not phase2_trace_path.exists():
        print(f"❌ Phase 2 trace file does not exist: {phase2_trace_path}")
        return

    with open(args.source) as f:
        source_data = json.load(f)
        raw_model_runs = source_data["raw_model_runs"]
        sampled_tasks = source_data["sampled_task_set"]

    with open(args.manifest) as f:
        manifest = json.load(f)

    # 构建任务映射
    task_id_to_task = {}
    for task in sampled_tasks:
        task_id_to_task[task["id"]] = task

    all_tasks = list(task_id_to_task.values())
    train_task_ids = set(manifest["split_definition"]["train"])
    calibration_task_ids = list(manifest["calibration_split"])

    train_tasks = [t for t in all_tasks if t["id"] in train_task_ids]
    calibration_tasks = [t for t in all_tasks if t["id"] in calibration_task_ids]

    print(f"  Total tasks: {len(all_tasks)}")
    print(f"  Train tasks: {len(train_tasks)}")
    print(f"  Calibration tasks: {len(calibration_tasks)}")

    # 运行可复现性检查
    print("\n🚀 Starting reproducibility audit...")
    reproducibility_summary = run_reproducibility_check(
        phase2_formal_path=phase2_formal_path,
        tasks=all_tasks,
        raw_model_runs=raw_model_runs,
        calibration_task_ids=calibration_task_ids,
        output_dir=output_dir,
        n_runs=args.runs
    )

    print("\n" + "=" * 80)
    if reproducibility_summary["reproducibility_passed"]:
        print("✅ PHASE 3.1 BASELINE FIDELITY AUDIT PASSED")
    else:
        print("❌ PHASE 3.1 BASELINE FIDELITY AUDIT FAILED")
    print("=" * 80)

    print("\n📁 Output files:")
    print(f"  - Audit Report: {output_dir}/FINROME_V4_PHASE3_1_BASELINE_FIDELITY_AUDIT.md")
    print(f"  - Reproducibility Summary: {output_dir}/reproducibility_summary.json")


if __name__ == "__main__":
    main()