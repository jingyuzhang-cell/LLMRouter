#!/usr/bin/env python3
"""Recover the frozen legacy-v2 policy and apply it to the 800-task confirmation set."""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch

from openclaw_router.experiment_protocol import objective_score
import scripts.run_finrome_formal_oof as base
import scripts.run_finrome_m3_m5 as m3m5
import scripts.tune_finrome_oof as tuning


ROOT = Path(__file__).resolve().parents[1]
DEV_DATA = ROOT / "data/finance_router/finrome_300"
TEST_DATA = ROOT / "data/finance_router/finrome_legacy_v2_confirmatory"
DEV_RUN = ROOT / "run_logs/finrome_300"
OUT = ROOT / "run_logs/finrome_legacy_v2_confirmatory/recovered_policy"
MODELS = base.MODELS


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def prepare() -> tuple[Path, Path, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    source_path = OUT / "combined_source.json"
    split_path = OUT / "split.json"
    embedding_path = OUT / "combined_embeddings.pt"
    dev_source = json.loads((DEV_RUN / "source_compat.json").read_text())
    test_tasks = rows(TEST_DATA / "tasks.jsonl")
    matrix = {(x["task_id"], x["model"]): x for x in rows(TEST_DATA / "utility_matrix.jsonl")}
    response_latest = {}
    for item in rows(TEST_DATA / "responses.jsonl"):
        response_latest[(item["task_id"], item["model"], item["repeat"])] = item
    tasks = list(dev_source["sampled_task_set"])
    raw = list(dev_source["raw_model_runs"])
    for task in test_tasks:
        canonical = dict(task)
        canonical["query"] = canonical.get("question", "")
        canonical["risk"] = .86 if canonical.get("risk_level") == "high" else .62
        tasks.append(canonical)
        for model in MODELS:
            aggregate = matrix[(task["id"], model)]
            for repeat in range(3):
                response = response_latest[(task["id"], model, repeat)]
                raw.append(
                    {
                        "task_id": task["id"],
                        "model": model,
                        "repeat": repeat,
                        "ok": bool(response.get("success")),
                        "quality": aggregate["quality"],
                        "raw_cost_usd": aggregate["cost_usd"],
                        "latency_ms": aggregate["latency_ms"],
                        "response": response.get("answer", ""),
                    }
                )
    source_path.write_text(json.dumps({"sampled_task_set": tasks, "raw_model_runs": raw}, ensure_ascii=False) + "\n")
    dev_split = json.loads((DEV_RUN / "split.json").read_text())
    split_path.write_text(
        json.dumps(
            {"train": dev_split["train"], "validation": dev_split["validation"], "test": [x["id"] for x in test_tasks]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    if not embedding_path.exists():
        old = torch.load(DEV_RUN / "longformer_embeddings.pt", map_location="cpu", weights_only=False)
        embedding_map = {task_id: old["embeddings"][i] for i, task_id in enumerate(old["task_ids"])}
        from llmrouter.utils.embeddings import get_longformer_embedding

        for start in range(0, len(test_tasks), 4):
            batch = test_tasks[start : start + 4]
            values = get_longformer_embedding([x.get("question", "") for x in batch]).cpu()
            for index, task in enumerate(batch):
                embedding_map[task["id"]] = values[index]
        ids = [x["id"] for x in tasks]
        torch.save(
            {"task_ids": ids, "embeddings": torch.stack([embedding_map[x] for x in ids]), "model": "allenai/longformer-base-4096"},
            embedding_path,
        )
    return source_path, split_path, embedding_path


def apply_legacy(m2_rows: list[dict], source: dict, split: dict, matrix: dict) -> tuple[list[dict], list[dict]]:
    tasks = {x["id"]: x for x in source["sampled_task_set"]}
    by = defaultdict(list)
    for item in source["raw_model_runs"]:
        by[(item["task_id"], item["model"])].append(item)
    risks = {task_id: base.risk(task) for task_id, task in tasks.items()}

    def utility(task_id: str, model: int) -> float:
        return float(matrix[(task_id, MODELS[model])]["utility"])

    def objective_failure(task_id: str, model: int) -> float:
        values = [objective_score(tasks[task_id], str(x.get("response") or "")) for x in by[(task_id, MODELS[model])]]
        values = [x for x in values if x is not None]
        return 1 - float(np.mean(values)) if values else 1.0

    calibration = split["validation"]
    global_stats = {
        model: {
            "failure": float(np.mean([objective_failure(task_id, model) for task_id in calibration])),
            "utility": float(np.mean([utility(task_id, model) for task_id in calibration])),
        }
        for model in range(4)
    }
    global_anchor = min(range(4), key=lambda model: (global_stats[model]["failure"], -global_stats[model]["utility"], model))
    groups = defaultdict(list)
    for task_id in calibration:
        groups[(risks[task_id], tasks[task_id].get("task_type"))].append(task_id)
    anchor_stats = {}
    anchor_map = {}
    for key, task_ids in groups.items():
        stats = {
            model: {
                "failure": float(np.mean([objective_failure(task_id, model) for task_id in task_ids])),
                "utility": float(np.mean([utility(task_id, model) for task_id in task_ids])),
            }
            for model in range(4)
        }
        anchor_stats[key] = stats
        anchor_map[key] = min(range(4), key=lambda model: (stats[model]["failure"], -stats[model]["utility"], model))

    selected = []
    trace = []
    for row in m2_rows:
        task_id = row["task_id"]
        initial = int(row["selected"])
        key = (risks[task_id], tasks[task_id].get("task_type"))
        stats = anchor_stats.get(key, global_stats)
        anchor = anchor_map.get(key, global_anchor)
        response = str(by[(task_id, MODELS[initial])][0].get("response") or "")
        objective = objective_score(tasks[task_id], response)
        rule = bool(response.strip()) and (
            bool(re.search(r"最终答案|final answer|答案|结论", response, re.I))
            or tasks[task_id].get("task_type") not in {"financial_numerical_reasoning", "financial_table_text_reasoning"}
        )
        passed = rule and objective is not None and objective >= (.999 if risks[task_id] == "high" else .8)
        risk_gain = stats[initial]["failure"] - stats[anchor]["failure"]
        utility_loss = stats[initial]["utility"] - stats[anchor]["utility"]
        budget = .02 if risks[task_id] == "high" else .04
        escalated = not passed and initial != anchor and risk_gain > 0 and utility_loss <= budget
        final = anchor if escalated else initial
        selected.append({**row, "selected": final})
        trace.append(
            {
                "task_id": task_id,
                "initial": MODELS[initial],
                "rule_pass": rule,
                "objective": objective,
                "escalated": escalated,
                "anchor": MODELS[anchor],
                "risk_gain": risk_gain,
                "utility_loss": utility_loss,
                "utility_budget": budget,
                "final": MODELS[final],
                "review_status": "PENDING" if not passed else "NOT_REQUIRED",
            }
        )
    return selected, trace


def main() -> None:
    source_path, split_path, embedding_path = prepare()
    base.SOURCE = source_path
    base.SPLIT = split_path
    base.EMB = embedding_path
    tuning.OUT = DEV_RUN / "oof_tuning"
    m3m5.OUT = OUT / "provisional_existing_runner"
    m3m5.OUT.mkdir(parents=True, exist_ok=True)
    os.environ["FINROME_M5_ANCHOR_POLICY"] = "legacy_v1"
    m3m5.main()
    provisional = json.loads((m3m5.OUT / "report.json").read_text())
    policy = json.loads((TEST_DATA / "FROZEN_POLICY.json").read_text())
    if policy["upstream_M3_gate"]["passed"] is not False:
        raise SystemExit("Frozen upstream M3 gate is not false")
    source = json.loads(source_path.read_text())
    split = json.loads(split_path.read_text())
    test_matrix = {(x["task_id"], x["model"]): x for x in rows(TEST_DATA / "utility_matrix.jsonl")}
    dev_matrix = {(x["task_id"], x["model"]): x for x in rows(DEV_DATA / "utility_matrix.jsonl")}
    matrix = dev_matrix | test_matrix
    m3_rows = provisional["M2"]["rows"]
    m5_rows, trace = apply_legacy(m3_rows, source, split, matrix)

    historical = json.loads((DEV_RUN / "m5_legacy_repaired_dev_valid/report.json").read_text())
    historical_m5, _ = apply_legacy(historical["M2"]["rows"], source, split, matrix)
    expected = [(x["task_id"], x["selected"]) for x in historical["M5"]["rows"]]
    observed = [(x["task_id"], x["selected"]) for x in historical_m5]
    if observed != expected:
        raise SystemExit(f"Development reconstruction failed: {sum(a != b for a, b in zip(observed, expected))} differences")

    assignments = []
    for m3, m5 in zip(m3_rows, m5_rows):
        if m3["task_id"] != m5["task_id"]:
            raise SystemExit("Task order mismatch")
        assignments.append({"task_id": m3["task_id"], "M3_v2": MODELS[int(m3["selected"])], "M5_legacy_v2": MODELS[int(m5["selected"])]})
    (OUT / "assignments.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in assignments))
    (OUT / "verifier_trace.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in trace))
    report = {
        "status": "RECOVERED_FROZEN_POLICY_APPLIED",
        "tasks": len(assignments),
        "development_reconstruction": "45/45 M5 selections exact",
        "frozen_gate_enforced": "M3=M4=M2 because upstream_M3_gate.passed=false",
        "selection_counts": {
            "M3_v2": dict(Counter(x["M3_v2"] for x in assignments)),
            "M5_legacy_v2": dict(Counter(x["M5_legacy_v2"] for x in assignments)),
        },
    }
    (OUT / "RECOVERY.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
