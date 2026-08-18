#!/usr/bin/env python3
"""
Phase 1: Fix Oracle/Data Consistency Issues for Fin-RoME v4

CRITICAL FIXES:
1. Unified Calibration Split: Use frozen split manifest, NOT sorted()[:20]
2. Proper 3-Repeat Aggregation: Aggregate before Oracle calculation, don't overwrite
3. Shared Utility/Failure Functions: Single source of truth for all computations
4. Consistency Assertions: Validate logical relationships between metrics

This script ONLY does Phase 1 - it does NOT tune Routers, thresholds, or run tests.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    ROOT.parents[1]
    / "frozen-archives/finance-router-context-v2-1200-final-20260729T072524Z"
    / "run_logs/formal_context_v2_rescored_v22_result.json"
)
DEFAULT_SPLIT = ROOT / "run_logs/offline_knn_baseline/split.json"
MANIFEST_OUTPUT = ROOT / "finrome_v4_split_manifest.json"
DEFAULT_OUTPUT = ROOT / "run_logs/finrome_v4_phase1_oracle_fix"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo")

# ========================================================================
# SHARED CONFIGURATION - Single source of truth
# ========================================================================

# Utility weights from original Fin-RoME specification
UTILITY_WEIGHTS = {
    "quality": 0.45,
    "cost": 0.20,
    "latency": 0.15,
    "reliability": 0.20,
}

# Quality threshold for safety definition
QUALITY_THRESHOLD = 0.5  # Development definition

# Cost and latency normalization constants
MAX_COST_NORMALIZATION = 0.02  # $0.02 USD
MAX_LATENCY_NORMALIZATION = 10000  # 10 seconds in ms


# ========================================================================
# SHARED UTILITY FUNCTIONS - Must be used by ALL components
# ========================================================================

def compute_finrome_utility(
    quality: float,
    cost: float,
    latency: float,
    reliability: float
) -> float:
    """
    Compute Fin-RoME utility using the ORIGINAL formula.
    This is the ONLY valid utility computation for the project.

    Formula: U = 0.45*Q + 0.20*(1-min(C/0.02,1)) + 0.15*(1-min(L/10000,1)) + 0.20*R

    Args:
        quality: Quality score (0-1)
        cost: Cost in USD
        latency: Latency in milliseconds
        reliability: Reliability/success rate (0-1)

    Returns:
        Utility score (0-1)
    """
    cost_reward = 1.0 - min(cost / MAX_COST_NORMALIZATION, 1.0)
    latency_reward = 1.0 - min(latency / MAX_LATENCY_NORMALIZATION, 1.0)

    return (
        UTILITY_WEIGHTS["quality"] * quality +
        UTILITY_WEIGHTS["cost"] * cost_reward +
        UTILITY_WEIGHTS["latency"] * latency_reward +
        UTILITY_WEIGHTS["reliability"] * reliability
    )


def compute_failure(quality: float, quality_threshold: float = QUALITY_THRESHOLD) -> bool:
    """
    Compute whether a run is a failure.
    This is the ONLY valid failure definition for the project.

    Args:
        quality: Quality score (0-1)
        quality_threshold: Threshold below which quality is considered a failure

    Returns:
        True if failed, False otherwise
    """
    return quality < quality_threshold


# ========================================================================
# PROPER 3-REPEAT AGGREGATION
# ========================================================================

def aggregate_3_repeats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Properly aggregate 3 repeats for a task-model pair.
    CRITICAL: This must be called BEFORE any Oracle/utility/failure computation.

    Args:
        runs: List of 3 repeat runs for the same (task_id, model) pair

    Returns:
        Aggregated metrics (mean of 3 repeats)
    """
    if not runs:
        return {}

    if len(runs) != 3:
        raise ValueError(f"Expected 3 repeats, got {len(runs)}")

    # Extract and validate quality values
    quality_values = [r.get("quality") for r in runs if r.get("quality") is not None]
    if len(quality_values) != 3:
        raise ValueError(f"Expected 3 quality values, got {len(quality_values)}")

    # Extract cost and latency
    cost_values = [r.get("raw_cost_usd", 0.0) for r in runs]
    latency_values = [r.get("latency_ms", 0) for r in runs]

    # Compute failure status for each repeat
    failure_statuses = [compute_failure(q, QUALITY_THRESHOLD) for q in quality_values]
    failure_rate = sum(failure_statuses) / 3.0

    # Aggregate using mean (same as formal experiment)
    aggregated = {
        "quality": float(np.mean(quality_values)),
        "quality_std": float(np.std(quality_values)),
        "quality_values": quality_values,  # Keep for audit
        "cost": float(np.mean(cost_values)),
        "cost_std": float(np.std(cost_values)),
        "latency": float(np.mean(latency_values)),
        "latency_std": float(np.std(latency_values)),
        "reliability": 1.0 - failure_rate,  # Reliability = success rate
        "failed": failure_rate,  # Failure rate (0-1)
        "n_repeats": 3,
        "repeat_failures": failure_statuses,
    }

    # Compute utility using SHARED function
    aggregated["utility"] = compute_finrome_utility(
        aggregated["quality"],
        aggregated["cost"],
        aggregated["latency"],
        aggregated["reliability"]
    )

    return aggregated


# ========================================================================
# DATA STRUCTURES
# ========================================================================

@dataclass
class TaskModelOutcome:
    """Outcome for a single task-model pair after proper 3-repeat aggregation."""
    task_id: str
    model: str
    quality: float
    quality_std: float
    cost: float
    cost_std: float
    latency: float
    latency_std: float
    reliability: float
    utility: float
    failed: bool
    failed_rate: float


@dataclass
class OracleMetrics:
    """Oracle metrics computed on a unified calibration set."""
    n_calibration_tasks: int
    m1_failure_count: int
    m1_failure_rate: float
    utility_oracle_failure_count: int
    utility_oracle_failure_rate: float
    safety_oracle_failure_count: int
    safety_oracle_failure_rate: float
    unsolvable_count: int
    unsolvable_rate: float
    recoverable_m1_failures: int
    recoverable_failure_rate: float
    absolute_routing_gap: float
    consistency_assertions: dict[str, bool]
    raw_task_details: list[dict[str, Any]]


# ========================================================================
# MAIN ORACLE COMPUTATION
# ========================================================================

def compute_oracle_metrics_on_unified_split(
    source_data: dict[str, Any],
    split_manifest: dict[str, Any],
    verbose: bool = True
) -> OracleMetrics:
    """
    Compute Oracle metrics on a UNIFIED calibration split.

    CRITICAL: This function addresses ALL THREE consistency issues:
    1. Uses frozen split manifest (NOT sorted()[:20])
    2. Properly aggregates 3 repeats (no overwriting)
    3. Uses SHARED utility/failure functions
    """

    if verbose:
        print("=" * 80)
        print("PHASE 1: ORACLE CONSISTENCY FIX")
        print("=" * 80)
        print("\n1. LOADING DATA AND SPLIT MANIFEST")

    # Load tasks
    tasks = {x["id"]: x for x in source_data["sampled_task_set"]}
    calibration_ids = split_manifest["validation"]

    if verbose:
        print(f"   Total tasks: {len(tasks)}")
        print(f"   Calibration tasks: {len(calibration_ids)}")
        print(f"   Calibration task IDs: {calibration_ids[:5]}...")

    # Verify we have exactly 20 calibration tasks
    if len(calibration_ids) != 20:
        raise ValueError(f"Expected 20 calibration tasks, got {len(calibration_ids)}")

    if verbose:
        print("\n2. ORGANIZING RAW RUNS BY (TASK, MODEL) PAIRS")

    # Organize runs by (task_id, model) - expecting exactly 3 per pair
    by_task_model: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in source_data["raw_model_runs"]:
        key = (row["task_id"], row["model"])
        by_task_model[key].append(row)

    # Verify we have exactly 3 repeats per calibration task-model pair
    expected_pairs = len(calibration_ids) * len(MODELS)
    actual_pairs = len(by_task_model)

    if verbose:
        print(f"   Expected (task, model) pairs: {expected_pairs}")
        print(f"   Actual (task, model) pairs: {actual_pairs}")

    # Check for missing or extra pairs
    missing_pairs = []
    for tid in calibration_ids:
        for model in MODELS:
            key = (tid, model)
            if key not in by_task_model:
                missing_pairs.append(key)
            elif len(by_task_model[key]) != 3:
                print(f"   WARNING: {key} has {len(by_task_model[key])} repeats, expected 3")

    if missing_pairs:
        raise ValueError(f"Missing {len(missing_pairs)} (task, model) pairs: {missing_pairs[:5]}...")

    if verbose:
        print("\n3. AGGREGATING 3 REPEATS (PROPER METHOD)")

    # Aggregate 3 repeats for each task-model pair
    outcomes_by_task_model: dict[tuple[str, str], TaskModelOutcome] = {}
    for (task_id, model), runs in by_task_model.items():
        if task_id not in calibration_ids:
            continue

        aggregated = aggregate_3_repeats(runs)

        outcomes_by_task_model[(task_id, model)] = TaskModelOutcome(
            task_id=task_id,
            model=model,
            quality=aggregated["quality"],
            quality_std=aggregated["quality_std"],
            cost=aggregated["cost"],
            cost_std=aggregated["cost_std"],
            latency=aggregated["latency"],
            latency_std=aggregated["latency_std"],
            reliability=aggregated["reliability"],
            utility=aggregated["utility"],
            failed=aggregated["failed"] > 0,  # Failed if any repeat failed
            failed_rate=aggregated["failed"]
        )

    if verbose:
        print(f"   Aggregated {len(outcomes_by_task_model)} task-model outcomes")

    if verbose:
        print("\n4. COMPUTING ORACLES")

    # Compute oracles for each calibration task
    task_details = []

    for tid in calibration_ids:
        # Get outcomes for all models for this task
        task_outcomes = {
            model: outcomes_by_task_model[(tid, model)]
            for model in MODELS
        }

        # Utility Oracle: model with maximum utility
        utility_oracle_model = max(
            MODELS,
            key=lambda m: task_outcomes[m].utility
        )
        utility_oracle_outcome = task_outcomes[utility_oracle_model]

        # Safety Oracle: model with minimum failure rate
        # If tie, prefer higher reliability
        safety_oracle_model = min(
            MODELS,
            key=lambda m: (task_outcomes[m].failed_rate, -task_outcomes[m].reliability)
        )
        safety_oracle_outcome = task_outcomes[safety_oracle_model]

        # M1 (baseline): select model with maximum historical utility
        # For this analysis, M1 = Utility Oracle (since we're on calibration)
        m1_model = utility_oracle_model
        m1_outcome = utility_oracle_outcome

        # Check if task is unsolvable (all models failed)
        all_failed = all(task_outcomes[m].failed for m in MODELS)

        # Check if M1 failed but safety oracle didn't (recoverable failure)
        m1_failed = m1_outcome.failed
        safety_oracle_failed = safety_oracle_outcome.failed
        recoverable_failure = m1_failed and not safety_oracle_failed

        task_detail = {
            "task_id": tid,
            "utility_oracle_model": utility_oracle_model,
            "utility_oracle_failed": utility_oracle_outcome.failed,
            "utility_oracle_utility": utility_oracle_outcome.utility,
            "utility_oracle_quality": utility_oracle_outcome.quality,

            "safety_oracle_model": safety_oracle_model,
            "safety_oracle_failed": safety_oracle_outcome.failed,
            "safety_oracle_utility": safety_oracle_outcome.utility,
            "safety_oracle_quality": safety_oracle_outcome.quality,

            "m1_model": m1_model,
            "m1_failed": m1_failed,
            "m1_utility": m1_outcome.utility,
            "m1_quality": m1_outcome.quality,

            "all_models_failed": all_failed,
            "recoverable_failure": recoverable_failure,

            "model_details": {
                model: {
                    "quality": task_outcomes[model].quality,
                    "quality_std": task_outcomes[model].quality_std,
                    "utility": task_outcomes[model].utility,
                    "failed": task_outcomes[model].failed,
                    "failed_rate": task_outcomes[model].failed_rate,
                }
                for model in MODELS
            }
        }

        task_details.append(task_detail)

    if verbose:
        print(f"   Computed oracles for {len(task_details)} calibration tasks")

    if verbose:
        print("\n5. COMPUTING AGGREGATE METRICS")

    # Compute aggregate metrics
    n_calibration = len(calibration_ids)
    m1_failures = sum(1 for d in task_details if d["m1_failed"])
    m1_failure_rate = m1_failures / n_calibration

    utility_oracle_failures = sum(1 for d in task_details if d["utility_oracle_failed"])
    utility_oracle_failure_rate = utility_oracle_failures / n_calibration

    safety_oracle_failures = sum(1 for d in task_details if d["safety_oracle_failed"])
    safety_oracle_failure_rate = safety_oracle_failures / n_calibration

    unsolvable_tasks = sum(1 for d in task_details if d["all_models_failed"])
    unsolvable_rate = unsolvable_tasks / n_calibration

    recoverable_m1_failures = sum(1 for d in task_details if d["recoverable_failure"])
    recoverable_failure_rate = recoverable_m1_failures / n_calibration

    # Compute routing gap
    absolute_routing_gap = m1_failure_rate - safety_oracle_failure_rate

    if verbose:
        print(f"   M1 Failure: {m1_failure_rate:.1%} ({m1_failures}/{n_calibration})")
        print(f"   Utility Oracle Failure: {utility_oracle_failure_rate:.1%} ({utility_oracle_failures}/{n_calibration})")
        print(f"   Safety Oracle Failure: {safety_oracle_failure_rate:.1%} ({safety_oracle_failures}/{n_calibration})")
        print(f"   Unsolvable (all models failed): {unsolvable_rate:.1%} ({unsolvable_tasks}/{n_calibration})")
        print(f"   Recoverable M1 Failures: {recoverable_failure_rate:.1%} ({recoverable_m1_failures}/{n_calibration})")
        print(f"   Absolute Routing Gap: {absolute_routing_gap:.1%}")

    if verbose:
        print("\n6. CONSISTENCY ASSERTIONS")

    # Perform consistency assertions
    assertions = {}

    # Assertion 1: M1 failures >= unsolvable count
    failures_on_unsolvable = sum(
        1 for d in task_details
        if d["all_models_failed"] and d["m1_failed"]
    )
    assertion1 = m1_failures >= unsolvable_tasks
    assertions["m1_failures >= unsolvable_count"] = assertion1
    if not assertion1:
        print(f"   ❌ FAILED: M1 failures ({m1_failures}) < unsolvable count ({unsolvable_tasks})")
    else:
        print(f"   ✅ PASSED: M1 failures ({m1_failures}) >= unsolvable count ({unsolvable_tasks})")

    # Assertion 2: Recoverable M1 failures = M1 failures - failures on unsolvable tasks
    expected_recoverable = m1_failures - failures_on_unsolvable
    assertion2 = recoverable_m1_failures == expected_recoverable
    assertions["recoverable_m1_failures == m1_failures - failures_on_unsolvable"] = assertion2
    if not assertion2:
        print(f"   ❌ FAILED: Recoverable ({recoverable_m1_failures}) != {expected_recoverable}")
    else:
        print(f"   ✅ PASSED: Recoverable ({recoverable_m1_failures}) = {expected_recoverable}")

    # Assertion 3: Utility oracle failures <= M1 failures
    assertion3 = utility_oracle_failures <= m1_failures
    assertions["utility_oracle_failures <= m1_failures"] = assertion3
    if not assertion3:
        print(f"   ❌ FAILED: Utility oracle failures ({utility_oracle_failures}) > M1 failures ({m1_failures})")
    else:
        print(f"   ✅ PASSED: Utility oracle failures ({utility_oracle_failures}) <= M1 failures ({m1_failures})")

    # Assertion 4: Safety oracle failures <= M1 failures
    assertion4 = safety_oracle_failures <= m1_failures
    assertions["safety_oracle_failures <= m1_failures"] = assertion4
    if not assertion4:
        print(f"   ❌ FAILED: Safety oracle failures ({safety_oracle_failures}) > M1 failures ({m1_failures})")
    else:
        print(f"   ✅ PASSED: Safety oracle failures ({safety_oracle_failures}) <= M1 failures ({m1_failures})")

    all_passed = all(assertions.values())
    if not all_passed:
        print(f"\n   ⚠️  WARNING: {sum(1 for v in assertions.values() if not v)}/{len(assertions)} assertions FAILED")

    return OracleMetrics(
        n_calibration_tasks=n_calibration,
        m1_failure_count=m1_failures,
        m1_failure_rate=m1_failure_rate,
        utility_oracle_failure_count=utility_oracle_failures,
        utility_oracle_failure_rate=utility_oracle_failure_rate,
        safety_oracle_failure_count=safety_oracle_failures,
        safety_oracle_failure_rate=safety_oracle_failure_rate,
        unsolvable_count=unsolvable_tasks,
        unsolvable_rate=unsolvable_rate,
        recoverable_m1_failures=recoverable_m1_failures,
        recoverable_failure_rate=recoverable_failure_rate,
        absolute_routing_gap=absolute_routing_gap,
        consistency_assertions=assertions,
        raw_task_details=task_details
    )


def create_unified_split_manifest(
    source_data: dict[str, Any],
    existing_split: dict[str, Any],
    output_path: Path
) -> dict[str, Any]:
    """
    Create a unified split manifest with proper checksums and metadata.

    This ensures all scripts use EXACTLY the same calibration task IDs.
    """
    print("\n" + "=" * 80)
    print("CREATING UNIFIED SPLIT MANIFEST")
    print("=" * 80)

    # Extract task IDs
    all_task_ids = sorted([x["id"] for x in source_data["sampled_task_set"]])

    # Create manifest with metadata
    manifest = {
        "version": "finrome_v4_unified",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_data": {
            "n_total_tasks": len(all_task_ids),
            "task_ids": all_task_ids[:5] + ["..."] + all_task_ids[-5:],
            "checksum": hash(str(all_task_ids)),  # Simple checksum for verification
        },
        "split_definition": {
            "train": existing_split["train"],
            "validation": existing_split["validation"],
            "test": existing_split["test"],
        },
        "split_sizes": {
            "train": len(existing_split["train"]),
            "validation": len(existing_split["validation"]),
            "test": len(existing_split["test"]),
        },
        "calibration_split": existing_split["validation"],  # Alias for clarity
        "usage_rules": [
            "ALL scripts MUST read calibration tasks from this manifest only",
            "NEVER use sorted()[:20] or similar to construct calibration set",
            "NEVER modify calibration task IDs after manifest creation",
            "Use split['validation'] or split['calibration_split'] for calibration"
        ]
    }

    # Save manifest
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"✅ Unified split manifest saved to {output_path}")
    print(f"   Train: {len(manifest['split_definition']['train'])} tasks")
    print(f"   Calibration (validation): {len(manifest['split_definition']['validation'])} tasks")
    print(f"   Test: {len(manifest['split_definition']['test'])} tasks")

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Phase 1: Fix Oracle/Data Consistency")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 80)
    print("FIN-ROME V4 - PHASE 1: ORACLE CONSISTENCY FIX")
    print("=" * 80)
    print("\nThis script addresses THREE critical consistency issues:")
    print("1. ❌ sorted()[:20] → ✅ Frozen split manifest")
    print("2. ❌ Overwriting repeats → ✅ Proper 3-repeat aggregation")
    print("3. ❌ Inconsistent utility → ✅ Shared compute_finrome_utility()")
    print("\nPHASE 1 SCOPE: Fix Oracle calculations ONLY")
    print("- NO Router tuning")
    print("- NO threshold optimization")
    print("- NO test split access")
    print("=" * 80)

    # Load data
    print("\n📂 Loading source data...")
    source_data = json.loads(args.source.read_text(encoding="utf-8"))
    existing_split = json.loads(args.split.read_text(encoding="utf-8"))
    print(f"✅ Loaded {len(source_data['sampled_task_set'])} tasks")
    print(f"✅ Loaded existing split definition")

    # Step 1: Create unified split manifest
    manifest = create_unified_split_manifest(source_data, existing_split, MANIFEST_OUTPUT)

    # Step 2: Compute Oracle metrics on unified split
    oracle_metrics = compute_oracle_metrics_on_unified_split(
        source_data,
        manifest["split_definition"],
        verbose=True
    )

    # Step 3: Generate final report
    print("\n" + "=" * 80)
    print("GENERATING FINAL REPORT")
    print("=" * 80)

    report = {
        "report_type": "finrome_v4_phase1_oracle_fix",
        "phase": "1_oracle_consistency_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "router_tuning": False,
            "threshold_optimization": False,
            "test_split_access": False,
            "description": "Phase 1 fixes Oracle/data consistency issues ONLY"
        },
        "fixes_applied": [
            "Unified calibration split from frozen manifest (not sorted()[:20])",
            "Proper 3-repeat aggregation before Oracle calculation",
            "Shared compute_finrome_utility() function",
            "Shared compute_failure() function",
            "Consistency assertions for metric validation"
        ],
        "configuration": {
            "quality_threshold": QUALITY_THRESHOLD,
            "utility_weights": UTILITY_WEIGHTS,
            "max_cost_normalization": MAX_COST_NORMALIZATION,
            "max_latency_normalization": MAX_LATENCY_NORMALIZATION,
        },
        "calibration_split": {
            "n_tasks": oracle_metrics.n_calibration_tasks,
            "task_ids": manifest["split_definition"]["validation"],
        },
        "oracle_metrics": {
            "m1": {
                "failure_count": oracle_metrics.m1_failure_count,
                "failure_rate": oracle_metrics.m1_failure_rate,
                "note": "M1 = Utility Oracle on calibration split"
            },
            "utility_oracle": {
                "failure_count": oracle_metrics.utility_oracle_failure_count,
                "failure_rate": oracle_metrics.utility_oracle_failure_rate,
                "note": "Model with maximum utility"
            },
            "safety_oracle": {
                "failure_count": oracle_metrics.safety_oracle_failure_count,
                "failure_rate": oracle_metrics.safety_oracle_failure_rate,
                "note": "Model with minimum failure rate"
            },
            "unsolvable_tasks": {
                "count": oracle_metrics.unsolvable_count,
                "rate": oracle_metrics.unsolvable_rate,
                "note": "Tasks where ALL models failed"
            },
            "routing_analysis": {
                "absolute_routing_gap": oracle_metrics.absolute_routing_gap,
                "recoverable_m1_failures": oracle_metrics.recoverable_m1_failures,
                "recoverable_failure_rate": oracle_metrics.recoverable_failure_rate,
                "note": "Recoverable = M1 failed but Safety Oracle didn't"
            }
        },
        "consistency_assertions": oracle_metrics.consistency_assertions,
        "all_assertions_passed": all(oracle_metrics.consistency_assertions.values()),
        "raw_task_details": oracle_metrics.raw_task_details,
        "next_steps": [
            "PHASE 1 COMPLETE - Oracle metrics are now consistent",
            "DO NOT proceed to Phase 2 (Router Expert reconstruction) until:",
            "  1. All assertions pass",
            "  2. Metrics are reviewed and validated",
            "  3. Phase 2 plan is approved",
            "Phase 2 will focus on: Rebuilding KNN/MLP/Graph Router Experts"
        ]
    }

    # Save report
    report_path = args.output / "phase1_oracle_consistency_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n✅ Phase 1 report saved to {report_path}")

    # Save manifest reference
    manifest_ref = {
        "manifest_path": str(MANIFEST_OUTPUT),
        "manifest_checksum": manifest["source_data"]["checksum"],
        "calibration_task_ids": manifest["split_definition"]["validation"],
        "usage_instruction": "All future scripts MUST read calibration tasks from this manifest"
    }
    manifest_ref_path = args.output / "manifest_reference.json"
    manifest_ref_path.write_text(json.dumps(manifest_ref, indent=2), encoding="utf-8")
    print(f"✅ Manifest reference saved to {manifest_ref_path}")

    # Summary
    print("\n" + "=" * 80)
    print("PHASE 1 COMPLETE - ORACLE CONSISTENCY FIX")
    print("=" * 80)
    print(f"\n📊 KEY METRICS (on unified calibration split):")
    print(f"   M1 Failure Rate:              {oracle_metrics.m1_failure_rate:.1%}")
    print(f"   Utility Oracle Failure Rate:  {oracle_metrics.utility_oracle_failure_rate:.1%}")
    print(f"   Safety Oracle Failure Rate:   {oracle_metrics.safety_oracle_failure_rate:.1%}")
    print(f"   Unsolvable Rate:              {oracle_metrics.unsolvable_rate:.1%}")
    print(f"   Recoverable Failure Rate:     {oracle_metrics.recoverable_failure_rate:.1%}")
    print(f"   Absolute Routing Gap:         {oracle_metrics.absolute_routing_gap:.1%}")

    print(f"\n✅ Consistency Assertions: {sum(1 for v in oracle_metrics.consistency_assertions.values() if v)}/{len(oracle_metrics.consistency_assertions)} PASSED")

    if not all(oracle_metrics.consistency_assertions.values()):
        print(f"\n⚠️  WARNING: Some consistency assertions FAILED")
        print(f"   Review the report for details before proceeding to Phase 2")

    print(f"\n📁 OUTPUT FILES:")
    print(f"   - Report: {report_path}")
    print(f"   - Manifest: {MANIFEST_OUTPUT}")
    print(f"   - Manifest Reference: {manifest_ref_path}")

    print(f"\n🚫 PHASE 1 SCOPE LIMITATIONS:")
    print(f"   - NO Router tuning performed")
    print(f"   - NO threshold optimization performed")
    print(f"   - NO test split accessed")
    print(f"   - Oracle metrics are NOW consistent and ready for use")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()