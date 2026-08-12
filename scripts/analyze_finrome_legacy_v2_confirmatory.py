#!/usr/bin/env python3
"""Preregistered statistics plus separately labelled exploratory diagnostics."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/finance_router/finrome_legacy_v2_confirmatory"
POLICY = ROOT / "run_logs/finrome_legacy_v2_confirmatory/recovered_policy"
OUT = ROOT / "run_logs/finrome_legacy_v2_confirmatory/analysis"
SEED = 20260822
NBOOT = 10_000
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo")


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_mcnemar_one_sided(improved: int, worsened: int) -> float:
    n = improved + worsened
    if n == 0:
        return 1.0
    return min(1.0, sum(math.comb(n, k) for k in range(improved, n + 1)) / (2**n))


def bootstrap(values: np.ndarray, rng: np.random.Generator) -> dict:
    n = len(values)
    means = np.empty(NBOOT)
    for start in range(0, NBOOT, 500):
        size = min(500, NBOOT - start)
        indices = rng.integers(0, n, size=(size, n))
        means[start : start + size] = values[indices].mean(axis=1)
    low, high = np.quantile(means, [.025, .975])
    return {"n": n, "mean_delta": float(values.mean()), "ci95": [float(low), float(high)]}


def sign_flip_p(values: np.ndarray, rng: np.random.Generator) -> float:
    observed = abs(float(values.mean()))
    hits = 0
    for _ in range(NBOOT):
        statistic = abs(float((values * rng.choice((-1.0, 1.0), size=len(values))).mean()))
        hits += statistic >= observed - 1e-15
    return (hits + 1) / (NBOOT + 1)


def holm(items: list[dict]) -> None:
    ordered = sorted(enumerate(items), key=lambda pair: pair[1]["raw_p"])
    running = 0.0
    total = len(items)
    for rank, (index, item) in enumerate(ordered):
        running = max(running, min(1.0, (total - rank) * item["raw_p"]))
        items[index]["holm_p"] = running


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = {x["id"]: x for x in rows(DATA / "tasks.jsonl")}
    matrix = {(x["task_id"], x["model"]): x for x in rows(DATA / "utility_matrix.jsonl")}
    assignments = rows(POLICY / "assignments.jsonl")
    if len(assignments) != 800 or set(tasks) != {x["task_id"] for x in assignments}:
        raise SystemExit("Recovered assignments do not cover the frozen 800-task set")
    trace = {x["task_id"]: x for x in rows(POLICY / "verifier_trace.jsonl")}
    paired = []
    for assignment in assignments:
        task_id = assignment["task_id"]
        candidates = [matrix[(task_id, model)] for model in MODELS]
        oracle = max(candidates, key=lambda x: (x["utility"], x["model"]))["model"]
        item = {"task_id": task_id, "dataset": tasks[task_id]["dataset"], "risk_level": tasks[task_id]["risk_level"]}
        for policy_name in ("M3_v2", "M5_legacy_v2"):
            model = assignment[policy_name]
            value = matrix[(task_id, model)]
            item[policy_name] = {
                "model": model,
                "failure": int(bool(value["failure"])),
                "quality": float(value["quality"]),
                "utility": float(value["utility"]),
                "cost_usd": float(value["cost_usd"]),
                "latency_ms": float(value["latency_ms"]),
                "reliability": float(value["reliability"]),
                "accuracy": int(model == oracle),
                "regret": float(max(x["utility"] for x in candidates) - value["utility"]),
            }
        paired.append(item)

    high = [x for x in paired if x["risk_level"] == "high"]
    improved = sum(x["M3_v2"]["failure"] == 1 and x["M5_legacy_v2"]["failure"] == 0 for x in high)
    worsened = sum(x["M3_v2"]["failure"] == 0 and x["M5_legacy_v2"]["failure"] == 1 for x in high)
    unchanged_fail = sum(x["M3_v2"]["failure"] == x["M5_legacy_v2"]["failure"] == 1 for x in high)
    unchanged_pass = sum(x["M3_v2"]["failure"] == x["M5_legacy_v2"]["failure"] == 0 for x in high)
    primary_p = exact_mcnemar_one_sided(improved, worsened)
    utility_delta = np.array([x["M5_legacy_v2"]["utility"] - x["M3_v2"]["utility"] for x in paired])
    utility_gate = bootstrap(utility_delta, np.random.default_rng(SEED))
    utility_gate["margin"] = -0.01
    utility_gate["passed"] = utility_gate["ci95"][0] >= -0.01

    endpoint_defs = (
        ("overall_failure_rate", "failure", -1.0),
        ("accuracy", "accuracy", 1.0),
        ("mean_regret", "regret", -1.0),
        ("cost_usd", "cost_usd", -1.0),
        ("latency_ms", "latency_ms", -1.0),
    )
    secondary = []
    for index, (name, field, favorable_sign) in enumerate(endpoint_defs):
        delta = np.array([x["M5_legacy_v2"][field] - x["M3_v2"][field] for x in paired])
        result = bootstrap(delta, np.random.default_rng(SEED + index + 1))
        result.update({"endpoint": name, "direction": "M5-M3", "favorable_sign": favorable_sign, "raw_p": sign_flip_p(delta, np.random.default_rng(SEED + 100 + index))})
        secondary.append(result)
    holm(secondary)

    def summary(values: list[dict]) -> dict:
        result = {"n": len(values)}
        for policy_name in ("M3_v2", "M5_legacy_v2"):
            result[policy_name] = {
                field: float(np.mean([x[policy_name][field] for x in values]))
                for field in ("failure", "accuracy", "utility", "regret", "cost_usd", "latency_ms", "reliability")
            }
        return result

    formal = {
        "report_type": "finrome_legacy_v2_preregistered_confirmatory_analysis",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "primary": {
            "endpoint": "paired high-risk failure rate",
            "population": len(high),
            "method": "exact paired McNemar, one-sided",
            "alternative": "M5_legacy_v2 lower failure",
            "alpha": .025,
            "transitions": {"M3_fail_M5_pass": improved, "M3_pass_M5_fail": worsened, "both_fail": unchanged_fail, "both_pass": unchanged_pass},
            "p_value": primary_p,
            "significant": primary_p < .025,
        },
        "key_secondary_noninferiority": utility_gate,
        "other_secondary": secondary,
        "descriptive": summary(paired),
        "coverage_and_escalation": {
            "M3_coverage": 1.0,
            "M5_coverage": 1.0,
            "M5_escalation_rate": float(np.mean([trace[x["task_id"]]["escalated"] for x in paired])),
            "human_review": "PENDING; excluded from confirmatory decisions",
        },
        "multiplicity_note": "Holm adjustment applied to five implementation-defined paired sign-flip tests; the preregistration specified Holm but did not name the secondary test statistic.",
        "integrity": {"matrix_sha256": sha(DATA / "utility_matrix.jsonl"), "assignments_sha256": sha(POLICY / "assignments.jsonl"), "recovery": json.loads((POLICY / "RECOVERY.json").read_text())},
    }
    (OUT / "formal_analysis.json").write_text(json.dumps(formal, ensure_ascii=False, indent=2) + "\n")

    strata = {}
    for field in ("dataset", "risk_level"):
        strata[field] = {value: summary([x for x in paired if x[field] == value]) for value in sorted({x[field] for x in paired})}
    judge_latest = {}
    for item in rows(DATA / "judges.jsonl"):
        judge_latest[(item["task_id"], item["candidate_model"], item["repeat"], item["judge_model"])] = item
    judge_bias = defaultdict(list)
    for item in judge_latest.values():
        if item.get("parsed") and item.get("score") is not None:
            judge_bias[item["judge_model"]].append(float(item["score"]))
    exploratory = {
        "report_type": "EXPLORATORY_NOT_PREREGISTERED",
        "stratified_descriptive": strata,
        "judge_model_score_means": {model: {"n": len(values), "mean": float(np.mean(values)), "std": float(np.std(values))} for model, values in sorted(judge_bias.items())},
        "pending_human_review_sensitivity": "DEFERRED until blinded human labels are complete",
    }
    (OUT / "exploratory_robustness.json").write_text(json.dumps(exploratory, ensure_ascii=False, indent=2) + "\n")
    seal = {"status": "ANALYSIS_COMPLETE", "formal_sha256": sha(OUT / "formal_analysis.json"), "exploratory_sha256": sha(OUT / "exploratory_robustness.json"), "human_review": "PENDING"}
    (OUT / "ANALYSIS_COMPLETE.json").write_text(json.dumps(seal, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"primary": formal["primary"], "utility_gate": utility_gate, "descriptive": formal["descriptive"], "seal": seal}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
