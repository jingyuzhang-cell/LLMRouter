#!/usr/bin/env python3
"""Quantify whether stable model differences are large and predictable enough to route."""
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

ROOT = Path("/root")
EXP = ROOT / "target_support_expansion_v1"
OUT = ROOT / "phase_c7_1"
PROTOCOL = OUT / "C7_1_PROTOCOL.json"
SEED = 20260831
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
ANCHOR_INDEX = MODELS.index("qwen-plus")


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def finite_spearman(actual, predicted):
    value = spearmanr(actual, predicted).statistic
    return float(value) if np.isfinite(value) else None


old = json.loads((ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text())
new = json.loads((EXP / "EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
ids = sorted(set(old["train_task_ids"] + old["validation_task_ids"] + new["train_task_ids"]))
assert len(ids) == 419 and not set(ids) & set(new["validation_task_ids"])

raw = read_jsonl(ROOT / "five_model_routability_audit/five_model_training_repeats_frozen.jsonl")
raw += read_jsonl(EXP / "expanded_five_model_repeats_frozen.jsonl")
lookup = {(r["task_id"], r["model"], int(r["repeat"])): r for r in raw if r["task_id"] in ids}
quality = np.asarray([[[float(lookup[(tid, model, rep)]["quality"]) for rep in range(3)] for model in MODELS] for tid in ids])

decision_rows = {r["task_id"]: r for r in read_jsonl(ROOT / "phase_c7/C7_OOF_DECISIONS.jsonl")}
assert set(decision_rows) == set(ids)
predicted = np.asarray([[float(decision_rows[tid]["predicted_quality"][model]) for model in MODELS] for tid in ids])
actual = quality.mean(axis=2)
error = predicted - actual
global_mae = float(np.mean(np.abs(error)))

per_model = {}
for m, model in enumerate(MODELS):
    per_model[model] = {
        "mae": float(np.mean(np.abs(error[:, m]))),
        "rmse": float(np.sqrt(np.mean(error[:, m] ** 2))),
        "spearman": finite_spearman(actual[:, m], predicted[:, m]),
        "actual_std": float(np.std(actual[:, m], ddof=1)),
        "prediction_std": float(np.std(predicted[:, m], ddof=1)),
    }

sorted_quality = np.sort(actual, axis=1)
margin = sorted_quality[:, -1] - sorted_quality[:, -2]
repeat_variance = quality.var(axis=2, ddof=1)
order = np.argsort(actual, axis=1)
top, second = order[:, -1], order[:, -2]
positions = np.arange(len(ids))
margin_noise = np.sqrt(repeat_variance[positions, top] + repeat_variance[positions, second] + 1e-8)
snr = margin / margin_noise
margin_summary = {
    "quantiles": {str(q): float(np.quantile(margin, q)) for q in (0, .1, .25, .5, .75, .9, 1)},
    "mean": float(np.mean(margin)), "global_quality_mae": global_mae,
    "fraction_margin_above_global_mae": float(np.mean(margin > global_mae)),
    "fraction_margin_above_0_10": float(np.mean(margin > .10)),
    "median_margin_to_prediction_mae_ratio": float(np.median(margin) / global_mae),
    "fraction_margin_noise_snr_below_1": float(np.mean(snr < 1)),
    "median_margin_noise_snr": float(np.median(snr)),
}

advantage = actual - actual[:, ANCHOR_INDEX:ANCHOR_INDEX+1]
pred_advantage = predicted - predicted[:, ANCHOR_INDEX:ANCHOR_INDEX+1]
advantage_metrics = {}
for m, model in enumerate(MODELS):
    if m == ANCHOR_INDEX:
        continue
    labels = advantage[:, m] > 0
    non_tie = advantage[:, m] != 0
    auc = float(roc_auc_score(labels, pred_advantage[:, m])) if len(np.unique(labels)) == 2 else None
    advantage_metrics[model] = {
        "mae": float(np.mean(np.abs(pred_advantage[:, m] - advantage[:, m]))),
        "spearman": finite_spearman(advantage[:, m], pred_advantage[:, m]),
        "auc_advantage_gt_0": auc,
        "sign_accuracy_non_ties": float(np.mean((pred_advantage[non_tie, m] > 0) == labels[non_tie])),
        "positive_prevalence": float(np.mean(labels)),
        "actual_advantage_std": float(np.std(advantage[:, m], ddof=1)),
    }

winners = quality.argmax(axis=1)
same_winner_all_repeats = np.all(winners == winners[:, :1], axis=1)
pair_agreements = []
for a in range(len(MODELS)):
    for b in range(a + 1, len(MODELS)):
        signs = np.sign(quality[:, a, :] - quality[:, b, :])
        pair_agreements.extend(np.all(signs == signs[:, :1], axis=1).tolist())

held_oracle, held_single, observed_oracle = [], [], []
for held in range(3):
    selection_repeats = [r for r in range(3) if r != held]
    selected = quality[:, :, selection_repeats].mean(axis=2).argmax(axis=1)
    best_single = int(quality[:, :, selection_repeats].mean(axis=(0, 2)).argmax())
    held_oracle.extend(quality[positions, selected, held].tolist())
    held_single.extend(quality[:, best_single, held].tolist())
    observed_oracle.extend(quality[:, :, held].max(axis=1).tolist())
stable_gap = float(np.mean(held_oracle) - np.mean(held_single))
noise_gap = float(np.mean(observed_oracle) - np.mean(held_oracle))

predictable = [m for m, x in advantage_metrics.items() if x["auc_advantage_gt_0"] is not None
               and x["auc_advantage_gt_0"] >= .65 and x["spearman"] is not None and x["spearman"] >= .20]
signal_insufficient = bool(np.median(margin) < global_mae and not predictable)
stable_headroom = bool(stable_gap > .02)
if signal_insufficient and stable_headroom:
    decision = "COLLECT_CAPABILITY_STRATIFIED_DATA"
elif not stable_headroom:
    decision = "IMPROVE_REPEAT_AND_EVALUATION_SYSTEM"
else:
    decision = "PREREGISTER_CAPABILITY_AWARE_ROUTER_ON_NEW_VALIDATION"

rng = np.random.default_rng(SEED)
boot_idx = rng.integers(0, len(ids), size=(10000, len(ids)))
task_cross_repeat_gain = np.mean([quality[positions, quality[:, :, [r for r in range(3) if r != h]].mean(axis=2).argmax(axis=1), h]
                                  - quality[:, int(quality[:, :, [r for r in range(3) if r != h]].mean(axis=(0, 2)).argmax()), h]
                                  for h in range(3)], axis=0)
boot = task_cross_repeat_gain[boot_idx].mean(axis=1)
report = {
    "status": "C7_1_AUDIT_COMPLETE", "decision": decision,
    "integrity": {"tasks": len(ids), "models": len(MODELS), "repeats": 3, "v3_outcomes_used": False,
                  "external_api_calls": 0, "prediction_rows_reused_without_refit": len(decision_rows),
                  "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()},
    "margin_vs_error": margin_summary, "per_model_predictability": per_model,
    "advantage_vs_qwen_plus": advantage_metrics,
    "repeat_stability": {"same_winner_all_three_repeats": float(np.mean(same_winner_all_repeats)),
                         "all_three_repeats_same_pairwise_sign": float(np.mean(pair_agreements)),
                         "cross_repeat_replicable_oracle_gap": stable_gap, "noise_induced_oracle_gap": noise_gap,
                         "stable_gap_ci95": [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))]},
    "decision_evidence": {"signal_insufficient": signal_insufficient, "stable_headroom": stable_headroom,
                          "predictable_non_anchor_advantages": predictable},
}
(OUT / "C7_1_RESULTS.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
targets = (PROTOCOL, OUT / "C7_1_RESULTS.json")
(OUT / "C7_1_SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in targets))
print(json.dumps(report, ensure_ascii=False, indent=2))
