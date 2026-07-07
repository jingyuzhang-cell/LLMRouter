"""Build router training labels from normalized finance QA records.

Input records follow data/finance_router_training_schema.md.
When model_results are empty, the script can create deterministic simulation
results so the pipeline can be tested before expensive real API calls.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "finance_router" / "standardized" / "finance_router_tasks.jsonl"
DEFAULT_JSONL = ROOT / "data" / "finance_router" / "routing" / "finance_router_train.jsonl"
DEFAULT_CSV = ROOT / "data" / "finance_router" / "routing" / "finance_router_train.csv"
DEFAULT_MODELS = ["deepseek-chat", "qwen-plus", "gemini-2.5-flash", "glm-5.2"]


MODEL_PROFILES = {
    "deepseek-chat": {"quality": 0.88, "cost": 0.55, "latency": 0.58, "reliability": 0.88},
    "qwen-plus": {"quality": 0.84, "cost": 0.45, "latency": 0.38, "reliability": 0.86},
    "gemini-2.5-flash": {"quality": 0.78, "cost": 0.28, "latency": 0.18, "reliability": 0.72},
    "glm-5.2": {"quality": 0.91, "cost": 0.82, "latency": 0.90, "reliability": 0.86},
}


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def normalize_answer(text: Any) -> str:
    value = str(text or "").lower().strip()
    value = value.replace(",", "")
    value = re.sub(r"\s+", " ", value)
    return value


def extract_number(text: Any) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(text or "").replace(",", ""))
    return float(match.group(0)) if match else None


def quality_from_answer(prediction: str, gold: str, task: Dict[str, Any]) -> float:
    pred = normalize_answer(prediction)
    target = normalize_answer(gold)
    if not target:
        return 0.0
    if pred == target:
        return 1.0
    if target in pred:
        return 0.88
    gold_num = extract_number(target)
    pred_num = extract_number(pred)
    if gold_num is not None and pred_num is not None:
        denom = max(1.0, abs(gold_num))
        error = abs(pred_num - gold_num) / denom
        if error <= 0.01:
            return 0.95
        if error <= 0.05:
            return 0.80
        if error <= 0.10:
            return 0.65
    overlap = len(set(pred.split()) & set(target.split())) / max(1, len(set(target.split())))
    return round(min(0.72, overlap), 3)


def nonlinear_params(task: Dict[str, Any]) -> Dict[str, float]:
    risk = task.get("risk_level") or "medium"
    if risk == "high":
        return {"alpha": 2.15, "beta": 1.90, "gamma": 0.42, "delta": 0.34}
    if risk == "medium":
        return {"alpha": 1.65, "beta": 1.40, "gamma": 0.62, "delta": 0.52}
    return {"alpha": 1.20, "beta": 1.05, "gamma": 0.95, "delta": 0.88}


def nonlinear_utility(metrics: Dict[str, float], task: Dict[str, Any]) -> float:
    params = nonlinear_params(task)
    quality = max(0.001, float(metrics["quality"]))
    reliability = max(0.001, float(metrics["reliability"]))
    cost = max(0.0, float(metrics["cost"]))
    latency = max(0.0, float(metrics["latency"]))
    score = (
        (quality ** params["alpha"])
        * (reliability ** params["beta"])
        * math.exp(-params["gamma"] * cost)
        * math.exp(-params["delta"] * latency)
    )
    return round(max(0.0, min(1.0, score)), 4)


def simulated_metrics(task: Dict[str, Any], model: str) -> Dict[str, float]:
    profile = dict(MODEL_PROFILES.get(model, {"quality": 0.70, "cost": 0.50, "latency": 0.50, "reliability": 0.70}))
    task_type = task.get("task_type", "")
    if "numerical" in task_type and model in {"deepseek-chat", "glm-5.2"}:
        profile["quality"] += 0.07
    if "table" in task_type and model in {"qwen-plus", "deepseek-chat"}:
        profile["quality"] += 0.08
    if "audit" in task_type or task.get("risk_level") == "high":
        if model in {"deepseek-chat", "glm-5.2"}:
            profile["quality"] += 0.06
            profile["reliability"] += 0.03
    if task.get("requires_kg_reasoning") and model in {"deepseek-chat", "qwen-plus"}:
        profile["quality"] += 0.08
    return {key: round(max(0.0, min(1.0, value)), 3) for key, value in profile.items()}


def metrics_from_model_result(task: Dict[str, Any], model: str, result: Dict[str, Any], simulate_missing: bool) -> Dict[str, float]:
    if not result and simulate_missing:
        return simulated_metrics(task, model)
    if not result:
        return {"quality": 0.0, "cost": 1.0, "latency": 1.0, "reliability": 0.0}
    if result.get("quality") is not None:
        quality = float(result["quality"])
    else:
        quality = quality_from_answer(str(result.get("answer", "")), str(task.get("gold_answer", "")), task)
    success = result.get("success")
    reliability = 1.0 if success is True else 0.0 if success is False else MODEL_PROFILES.get(model, {}).get("reliability", 0.70)
    latency_ms = float(result.get("latency_ms") or 0.0)
    latency = min(1.0, latency_ms / 60000.0) if latency_ms else MODEL_PROFILES.get(model, {}).get("latency", 0.50)
    cost_usd = float(result.get("cost_usd") or result.get("raw_cost_usd") or 0.0)
    cost = min(1.0, cost_usd / 0.01) if cost_usd else MODEL_PROFILES.get(model, {}).get("cost", 0.50)
    return {
        "quality": round(max(0.0, min(1.0, quality)), 3),
        "cost": round(max(0.0, min(1.0, cost)), 3),
        "latency": round(max(0.0, min(1.0, latency)), 3),
        "reliability": round(max(0.0, min(1.0, reliability)), 3),
    }


def build_training_record(task: Dict[str, Any], models: List[str], simulate_missing: bool) -> Dict[str, Any]:
    model_results = task.get("model_results") or {}
    effective_models = models
    if model_results and not simulate_missing:
        effective_models = [model for model in models if model in model_results]
        if not effective_models:
            effective_models = list(model_results.keys())
    scored: List[Tuple[str, float, Dict[str, float]]] = []
    enriched_results: Dict[str, Any] = {}
    for model in effective_models:
        result = model_results.get(model) or {}
        metrics = metrics_from_model_result(task, model, result, simulate_missing)
        score = nonlinear_utility(metrics, task)
        scored.append((model, score, metrics))
        enriched_results[model] = {**result, "metrics": metrics, "router_score": score}
    scored.sort(key=lambda item: item[1], reverse=True)
    best_model, best_score, _ = scored[0]
    return {
        **task,
        "model_results": enriched_results,
        "best_model": best_model,
        "best_score": best_score,
        "candidate_scores": {model: score for model, score, _ in scored},
        "router_training": {
            "target": best_model,
            "method": "finance_risk_adaptive_nonlinear",
            "utility": "Q^alpha * R^beta * exp(-gamma*C) * exp(-delta*L)",
            "params": nonlinear_params(task),
        },
    }


def write_csv(path: Path, records: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "query", "best_model", "dataset", "task_type", "risk_level"])
        writer.writeheader()
        for item in records:
            writer.writerow({
                "id": item.get("id"),
                "query": item.get("question"),
                "best_model": item.get("best_model"),
                "dataset": item.get("dataset"),
                "task_type": item.get("task_type"),
                "risk_level": item.get("risk_level"),
            })


def main() -> None:
    parser = argparse.ArgumentParser(description="Build finance router training labels.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_JSONL)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--simulate-missing", action="store_true", help="Create deterministic model metrics when model_results are empty.")
    args = parser.parse_args()

    tasks = read_jsonl(args.input)
    records = [build_training_record(task, args.models, args.simulate_missing) for task in tasks]
    write_jsonl(args.output_jsonl, records)
    write_csv(args.output_csv, records)
    print(f"Wrote {len(records)} training records to {args.output_jsonl}")
    print(f"Wrote CSV summary to {args.output_csv}")


if __name__ == "__main__":
    main()
