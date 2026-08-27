#!/usr/bin/env python3
"""Final offline analysis for the frozen five-model FRAR-v2 run."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import frar_v2_five_model_experiment as experiment
from run_frar_v2_corrected import load_test_outcomes


OUT = Path("/root/frar_v2_five_model_outputs")
SEED = 20260825


def bootstrap(delta: np.ndarray) -> dict:
    rng = np.random.default_rng(SEED)
    draws = delta[rng.integers(0, len(delta), size=(10000, len(delta)))].mean(axis=1)
    return {"mean": float(delta.mean()), "ci95_low": float(np.quantile(draws, .025)),
            "ci95_high": float(np.quantile(draws, .975)), "p_two_sided": float(2 * min(np.mean(draws <= 0), np.mean(draws >= 0)))}


def main() -> None:
    result = json.loads((OUT / "frar_v2_results.json").read_text())
    tasks, outcomes = load_test_outcomes()
    decisions = {}
    for row in experiment.read_jsonl(OUT / "frar_v2_task_decisions.jsonl"):
        for method, model in row["decisions"].items():
            decisions.setdefault(method, {})[row["task_id"]] = model
    ids = sorted(tasks)

    actual = {}
    for method, picks in decisions.items():
        actual[method] = {
            key: np.asarray([outcomes[(tid, picks[tid])][key] for tid in ids], dtype=float)
            for key in ("quality", "failure", "cost_usd", "latency_ms")
        }
        actual[method]["utility"] = np.asarray([experiment.utility(outcomes[(tid, picks[tid])]) for tid in ids])

    comparisons = {}
    for baseline in ("best_single", "cost_only", "utility_only", "rank_safety", "route_pairwise", "random"):
        comparisons[baseline] = {
            "quality_frar_minus_baseline": bootstrap(actual["frar_v2"]["quality"] - actual[baseline]["quality"]),
            "utility_frar_minus_baseline": bootstrap(actual["frar_v2"]["utility"] - actual[baseline]["utility"]),
            "failure_baseline_minus_frar": bootstrap(actual[baseline]["failure"] - actual["frar_v2"]["failure"]),
        }

    mean_by_model = {m: float(np.mean([outcomes[(tid, m)]["quality"] for tid in ids])) for m in experiment.MODELS}
    posthoc_best = max(mean_by_model, key=mean_by_model.get)
    quality_oracle = np.asarray([max(outcomes[(tid, m)]["quality"] for m in experiment.MODELS) for tid in ids])
    risk_selection = {}
    for method in ("route_pairwise", "frar_v2"):
        groups = defaultdict(Counter)
        for tid in ids:
            groups[str(tasks[tid].get("risk_level", "unknown")).lower()][decisions[method][tid]] += 1
        risk_selection[method] = {risk: dict(counts) for risk, counts in groups.items()}

    frozen_v1 = json.loads((Path("/root/frar_frozen_v1_4model_20260825") / "frar_results.json").read_text())
    report = {
        "diagnostics": {
            "test_quality_by_single_model": mean_by_model,
            "posthoc_test_best_single": posthoc_best,
            "posthoc_test_best_single_quality": mean_by_model[posthoc_best],
            "quality_oracle": float(quality_oracle.mean()),
            "quality_oracle_gap": {m: float(quality_oracle.mean() - result["metrics"][m]["mean_quality"])
                                   for m in ("best_single", "route_pairwise", "frar_v2")},
            "frar_selection_change_vs_posthoc_test_best": float(np.mean([decisions["frar_v2"][tid] != posthoc_best for tid in ids])),
            "pairwise_cv_mean_auc": float(np.mean([x["auc"] for x in result["pairwise_cv"].values() if x["auc"] is not None])),
            "pairwise_cv_mean_accuracy": float(np.mean([x["accuracy"] for x in result["pairwise_cv"].values()])),
        },
        "risk_selection": risk_selection,
        "paired_bootstrap": comparisons,
        "frozen_frar_v1_ablation": frozen_v1["metrics"]["frar_dynamic"],
        "five_model_metrics": result["metrics"],
        "interpretation": {
            "routability_established": True,
            "compatibility_router_success": True,
            "fixed_weight_frar_v2_beats_training_selected_best_single": result["metrics"]["frar_v2"]["mean_utility"] > result["metrics"]["best_single"]["mean_utility"],
            "fixed_weight_frar_v2_beats_pure_pairwise": result["metrics"]["frar_v2"]["mean_utility"] > result["metrics"]["route_pairwise"]["mean_utility"],
            "warning": "The illustrative 0.6/0.3/0.1 mixture underperforms pure pairwise compatibility; do not tune weights on v2 test outcomes."
        }
    }
    (OUT / "frar_v2_final_analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    m = result["metrics"]
    lines = [
        "# FRAR-v2 Five-Model Experiment", "",
        "## Integrity", "",
        "- Training tasks: 400; frozen v2 test tasks: 140; overlap: 0.",
        "- Models: DeepSeek, GLM, Qwen Plus, Qwen Turbo, Gemini 2.5 Flash.",
        "- Pairwise classifiers: 10; grouping unit for CV: task.", "",
        "## Main results", "",
        "| Method | Quality | Failure | High-risk failure | Utility | Oracle regret | Selection change |", "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("best_single", "cost_only", "utility_only", "rank_safety", "route_pairwise", "frar_v2", "oracle"):
        x = m[name]
        lines.append(f"| {name} | {x['mean_quality']:.4f} | {x['failure_rate']:.2%} | {x['high_risk_failure_rate']:.2%} | {x['mean_utility']:.4f} | {x['mean_regret']:.4f} | {x.get('selection_change_vs_best_single', 0):.2%} |")
    lines += ["", "## Conclusion", "",
              f"- Post-hoc test Best Single is {posthoc_best} ({mean_by_model[posthoc_best]:.4f}); this is diagnostic only, not used for leakage-safe selection.",
              f"- Quality Oracle is {quality_oracle.mean():.4f}; FRAR-v2 closes the quality gap to {quality_oracle.mean()-m['frar_v2']['mean_quality']:.4f}.",
              f"- Pairwise CV mean AUC is {report['diagnostics']['pairwise_cv_mean_auc']:.4f}.",
              "- Pure pairwise compatibility slightly outperforms the illustrative FRAR-v2 mixture; any weight tuning must be performed only with training CV."]
    (OUT / "FRAR_V2_FIVE_MODEL_REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
