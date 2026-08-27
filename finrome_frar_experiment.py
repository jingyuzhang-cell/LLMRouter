#!/usr/bin/env python3
"""Leakage-safe Financial Risk-Aware Routing (FRAR) experiment.

Training: Fin-RoME original + safety expansion v1 only.
Evaluation: frozen safety expansion v2 only.  V2 outcomes are loaded only after
all routing decisions have been frozen in memory.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo")
LAMBDAS = (0.0, 0.1, 0.2, 0.5, 1.0, 2.0)
UTILITY_WEIGHTS = {"quality": 0.45, "cost": 0.20, "latency": 0.15, "reliability": 0.20}
DEFAULT_DYNAMIC_LAMBDA = {"low": 0.1, "medium": 0.3, "high": 0.7, "unknown": 0.3}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def task_text(task: dict[str, Any]) -> str:
    evidence = task.get("evidence", [])
    evidence_text = json.dumps(evidence, ensure_ascii=False) if evidence else ""
    return " ".join((str(task.get("question", "")), str(task.get("context", "")), evidence_text))


def table_size(table: Any) -> tuple[int, int]:
    if not isinstance(table, list):
        return 0, 0
    rows = len(table)
    cols = max((len(row) for row in table if isinstance(row, list)), default=0)
    return rows, cols


def feature_row(task: dict[str, Any], model: str) -> dict[str, Any]:
    text = task_text(task)
    rows, cols = table_size(task.get("table", []))
    evidence = task.get("evidence", [])
    return {
        "text": text,
        "model_text": " ".join(model.replace("-", "_") + "__" + token for token in text.lower().split()),
        "model": model,
        "dataset": str(task.get("dataset", "unknown")),
        "task_type": str(task.get("task_type", "unknown")),
        "risk_level": str(task.get("risk_level", "unknown")).lower(),
        "context_chars": len(str(task.get("context", ""))),
        "question_chars": len(str(task.get("question", ""))),
        "table_rows": rows,
        "table_cols": cols,
        "evidence_spans": len(evidence) if isinstance(evidence, list) else 0,
        "requires_calculation": int(bool(task.get("requires_calculation", False))),
        "requires_table_reasoning": int(bool(task.get("requires_table_reasoning", False))),
        "requires_kg_reasoning": int(bool(task.get("requires_kg_reasoning", False))),
        "requires_verification": int(bool(task.get("requires_verification", False))),
    }


TEXT = "text"
CATEGORICAL = ["model", "dataset", "task_type", "risk_level"]
NUMERIC = [
    "context_chars", "question_chars", "table_rows", "table_cols", "evidence_spans",
    "requires_calculation", "requires_table_reasoning", "requires_kg_reasoning", "requires_verification",
]


def make_preprocessor() -> ColumnTransformer:
    return ColumnTransformer([
        ("text", TfidfVectorizer(max_features=5000, ngram_range=(1, 2), min_df=2, sublinear_tf=True), TEXT),
        ("model_text", TfidfVectorizer(max_features=10000, ngram_range=(1, 2), min_df=2, sublinear_tf=True), "model_text"),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ("num", Pipeline([("impute", SimpleImputer()), ("scale", StandardScaler())]), NUMERIC),
    ])


def judge_models(candidate: str) -> tuple[str, str]:
    if candidate == "deepseek-chat":
        return "qwen-plus", "glm-5.2"
    if candidate in ("qwen-plus", "qwen-turbo"):
        return "deepseek-chat", "glm-5.2"
    return "deepseek-chat", "qwen-plus"


def labeled_rows(data_dirs: list[Path]) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, float]]]:
    features: list[dict[str, Any]] = []
    labels: dict[tuple[str, str], list[dict[str, float]]] = defaultdict(list)
    for directory in data_dirs:
        tasks = {x["id"]: x for x in load_jsonl(directory / "tasks.jsonl")}
        responses = {(x["task_id"], x["model"], int(x.get("repeat", 0))): x for x in load_jsonl(directory / "responses.jsonl")}
        judges = {(x["task_id"], x["candidate_model"], int(x.get("repeat", 0)), x["judge_model"]): x
                  for x in load_jsonl(directory / "judges.jsonl")}
        for (task_id, model, repeat), response in responses.items():
            if task_id not in tasks or model not in MODELS or not response.get("success"):
                continue
            scores = [judges[(task_id, model, repeat, jm)].get("score") for jm in judge_models(model)
                      if (task_id, model, repeat, jm) in judges and judges[(task_id, model, repeat, jm)].get("parsed")]
            scores = [float(x) for x in scores if x is not None]
            if not scores:
                continue
            labels[(task_id, model)].append({
                "quality": float(np.mean(scores)),
                "failure": float(np.mean(scores) < 0.5),
                "cost": float(response.get("cost_usd") or 0.0),
                "latency": float(response.get("latency_ms") or 0.0),
                "reliability": float(response.get("error") is None),
            })
        for (task_id, model), repeats in labels.copy().items():
            if task_id not in tasks or any(r.get("task_id") == task_id and r.get("model") == model for r in features):
                continue
            row = feature_row(tasks[task_id], model)
            row.update({"task_id": task_id, **{k: float(np.mean([x[k] for x in repeats])) for k in repeats[0]}})
            features.append(row)
    return features, {k: {n: float(np.mean([x[n] for x in v])) for n in v[0]} for k, v in labels.items()}


def scored_labeled_rows(data_dirs: list[Path]) -> list[dict[str, Any]]:
    """Load project-standard scored responses and aggregate repeats per task-model."""
    result = []
    seen = set()
    for directory in data_dirs:
        tasks = {x["id"]: x for x in load_jsonl(directory / "tasks.jsonl")}
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in load_jsonl(directory / "scored_responses.jsonl"):
            key = (row["task_id"], row["model"])
            if key[0] in tasks and key[1] in MODELS and row.get("quality") is not None:
                grouped[key].append(row)
        for (task_id, model), repeats in grouped.items():
            if (task_id, model) in seen:
                continue
            seen.add((task_id, model))
            quality = float(np.mean([float(x["quality"]) for x in repeats]))
            row = feature_row(tasks[task_id], model)
            row.update({
                "task_id": task_id, "quality": quality, "failure": float(quality < 0.5),
                "cost": float(np.mean([float(x.get("cost_usd") or 0.0) for x in repeats])),
                "latency": float(np.mean([float(x.get("latency_ms") or 0.0) for x in repeats])),
                "reliability": float(np.mean([float(x.get("reliability", 0.0)) for x in repeats])),
            })
            result.append(row)
    return result

def frozen_test_outcomes(test_dir: Path, frozen_path: Path) -> dict[tuple[str, str], dict[str, float]]:
    """Join immutable judge outcomes with response telemetry for evaluation only."""
    quality_rows: dict[tuple[str, str], list[dict[str, float]]] = defaultdict(list)
    for row in load_jsonl(frozen_path):
        quality_rows[(row["task_id"], row["model"])].append({
            "quality": float(row["avg_score"]), "failure": float(row["failure"])})
    telemetry_rows: dict[tuple[str, str], list[dict[str, float]]] = defaultdict(list)
    for row in load_jsonl(test_dir / "responses.jsonl"):
        if row.get("success") and row.get("model") in MODELS:
            telemetry_rows[(row["task_id"], row["model"])].append({
                "cost": float(row.get("cost_usd") or 0.0),
                "latency": float(row.get("latency_ms") or 0.0),
                "reliability": float(row.get("error") is None)})
    outcomes = {}
    for key, values in quality_rows.items():
        if key not in telemetry_rows:
            continue
        telemetry = telemetry_rows[key]
        outcomes[key] = {
            "quality": float(np.mean([x["quality"] for x in values])),
            "failure": float(np.mean([x["failure"] for x in values])),
            "cost": float(np.mean([x["cost"] for x in telemetry])),
            "latency": float(np.mean([x["latency"] for x in telemetry])),
            "reliability": float(np.mean([x["reliability"] for x in telemetry])),
        }
    return outcomes

@dataclass
class FrozenModels:
    quality: Pipeline
    risk: Pipeline
    telemetry: dict[str, dict[str, float]]
    best_single: str


def fit_models(rows: list[dict[str, Any]]) -> FrozenModels:
    quality = Pipeline([("features", make_preprocessor()), ("model", Ridge(alpha=8.0, solver="lsqr"))])
    risk = Pipeline([("features", make_preprocessor()), ("model", Ridge(alpha=8.0, solver="lsqr"))])
    yq = np.asarray([r["quality"] for r in rows])
    yf = np.asarray([r["failure"] for r in rows], dtype=float)
    frame = pd.DataFrame(rows)
    quality.fit(frame, yq)
    risk.fit(frame, yf)
    telemetry: dict[str, dict[str, float]] = {}
    for model in MODELS:
        subset = [r for r in rows if r["model"] == model]
        telemetry[model] = {k: float(np.median([r[k] for r in subset])) for k in ("cost", "latency", "reliability")}
    by_model = {m: np.mean([r["quality"] for r in rows if r["model"] == m]) for m in MODELS}
    return FrozenModels(quality, risk, telemetry, max(by_model, key=by_model.get))


def decision_candidates(tasks: dict[str, dict[str, Any]], fitted: FrozenModels) -> dict[str, list[dict[str, Any]]]:
    all_rows = [feature_row(task, model) | {"task_id": task_id} for task_id, task in tasks.items() for model in MODELS]
    frame = pd.DataFrame(all_rows)
    quality_hat = np.clip(fitted.quality.predict(frame), 0, 1)
    risk_hat = np.clip(fitted.risk.predict(frame), 0, 1)
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row, qhat, rhat in zip(all_rows, quality_hat, risk_hat):
        telemetry = fitted.telemetry[row["model"]]
        cost_score = 1.0 / (1.0 + telemetry["cost"] * 1000.0)
        latency_score = 1.0 / (1.0 + telemetry["latency"] / 1000.0)
        utility_hat = (0.45 * qhat + 0.20 * cost_score + 0.15 * latency_score + 0.20 * telemetry["reliability"])
        result[row["task_id"]].append({
            "model": row["model"], "quality_hat": float(qhat), "risk_hat": float(rhat),
            "utility_hat": float(utility_hat), "risk_level": row["risk_level"],
        })
    return result


def freeze_decisions(candidates: dict[str, list[dict[str, Any]]], fitted: FrozenModels,
                     dynamic_lambda: dict[str, float], seed: int) -> dict[str, dict[str, str]]:
    rng = np.random.default_rng(seed)
    decisions: dict[str, dict[str, str]] = defaultdict(dict)
    for task_id, options in candidates.items():
        decisions["best_single"][task_id] = fitted.best_single
        decisions["random"][task_id] = str(rng.choice(MODELS))
        decisions["utility_only"][task_id] = max(options, key=lambda x: x["utility_hat"])["model"]
        highest_risk = max(options, key=lambda x: x["risk_hat"])["model"]
        decisions["rank_safety"][task_id] = max((x for x in options if x["model"] != highest_risk), key=lambda x: x["utility_hat"])["model"]
        risk_level = options[0]["risk_level"]
        lam = dynamic_lambda.get(risk_level, dynamic_lambda["unknown"])
        decisions["frar_dynamic"][task_id] = max(options, key=lambda x: x["utility_hat"] - lam * x["risk_hat"])["model"]
        for fixed in LAMBDAS:
            decisions[f"frar_lambda_{fixed:g}"][task_id] = max(options, key=lambda x: x["utility_hat"] - fixed * x["risk_hat"])["model"]
    return decisions


def outcome_utility(outcome: dict[str, float]) -> float:
    return (0.45 * outcome["quality"] + 0.20 / (1 + outcome["cost"] * 1000) +
            0.15 / (1 + outcome["latency"] / 1000) + 0.20 * outcome["reliability"])


def metrics_for(selected: dict[str, str], outcomes: dict[tuple[str, str], dict[str, float]],
                tasks: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records = []
    for task_id, model in selected.items():
        out = outcomes[(task_id, model)]
        oracle = max(outcome_utility(outcomes[(task_id, m)]) for m in MODELS)
        utility = outcome_utility(out)
        records.append({"task_id": task_id, "model": model, "quality": out["quality"], "failure": out["failure"],
                        "cost_usd": out["cost"], "latency_ms": out["latency"], "utility": utility,
                        "regret": oracle - utility, "risk_level": str(tasks[task_id].get("risk_level", "unknown")).lower()})
    arr = lambda key: np.asarray([r[key] for r in records], dtype=float)
    high = [r for r in records if r["risk_level"] == "high"]
    summary = {
        "n_tasks": len(records), "mean_quality": float(arr("quality").mean()), "failure_rate": float(arr("failure").mean()),
        "high_risk_failure_rate": float(np.mean([r["failure"] for r in high])) if high else None,
        "mean_cost_usd": float(arr("cost_usd").mean()), "mean_latency_ms": float(arr("latency_ms").mean()),
        "mean_utility": float(arr("utility").mean()), "mean_regret": float(arr("regret").mean()),
    }
    return summary, records


def bootstrap_delta(a: list[dict[str, Any]], b: list[dict[str, Any]], key: str, seed: int = 20260825) -> dict[str, float]:
    av = np.asarray([x[key] for x in a]); bv = np.asarray([x[key] for x in b]); delta = av - bv
    rng = np.random.default_rng(seed)
    draws = delta[rng.integers(0, len(delta), size=(10000, len(delta)))].mean(axis=1)
    return {"mean": float(delta.mean()), "ci95_low": float(np.quantile(draws, .025)), "ci95_high": float(np.quantile(draws, .975))}


def pareto_methods(metrics: dict[str, dict[str, Any]]) -> list[str]:
    # Maximise quality; minimise failure, cost, latency.
    result = []
    for name, x in metrics.items():
        dominated = any(other != name and y["mean_quality"] >= x["mean_quality"] and y["failure_rate"] <= x["failure_rate"]
                        and y["mean_cost_usd"] <= x["mean_cost_usd"] and y["mean_latency_ms"] <= x["mean_latency_ms"]
                        and (y["mean_quality"] > x["mean_quality"] or y["failure_rate"] < x["failure_rate"]
                             or y["mean_cost_usd"] < x["mean_cost_usd"] or y["mean_latency_ms"] < x["mean_latency_ms"])
                        for other, y in metrics.items())
        if not dominated:
            result.append(name)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/data/finance_router"))
    parser.add_argument("--output-dir", type=Path, default=Path("/root/frar_outputs"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--expanded-training", action="store_true", help="add leakage-audited confirmatory and legacy labels")
    args = parser.parse_args()
    train_dirs = [args.data_root / "finrome_300", args.data_root / "safety_expansion_v1"]
    if args.expanded_training:
        train_dirs += [args.data_root / "finrome_300_confirmatory_v3", args.data_root / "finrome_legacy_v2_confirmatory"]
    test_dir = args.data_root / "safety_expansion_v2_counterexample_enrichment"
    train_rows = scored_labeled_rows(train_dirs)
    fitted = fit_models(train_rows)
    test_tasks = {x["id"]: x for x in load_jsonl(test_dir / "tasks.jsonl")}
    candidates = decision_candidates(test_tasks, fitted)
    decisions = freeze_decisions(candidates, fitted, DEFAULT_DYNAMIC_LAMBDA, args.seed)
    # Evaluation boundary: no V2 response/judge/outcome was read before this line.
    test_outcomes = frozen_test_outcomes(test_dir, Path("/root/phase3_2a1y22_outputs/utility_matrix_v2_frozen.jsonl"))
    complete = {tid for tid in test_tasks if all((tid, m) in test_outcomes for m in MODELS)}
    test_tasks = {k: v for k, v in test_tasks.items() if k in complete}
    decisions = {name: {k: v for k, v in picks.items() if k in complete} for name, picks in decisions.items()}
    decisions["oracle"] = {tid: max(MODELS, key=lambda m: outcome_utility(test_outcomes[(tid, m)])) for tid in complete}
    summaries, records = {}, {}
    for name, selected in decisions.items():
        summaries[name], records[name] = metrics_for(selected, test_outcomes, test_tasks)
    comparisons = {name: {k: bootstrap_delta(records[name], records["utility_only"], k)
                          for k in ("quality", "failure", "utility")}
                   for name in ("rank_safety", "frar_dynamic")}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "protocol": {"train_sets": [x.name for x in train_dirs], "test_set": test_dir.name,
                     "repeat_aggregation": "mean_before_routing_evaluation", "failure_definition": "mean repeat failure rate",
                     "utility_weights": UTILITY_WEIGHTS, "dynamic_lambda": DEFAULT_DYNAMIC_LAMBDA,
                     "selection_outcome_separation": True, "random_seed": args.seed},
        "training": {"rows": len(train_rows), "best_single_selected_on_training": fitted.best_single,
                     "historical_telemetry": fitted.telemetry},
        "metrics": summaries, "paired_bootstrap_vs_utility_only": comparisons,
        "pareto_nondominated": pareto_methods({k: v for k, v in summaries.items() if k != "oracle"}),
    }
    (args.output_dir / "frar_results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (args.output_dir / "frar_task_decisions.jsonl").open("w", encoding="utf-8") as fh:
        for tid in sorted(complete):
            fh.write(json.dumps({"task_id": tid, "candidates": candidates[tid],
                                 "decisions": {k: v[tid] for k, v in decisions.items()}}, ensure_ascii=False) + "\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
