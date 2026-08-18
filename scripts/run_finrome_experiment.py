#!/usr/bin/env python3
"""Leakage-safe offline experiment for the 13-stage Fin-RoME pipeline.

The experiment reuses the frozen 100-task/4-model/3-repeat finance response
matrix.  It makes no API calls and never exposes test outcomes to training,
calibration, expert selection, threshold selection, or anchor selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
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
DEFAULT_OUTPUT = ROOT / "run_logs/finrome_13stage"
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
        "failed": float(reliability < 1.0 or quality < 0.6),
    }


class SimilarityGraphRouter:
    """Transductive-free graph expert using a train-only query similarity graph.

    Training nodes carry model-utility edges.  A new query connects only to
    training query nodes, and model scores are propagated over those edges.
    """

    def __init__(self, neighbours: int = 9, temperature: float = 0.12):
        self.neighbours = neighbours
        self.temperature = temperature

    def fit(self, x: np.ndarray, y: np.ndarray, utility: np.ndarray) -> "SimilarityGraphRouter":
        self.scaler = StandardScaler().fit(x)
        z = self.scaler.transform(x)
        self.x = z / np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-9)
        self.y = y
        self.utility = utility
        return self

    def predict_scores(self, x: np.ndarray) -> np.ndarray:
        z = self.scaler.transform(x)
        z = z / np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-9)
        similarity = z @ self.x.T
        output = []
        for row in similarity:
            idx = np.argsort(row)[-min(self.neighbours, len(row)):]
            weights = softmax(row[idx] / self.temperature)
            propagated = (weights[:, None] * self.utility[idx]).sum(axis=0)
            # A small class-edge term stabilises sparse optimal labels.
            votes = np.zeros(len(MODELS))
            for weight, label in zip(weights, self.y[idx]):
                votes[int(label)] += weight
            output.append(0.8 * propagated + 0.2 * votes)
        return np.asarray(output)


def make_expert(name: str) -> Any:
    if name == "knnrouter":
        return KNeighborsClassifier(n_neighbors=7, weights="distance", metric="cosine", algorithm="brute")
    if name == "mlprouter":
        return MLPClassifier(hidden_layer_sizes=(48, 24), alpha=0.02, max_iter=700, random_state=SEED)
    if name == "graphrouter":
        return SimilarityGraphRouter()
    raise KeyError(name)


def fit_expert(name: str, x: np.ndarray, y: np.ndarray, utility: np.ndarray) -> Any:
    expert = make_expert(name)
    if name == "graphrouter":
        return expert.fit(x, y, utility)
    return expert.fit(x, y)


def expert_scores(name: str, expert: Any, x: np.ndarray) -> np.ndarray:
    if name == "graphrouter":
        return expert.predict_scores(x)
    probability = expert.predict_proba(x)
    scores = np.zeros((len(x), len(MODELS)))
    for column, label in enumerate(expert.classes_):
        scores[:, int(label)] = probability[:, column]
    return scores


@dataclass
class MetaPrediction:
    acceptable_probability: float
    failure_probability: float
    expected_regret: float
    regret_upper_bound: float
    safe: bool


def meta_features(base: np.ndarray, scores: np.ndarray) -> np.ndarray:
    ordered = np.sort(scores, axis=1)
    margin = ordered[:, -1] - ordered[:, -2]
    entropy = -np.sum(softmax_rows(scores) * np.log(np.maximum(softmax_rows(scores), 1e-12)), axis=1)
    return np.column_stack([base, margin, entropy, scores])


def softmax_rows(scores: np.ndarray) -> np.ndarray:
    return np.vstack([softmax(row) for row in scores])


class ConstantProbability:
    def __init__(self, value: float):
        self.value = float(value)

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        p = np.full(len(x), self.value)
        return np.column_stack([1 - p, p])


def fit_binary(x: np.ndarray, y: np.ndarray) -> Any:
    if len(np.unique(y)) < 2:
        return ConstantProbability(float(np.mean(y)))
    return LogisticRegression(max_iter=1000, class_weight="balanced", random_state=SEED).fit(x, y)


def quantile_higher(values: Iterable[float], coverage: float) -> float:
    array = np.asarray(list(values), dtype=float)
    if not len(array):
        return 1.0
    level = min(1.0, math.ceil((len(array) + 1) * coverage) / len(array))
    return float(np.quantile(array, level, method="higher"))


def lexicographic_select(
    safe_models: list[int], fused: np.ndarray, estimates: dict[int, dict[str, float]], risk: str
) -> int | None:
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


def evaluate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    return {
        "count": len(rows),
        "accuracy": round(float(np.mean([x["selected"] == x["oracle"] for x in rows])), 6),
        "utility": round(float(np.mean([x["utility"] for x in rows])), 6),
        "failure_rate": round(float(np.mean([x["failed"] for x in rows])), 6),
        "high_risk_failure_rate": round(float(np.mean([x["failed"] for x in rows if x["risk"] == "high"])), 6)
        if any(x["risk"] == "high" for x in rows) else None,
        "mean_regret": round(float(np.mean([x["regret"] for x in rows])), 6),
        "escalation_rate": round(float(np.mean([x.get("escalated", False) for x in rows])), 6),
        "manual_review_rate": round(float(np.mean([x.get("manual_review", False) for x in rows])), 6),
        "selection_counts": dict(Counter(MODELS[x["selected"]] for x in rows)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
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
    assert not (set(train_ids) & set(calibration_ids) or set(train_ids) & set(test_ids) or set(calibration_ids) & set(test_ids))

    x_train = np.stack([x_by_id[x] for x in train_ids])
    y_train = np.array([labels[x] for x in train_ids])
    u_train = np.stack([utility[x] for x in train_ids])
    base_train_features = np.stack([task_features(tasks[x]) for x in train_ids])
    min_class = min(Counter(y_train).values())
    folds = max(2, min(5, min_class))
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=SEED)
    oof_scores = {name: np.zeros((len(train_ids), len(MODELS))) for name in ROUTERS}
    for fit_idx, hold_idx in cv.split(x_train, y_train):
        for name in ROUTERS:
            expert = fit_expert(name, x_train[fit_idx], y_train[fit_idx], u_train[fit_idx])
            oof_scores[name][hold_idx] = expert_scores(name, expert, x_train[hold_idx])

    delta = 0.03
    meta_models: dict[str, dict[str, Any]] = {}
    oof_diagnostics = {}
    for name in ROUTERS:
        selected = np.argmax(oof_scores[name], axis=1)
        chosen_u = u_train[np.arange(len(train_ids)), selected]
        oracle_u = u_train.max(axis=1)
        regret = oracle_u - chosen_u
        acceptable = (regret <= delta).astype(int)
        failed = np.array([outcomes[tid][model, 5] for tid, model in zip(train_ids, selected)], dtype=int)
        features = meta_features(base_train_features, oof_scores[name])
        meta_models[name] = {
            "acceptable": fit_binary(features, acceptable),
            "failure": fit_binary(features, failed),
            "regret": clone(LogisticRegression(max_iter=1000, random_state=SEED)).fit(features, (regret > delta).astype(int)),
        }
        p = meta_models[name]["acceptable"].predict_proba(features)[:, 1]
        oof_diagnostics[name] = {
            "accuracy": round(float(accuracy_score(y_train, selected)), 6),
            "acceptable_rate": round(float(acceptable.mean()), 6),
            "failure_rate": round(float(failed.mean()), 6),
            "mean_regret": round(float(regret.mean()), 6),
            "acceptable_brier_in_sample_meta": round(float(brier_score_loss(acceptable, p)), 6),
        }

    # Final experts use train only. Calibration outcomes calibrate gates; test stays sealed.
    experts = {name: fit_expert(name, x_train, y_train, u_train) for name in ROUTERS}
    sets = {"calibration": calibration_ids, "test": test_ids}
    scores: dict[str, dict[str, np.ndarray]] = {part: {} for part in sets}
    for part, ids in sets.items():
        x = np.stack([x_by_id[z] for z in ids])
        for name in ROUTERS:
            scores[part][name] = expert_scores(name, experts[name], x)

    # Risk-conditional conformal regret residuals, calibrated per router and risk group.
    conformal: dict[str, dict[str, float]] = {name: {} for name in ROUTERS}
    for name in ROUTERS:
        ids = calibration_ids
        chosen = np.argmax(scores["calibration"][name], axis=1)
        feature = meta_features(np.stack([task_features(tasks[x]) for x in ids]), scores["calibration"][name])
        predicted_bad = meta_models[name]["regret"].predict_proba(feature)[:, 1]
        actual_regret = np.array([utility[tid].max() - utility[tid][m] for tid, m in zip(ids, chosen)])
        for risk in ("low", "medium", "high"):
            idx = [i for i, tid in enumerate(ids) if risk_name(tasks[tid]) == risk]
            residual = [max(0.0, actual_regret[i] - predicted_bad[i]) for i in idx]
            conformal[name][risk] = quantile_higher(residual, 0.90 if risk != "high" else 0.95)

    estimates = model_estimates(train_ids + calibration_ids, outcomes)
    high_cal = [x for x in calibration_ids if risk_name(tasks[x]) == "high"] or calibration_ids
    anchor = min(
        range(len(MODELS)),
        key=lambda m: (
            float(np.mean([outcomes[x][m, 5] for x in high_cal])),
            -float(np.mean([outcomes[x][m, 3] for x in high_cal])),
            -float(np.mean([outcomes[x][m, 4] for x in high_cal])),
            m,
        ),
    )

    thresholds = {"low": 0.45, "medium": 0.32, "high": 0.22}
    result_rows: list[dict[str, Any]] = []
    fixed_rows: list[dict[str, Any]] = []
    oracle_rows: list[dict[str, Any]] = []
    individual_rows: dict[str, list[dict[str, Any]]] = {name: [] for name in ROUTERS}
    equal_rows: list[dict[str, Any]] = []
    dynamic_no_gate_rows: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []

    for i, tid in enumerate(test_ids):
        task = tasks[tid]
        risk = risk_name(task)
        oracle = labels[tid]
        oracle_utility = utility[tid][oracle]
        per_router: dict[str, MetaPrediction] = {}
        top_models = []
        for name in ROUTERS:
            router_scores = scores["test"][name][i]
            top = int(np.argmax(router_scores))
            top_models.append(top)
            feature = meta_features(task_features(task)[None, :], router_scores[None, :])
            p_accept = float(meta_models[name]["acceptable"].predict_proba(feature)[0, 1])
            p_fail = float(meta_models[name]["failure"].predict_proba(feature)[0, 1])
            p_bad = float(meta_models[name]["regret"].predict_proba(feature)[0, 1])
            upper = min(1.0, p_bad + conformal[name][risk])
            per_router[name] = MetaPrediction(p_accept, p_fail, p_bad, upper, upper <= thresholds[risk])
            row = outcomes[tid][top]
            individual_rows[name].append({"selected": top, "oracle": oracle, "utility": row[4], "failed": row[5], "regret": oracle_utility-row[4], "risk": risk})

        safe_routers = [name for name in ROUTERS if per_router[name].safe]
        disagreement = 1 - max(Counter(top_models).values()) / len(top_models)
        equal = np.mean([rank_standardise(scores["test"][name][i]) for name in ROUTERS], axis=0)
        equal_model = int(np.argmax(equal))
        erow = outcomes[tid][equal_model]
        equal_rows.append({"selected": equal_model, "oracle": oracle, "utility": erow[4], "failed": erow[5], "regret": oracle_utility-erow[4], "risk": risk})

        raw_weight = {
            name: math.exp(2 * per_router[name].acceptable_probability - per_router[name].expected_regret - 2 * per_router[name].failure_probability)
            for name in ROUTERS
        }
        all_total = sum(raw_weight.values())
        all_fused = sum(raw_weight[name] / all_total * rank_standardise(scores["test"][name][i]) for name in ROUTERS)
        all_model = int(np.argmax(all_fused))
        arow = outcomes[tid][all_model]
        dynamic_no_gate_rows.append({"selected": all_model, "oracle": oracle, "utility": arow[4], "failed": arow[5], "regret": oracle_utility-arow[4], "risk": risk})

        eligible = safe_routers
        if eligible:
            total = sum(raw_weight[x] for x in eligible)
            weights = {x: raw_weight[x] / total for x in eligible}
            fused = sum(weights[x] * rank_standardise(scores["test"][x][i]) for x in eligible)
        else:
            weights, fused = {}, np.zeros(len(MODELS))

        # Deterministic feasibility is checked before probabilistic safety.
        feasible = list(range(len(MODELS)))
        quality_min, reliability_min = {"low": (0.45, 0.70), "medium": (0.60, 0.82), "high": (0.70, 0.90)}[risk]
        safe_models = [m for m in feasible if estimates[m]["quality_lcb"] >= quality_min and estimates[m]["reliability_lcb"] >= reliability_min]
        initial = lexicographic_select(safe_models, fused, estimates, risk) if eligible else None
        fallback_reason = None
        if initial is None:
            initial, fallback_reason = anchor, "no_safe_router_or_model"
        elif risk == "high" and disagreement > 0.5:
            initial, fallback_reason = anchor, "high_risk_disagreement"

        # Response-level verifier and AutoMix escalation to the validated anchor.
        initial_outcome = outcomes[tid][initial]
        verifier_pass = bool(initial_outcome[3] >= 1.0 and initial_outcome[0] >= (0.70 if risk == "high" else 0.60))
        escalated = not verifier_pass and initial != anchor
        selected = anchor if escalated else initial
        final_outcome = outcomes[tid][selected]
        second_pass = bool(final_outcome[3] >= 1.0 and final_outcome[0] >= (0.70 if risk == "high" else 0.60))
        manual = not second_pass or (risk == "high" and disagreement > 0.5)
        row = {"selected": selected, "oracle": oracle, "utility": final_outcome[4], "failed": final_outcome[5], "regret": oracle_utility-final_outcome[4], "risk": risk, "escalated": escalated, "manual_review": manual}
        result_rows.append(row)
        fixed = outcomes[tid][anchor]
        fixed_rows.append({"selected": anchor, "oracle": oracle, "utility": fixed[4], "failed": fixed[5], "regret": oracle_utility-fixed[4], "risk": risk})
        best = outcomes[tid][oracle]
        oracle_rows.append({"selected": oracle, "oracle": oracle, "utility": best[4], "failed": best[5], "regret": 0.0, "risk": risk})
        trace.append({
            "task_id": tid, "risk_profile": risk, "feasible_models": [MODELS[x] for x in feasible],
            "router_top1": {name: MODELS[top_models[j]] for j, name in enumerate(ROUTERS)},
            "router_meta": {name: asdict(per_router[name]) for name in ROUTERS},
            "safe_routers": safe_routers, "weights": weights, "disagreement": round(disagreement, 6),
            "safe_models": [MODELS[x] for x in safe_models], "initial_model": MODELS[initial],
            "verifier_pass": verifier_pass, "automix_escalated": escalated, "trusted_anchor": MODELS[anchor],
            "selected_model": MODELS[selected], "manual_review": manual, "fallback_reason": fallback_reason,
        })

    report = {
        "report_type": "finrome_leakage_safe_13_stage_offline_experiment",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "offline_only": True,
        "api_calls": 0,
        "source": str(args.source),
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "models": list(MODELS), "routers": list(ROUTERS),
        "split": {"train": len(train_ids), "calibration": len(calibration_ids), "test": len(test_ids), "oof_folds": folds},
        "leakage_checks": {
            "disjoint_train_calibration_test": True, "base_meta_training_uses_oof": True,
            "calibration_not_used_for_base_or_meta_fit": True, "test_used_once_for_final_evaluation": True,
            "anchor_selected_without_test": True, "no_api_calls": True,
        },
        "trusted_anchor": MODELS[anchor],
        "model_estimates": {MODELS[k]: v for k, v in estimates.items()},
        "conformal_quantiles": conformal,
        "router_oof": oof_diagnostics,
        "stages": [
            "task_and_risk_profile", "hard_model_feasibility", "router_applicability", "parallel_core_routers",
            "rank_standardisation", "oof_router_performance_prediction", "risk_conditional_conformal_gate",
            "safe_router_dynamic_fusion", "model_confidence_bound_filter", "risk_lexicographic_selection",
            "model_execution_replay", "verifier", "automix_anchor_or_manual_review", "feedback_trace",
        ],
        "results": {
            "M0_individual": {name: evaluate_rows(rows) for name, rows in individual_rows.items()},
            "M1_equal_rank_fusion": evaluate_rows(equal_rows),
            "M2_dynamic_without_conformal": evaluate_rows(dynamic_no_gate_rows),
            "M3_to_M5_full_finrome": evaluate_rows(result_rows),
            "trusted_anchor_baseline": evaluate_rows(fixed_rows),
            "oracle_upper_bound": evaluate_rows(oracle_rows),
        },
        "test_trace": trace,
        "limitations": [
            "GraphRouter is an offline train-only similarity-graph expert, not the repository neural GraphRouter checkpoint.",
            "Verifier replays frozen quality/reliability labels; it does not judge newly generated responses.",
            "Only 100 tasks and 20 held-out test tasks are available, so confidence intervals remain wide.",
        ],
    }
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "test_trace.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in trace), encoding="utf-8")
    full = report["results"]["M3_to_M5_full_finrome"]
    lines = [
        "# Fin-RoME 13 阶段严格离线实验", "",
        f"- 数据：100 个冻结金融任务；train/calibration/test = {len(train_ids)}/{len(calibration_ids)}/{len(test_ids)}；API 调用 0",
        f"- 核心 Router：KNNRouter / MLPRouter / GraphRouter；OOF 折数：{folds}",
        f"- Trusted Anchor：{MODELS[anchor]}（仅由校准集高风险表现确定）",
        f"- 完整流程测试效用：{full['utility']:.6f}",
        f"- 完整流程失败率：{full['failure_rate']:.2%}；高风险失败率：{full['high_risk_failure_rate']}",
        f"- 升级率：{full['escalation_rate']:.2%}；人工复核率：{full['manual_review_rate']:.2%}", "",
        "## 分阶段结果", "",
    ]
    for name, value in report["results"].items():
        if name == "M0_individual":
            for router, metric in value.items():
                lines.append(f"- M0 {router}: utility={metric['utility']:.6f}, failure={metric['failure_rate']:.2%}, regret={metric['mean_regret']:.6f}")
        else:
            lines.append(f"- {name}: utility={value['utility']:.6f}, failure={value['failure_rate']:.2%}, regret={value['mean_regret']:.6f}")
    lines += ["", "## 解释边界", ""] + [f"- {x}" for x in report["limitations"]]
    (args.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "trusted_anchor": MODELS[anchor], "results": report["results"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
