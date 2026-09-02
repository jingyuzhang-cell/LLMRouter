#!/usr/bin/env python3
"""Frozen E2.1-A page-evidence scoring, bootstrap, and PASS/FAIL gate."""

import json
from collections import Counter
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "e2_1_protocol"
MODELS = ("qwen-plus", "glm-5.2", "deepseek")
ANCHOR = "qwen-plus"
ROTATIONS = (((0, 1), 2), ((0, 2), 1), ((1, 2), 0))
TIE = 0.01
BOOTSTRAPS = 10000
SEED = 20260901


def rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x]


def prf(predicted: set[str], gold: set[str]) -> tuple[float, float, float]:
    if not predicted:
        return 0.0, 0.0, 0.0
    overlap = len(predicted & gold)
    precision = overlap / len(predicted)
    recall = overlap / len(gold)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def tolerant_gold(gold: set[str]) -> set[str]:
    expanded = set()
    for evidence_id in gold:
        prefix, page = evidence_id.rsplit(":", 1)
        page = int(page)
        expanded.update(f"{prefix}:{x}" for x in (page - 1, page, page + 1) if x >= 1)
    return expanded


def percentile_ci(values: np.ndarray) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    n = len(values)
    means = np.empty(BOOTSTRAPS)
    for i in range(BOOTSTRAPS):
        means[i] = values[rng.integers(0, n, n)].mean()
    return tuple(float(x) for x in np.percentile(means, [2.5, 97.5]))


def main() -> None:
    tasks = rows(DATA / "E2_1_A_FRESH_360_TASKS.jsonl")
    gold_rows = rows(DATA / "E2_1_NATIVE_PAGE_GOLD_360.jsonl")
    response_rows = rows(DATA / "E2_1_A_RESPONSES.jsonl")
    task_ids = [x["task_id"] for x in tasks]
    expected = {(t, m, r) for t in task_ids for m in MODELS for r in range(3)}
    by_key = {(x["task_id"], x["model"], int(x["repeat"])): x for x in response_rows}
    missing = sorted(expected - set(by_key))
    extra = sorted(set(by_key) - expected)
    if missing or extra:
        raise SystemExit(f"Incomplete matrix: raw_rows={len(response_rows)} missing={len(missing)} extra={len(extra)}")
    gold = {x["task_id"]: set(x["dataset_page_evidence_ids"]) for x in gold_rows}
    quality, precision, recall, tolerant = {}, {}, {}, {}
    invalid = Counter()
    failures = Counter()
    for key, row in by_key.items():
        tid, model, _ = key
        pred = set(row["predicted_evidence_ids"]) if row.get("format_valid") else set()
        p, r, f = prf(pred, gold[tid])
        quality[key], precision[key], recall[key] = f, p, r
        tolerant[key] = prf(pred, tolerant_gold(gold[tid]))[2]
        invalid[model] += not bool(row.get("format_valid"))
        failures[model] += not bool(row.get("provider_success"))

    task_gap = {tid: [] for tid in task_ids}
    reversals = []
    rotation_details = []
    for train_repeats, heldout in ROTATIONS:
        global_train = {
            model: np.mean([quality[(tid, model, r)] for tid in task_ids for r in train_repeats])
            for model in MODELS
        }
        best_single = max(MODELS, key=lambda m: (global_train[m], -MODELS.index(m)))
        oracle_scores, single_scores = [], []
        for tid in task_ids:
            train_score = {
                model: np.mean([quality[(tid, model, r)] for r in train_repeats])
                for model in MODELS
            }
            ranked = sorted(MODELS, key=lambda m: (-train_score[m], MODELS.index(m)))
            picked = ranked[0]
            oracle = quality[(tid, picked, heldout)]
            single = quality[(tid, best_single, heldout)]
            task_gap[tid].append(oracle - single)
            oracle_scores.append(oracle)
            single_scores.append(single)
            heldout_ranked = sorted(MODELS, key=lambda m: (-quality[(tid, m, heldout)], MODELS.index(m)))
            if train_score[ranked[0]] - train_score[ranked[1]] >= TIE:
                reversals.append(heldout_ranked[0] != ranked[0])
        rotation_details.append({
            "train_repeats": list(train_repeats), "heldout_repeat": heldout,
            "best_single_model": best_single,
            "stable_oracle_mean": float(np.mean(oracle_scores)),
            "best_single_mean": float(np.mean(single_scores)),
            "gap": float(np.mean(oracle_scores) - np.mean(single_scores)),
        })
    gap_values = np.array([np.mean(task_gap[tid]) for tid in task_ids])
    gap = float(gap_values.mean())
    gap_ci = percentile_ci(gap_values)

    stable_specialist = []
    margins = []
    for tid in task_ids:
        means = {m: float(np.mean([quality[(tid, m, r)] for r in range(3)])) for m in MODELS}
        ranked = sorted(MODELS, key=lambda m: (-means[m], MODELS.index(m)))
        margins.append(means[ranked[0]] - means[ranked[1]])
        qualifies = any(
            all(quality[(tid, m, r)] - quality[(tid, ANCHOR, r)] >= TIE for r in range(3))
            for m in MODELS if m != ANCHOR
        )
        stable_specialist.append(qualifies)
    s_n1 = float(np.mean(stable_specialist))
    median_margin = float(np.median(margins))
    primary_pass = gap >= 0.03 and gap_ci[0] > 0
    secondary_pass = s_n1 >= 0.10 and median_margin > 0
    overall_pass = primary_pass and secondary_pass
    model_metrics = {}
    for model in MODELS:
        keys = [(tid, model, r) for tid in task_ids for r in range(3)]
        model_metrics[model] = {
            "strict_f1_mean": float(np.mean([quality[k] for k in keys])),
            "strict_precision_mean": float(np.mean([precision[k] for k in keys])),
            "strict_recall_mean": float(np.mean([recall[k] for k in keys])),
            "neighbor_tolerant_f1_mean": float(np.mean([tolerant[k] for k in keys])),
            "invalid_format_rate": invalid[model] / len(keys),
            "provider_failure_rate": failures[model] / len(keys),
        }
    result = {
        "status": "E2_1_A_PASS" if overall_pass else "E2_1_A_FAIL",
        "integrity": {"tasks": len(task_ids), "raw_response_rows": len(response_rows), "unique_latest_rows": len(by_key), "expected_rows": len(expected)},
        "primary": {"G_N1": gap, "bootstrap_95_ci": list(gap_ci), "threshold": 0.03, "pass": primary_pass},
        "secondary": {"S_N1": s_n1, "median_margin": median_margin, "pass": secondary_pass},
        "diagnostic": {"heldout_top1_top2_reversal_rate": float(np.mean(reversals)) if reversals else None},
        "model_metrics": model_metrics,
        "rotations": rotation_details,
        "overall_pass": overall_pass,
        "next_action": "RUN_E2_1_B" if overall_pass else "STOP_N1_HYPOTHESIS_NO_ROUTER_TRAINING",
        "definitions": {
            "S_N1": "Task rate where a non-anchor model beats qwen-plus by at least 0.01 in all three repeats.",
            "median_margin": "Median task-level gap between top two models after averaging each model over repeats."
        }
    }
    (DATA / "E2_1_A_RESULTS.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
