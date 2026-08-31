#!/usr/bin/env python3
"""Leakage-safe capability x requirement routing after the failed v3 utility gate."""
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path("/root")
EXP = ROOT / "target_support_expansion_v1"
OUT = ROOT / "phase_c4"
PROTOCOL = OUT / "C4_PROTOCOL.json"
SEED = 20260830
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
REQ_NAMES = ("numerical", "table", "long_context", "multi_hop", "compliance", "evidence_synthesis")


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def requirement_features(task):
    """Request-time-only features. Deliberately never reads gold/evidence/type/dataset."""
    question = str(task.get("question") or "")
    context = str(task.get("context") or "")
    table = task.get("table") or []
    text = (question + " " + context).lower()
    words = re.findall(r"\b\w+\b", text)
    cells = [str(value) for row in table if isinstance(row, list) for value in row]
    numeric_cells = sum(bool(re.search(r"[-+]?[$£€]?\(?\d[\d,.]*%?\)?", value)) for value in cells)
    arithmetic_terms = sum(text.count(term) for term in (
        "difference", "increase", "decrease", "ratio", "percent", "percentage",
        "average", "total", "change", "sum", "minus", "divided", "growth",
    ))
    numerical = math.log1p(numeric_cells + 2 * arithmetic_terms + len(re.findall(r"[+*/]", question)))
    table_need = math.log1p(len(table) * max((len(row) for row in table if isinstance(row, list)), default=0))
    table_need += numeric_cells / max(1, len(cells))
    long_context = math.log1p(len(words))
    multi_hop = math.log1p(arithmetic_terms + question.lower().count(" and ") + question.lower().count(" between "))
    compliance_terms = sum(text.count(term) for term in (
        "section", "article", "rule", "regulation", "clause", "paragraph", "must",
        "shall", "required", "prohibited", "except", "unless", "notwithstanding",
    ))
    compliance = math.log1p(compliance_terms)
    synthesis_terms = sum(question.lower().count(term) for term in (
        "according to", "based on", "compare", "explain", "why", "which", "both", "list",
    ))
    paragraph_count = len([p for p in re.split(r"\n\s*\n|\n", context) if p.strip()])
    evidence_synthesis = math.log1p(synthesis_terms + min(paragraph_count, 20))
    return np.asarray((numerical, table_need, long_context, multi_hop, compliance, evidence_synthesis), dtype=float)


tasks = {row["id"]: row for row in read_jsonl(EXP / "combined_509_tasks_frozen.jsonl")}
outcomes = {(row["task_id"], row["model"]): row for row in read_jsonl(EXP / "combined_509_task_model_matrix_frozen.jsonl")}
old_split = json.loads((ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text())
new_split = json.loads((EXP / "EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
ids = sorted(set(old_split["train_task_ids"] + old_split["validation_task_ids"] + new_split["train_task_ids"]))
excluded = set(new_split["validation_task_ids"])
assert len(ids) == 419 and not set(ids) & excluded
assert all((task_id, model) in outcomes for task_id in ids for model in MODELS)

requirements = np.vstack([requirement_features(tasks[task_id]) for task_id in ids])
utilities = np.asarray([[float(outcomes[(task_id, model)]["utility"]) for model in MODELS] for task_id in ids])
outer = KFold(5, shuffle=True, random_state=SEED)
choices = {}
baselines = {}
decision_rows = []
capability_rows = []

for fold, (train, valid) in enumerate(outer.split(ids)):
    train_means = utilities[train].mean(axis=0)
    baseline_index = int(np.argmax(train_means))
    baseline = MODELS[baseline_index]
    inner = KFold(5, shuffle=True, random_state=SEED + 100 + fold)
    prediction_ensemble = []
    for inner_fold, (inner_train_local, _) in enumerate(inner.split(train)):
        inner_train = train[inner_train_local]
        estimator = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
        estimator.fit(requirements[inner_train], utilities[inner_train])
        prediction_ensemble.append(estimator.predict(requirements[valid]))
        scaler = estimator.named_steps["standardscaler"]
        ridge = estimator.named_steps["ridge"]
        for model_index, model in enumerate(MODELS):
            capability_rows.append({
                "outer_fold": fold,
                "inner_fold": inner_fold,
                "model": model,
                "requirement_names": list(REQ_NAMES),
                "standardized_capability": [float(x) for x in ridge.coef_[model_index]],
                "training_feature_mean": [float(x) for x in scaler.mean_],
                "training_feature_scale": [float(x) for x in scaler.scale_],
            })
    prediction_ensemble = np.asarray(prediction_ensemble)
    advantage_ensemble = prediction_ensemble - prediction_ensemble[:, :, baseline_index:baseline_index + 1]
    advantage_mean = advantage_ensemble.mean(axis=0)
    advantage_std = advantage_ensemble.std(axis=0, ddof=1)
    lcb = advantage_mean - 1.645 * advantage_std
    for local, position in enumerate(valid):
        task_id = ids[position]
        candidate_index = int(np.argmax(lcb[local]))
        selected = MODELS[candidate_index] if lcb[local, candidate_index] > 0 else baseline
        choices[task_id] = selected
        baselines[task_id] = baseline
        decision_rows.append({
            "task_id": task_id,
            "outer_fold": fold,
            "baseline_model": baseline,
            "selected_model": selected,
            "predicted_advantage": {model: float(advantage_mean[local, i]) for i, model in enumerate(MODELS)},
            "advantage_std": {model: float(advantage_std[local, i]) for i, model in enumerate(MODELS)},
            "lcb90": {model: float(lcb[local, i]) for i, model in enumerate(MODELS)},
            "requirements": {name: float(requirements[position, i]) for i, name in enumerate(REQ_NAMES)},
        })

assert len(choices) == len(ids) == len(decision_rows)
selected_utility = np.asarray([outcomes[(task_id, choices[task_id])]["utility"] for task_id in ids])
baseline_utility = np.asarray([outcomes[(task_id, baselines[task_id])]["utility"] for task_id in ids])
oracle_utility = np.asarray([max(outcomes[(task_id, model)]["utility"] for model in MODELS) for task_id in ids])
delta = selected_utility - baseline_utility
oracle_gap = float(oracle_utility.mean() - baseline_utility.mean())
rng = np.random.default_rng(SEED)
indices = rng.integers(0, len(ids), size=(10000, len(ids)))
bootstrap = delta[indices].mean(axis=1)
high = [task_id for task_id in ids if str(tasks[task_id].get("risk_level")).lower() == "high"]
switches = [task_id for task_id in ids if choices[task_id] != baselines[task_id]]
gains = np.asarray([outcomes[(task_id, choices[task_id])]["utility"] - outcomes[(task_id, baselines[task_id])]["utility"] for task_id in switches])


def failure_rate(task_ids, selected):
    return float(np.mean([bool(outcomes[(task_id, selected[task_id])]["failure"]) for task_id in task_ids]))


metrics = {
    "oof_utility": float(selected_utility.mean()),
    "best_single_utility": float(baseline_utility.mean()),
    "oracle_utility": float(oracle_utility.mean()),
    "oracle_gap": oracle_gap,
    "gap_recovery": float(delta.mean() / oracle_gap) if oracle_gap > 0 else None,
    "delta_utility": float(delta.mean()),
    "delta_utility_ci95": [float(np.quantile(bootstrap, 0.025)), float(np.quantile(bootstrap, 0.975))],
    "bootstrap_probability_delta_positive": float(np.mean(bootstrap > 0)),
    "failure_rate": failure_rate(ids, choices),
    "best_single_failure_rate": failure_rate(ids, baselines),
    "high_risk_failure_rate": failure_rate(high, choices),
    "best_single_high_risk_failure_rate": failure_rate(high, baselines),
    "selection_counts": dict(Counter(choices.values())),
    "switch_count": len(switches),
    "beneficial_switch_count": int(np.sum(gains > 0)),
    "harmful_switch_count": int(np.sum(gains < 0)),
    "net_switch_utility": float(gains.sum()),
}
gate = {
    "gap_recovery_above_0": metrics["gap_recovery"] > 0,
    "bootstrap_probability_ge_0.90": metrics["bootstrap_probability_delta_positive"] >= 0.90,
    "failure_router_le_best": metrics["failure_rate"] <= metrics["best_single_failure_rate"],
    "high_risk_failure_router_le_best": metrics["high_risk_failure_rate"] <= metrics["best_single_high_risk_failure_rate"],
}
status = "C4_DEVELOPMENT_PASS" if all(gate.values()) else "C4_DEVELOPMENT_FAIL"
decision_rows.sort(key=lambda row: row["task_id"])
(OUT / "C4_OOF_DECISIONS.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in decision_rows))
(OUT / "C4_FOLD_CAPABILITIES.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in capability_rows))
report = {
    "status": status,
    "method": "fold-local capability x observable requirement Ridge with 90% advantage LCB",
    "integrity": {
        "tasks": len(ids),
        "excluded_diagnostic_overlap": len(set(ids) & excluded),
        "v3_outcomes_used": False,
        "gold_or_evidence_features_used": False,
        "external_api_calls": 0,
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "bootstrap_unit": "task",
    },
    "metrics": metrics,
    "development_gate": {**gate, "pass": all(gate.values())},
}
(OUT / "C4_OOF_RESULTS.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
hash_targets = (PROTOCOL, OUT / "C4_OOF_DECISIONS.jsonl", OUT / "C4_FOLD_CAPABILITIES.jsonl", OUT / "C4_OOF_RESULTS.json")
(OUT / "C4_SHA256SUMS").write_text("".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in hash_targets))
print(json.dumps(report, ensure_ascii=False, indent=2))
