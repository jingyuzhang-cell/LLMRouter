#!/usr/bin/env python3
"""Build and mechanically audit the frozen five-model training environment."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


ROOT = Path("/root")
PROJECT = ROOT / "autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main"
DATA_ROOT = PROJECT / "data/finance_router"
PILOT = ROOT / "gemini_frar_pilot/five_model_v1"
OUT = ROOT / "five_model_routability_audit"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
OLD_MODELS = MODELS[:-1]
TIE_MARGIN = 0.01

sys.path.insert(0, str(PROJECT))
from openclaw_router.experiment_protocol import objective_score


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def utility(quality: float, cost: float, latency: float, reliability: float) -> float:
    return (.45 * quality + .20 * (1 - min(cost / .02, 1)) +
            .15 * (1 - min(latency / 10000, 1)) + .20 * reliability)


def build_repeat_rows(tasks: list[dict]) -> list[dict]:
    by_source: dict[str, dict[tuple[str, str, int], dict]] = {}
    for source in sorted({task["_source_dataset_dir"] for task in tasks}):
        latest = {}
        for row in read_jsonl(DATA_ROOT / source / "scored_responses.jsonl"):
            latest[(row["task_id"], row["model"], int(row.get("repeat", 0)))] = row
        by_source[source] = latest

    gemini_responses = {(row["task_id"], int(row["repeat"])): row for row in read_jsonl(PILOT / "gemini_training_pilot_responses_frozen.jsonl")}
    judge_latest = {}
    for row in read_jsonl(PILOT / "gemini_training_pilot_judges_frozen.jsonl"):
        judge_latest[(row["task_id"], int(row["repeat"]), row["judge_model"])] = row

    rows = []
    for task in tasks:
        task_id = task["id"]
        for model in OLD_MODELS:
            for repeat in range(3):
                old = by_source[task["_source_dataset_dir"]][(task_id, model, repeat)]
                rows.append({"task_id": task_id, "model": model, "repeat": repeat,
                    "dataset": task.get("dataset"), "task_type": task.get("task_type"), "risk_level": task.get("risk_level"),
                    "quality": float(old["quality"]), "cost_usd": float(old.get("cost_usd") or 0),
                    "latency_ms": float(old.get("latency_ms") or 0), "reliability": float(old.get("reliability", 1)),
                    "scoring_rule": "frozen_project_scored_response"})
        for repeat in range(3):
            response = gemini_responses[(task_id, repeat)]
            objective = float(objective_score(task, str(response.get("answer") or "")) or 0)
            judge_scores = [float(judge_latest[(task_id, repeat, judge)]["score"]) for judge in ("deepseek-chat", "qwen-plus")]
            quality = objective
            rule = "objective_score"
            if task.get("task_type") == "financial_audit_compliance_qa":
                quality = .55 * objective + .45 * float(np.mean(judge_scores))
                rule = "0.55*objective+0.45*dual_judge_mean"
            rows.append({"task_id": task_id, "model": "gemini-2.5-flash", "repeat": repeat,
                "dataset": task.get("dataset"), "task_type": task.get("task_type"), "risk_level": task.get("risk_level"),
                "quality": quality, "objective_score": objective, "judge_scores": judge_scores,
                "cost_usd": float(response.get("cost_usd") or 0), "latency_ms": float(response.get("latency_ms") or 0),
                "reliability": float(response.get("error") is None), "scoring_rule": rule})
    return rows


def aggregate(repeats: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in repeats:
        grouped[(row["task_id"], row["model"])].append(row)
    matrix = []
    for (task_id, model), rows in sorted(grouped.items()):
        assert sorted(x["repeat"] for x in rows) == [0, 1, 2]
        quality = float(np.mean([x["quality"] for x in rows])); cost = float(np.mean([x["cost_usd"] for x in rows]))
        latency = float(np.mean([x["latency_ms"] for x in rows])); reliability = float(np.mean([x["reliability"] for x in rows]))
        matrix.append({"task_id": task_id, "model": model, "dataset": rows[0]["dataset"], "task_type": rows[0]["task_type"],
            "risk_level": rows[0]["risk_level"], "quality": quality, "failure": bool(reliability < 1 or quality < .6),
            "cost_usd": cost, "latency_ms": latency, "reliability": reliability,
            "utility": utility(quality, cost, latency, reliability), "repeats": 3, "repeat_aggregation": "mean"})
    return matrix


def entropy(counts: Counter, total: int) -> tuple[float, float]:
    probs = [count / total for count in counts.values() if count]
    value = -sum(p * math.log(p) for p in probs)
    return value, value / math.log(len(MODELS))


def group_audit(task_ids: list[str], outcomes: dict[tuple[str, str], dict]) -> dict:
    mean_utility = {model: float(np.mean([outcomes[(tid, model)]["utility"] for tid in task_ids])) for model in MODELS}
    mean_quality = {model: float(np.mean([outcomes[(tid, model)]["quality"] for tid in task_ids])) for model in MODELS}
    best_u = max(mean_utility, key=mean_utility.get); best_q = max(mean_quality, key=mean_quality.get)
    oracle_u = float(np.mean([max(outcomes[(tid, model)]["utility"] for model in MODELS) for tid in task_ids]))
    oracle_q = float(np.mean([max(outcomes[(tid, model)]["quality"] for model in MODELS) for tid in task_ids]))
    return {"n": len(task_ids), "best_single_utility_model": best_u, "best_single_utility": mean_utility[best_u],
            "utility_oracle": oracle_u, "utility_oracle_gap": oracle_u - mean_utility[best_u],
            "best_single_quality_model": best_q, "best_single_quality": mean_quality[best_q],
            "quality_oracle": oracle_q, "quality_oracle_gap": oracle_q - mean_quality[best_q]}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tasks_list = read_jsonl(PILOT / "gemini_training_pilot_tasks.jsonl"); tasks = {x["id"]: x for x in tasks_list}
    repeats = build_repeat_rows(tasks_list); matrix = aggregate(repeats)
    assert len(repeats) == 400 * 5 * 3 and len({(x["task_id"], x["model"], x["repeat"]) for x in repeats}) == len(repeats)
    assert len(matrix) == 400 * 5 and all(x["repeats"] == 3 for x in matrix)
    v2_ids = {x["id"] for x in read_jsonl(DATA_ROOT / "safety_expansion_v2_counterexample_enrichment/tasks.jsonl")}
    assert not (set(tasks) & v2_ids)
    repeat_path = OUT / "five_model_training_repeats_frozen.jsonl"; matrix_path = OUT / "five_model_task_model_matrix_frozen.jsonl"
    write_jsonl(repeat_path, repeats); write_jsonl(matrix_path, matrix)
    outcomes = {(x["task_id"], x["model"]): x for x in matrix}; task_ids = sorted(tasks)
    overall = group_audit(task_ids, outcomes)

    utility_winners = Counter(); quality_winners = Counter(); unique_utility = Counter(); unique_quality = Counter(); unique_safe = Counter()
    for tid in task_ids:
        ranked_u = sorted(MODELS, key=lambda m: outcomes[(tid, m)]["utility"], reverse=True)
        ranked_q = sorted(MODELS, key=lambda m: outcomes[(tid, m)]["quality"], reverse=True)
        utility_winners[ranked_u[0]] += 1; quality_winners[ranked_q[0]] += 1
        if outcomes[(tid, ranked_u[0])]["utility"] - outcomes[(tid, ranked_u[1])]["utility"] > TIE_MARGIN: unique_utility[ranked_u[0]] += 1
        if outcomes[(tid, ranked_q[0])]["quality"] - outcomes[(tid, ranked_q[1])]["quality"] > TIE_MARGIN: unique_quality[ranked_q[0]] += 1
        safe = [m for m in MODELS if not outcomes[(tid, m)]["failure"]]
        if len(safe) == 1: unique_safe[safe[0]] += 1
    h, normalized_h = entropy(utility_winners, len(task_ids))

    gd = Counter()
    for tid in task_ids:
        gemini = outcomes[(tid, "gemini-2.5-flash")]; deepseek = outcomes[(tid, "deepseek-chat")]
        delta = gemini["utility"] - deepseek["utility"]
        gd["gemini_wins" if delta > TIE_MARGIN else "deepseek_wins" if delta < -TIE_MARGIN else "tie"] += 1
        if gemini["failure"] and deepseek["failure"]: gd["both_fail"] += 1

    groups: dict[str, list[str]] = defaultdict(list)
    for tid, task in tasks.items():
        groups[f"risk:{str(task.get('risk_level','unknown')).lower()}"].append(tid)
        groups[f"dataset:{task.get('dataset','unknown')}"] .append(tid)
        groups[f"task_type:{task.get('task_type','unknown')}"] .append(tid)
        if task.get("requires_table_reasoning"): groups["capability:table_reasoning"].append(tid)
        if task.get("requires_kg_reasoning"): groups["capability:kg_reasoning"].append(tid)
        if "multihop" in str(task.get("task_type", "")).lower(): groups["capability:multi_hop"].append(tid)
        if len(str(task.get("context", ""))) >= 8000: groups["capability:long_context_ge_8000_chars"].append(tid)
    conditional = {name: group_audit(ids, outcomes) for name, ids in sorted(groups.items()) if ids}

    gates = {"complete_400x5x3": True, "train_test_overlap_zero": True,
        "utility_oracle_gap_ge_0.02": overall["utility_oracle_gap"] >= .02,
        "quality_oracle_gap_ge_0.03": overall["quality_oracle_gap"] >= .03,
        "normalized_winner_entropy_ge_0.35": normalized_h >= .35,
        "top_utility_winner_share_le_0.75": max(utility_winners.values()) / len(task_ids) <= .75,
        "gemini_win_rate_ge_0.10": gd["gemini_wins"] / len(task_ids) >= .10,
        "deepseek_win_rate_ge_0.10": gd["deepseek_wins"] / len(task_ids) >= .10}
    report = {"protocol":{"models":MODELS,"tasks":len(task_ids),"repeats":3,"repeat_aggregation":"mean","tie_margin":TIE_MARGIN,
        "quality_rule":"objective; compliance=0.55*objective+0.45*dual_judge_mean","failure_rule":"reliability<1 or mean_quality<0.6",
        "utility_rule":"0.45Q+0.20(1-min(C/.02,1))+0.15(1-min(L/10000,1))+0.20R","router_training_performed":False},
        "integrity":{"repeat_rows":len(repeats),"matrix_rows":len(matrix),"duplicate_repeat_keys":0,"missing_repeat_keys":0,"v2_task_overlap":0,
            "repeats_sha256":hashlib.sha256(repeat_path.read_bytes()).hexdigest(),"matrix_sha256":hashlib.sha256(matrix_path.read_bytes()).hexdigest()},
        "overall":overall,"utility_winner_distribution":dict(utility_winners),"quality_winner_distribution":dict(quality_winners),
        "unique_utility_winner":dict(unique_utility),"unique_quality_winner":dict(unique_quality),"unique_safe_model":dict(unique_safe),
        "gemini_vs_deepseek":{**dict(gd),"n":len(task_ids),"gemini_win_rate":gd["gemini_wins"]/len(task_ids),"deepseek_win_rate":gd["deepseek_wins"]/len(task_ids)},
        "winner_entropy":{"nats":h,"normalized":normalized_h,"top_winner_share":max(utility_winners.values())/len(task_ids)},
        "conditional_oracle_gaps":conditional,"routability_gate":{**gates,"pass":all(gates.values())}}
    (OUT / "five_model_routability_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
