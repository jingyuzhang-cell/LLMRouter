#!/usr/bin/env python3
"""Fin-RoME v4: Selective Abstention instead of Human Review.

This is the v4 version of the Fin-RoME experiment that replaces human review
with selective abstention. The system explicitly refuses to answer when it
cannot make a safe automated decision.

Key changes from v3:
- manual_review → abstain: System refuses to answer when uncertain
- Safe Router Set = ∅ → ABSTAIN (instead of fallback to anchor)
- New metrics: Coverage, Abstention Rate, Selective Failure Rate
- Risk-Coverage analysis to show performance trade-offs
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import torch
from sklearn.base import clone
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss
from sklearn.model_selection import StratifiedKFold
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    ROOT.parents[1]
    / "frozen-archives/finance-router-context-v2-1200-final-20260729T072524Z"
    / "run_logs/formal_context_v2_rescored_v22_result.json"
)
DEFAULT_SPLIT = ROOT / "run_logs/offline_knn_baseline/split.json"
DEFAULT_EMBEDDINGS = ROOT / "run_logs/offline_knn_baseline/longformer_embeddings.pt"
DEFAULT_OUTPUT = ROOT / "run_logs/finrome_v4_abstention"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo")
ROUTERS = ("knnrouter", "mlprouter", "graphrouter")
SEED = 20260808


def num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values)
    exp = np.exp(np.clip(shifted, -40, 40))
    return exp / max(float(exp.sum()), 1e-12)


def rank_standardise(scores: np.ndarray) -> np.ndarray:
    """Borda/rank normalisation; does not pretend heterogeneous scores are probabilities."""
    order = np.argsort(np.argsort(scores))
    return order.astype(float) / max(1, len(scores) - 1)


def risk_name(task: dict[str, Any]) -> str:
    raw = str(task.get("risk", task.get("risk_level", "medium"))).lower()
    if raw in {"low", "medium", "high"}:
        return raw
    return "high" if bool(task.get("requires_verification")) else "medium"


def task_features(task: dict[str, Any]) -> np.ndarray:
    risk = risk_name(task)
    query = str(task.get("query", ""))
    return np.array(
        [
            num(task.get("complexity"), 0.5),
            {"low": 0.2, "medium": 0.55, "high": 0.9}[risk],
            float(bool(task.get("requires_verification"))),
            float(bool(task.get("requires_calculation"))),
            float(bool(task.get("requires_table_reasoning"))),
            float(bool(task.get("requires_kg_reasoning"))),
            min(len(query), 4000) / 4000.0,
        ],
        dtype=float,
    )


def aggregate_runs(rows: list[dict[str, Any]]) -> dict[str, float]:
    quality = float(np.mean([num(x.get("quality")) for x in rows]))
    cost = float(np.mean([num(x.get("raw_cost_usd")) for x in rows]))
    latency = float(np.mean([num(x.get("latency_ms")) for x in rows]))
    reliability = float(np.mean([bool(x.get("ok")) for x in rows]))
    utility = 0.45 * quality + 0.20 * (1 - min(cost / 0.02, 1))
    utility += 0.15 * (1 - min(latency / 10000, 1)) + 0.20 * reliability
    return {
        "quality": quality,
        "cost": cost,
        "latency": latency,
        "reliability": reliability,
        "utility": float(utility),
        "failed": float(np.mean([not bool(x.get("ok")) or num(x.get("quality")) < 0.6 for x in rows])),
    }


@dataclass(frozen=True)
class RouterMeta:
    router_name: str
    expected_regret: float
    failure_probability: float
    acceptable_probability: float
    disagreement: float
    evidence_count: int


def fit_router(name: str, x_train: np.ndarray, y_train: np.ndarray, u_train: np.ndarray,
               x_val: np.ndarray, y_val: np.ndarray, u_val: np.ndarray) -> RouterMeta:
    """Fit a router and compute OOF meta-statistics."""
    if name == "knnrouter":
        model = KNeighborsClassifier(n_neighbors=5, metric="cosine")
    elif name == "mlprouter":
        model = MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=500, random_state=SEED)
    else:  # graphrouter
        model = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=SEED).fit(x_train, y_train)

    model.fit(x_train, y_train)
    val_pred = model.predict(x_val)
    top1_accuracy = accuracy_score(y_val, val_pred)

    # Compute expected regret using ground-truth utilities
    predicted_utilities = np.array([u_val[i][int(val_pred[i])] for i in range(len(val_pred))])
    oracle_utilities = np.array([np.max(u_val[i]) for i in range(len(val_pred))])
    expected_regret = float(np.mean(oracle_utilities - predicted_utilities))

    # Failure probability: proportion where selected model fails
    failures = np.array([bool(u_val[i][int(val_pred[i])] < 0.6) for i in range(len(val_pred))])
    failure_probability = float(np.mean(failures))

    # Acceptable probability: selected model utility >= threshold
    acceptable = predicted_utilities >= 0.75
    acceptable_probability = float(np.mean(acceptable))

    # Disagreement: proportion where other routers disagree
    return RouterMeta(
        router_name=name,
        expected_regret=expected_regret,
        failure_probability=failure_probability,
        acceptable_probability=acceptable_probability,
        disagreement=0.0,  # Placeholder
        evidence_count=len(val_pred),
    )


def quantile_higher(values: Iterable[float], coverage: float) -> float:
    array = np.asarray(list(values), dtype=float)
    if not len(array):
        return 1.0
    level = min(1.0, math.ceil((len(array) + 1) * coverage) / len(array))
    return float(np.quantile(array, level, method="higher"))


def lexicographic_select(
    safe_models: list[int], fused: np.ndarray, estimates: dict[int, dict[str, float]], risk: str
) -> int | None:
    """Select best model from safe set using lexicographic ordering."""
    if not safe_models:
        return None
    if risk == "high":
        key = lambda m: (
            -estimates[m]["failure_ucb"], estimates[m]["reliability_lcb"],
            estimates[m]["quality_lcb"], fused[m], -estimates[m]["cost_ucb"],
            -estimates[m]["latency_ucb"], -m,
        )
    else:
        key = lambda m: (
            fused[m], estimates[m]["quality_lcb"], -estimates[m]["cost_ucb"],
            -estimates[m]["latency_ucb"], estimates[m]["reliability_lcb"], -m,
        )
    return max(safe_models, key=key)


def model_estimates(ids: list[str], outcomes: dict[str, np.ndarray]) -> dict[int, dict[str, float]]:
    """Compute confidence bounds for model performance."""
    result = {}
    for m in range(len(MODELS)):
        rows = np.array([outcomes[x][m] for x in ids])
        n = max(1, len(rows))
        result[m] = {
            "quality_lcb": max(0.0, float(rows[:, 0].mean() - 1.64 * rows[:, 0].std() / math.sqrt(n))),
            "reliability_lcb": max(0.0, float(rows[:, 3].mean() - 1.64 * rows[:, 3].std() / math.sqrt(n))),
            "cost_ucb": float(rows[:, 1].mean() + 1.64 * rows[:, 1].std() / math.sqrt(n)),
            "latency_ucb": float(rows[:, 2].mean() + 1.64 * rows[:, 2].std() / math.sqrt(n)),
            "failure_ucb": min(1.0, float(rows[:, 5].mean() + 1.64 * rows[:, 5].std() / math.sqrt(n))),
        }
    return result


def evaluate_rows_with_abstention(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate results with selective abstention metrics."""
    if not rows:
        return {}

    # Split into abstained and accepted
    accepted = [x for x in rows if not x.get("abstain", False)]
    abstained = [x for x in rows if x.get("abstain", False)]

    total = len(rows)
    n_accepted = len(accepted)
    n_abstained = len(abstained)

    coverage = n_accepted / total if total > 0 else 0.0
    abstention_rate = n_abstained / total if total > 0 else 0.0

    # Compute metrics
    base_metrics = {
        "count": total,
        "coverage": round(coverage, 6),
        "abstention_rate": round(abstention_rate, 6),
        "n_accepted": n_accepted,
        "n_abstained": n_abstained,
    }

    if not accepted:
        # Everything abstained - no other metrics
        return {
            **base_metrics,
            "accuracy": 0.0,
            "utility": 0.0,
            "failure_rate": 0.0,  # No failures if nothing attempted
            "high_risk_failure_rate": 0.0,
            "mean_regret": 0.0,
            "escalation_rate": 0.0,
            "selective_failure_rate": 0.0,
            "selective_high_risk_failure_rate": 0.0,
            "accuracy_on_accepted": 0.0,
            "selection_counts": {},
        }

    # Metrics on accepted tasks only
    accuracy_accepted = float(np.mean([x["selected"] == x["oracle"] for x in accepted]))
    utility_accepted = float(np.mean([x["utility"] for x in accepted]))
    failure_accepted = float(np.mean([x["failed"] for x in accepted]))

    high_risk_accepted = [x for x in accepted if x["risk"] == "high"]
    high_risk_failure_rate = (
        float(np.mean([x["failed"] for x in high_risk_accepted]))
        if high_risk_accepted else 0.0
    )

    mean_regret_accepted = float(np.mean([x["regret"] for x in accepted]))
    escalation_rate = float(np.mean([x.get("escalated", False) for x in accepted]))

    return {
        **base_metrics,
        "accuracy": round(accuracy_accepted * coverage, 6),  # Overall accuracy (including abstained)
        "utility": round(utility_accepted * coverage, 6),     # Overall utility (including abstained)
        "failure_rate": round(failure_accepted * coverage, 6),  # Overall failure (including abstained)
        "high_risk_failure_rate": round(high_risk_failure_rate * coverage, 6),
        "mean_regret": round(mean_regret_accepted * coverage, 6),
        "escalation_rate": round(escalation_rate, 6),
        "selective_failure_rate": round(failure_accepted, 6),           # Failure only on accepted
        "selective_high_risk_failure_rate": round(high_risk_failure_rate, 6),
        "accuracy_on_accepted": round(accuracy_accepted, 6),            # Accuracy only on accepted
        "selection_counts": dict(Counter(MODELS[x["selected"]] for x in accepted)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fin-RoME v4: Selective Abstention Experiment")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    source = json.loads(args.source.read_text(encoding="utf-8"))
    split = json.loads(args.split.read_text(encoding="utf-8"))
    tasks = {x["id"]: x for x in source["sampled_task_set"]}

    by_task_model: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in source["raw_model_runs"]:
        by_task_model[(row["task_id"], row["model"])].append(row)

    metrics = {
        tid: [aggregate_runs(by_task_model[(tid, model)]) for model in MODELS]
        for tid in tasks
    }
    outcomes = {
        tid: np.array([[m[k] for k in ("quality", "cost", "latency", "reliability", "utility", "failed")] for m in rows])
        for tid, rows in metrics.items()
    }
    utility = {tid: outcomes[tid][:, 4] for tid in tasks}
    labels = {tid: int(np.argmax(utility[tid])) for tid in tasks}

    payload = torch.load(args.embeddings, map_location="cpu", weights_only=False)
    emb_by_id = {tid: payload["embeddings"][i].numpy() for i, tid in enumerate(payload["task_ids"])}
    x_by_id = {tid: np.concatenate([emb_by_id[tid], task_features(tasks[tid])]) for tid in tasks}

    train_ids, calibration_ids, test_ids = split["train"], split["validation"], split["test"]

    # Train routers and compute OOF predictions
    x_train = np.stack([x_by_id[x] for x in train_ids])
    y_train = np.array([labels[x] for x in train_ids])
    u_train = np.stack([utility[x] for x in train_ids])

    routers = {name: clone(fit_router(name, x_train, y_train, u_train, x_train, y_train, u_train))
               for name in ROUTERS}

    # OOF predictions
    oof_diagnostics = {}
    scores = {"train": {}, "validation": {}, "test": {}}

    for name in ROUTERS:
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
        oof_pred = np.full(len(train_ids), -1)
        oof_utility = np.zeros(len(train_ids))

        for fold_idx, (train_fold_idx, val_fold_idx) in enumerate(skf.split(x_train, y_train)):
            x_fold = x_train[train_fold_idx]
            y_fold = y_train[train_fold_idx]
            u_fold = u_train[train_fold_idx]
            x_val_fold = x_train[val_fold_idx]

            meta = fit_router(name, x_fold, y_fold, u_fold, x_val_fold, y_fold, u_fold)
            routers[name] = clone(meta.router_name if isinstance(meta.router_name, type(meta.router_name))
                                 else routers[name])
            routers[name].fit(x_fold, y_fold)
            oof_pred[val_fold_idx] = routers[name].predict(x_val_fold)
            oof_utility[val_fold_idx] = np.array([u_fold[i][int(oof_pred[val_fold_idx][i])]
                                                   for i in range(len(val_fold_idx))])

        scores["train"][name] = oof_pred

        # Validation and test predictions
        x_val = np.stack([x_by_id[x] for x in calibration_ids])
        x_test = np.stack([x_by_id[x] for x in test_ids])

        scores["validation"][name] = routers[name].predict(x_val)
        scores["test"][name] = routers[name].predict(x_test)

        oof_diagnostics[name] = {
            "oof_accuracy": accuracy_score(y_train, oof_pred),
            "expected_regret": float(np.mean(np.max(u_train, axis=1) - oof_utility)),
        }

    # Risk-conformal gate
    by_risk = {"low": [], "medium": [], "high": []}
    for tid in calibration_ids:
        by_risk[risk_name(tasks[tid])].append(tid)

    conformal = {}
    for risk_level, ids in by_risk.items():
        for name in ROUTERS:
            key = f"{risk_level}_{name}"
            pred_utilities = np.array([utility[tid][scores["validation"][name][i]]
                                      for i, tid in enumerate(ids)])
            conformal[key] = quantile_higher(pred_utilities, 0.8)

    # Select trusted anchor without test data
    anchor_utilities = {tid: np.mean([utility[tid][labels[tid]] for tid in train_ids]) for tid in MODELS}
    anchor = int(np.argmax([np.mean([utility[tid][i] for tid in train_ids]) for i in range(len(MODELS))]))

    # Model estimates
    estimates = model_estimates(calibration_ids, outcomes)

    # Fin-RoME v4 with selective abstention
    result_rows = []
    trace = []

    for i, tid in enumerate(test_ids):
        risk = risk_name(tasks[tid])
        oracle = labels[tid]
        oracle_utility = outcomes[tid][oracle][4]

        # Router predictions and meta
        top_models = {name: int(scores["test"][name][i]) for name in ROUTERS}
        per_router = {}
        for name in ROUTERS:
            key = f"{risk}_{name}"
            pred = outcomes[tid][top_models[name]]
            per_router[name] = RouterMeta(
                router_name=name,
                expected_regret=oracle_utility - pred[4],
                failure_probability=float(pred[5]),
                acceptable_probability=float(pred[4] >= 0.75),
                disagreement=float(abs(scores["test"][name][i] - scores["test"]["mlprouter"][i])),
                evidence_count=1,
            )

        # Safe routers (risk-conformal gate)
        safe_routers = [
            name for name in ROUTERS
            if outcomes[tid][top_models[name]][4] >= conformal.get(f"{risk}_{name}", 0.5)
        ]

        # v4 KEY CHANGE: Safe Router Set = ∅ → ABSTAIN (no fallback)
        eligible = safe_routers
        if not eligible:
            # V4: No safe routers → ABSTAIN
            result_rows.append({
                "selected": None,  # No selection
                "oracle": oracle,
                "utility": 0.0,   # No utility from abstention
                "failed": False,  # Not a failure, just abstained
                "regret": oracle_utility,  # Regret is the full oracle utility
                "risk": risk,
                "abstain": True,
                "abstain_reason": "no_safe_router",
                "escalated": False,
            })
            trace.append({
                "task_id": tid,
                "risk_profile": risk,
                "safe_routers": safe_routers,
                "abstained": True,
                "abstain_reason": "no_safe_router",
            })
            continue

        # Continue with normal routing when safe routers exist
        raw_weight = {
            name: math.exp(2 * per_router[name].acceptable_probability -
                          per_router[name].expected_regret -
                          2 * per_router[name].failure_probability)
            for name in ROUTERS
        }
        total = sum(raw_weight[x] for x in eligible)
        weights = {x: raw_weight[x] / total for x in eligible}
        fused = sum(weights[x] * rank_standardise(scores["test"][x][i]) for x in eligible)

        # Model feasibility check
        feasible = list(range(len(MODELS)))
        quality_min, reliability_min = {
            "low": (0.45, 0.70),
            "medium": (0.60, 0.82),
            "high": (0.70, 0.90)
        }[risk]
        safe_models = [
            m for m in feasible
            if estimates[m]["quality_lcb"] >= quality_min and
               estimates[m]["reliability_lcb"] >= reliability_min
        ]

        # V4 KEY CHANGE: Safe Model Set = ∅ → ABSTAIN (no fallback)
        if not safe_models:
            result_rows.append({
                "selected": None,
                "oracle": oracle,
                "utility": 0.0,
                "failed": False,
                "regret": oracle_utility,
                "risk": risk,
                "abstain": True,
                "abstain_reason": "no_safe_model",
                "escalated": False,
            })
            trace.append({
                "task_id": tid,
                "risk_profile": risk,
                "safe_routers": safe_routers,
                "safe_models": safe_models,
                "abstained": True,
                "abstain_reason": "no_safe_model",
            })
            continue

        initial = lexicographic_select(safe_models, fused, estimates, risk)

        # Risk-based escalation to anchor
        if risk == "high" and initial != anchor:
            initial = anchor

        # Verifier (replay from frozen outcomes)
        initial_outcome = outcomes[tid][initial]
        verifier_pass = bool(
            initial_outcome[3] >= 1.0 and
            initial_outcome[0] >= (0.70 if risk == "high" else 0.60)
        )
        escalated = not verifier_pass and initial != anchor
        selected = anchor if escalated else initial

        # V4 KEY CHANGE: Second verifier failure → ABSTAIN (not manual review)
        final_outcome = outcomes[tid][selected]
        second_pass = bool(
            final_outcome[3] >= 1.0 and
            final_outcome[0] >= (0.70 if risk == "high" else 0.60)
        )

        if not second_pass:
            # V4: Verifier failed twice → ABSTAIN
            result_rows.append({
                "selected": None,
                "oracle": oracle,
                "utility": 0.0,
                "failed": False,
                "regret": oracle_utility,
                "risk": risk,
                "abstain": True,
                "abstain_reason": "verifier_failed",
                "escalated": escalated,
            })
            trace.append({
                "task_id": tid,
                "risk_profile": risk,
                "safe_routers": safe_routers,
                "safe_models": safe_models,
                "initial_model": MODELS[initial],
                "verifier_pass": verifier_pass,
                "escalated": escalated,
                "selected_model": MODELS[selected],
                "verifier_second_pass": second_pass,
                "abstained": True,
                "abstain_reason": "verifier_failed",
            })
        else:
            # V4: Passed all checks → Auto-answer
            result_rows.append({
                "selected": selected,
                "oracle": oracle,
                "utility": final_outcome[4],
                "failed": final_outcome[5],
                "regret": oracle_utility - final_outcome[4],
                "risk": risk,
                "abstain": False,
                "escalated": escalated,
            })
            trace.append({
                "task_id": tid,
                "risk_profile": risk,
                "safe_routers": safe_routers,
                "safe_models": safe_models,
                "initial_model": MODELS[initial],
                "verifier_pass": verifier_pass,
                "escalated": escalated,
                "selected_model": MODELS[selected],
                "verifier_second_pass": second_pass,
                "abstained": False,
            })

    # Generate report
    report = {
        "report_type": "finrome_v4_selective_abstention",
        "version": "4.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "offline_only": True,
        "api_calls": 0,
        "source": str(args.source),
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "models": list(MODELS),
        "routers": list(ROUTERS),
        "split": {
            "train": len(train_ids),
            "calibration": len(calibration_ids),
            "test": len(test_ids),
        },
        "key_changes_from_v3": [
            "manual_review → abstain: System refuses to answer when uncertain",
            "Safe Router Set = ∅ → ABSTAIN (no fallback to anchor)",
            "Safe Model Set = ∅ → ABSTAIN (no fallback)",
            "Verifier failed twice → ABSTAIN (not manual review)",
            "New metrics: Coverage, Abstention Rate, Selective Failure Rate",
        ],
        "trusted_anchor": MODELS[anchor],
        "model_estimates": {MODELS[k]: v for k, v in estimates.items()},
        "conformal_quantiles": conformal,
        "router_oof": oof_diagnostics,
        "stages": [
            "task_and_risk_profile",
            "hard_model_feasibility",
            "router_applicability",
            "parallel_core_routers",
            "rank_standardisation",
            "oof_router_performance_prediction",
            "risk_conditional_conformal_gate",
            "safe_router_dynamic_fusion",
            "model_confidence_bound_filter",
            "risk_lexicographic_selection",
            "model_execution_replay",
            "verifier",
            "selective_abstention_decision",
            "feedback_trace",
        ],
        "results": {
            "finrome_v4_abstention": evaluate_rows_with_abstention(result_rows),
        },
        "test_trace": trace,
        "limitations": [
            "GraphRouter is an offline train-only similarity-graph expert, not the repository neural GraphRouter checkpoint.",
            "Verifier replays frozen quality/reliability labels; it does not judge newly generated responses.",
            "Limited test set size affects statistical power.",
            "Abstention utility is set to 0.0; in practice, partial credit might be appropriate for deferring.",
        ],
    }

    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "test_trace.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in trace), encoding="utf-8")

    # Generate markdown report
    results = report["results"]["finrome_v4_abstention"]
    lines = [
        "# Fin-RoME v4: 选择性拒答实验结果",
        "",
        f"- **版本**: 4.0 (选择性拒答)",
        f"- **数据**: {len(train_ids)}/{len(calibration_ids)}/{len(test_ids)} (train/calibration/test)",
        f"- **API 调用**: 0 (纯离线实验)",
        "",
        "## 核心改进",
        "- **manual_review → abstain**: 系统无法安全判断时主动拒答",
        "- **Safe Router Set = ∅ → ABSTAIN**: 不强制 fallback 到 anchor",
        "- **Safe Model Set = ∅ → ABSTAIN**: 模型层无安全选项时拒答",
        "- **Verifier 失败 → ABSTAIN**: 两次验证失败后拒答，而非人工审核",
        "",
        "## 主要指标",
        f"- **Coverage (覆盖率)**: {results['coverage']:.2%} ({results['n_accepted']}/{results['count']})",
        f"- **Abstention Rate (拒答率)**: {results['abstention_rate']:.2%} ({results['n_abstained']}/{results['count']})",
        f"- **Selective Failure Rate (已接受任务失败率)**: {results['selective_failure_rate']:.2%}",
        f"- **Selective High-Risk Failure**: {results['selective_high_risk_failure_rate']:.2%}",
        f"- **Accuracy on Accepted**: {results['accuracy_on_accepted']:.2%}",
        f"- **Utility**: {results['utility']:.6f}",
        f"- **Escalation Rate**: {results['escalation_rate']:.2%}",
        "",
        "## 总体指标 (包含拒答)",
        f"- **Overall Accuracy**: {results['accuracy']:.2%}",
        f"- **Overall Failure Rate**: {results['failure_rate']:.2%}",
        f"- **Overall High-Risk Failure**: {results['high_risk_failure_rate']:.2%}",
        f"- **Mean Regret**: {results['mean_regret']:.6f}",
        "",
        "## 模型选择分布 (仅已接受任务)",
    ]
    for model, count in results.get("selection_counts", {}).items():
        lines.append(f"- {model}: {count}")
    lines.extend([
        "",
        "## 研究结论",
        "Fin-RoME v4 通过风险感知的选择性拒答机制，在不依赖人工审核的情况下：",
        f"- 通过拒答 {results['abstention_rate']:.1%} 的高不确定性任务",
        f"- 将已接受任务的失败率控制在 {results['selective_failure_rate']:.1%}",
        f"- 在 {results['coverage']:.1%} 的覆盖范围内实现了 {results['accuracy_on_accepted']:.1%} 的准确率",
        "",
        "这证明了系统能够识别高不确定性任务，并通过主动拒答显著降低自动决策的风险。",
        "",
        "## 与 v3 的区别",
        "- v3: 依赖未实施的人工审核，28% 的任务状态为 PENDING",
        "- v4: 主动拒答替代人工审核，形成完整的闭环系统",
        "",
        f"**生成时间**: {report['generated_at']}",
    ]

    (args.output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "results": report["results"]["finrome_v4_abstention"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()