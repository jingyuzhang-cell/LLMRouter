#!/usr/bin/env python3
"""Train and validate utility-pairwise routing on the frozen target-support split."""

import hashlib
import json
from pathlib import Path

import numpy as np

import train_utility_pairwise_router as router


ROOT = Path("/root")
SPLIT = ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json"
MATRIX = ROOT / "five_model_routability_audit/five_model_task_model_matrix_frozen.jsonl"
TASKS = ROOT / "gemini_frar_pilot/five_model_v1/gemini_training_pilot_tasks.jsonl"
OUT = ROOT / "target_support_pairwise_outputs"


def bootstrap_recovery(ids, choices, outcomes, best_model, seed=20260827):
    selected = np.asarray([outcomes[(tid, choices[tid])]["utility"] for tid in ids])
    best = np.asarray([outcomes[(tid, best_model)]["utility"] for tid in ids])
    oracle = np.asarray([max(outcomes[(tid, model)]["utility"] for model in router.MODELS) for tid in ids])
    rng = np.random.default_rng(seed); samples = rng.integers(0, len(ids), size=(10000, len(ids)))
    denominator = oracle[samples].mean(axis=1) - best[samples].mean(axis=1)
    recovery = np.divide(selected[samples].mean(axis=1) - best[samples].mean(axis=1), denominator,
                         out=np.full_like(denominator, np.nan), where=denominator > 0)
    return {"mean": float(np.nanmean(recovery)), "ci95_low": float(np.nanquantile(recovery, .025)),
            "ci95_high": float(np.nanquantile(recovery, .975)), "positive_probability": float(np.nanmean(recovery > 0))}


split = json.loads(SPLIT.read_text()); all_tasks = {x["id"]: x for x in router.read_jsonl(TASKS)}
matrix = router.read_jsonl(MATRIX); all_outcomes = {(x["task_id"], x["model"]): x for x in matrix}
train_ids = split["train_task_ids"]; validation_ids = split["validation_task_ids"]
train_tasks = {task_id: all_tasks[task_id] for task_id in train_ids}; validation_tasks = {task_id: all_tasks[task_id] for task_id in validation_ids}
train_outcomes = {(task_id, model): all_outcomes[(task_id, model)] for task_id in train_ids for model in router.MODELS}
validation_outcomes = {(task_id, model): all_outcomes[(task_id, model)] for task_id in validation_ids for model in router.MODELS}

fit_ids, oof_choices, _, pair_stats, models = router.fit_and_oof(train_tasks, train_outcomes)
validation_choices, validation_scores = router.predict(sorted(validation_ids), validation_tasks, models)
train_mean = {model: float(np.mean([train_outcomes[(task_id, model)]["utility"] for task_id in train_ids])) for model in router.MODELS}
best_model = max(train_mean, key=train_mean.get)
oof = router.evaluate(fit_ids, oof_choices, train_outcomes, best_model)
validation = router.evaluate(sorted(validation_ids), validation_choices, validation_outcomes, best_model)
validation["gap_recovery_bootstrap"] = bootstrap_recovery(sorted(validation_ids), validation_choices, validation_outcomes, best_model)

weighted_accuracy = float(np.average([x["pairwise_accuracy"] for x in pair_stats.values()], weights=[x["non_tie_n"] for x in pair_stats.values()]))
weighted_prior = float(np.average([x["global_prior_accuracy"] for x in pair_stats.values()], weights=[x["non_tie_n"] for x in pair_stats.values()]))
gates = {
    "pairwise_accuracy_lift_ge_0.03": weighted_accuracy - weighted_prior >= .03,
    "oof_gap_recovery_ge_0.20": oof["gap_recovery"] >= .20,
    "validation_gap_recovery_ge_0.20": validation["gap_recovery"] >= .20,
    "validation_oracle_match_lift_ge_0.05": validation["oracle_match"] - validation["best_single_oracle_match"] >= .05,
    "validation_selection_entropy_ge_0.20": validation["selection_entropy_normalized"] >= .20,
    "validation_recovery_bootstrap_positive_probability_ge_0.95": validation["gap_recovery_bootstrap"]["positive_probability"] >= .95,
    "v2_not_used": True,
}
report = {
    "protocol": {"split_version": split["version"], "target": "utility pairwise", "tie_margin": router.TIE_MARGIN,
                 "train_tasks": len(train_ids), "validation_tasks": len(validation_ids), "v2_used": False,
                 "frar_ablation_authorized_only_if_gate_passes": True},
    "integrity": {"split_sha256": hashlib.sha256(SPLIT.read_bytes()).hexdigest(), "matrix_sha256": hashlib.sha256(MATRIX.read_bytes()).hexdigest(),
                  "train_validation_overlap": len(set(train_ids) & set(validation_ids)), "v2_overlap": split["v2_overlap"]},
    "training_best_single": {"model": best_model, "mean_utility": train_mean[best_model], "all_models": train_mean},
    "pairwise_cv": {"weighted_accuracy": weighted_accuracy, "weighted_global_prior_accuracy": weighted_prior,
                    "weighted_lift": weighted_accuracy - weighted_prior, "by_pair": pair_stats},
    "oof": oof, "frozen_validation": validation,
    "target_support_interaction_gate": {**gates, "pass": all(gates.values())},
}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "target_support_pairwise_validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
with (OUT / "target_support_validation_decisions.jsonl").open("w") as handle:
    for task_id in sorted(validation_ids):
        handle.write(json.dumps({"task_id": task_id, "compatibility": validation_scores[task_id],
                                 "selected_model": validation_choices[task_id]}, ensure_ascii=False) + "\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
