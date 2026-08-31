#!/usr/bin/env python3
"""C6 response-aware accept/escalate cascade, grouped OOF and no API calls."""
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler

ROOT = Path("/root")
EXP = ROOT / "target_support_expansion_v1"
DATA = ROOT / "autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/data/finance_router"
OUT = ROOT / "phase_c6"
PROTOCOL = OUT / "C6_PROTOCOL.json"
SEED = 20260830
ANCHOR = "qwen-plus"
SPECIALISTS = ("deepseek-chat", "gemini-2.5-flash")


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def utility(row):
    quality = float(row["quality"])
    cost = float(row.get("cost_usd") or 0)
    latency = float(row.get("latency_ms") or 0)
    reliability = float(row.get("reliability", 1))
    return 0.45 * quality + 0.20 * (1 - min(cost / 0.02, 1)) + 0.15 * (1 - min(latency / 10000, 1)) + 0.20 * reliability


def tokens(text):
    return re.findall(r"[a-zA-Z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]", str(text).lower())


def observable_features(task, answer):
    question = str(task.get("question") or "")
    context = str(task.get("context") or "")
    table = task.get("table") or []
    source = context + " " + " ".join(str(value) for row in table if isinstance(row, list) for value in row)
    answer_tokens = tokens(answer)
    question_tokens = set(tokens(question))
    source_tokens = set(tokens(source))
    answer_set = set(answer_tokens)
    answer_numbers = re.findall(r"[-+]?\d[\d,.]*%?", answer)
    source_compact = re.sub(r"\s+", "", source.lower())
    number_coverage = np.mean([re.sub(r"\s+", "", number.lower()) in source_compact for number in answer_numbers]) if answer_numbers else 1.0
    refusal = sum(str(answer).lower().count(term) for term in ("cannot", "unable", "insufficient", "不确定", "无法", "没有足够"))
    uncertainty = sum(str(answer).lower().count(term) for term in ("may", "might", "likely", "possibly", "可能", "也许"))
    citations = len(re.findall(r"\b(?:section|article|rule|part|paragraph|clause)\s*[\d.()]+", str(answer).lower()))
    arithmetic = len(re.findall(r"[=+*/]|\b(?:minus|divided|difference|percent|ratio)\b", str(answer).lower()))
    neg_q = len(re.findall(r"\b(?:not|except|unless|without)\b|不|除非", question.lower()))
    neg_a = len(re.findall(r"\b(?:not|except|unless|without)\b|不|除非", str(answer).lower()))
    return np.asarray([
        math.log1p(len(answer_tokens)),
        math.log1p(len(str(answer))),
        len(answer_set & question_tokens) / max(1, len(question_tokens)),
        len(answer_set & source_tokens) / max(1, len(answer_set)),
        number_coverage,
        math.log1p(len(answer_numbers)),
        math.log1p(citations),
        math.log1p(arithmetic),
        math.log1p(refusal),
        math.log1p(uncertainty),
        abs(neg_q - neg_a),
        float(bool(re.search(r"\b(?:therefore|thus|answer|result)\b|因此|所以|答案", str(answer).lower()))),
        float(len(answer_tokens) >= 500),
    ], dtype=float)


tasks = {row["id"]: row for row in read_jsonl(EXP / "combined_509_tasks_frozen.jsonl")}
old_split = json.loads((ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text())
new_split = json.loads((EXP / "EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
task_ids = sorted(set(old_split["train_task_ids"] + old_split["validation_task_ids"] + new_split["train_task_ids"]))
assert len(task_ids) == 419 and not set(task_ids) & set(new_split["validation_task_ids"])

responses = []
for path in sorted(DATA.glob("*/responses.jsonl")):
    responses.extend(read_jsonl(path))
response_lookup = {}
for row in responses:
    if row.get("task_id") in tasks:
        response_lookup[(row["task_id"], row["model"], int(row.get("repeat", 0)))] = row
assert all((task_id, ANCHOR, repeat) in response_lookup for task_id in task_ids for repeat in range(3))
assert all(response_lookup[(task_id, ANCHOR, repeat)].get("success") for task_id in task_ids for repeat in range(3))

repeat_rows = read_jsonl(ROOT / "five_model_routability_audit/five_model_training_repeats_frozen.jsonl")
repeat_rows += read_jsonl(EXP / "expanded_five_model_repeats_frozen.jsonl")
outcomes = {}
for row in repeat_rows:
    if row["task_id"] in task_ids:
        outcomes[(row["task_id"], row["model"], int(row["repeat"]))] = {
            "utility": utility(row),
            "failure": bool(float(row.get("reliability", 1)) < 1 or float(row["quality"]) < 0.6),
        }
assert all((task_id, model, repeat) in outcomes for task_id in task_ids for model in (ANCHOR,) + SPECIALISTS for repeat in range(3))

samples = []
for task_position, task_id in enumerate(task_ids):
    for repeat in range(3):
        answer = str(response_lookup[(task_id, ANCHOR, repeat)].get("answer") or "")
        samples.append({
            "task_position": task_position,
            "task_id": task_id,
            "repeat": repeat,
            "answer": answer,
            "text": str(tasks[task_id].get("question") or "") + " [ANCHOR_ANSWER] " + answer,
            "features": observable_features(tasks[task_id], answer),
            "failure": outcomes[(task_id, ANCHOR, repeat)]["failure"],
            "risk": str(tasks[task_id].get("risk_level") or "").lower(),
        })

predicted_failure = np.zeros(len(samples))
selected_model = [None] * len(samples)
fold_specialists = []
outer = KFold(5, shuffle=True, random_state=SEED)
for fold, (train_tasks, valid_tasks) in enumerate(outer.split(task_ids)):
    train_set = set(int(x) for x in train_tasks)
    valid_set = set(int(x) for x in valid_tasks)
    train_indices = np.asarray([i for i, sample in enumerate(samples) if sample["task_position"] in train_set])
    valid_indices = np.asarray([i for i, sample in enumerate(samples) if sample["task_position"] in valid_set])
    vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=3, max_features=8000, sublinear_tf=True)
    train_text = vectorizer.fit_transform([samples[i]["text"] for i in train_indices])
    valid_text = vectorizer.transform([samples[i]["text"] for i in valid_indices])
    scaler = StandardScaler().fit(np.vstack([samples[i]["features"] for i in train_indices]))
    train_manual = csr_matrix(scaler.transform(np.vstack([samples[i]["features"] for i in train_indices])))
    valid_manual = csr_matrix(scaler.transform(np.vstack([samples[i]["features"] for i in valid_indices])))
    labels = np.asarray([samples[i]["failure"] for i in train_indices], dtype=int)
    classifier = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced", random_state=SEED + fold)
    classifier.fit(hstack([train_text, train_manual], format="csr"), labels)
    predicted_failure[valid_indices] = classifier.predict_proba(hstack([valid_text, valid_manual], format="csr"))[:, 1]
    specialist_means = {}
    for model in SPECIALISTS:
        specialist_means[model] = float(np.mean([
            outcomes[(task_ids[position], model, repeat)]["utility"]
            for position in train_tasks for repeat in range(3)
        ]))
    specialist = max(SPECIALISTS, key=lambda model: specialist_means[model])
    fold_specialists.append({"fold": fold, "selected_specialist": specialist, "training_mean_utility": specialist_means})
    for i in valid_indices:
        threshold = 0.35 if samples[i]["risk"] == "high" else 0.5
        selected_model[i] = specialist if predicted_failure[i] >= threshold else ANCHOR

assert all(model is not None for model in selected_model)
anchor_values = np.asarray([outcomes[(sample["task_id"], ANCHOR, sample["repeat"])]["utility"] for sample in samples])
cascade_values = np.asarray([outcomes[(sample["task_id"], selected_model[i], sample["repeat"])]["utility"] for i, sample in enumerate(samples)])
anchor_failures = np.asarray([outcomes[(sample["task_id"], ANCHOR, sample["repeat"])]["failure"] for sample in samples], dtype=bool)
cascade_failures = np.asarray([outcomes[(sample["task_id"], selected_model[i], sample["repeat"])]["failure"] for i, sample in enumerate(samples)], dtype=bool)
escalated = np.asarray([model != ANCHOR for model in selected_model])

task_delta = np.asarray([np.mean([
    cascade_values[i] - anchor_values[i] for i, sample in enumerate(samples) if sample["task_position"] == position
]) for position in range(len(task_ids))])
rng = np.random.default_rng(SEED)
bootstrap_indices = rng.integers(0, len(task_ids), size=(10000, len(task_ids)))
bootstrap = task_delta[bootstrap_indices].mean(axis=1)
high_mask = np.asarray([sample["risk"] == "high" for sample in samples])
tp = int(np.sum(escalated & anchor_failures))
fp = int(np.sum(escalated & ~anchor_failures))
fn = int(np.sum(~escalated & anchor_failures))
tn = int(np.sum(~escalated & ~anchor_failures))
metrics = {
    "cascade_utility": float(cascade_values.mean()),
    "anchor_utility": float(anchor_values.mean()),
    "delta_utility": float((cascade_values - anchor_values).mean()),
    "delta_utility_task_bootstrap_ci95": [float(np.quantile(bootstrap, 0.025)), float(np.quantile(bootstrap, 0.975))],
    "bootstrap_probability_delta_positive": float(np.mean(bootstrap > 0)),
    "cascade_failure": float(cascade_failures.mean()),
    "anchor_failure": float(anchor_failures.mean()),
    "cascade_high_risk_failure": float(cascade_failures[high_mask].mean()),
    "anchor_high_risk_failure": float(anchor_failures[high_mask].mean()),
    "escalation_rate": float(escalated.mean()),
    "high_risk_escalation_rate": float(escalated[high_mask].mean()),
    "verifier_failure_recall": float(tp / max(1, tp + fn)),
    "verifier_escalation_precision": float(tp / max(1, tp + fp)),
    "verifier_specificity": float(tn / max(1, tn + fp)),
    "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    "selection_counts": dict(Counter(selected_model)),
}
gate = {
    "utility_above_anchor": metrics["delta_utility"] > 0,
    "bootstrap_probability_ge_0.90": metrics["bootstrap_probability_delta_positive"] >= 0.90,
    "failure_not_above_anchor": metrics["cascade_failure"] <= metrics["anchor_failure"],
    "high_risk_failure_not_above_anchor": metrics["cascade_high_risk_failure"] <= metrics["anchor_high_risk_failure"],
}
decision_rows = []
for i, sample in enumerate(samples):
    decision_rows.append({
        "task_id": sample["task_id"],
        "repeat": sample["repeat"],
        "risk_level": sample["risk"],
        "predicted_anchor_failure": float(predicted_failure[i]),
        "threshold": 0.35 if sample["risk"] == "high" else 0.5,
        "anchor_failure": bool(anchor_failures[i]),
        "selected_model": selected_model[i],
        "escalated": bool(escalated[i]),
        "utility_gain": float(cascade_values[i] - anchor_values[i]),
    })
report = {
    "status": "C6_DEVELOPMENT_PASS" if all(gate.values()) else "C6_DEVELOPMENT_FAIL",
    "integrity": {
        "tasks": len(task_ids),
        "task_repeat_samples": len(samples),
        "task_grouped_oof": True,
        "anchor_response_coverage": len(samples),
        "gold_or_evidence_features_used": False,
        "v3_outcomes_used": False,
        "external_api_calls": 0,
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
    },
    "fold_specialists": fold_specialists,
    "metrics": metrics,
    "development_gate": {**gate, "pass": all(gate.values())},
}
(OUT / "C6_RESULTS.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
(OUT / "C6_DECISIONS.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in decision_rows))
targets = (PROTOCOL, OUT / "C6_RESULTS.json", OUT / "C6_DECISIONS.jsonl")
(OUT / "C6_SHA256SUMS").write_text("".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in targets))
print(json.dumps(report, ensure_ascii=False, indent=2))
