#!/usr/bin/env python3
"""Phase C5: cross-repeat routability noise-ceiling audit with no API calls."""
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/root")
EXP = ROOT / "target_support_expansion_v1"
OUT = ROOT / "phase_c5"
PROTOCOL = OUT / "C5_PROTOCOL.json"
SEED = 20260830
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
EPS = 1e-6


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def utility(row):
    quality = float(row["quality"])
    cost = float(row.get("cost_usd") or 0)
    latency = float(row.get("latency_ms") or 0)
    reliability = float(row.get("reliability", 1))
    return 0.45 * quality + 0.20 * (1 - min(cost / 0.02, 1)) + 0.15 * (1 - min(latency / 10000, 1)) + 0.20 * reliability


tasks = {row["id"]: row for row in read_jsonl(EXP / "combined_509_tasks_frozen.jsonl")}
old_split = json.loads((ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text())
new_split = json.loads((EXP / "EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
ids = sorted(set(old_split["train_task_ids"] + old_split["validation_task_ids"] + new_split["train_task_ids"]))
excluded = set(new_split["validation_task_ids"])
assert len(ids) == 419 and not set(ids) & excluded

repeat_rows = read_jsonl(ROOT / "five_model_routability_audit/five_model_training_repeats_frozen.jsonl")
repeat_rows += read_jsonl(EXP / "expanded_five_model_repeats_frozen.jsonl")
lookup = {}
for row in repeat_rows:
    key = (row["task_id"], row["model"], int(row["repeat"]))
    if row["task_id"] in ids:
        lookup[key] = utility(row)
assert len(lookup) == len(ids) * len(MODELS) * 3

cube = np.asarray([[[lookup[(task_id, model, repeat)] for repeat in range(3)] for model in MODELS] for task_id in ids])
task_n, model_n, repeat_n = cube.shape
assert cube.shape == (419, 5, 3)


def deterministic_argmax(values):
    return np.argmax(values, axis=-1)


fold_rows = []
replicable_by_task = np.zeros((task_n, 3))
best_single_by_task = np.zeros((task_n, 3))
observed_oracle_by_task = np.zeros((task_n, 3))
selected_model_by_task = np.zeros((task_n, 3), dtype=int)
for held_out in range(3):
    selection_repeats = [repeat for repeat in range(3) if repeat != held_out]
    selection_mean = cube[:, :, selection_repeats].mean(axis=2)
    selected = deterministic_argmax(selection_mean)
    selected_model_by_task[:, held_out] = selected
    replicable = cube[np.arange(task_n), selected, held_out]
    global_selection_means = selection_mean.mean(axis=0)
    baseline_index = int(np.argmax(global_selection_means))
    best_single = cube[:, baseline_index, held_out]
    observed_oracle = cube[:, :, held_out].max(axis=1)
    replicable_by_task[:, held_out] = replicable
    best_single_by_task[:, held_out] = best_single
    observed_oracle_by_task[:, held_out] = observed_oracle
    fold_rows.append({
        "held_out_repeat": held_out,
        "selection_repeats": selection_repeats,
        "cross_repeat_best_single_model": MODELS[baseline_index],
        "replicable_oracle_utility": float(replicable.mean()),
        "cross_repeat_best_single_utility": float(best_single.mean()),
        "observed_oracle_utility": float(observed_oracle.mean()),
        "stable_gap": float((replicable - best_single).mean()),
        "noise_gap": float((observed_oracle - replicable).mean()),
        "selected_counts": dict(Counter(MODELS[i] for i in selected)),
    })

replicable_task = replicable_by_task.mean(axis=1)
best_single_task = best_single_by_task.mean(axis=1)
observed_oracle_task = observed_oracle_by_task.mean(axis=1)
stable_delta = replicable_task - best_single_task
noise_delta = observed_oracle_task - replicable_task
rng = np.random.default_rng(SEED)
bootstrap_indices = rng.integers(0, task_n, size=(10000, task_n))
stable_bootstrap = stable_delta[bootstrap_indices].mean(axis=1)
noise_bootstrap = noise_delta[bootstrap_indices].mean(axis=1)

# Winner stability uses each repeat independently. Exact top ties are reported separately.
repeat_winners = deterministic_argmax(cube.transpose(0, 2, 1))
winner_counts = np.asarray([max(Counter(row).values()) for row in repeat_winners])
exact_ties = np.sum(np.isclose(cube, cube.max(axis=1, keepdims=True), atol=1e-12), axis=1) > 1

aggregate = cube.mean(axis=2)
order = np.argsort(-aggregate, axis=1, kind="stable")
top1 = order[:, 0]
top2 = order[:, 1]
top1_mean = aggregate[np.arange(task_n), top1]
top2_mean = aggregate[np.arange(task_n), top2]
margin = top1_mean - top2_mean
variance = cube.var(axis=2, ddof=1)
top1_variance = variance[np.arange(task_n), top1]
top2_variance = variance[np.arange(task_n), top2]
snr = margin / np.sqrt(top1_variance + top2_variance + EPS)

stability_rows = []
for i, task_id in enumerate(ids):
    stability_rows.append({
        "task_id": task_id,
        "risk_level": tasks[task_id].get("risk_level"),
        "repeat_winners": [MODELS[index] for index in repeat_winners[i]],
        "winner_max_count": int(winner_counts[i]),
        "any_exact_top_tie": bool(np.any(exact_ties[i])),
        "aggregate_top1": MODELS[top1[i]],
        "aggregate_top2": MODELS[top2[i]],
        "top1_top2_margin": float(margin[i]),
        "top1_repeat_variance": float(top1_variance[i]),
        "top2_repeat_variance": float(top2_variance[i]),
        "margin_noise_snr": float(snr[i]),
    })

# Stable complementarity for reduced candidate pools. This remains development-only.
global_model_means = cube.mean(axis=(0, 2))
anchor_index = int(np.argmax(global_model_means))
anchor = MODELS[anchor_index]
specialists = [model for model in MODELS if model != anchor]
pool_rows = []
for specialist_count in (1, 2):
    for subset in itertools.combinations(specialists, specialist_count):
        pool = (anchor,) + subset
        pool_indices = np.asarray([MODELS.index(model) for model in pool])
        per_task_gains = np.zeros((task_n, 3))
        selected_counts = Counter()
        for held_out in range(3):
            selection_repeats = [repeat for repeat in range(3) if repeat != held_out]
            selection_mean = cube[:, pool_indices][:, :, selection_repeats].mean(axis=2)
            local_selected = deterministic_argmax(selection_mean)
            selected = pool_indices[local_selected]
            selected_counts.update(MODELS[index] for index in selected)
            per_task_gains[:, held_out] = cube[np.arange(task_n), selected, held_out] - cube[:, anchor_index, held_out]
        task_gain = per_task_gains.mean(axis=1)
        boot = task_gain[bootstrap_indices].mean(axis=1)
        pool_rows.append({
            "anchor": anchor,
            "specialists": list(subset),
            "stable_gain_over_anchor": float(task_gain.mean()),
            "ci95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
            "probability_gain_positive": float(np.mean(boot > 0)),
            "selection_counts_across_three_folds": dict(selected_counts),
        })
pool_rows.sort(key=lambda row: (-row["stable_gain_over_anchor"], row["specialists"]))

stable_gap = float(stable_delta.mean())
noise_gap = float(noise_delta.mean())
report = {
    "status": "C5_COMPLETE",
    "integrity": {
        "tasks": task_n,
        "models": model_n,
        "repeats": repeat_n,
        "complete_keys": len(lookup),
        "excluded_diagnostic_overlap": len(set(ids) & excluded),
        "v3_outcomes_used": False,
        "external_api_calls": 0,
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "bootstrap_unit": "task",
    },
    "cross_repeat": {
        "observed_oracle_utility": float(observed_oracle_task.mean()),
        "replicable_oracle_utility": float(replicable_task.mean()),
        "cross_repeat_best_single_utility": float(best_single_task.mean()),
        "observed_oracle_gap": float((observed_oracle_task - best_single_task).mean()),
        "stable_gap": stable_gap,
        "noise_gap": noise_gap,
        "stable_share_of_observed_gap": float(stable_gap / (stable_gap + noise_gap)) if stable_gap + noise_gap > 0 else None,
        "stable_gap_ci95": [float(np.quantile(stable_bootstrap, 0.025)), float(np.quantile(stable_bootstrap, 0.975))],
        "probability_stable_gap_positive": float(np.mean(stable_bootstrap > 0)),
        "noise_gap_ci95": [float(np.quantile(noise_bootstrap, 0.025)), float(np.quantile(noise_bootstrap, 0.975))],
        "folds": fold_rows,
    },
    "winner_stability": {
        "winner_3_of_3_rate": float(np.mean(winner_counts == 3)),
        "winner_at_least_2_of_3_rate": float(np.mean(winner_counts >= 2)),
        "all_three_winners_different_rate": float(np.mean(winner_counts == 1)),
        "tasks_with_any_exact_top_tie_rate": float(np.mean(np.any(exact_ties, axis=1))),
        "median_top1_top2_margin": float(np.median(margin)),
        "median_margin_noise_snr": float(np.median(snr)),
        "snr_below_1_rate": float(np.mean(snr < 1)),
        "snr_below_2_rate": float(np.mean(snr < 2)),
    },
    "reduced_pool_audit": {
        "anchor": anchor,
        "anchor_mean_utility": float(global_model_means[anchor_index]),
        "best_pool": pool_rows[0],
        "all_pools": pool_rows,
    },
    "decision": {
        "stable_gap_threshold": 0.02,
        "branch": "RESPONSE_AWARE_CASCADE" if stable_gap >= 0.02 else "MEASUREMENT_REPAIR",
        "reason": "stable_gap >= 0.02" if stable_gap >= 0.02 else "stable_gap < 0.02",
    },
}
(OUT / "C5_RESULTS.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
(OUT / "C5_TASK_STABILITY.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in stability_rows))
targets = (PROTOCOL, OUT / "C5_RESULTS.json", OUT / "C5_TASK_STABILITY.jsonl")
(OUT / "C5_SHA256SUMS").write_text("".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in targets))
print(json.dumps(report, ensure_ascii=False, indent=2))
