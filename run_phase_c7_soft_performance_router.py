#!/usr/bin/env python3
"""C7: soft N-model quality prediction with a separate constrained decision layer."""
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

ROOT = Path("/root")
EXP = ROOT / "target_support_expansion_v1"
OUT = ROOT / "phase_c7"
PROTOCOL = OUT / "C7_PROTOCOL.json"
SEED = 20260831
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
ANCHOR = "qwen-plus"
W = {"quality": 0.45, "cost": 0.20, "latency": 0.15, "reliability": 0.20}
NEAR_BEST = 0.02
CATASTROPHIC_MARGIN = 0.05
CATASTROPHIC_RISK_MAX = 0.25


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def request_text(task):
    """Only request-time fields; never inspect labels or dataset metadata."""
    question = str(task.get("question") or "")
    context = str(task.get("context") or "")
    table = task.get("table") or []
    table_text = "\n".join(" | ".join(map(str, row)) for row in table if isinstance(row, list))
    return f"[QUESTION] {question}\n[CONTEXT] {context}\n[TABLE] {table_text}"


def normalized_utility(quality, cost, latency, reliability):
    return (W["quality"] * quality + W["cost"] * (1 - min(cost / 0.02, 1))
            + W["latency"] * (1 - min(latency / 10000, 1)) + W["reliability"] * reliability)


def failure(row):
    return bool(float(row["reliability"]) < 1 or float(row["quality"]) < 0.6)


tasks = {row["id"]: row for row in read_jsonl(EXP / "combined_509_tasks_frozen.jsonl")}
old_split = json.loads((ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text())
new_split = json.loads((EXP / "EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
ids = sorted(set(old_split["train_task_ids"] + old_split["validation_task_ids"] + new_split["train_task_ids"]))
assert len(ids) == 419 and not set(ids) & set(new_split["validation_task_ids"])

repeat_rows = read_jsonl(ROOT / "five_model_routability_audit/five_model_training_repeats_frozen.jsonl")
repeat_rows += read_jsonl(EXP / "expanded_five_model_repeats_frozen.jsonl")
rows = {(r["task_id"], r["model"], int(r["repeat"])): r for r in repeat_rows if r["task_id"] in ids}
assert all((task_id, model, repeat) in rows for task_id in ids for model in MODELS for repeat in range(3))

texts = [request_text(tasks[task_id]) for task_id in ids]
quality = np.asarray([[np.mean([float(rows[(task_id, model, r)]["quality"]) for r in range(3)])
                       for model in MODELS] for task_id in ids])
observed_utility = np.asarray([[np.mean([normalized_utility(**{
    "quality": float(rows[(task_id, model, r)]["quality"]),
    "cost": float(rows[(task_id, model, r)]["cost_usd"]),
    "latency": float(rows[(task_id, model, r)]["latency_ms"]),
    "reliability": float(rows[(task_id, model, r)]["reliability"]),
}) for r in range(3)]) for model in MODELS] for task_id in ids])
observed_failure = np.asarray([[np.mean([failure(rows[(task_id, model, r)]) for r in range(3)])
                                for model in MODELS] for task_id in ids])

predicted_quality = np.zeros_like(quality)
choices = np.full(len(ids), -1, dtype=int)
baselines = np.full(len(ids), -1, dtype=int)
decision_rows = []
outer = KFold(5, shuffle=True, random_state=SEED)
for fold, (train, valid) in enumerate(outer.split(ids)):
    word = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=12000, sublinear_tf=True)
    char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, max_features=8000, sublinear_tf=True)
    x_train = hstack([word.fit_transform([texts[i] for i in train]),
                      char.fit_transform([texts[i] for i in train])], format="csr")
    x_valid = hstack([word.transform([texts[i] for i in valid]),
                      char.transform([texts[i] for i in valid])], format="csr")
    predictor = Ridge(alpha=20.0).fit(x_train, quality[train])
    fold_quality = np.clip(predictor.predict(x_valid), 0, 1)
    predicted_quality[valid] = fold_quality

    profiles = []
    for model_index, model in enumerate(MODELS):
        train_model_rows = [rows[(ids[i], model, r)] for i in train for r in range(3)]
        profiles.append({
            "cost": float(np.mean([float(x["cost_usd"]) for x in train_model_rows])),
            "latency": float(np.mean([float(x["latency_ms"]) for x in train_model_rows])),
            "reliability": float(np.mean([float(x["reliability"]) for x in train_model_rows])),
        })
    predicted_u = np.asarray([[normalized_utility(fold_quality[j, m], **profiles[m]) for m in range(len(MODELS))]
                              for j in range(len(valid))])
    baseline = int(np.argmax(observed_utility[train].mean(axis=0)))
    anchor = MODELS.index(ANCHOR)
    catastrophic_risk = np.zeros(len(MODELS))
    for m in range(len(MODELS)):
        events = observed_utility[train, m] < observed_utility[train, anchor] - CATASTROPHIC_MARGIN
        catastrophic_risk[m] = (events.sum() + 1) / (len(events) + 2)
    catastrophic_risk[anchor] = 0.0
    for local, position in enumerate(valid):
        eligible = [m for m in range(len(MODELS)) if catastrophic_risk[m] <= CATASTROPHIC_RISK_MAX]
        best_predicted = max(predicted_u[local, m] for m in eligible)
        near_best = [m for m in eligible if predicted_u[local, m] >= best_predicted - NEAR_BEST]
        selected = min(near_best, key=lambda m: (profiles[m]["cost"], profiles[m]["latency"], m))
        choices[position] = selected
        baselines[position] = baseline
        decision_rows.append({
            "task_id": ids[position], "outer_fold": fold,
            "predicted_quality": {model: float(fold_quality[local, m]) for m, model in enumerate(MODELS)},
            "predicted_utility": {model: float(predicted_u[local, m]) for m, model in enumerate(MODELS)},
            "catastrophic_switch_risk_vs_anchor": {model: float(catastrophic_risk[m]) for m, model in enumerate(MODELS)},
            "selected_model": MODELS[selected], "fold_best_single": MODELS[baseline],
        })

assert np.all(choices >= 0) and np.all(baselines >= 0)
positions = np.arange(len(ids))
selected_u = observed_utility[positions, choices]
baseline_u = observed_utility[positions, baselines]
selected_f = observed_failure[positions, choices]
baseline_f = observed_failure[positions, baselines]
delta = selected_u - baseline_u
rng = np.random.default_rng(SEED)
bootstrap = delta[rng.integers(0, len(ids), size=(10000, len(ids)))].mean(axis=1)
high = np.asarray([str(tasks[task_id].get("risk_level") or "").lower() == "high" for task_id in ids])
oracle_u = observed_utility.max(axis=1)
gap = float(np.mean(oracle_u - baseline_u))
metrics = {
    "oof_utility": float(selected_u.mean()), "fold_local_best_single_utility": float(baseline_u.mean()),
    "oracle_utility": float(oracle_u.mean()), "oracle_gap": gap,
    "delta_utility": float(delta.mean()), "gap_recovery": float(delta.mean() / gap) if gap > 0 else None,
    "delta_utility_ci95": [float(np.quantile(bootstrap, .025)), float(np.quantile(bootstrap, .975))],
    "bootstrap_probability_delta_positive": float(np.mean(bootstrap > 0)),
    "failure_rate": float(selected_f.mean()), "best_single_failure_rate": float(baseline_f.mean()),
    "high_risk_failure_rate": float(selected_f[high].mean()),
    "best_single_high_risk_failure_rate": float(baseline_f[high].mean()),
    "quality_mae": float(np.mean(np.abs(predicted_quality - quality))),
    "selection_counts": dict(Counter(MODELS[i] for i in choices)),
}
gate = {
    "utility_above_best_single": metrics["delta_utility"] > 0,
    "bootstrap_probability_ge_0.90": metrics["bootstrap_probability_delta_positive"] >= .90,
    "failure_not_above_best_single": metrics["failure_rate"] <= metrics["best_single_failure_rate"],
    "high_risk_failure_not_above_best_single": metrics["high_risk_failure_rate"] <= metrics["best_single_high_risk_failure_rate"],
}
report = {
    "status": "C7_DEVELOPMENT_PASS" if all(gate.values()) else "C7_DEVELOPMENT_FAIL",
    "method": "soft five-model quality prediction plus independent constrained decision layer",
    "integrity": {"tasks": len(ids), "v3_outcomes_used": False, "gold_or_evidence_features_used": False,
                  "external_api_calls": 0, "task_grouped_oof": True,
                  "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()},
    "metrics": metrics, "development_gate": {**gate, "pass": all(gate.values())},
}
decision_rows.sort(key=lambda x: x["task_id"])
(OUT / "C7_OOF_DECISIONS.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in decision_rows))
(OUT / "C7_RESULTS.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
targets = (PROTOCOL, OUT / "C7_OOF_DECISIONS.jsonl", OUT / "C7_RESULTS.json")
(OUT / "C7_SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in targets))
print(json.dumps(report, ensure_ascii=False, indent=2))
