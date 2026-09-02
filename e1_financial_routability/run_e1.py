#!/usr/bin/env python3
"""E1: audit stable, learnable headroom in the frozen financial matrix."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np


ROOT = Path("/root")
OUT = ROOT / "e1_financial_routability"
PROTOCOL = OUT / "E1_PROTOCOL.json"
EXP = ROOT / "target_support_expansion_v1"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
SEED = 20260901


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(indices: np.ndarray, quality: np.ndarray) -> dict:
    values = quality[indices].mean(axis=2)
    means = values.mean(axis=0)
    best = int(np.argmax(means))
    oracle = values.max(axis=1)
    ordered = np.sort(values, axis=1)
    margins = ordered[:, -1] - ordered[:, -2]
    canonical = values.argmax(axis=1)
    unique = np.sum(values == oracle[:, None], axis=1) == 1
    exclusive_counts = Counter(canonical[unique])
    return {
        "tasks": int(len(indices)),
        "best_single_model": MODELS[best],
        "best_single_quality": float(means[best]),
        "observed_oracle_quality": float(oracle.mean()),
        "observed_oracle_gap": float(np.mean(oracle - values[:, best])),
        "strict_non_tie_rate": float(unique.mean()),
        "margin": {
            "mean": float(margins.mean()), "median": float(np.median(margins)),
            "q25": float(np.quantile(margins, .25)), "q75": float(np.quantile(margins, .75)),
            "fraction_above_0_10": float(np.mean(margins > .10)),
        },
        "canonical_winner_share": {MODELS[m]: float(np.mean(canonical == m)) for m in range(len(MODELS))},
        "exclusive_winner_share": {MODELS[m]: float(exclusive_counts[m] / len(indices)) for m in range(len(MODELS))},
    }


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text())
    old = json.loads((ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text())
    new = json.loads((EXP / "EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
    ids = sorted(set(old["train_task_ids"] + old["validation_task_ids"] + new["train_task_ids"]))
    if len(ids) != 419 or set(ids) & set(new["validation_task_ids"]):
        raise ValueError("Frozen development population mismatch or validation leakage")

    tasks = {r["id"]: r for r in read_jsonl(EXP / "combined_509_tasks_frozen.jsonl")}
    raw = read_jsonl(ROOT / "five_model_routability_audit/five_model_training_repeats_frozen.jsonl")
    raw += read_jsonl(EXP / "expanded_five_model_repeats_frozen.jsonl")
    lookup = {(r["task_id"], r["model"], int(r["repeat"])): r for r in raw if r["task_id"] in ids}
    expected = {(tid, model, rep) for tid in ids for model in MODELS for rep in range(3)}
    if set(lookup) != expected:
        raise ValueError(f"Frozen matrix mismatch: expected {len(expected)}, got {len(lookup)}")
    quality = np.asarray([[[float(lookup[(tid, model, rep)]["quality"]) for rep in range(3)]
                           for model in MODELS] for tid in ids])
    positions = np.arange(len(ids))
    actual = quality.mean(axis=2)

    # Cross-repeat selection estimates the replicable rather than noise-inflated oracle gap.
    held_gain = np.zeros((3, len(ids)))
    for held in range(3):
        selection_repeats = [r for r in range(3) if r != held]
        training_view = quality[:, :, selection_repeats].mean(axis=2)
        selected = training_view.argmax(axis=1)
        best = int(training_view.mean(axis=0).argmax())
        held_gain[held] = quality[positions, selected, held] - quality[:, best, held]
    task_stable_gain = held_gain.mean(axis=0)
    stable_gap = float(task_stable_gain.mean())

    # A stable unique winner must be uniquely best in every repeat and be the same model.
    repeat_max = quality.max(axis=1)
    repeat_unique = np.sum(quality == repeat_max[:, None, :], axis=1) == 1
    repeat_winner = quality.argmax(axis=1)
    stable_mask = np.all(repeat_unique, axis=1) & np.all(repeat_winner == repeat_winner[:, :1], axis=1)
    stable_winner = repeat_winner[:, 0]
    stable_shares = {MODELS[m]: float(np.mean(stable_mask & (stable_winner == m))) for m in range(len(MODELS))}

    rng = np.random.default_rng(SEED)
    boot_idx = rng.integers(0, len(ids), size=(10000, len(ids)))
    boot_stable_gap = task_stable_gain[boot_idx].mean(axis=1)
    observed_best = int(actual.mean(axis=0).argmax())
    observed_gain = actual.max(axis=1) - actual[:, observed_best]
    boot_observed_gap = observed_gain[boot_idx].mean(axis=1)

    correlation = np.corrcoef(actual, rowvar=False)
    correlation_rows = {
        MODELS[a]: {MODELS[b]: float(correlation[a, b]) for b in range(len(MODELS))}
        for a in range(len(MODELS))
    }
    subgroup = {}
    for field in ("dataset", "task_type"):
        values = sorted({str(tasks[tid].get(field) or "UNKNOWN") for tid in ids})
        subgroup[field] = {
            value: summary(np.asarray([i for i, tid in enumerate(ids) if str(tasks[tid].get(field) or "UNKNOWN") == value]), quality)
            for value in values
        }

    overall = summary(positions, quality)
    threshold = protocol["gate"]
    models_ge_10 = sum(share >= .10 for share in stable_shares.values())
    checks = {
        "observed_oracle_gap_ge_0.03": overall["observed_oracle_gap"] >= threshold["minimum_observed_oracle_gap"],
        "strict_non_tie_rate_ge_0.30": overall["strict_non_tie_rate"] >= threshold["minimum_strict_non_tie_rate"],
        "at_least_two_models_stable_unique_win_share_ge_0.10": models_ge_10 >= threshold["minimum_models_with_stable_unique_win_share_ge_0.10"],
        "cross_repeat_replicable_oracle_gap_ge_0.02": stable_gap >= threshold["minimum_cross_repeat_replicable_oracle_gap"],
        "bootstrap_probability_stable_gap_positive_ge_0.90": float(np.mean(boot_stable_gap > 0)) >= threshold["minimum_probability_stable_gap_positive"],
    }
    passed = all(checks.values())
    report = {
        "status": "E1_PASS" if passed else "E1_FAIL_STOP_BEFORE_E2",
        "integrity": {"tasks": len(ids), "models": len(MODELS), "repeats": 3, "complete_keys": len(lookup),
                      "external_api_calls": 0, "router_models_trained": 0, "c9_accessed": False,
                      "protocol_sha256": sha256(PROTOCOL)},
        "overall": overall,
        "cross_repeat_stability": {
            "stable_gap": stable_gap,
            "stable_gap_ci95": [float(np.quantile(boot_stable_gap, .025)), float(np.quantile(boot_stable_gap, .975))],
            "probability_stable_gap_positive": float(np.mean(boot_stable_gap > 0)),
            "observed_oracle_gap_ci95": [float(np.quantile(boot_observed_gap, .025)), float(np.quantile(boot_observed_gap, .975))],
            "stable_unique_winner_rate": float(stable_mask.mean()),
            "stable_unique_winner_share_by_model": stable_shares,
            "models_with_share_ge_0.10": models_ge_10,
        },
        "pearson_performance_correlation": correlation_rows,
        "subgroups": subgroup,
        "gate": {**checks, "pass": passed},
    }
    result_path = OUT / "E1_RESULTS.json"
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (OUT / "E1_SHA256SUMS").write_text(
        f"{sha256(PROTOCOL)}  {PROTOCOL.name}\n{sha256(result_path)}  {result_path.name}\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
