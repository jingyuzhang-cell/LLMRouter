#!/usr/bin/env python3
"""Build the repeat-aware router data layer and fairly compare three learning targets."""
import hashlib
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import KFold

ROOT = Path("/root")
EXP = ROOT / "target_support_expansion_v1"
OUT = ROOT / "phase_c8"
PROTOCOL = OUT / "C8_PROTOCOL.json"
SEED = 20260831
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
PAIRS = tuple(combinations(range(len(MODELS)), 2))


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def request_text(task):
    question, context, table = str(task.get("question") or ""), str(task.get("context") or ""), task.get("table") or []
    rendered = "\n".join(" | ".join(map(str, row)) for row in table if isinstance(row, list))
    return f"[QUESTION] {question}\n[CONTEXT] {context}\n[TABLE] {rendered}"


def utility(row):
    q, c, l, r = float(row["quality"]), float(row["cost_usd"]), float(row["latency_ms"]), float(row["reliability"])
    return .45*q + .20*(1-min(c/.02, 1)) + .15*(1-min(l/10000, 1)) + .20*r


tasks = {r["id"]: r for r in read_jsonl(EXP / "combined_509_tasks_frozen.jsonl")}
old = json.loads((ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text())
new = json.loads((EXP / "EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
ids = sorted(set(old["train_task_ids"] + old["validation_task_ids"] + new["train_task_ids"]))
assert len(ids) == 419 and not set(ids) & set(new["validation_task_ids"])
repeats = read_jsonl(ROOT / "five_model_routability_audit/five_model_training_repeats_frozen.jsonl")
repeats += read_jsonl(EXP / "expanded_five_model_repeats_frozen.jsonl")
lookup = {(r["task_id"], r["model"], int(r["repeat"])): r for r in repeats if r["task_id"] in ids}
assert all((tid, model, rep) in lookup for tid in ids for model in MODELS for rep in range(3))

quality_repeats = np.asarray([[[float(lookup[(tid, model, rep)]["quality"]) for rep in range(3)] for model in MODELS] for tid in ids])
utility_repeats = np.asarray([[[utility(lookup[(tid, model, rep)]) for rep in range(3)] for model in MODELS] for tid in ids])
quality_mean, quality_var = quality_repeats.mean(axis=2), quality_repeats.var(axis=2, ddof=1)
utility_mean = utility_repeats.mean(axis=2)
pair_prob = np.zeros((len(ids), len(PAIRS)))
for p, (a, b) in enumerate(PAIRS):
    pair_prob[:, p] = np.mean((quality_repeats[:, a] > quality_repeats[:, b]).astype(float)
                               + .5*(quality_repeats[:, a] == quality_repeats[:, b]), axis=1)

data_rows = []
for i, tid in enumerate(ids):
    for m, model in enumerate(MODELS):
        data_rows.append({"task_id": tid, "model": model, "repeats": 3,
                          "quality_mean": float(quality_mean[i, m]), "quality_variance": float(quality_var[i, m]),
                          "latency_mean_ms": float(np.mean([lookup[(tid, model, r)]["latency_ms"] for r in range(3)])),
                          "cost_mean_usd": float(np.mean([lookup[(tid, model, r)]["cost_usd"] for r in range(3)])),
                          "failure_rate": float(np.mean([float(lookup[(tid, model, r)]["reliability"]) < 1 or float(lookup[(tid, model, r)]["quality"]) < .6 for r in range(3)]))})
preference_rows = [{"task_id": tid, "model_a": MODELS[a], "model_b": MODELS[b], "win_probability_a": float(pair_prob[i, p]), "repeats": 3}
                   for i, tid in enumerate(ids) for p, (a, b) in enumerate(PAIRS)]

texts = [request_text(tasks[tid]) for tid in ids]
hard_label = quality_mean.argmax(axis=1)
predictions = {name: np.full(len(ids), -1, dtype=int) for name in ("hard", "pairwise", "performance")}
pred_quality = np.full_like(quality_mean, np.nan)
pred_pair = np.full_like(pair_prob, np.nan)
baselines = np.full(len(ids), -1, dtype=int)
folds = KFold(5, shuffle=True, random_state=SEED)
for fold, (train, valid) in enumerate(folds.split(ids)):
    word = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=12000, sublinear_tf=True)
    char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, max_features=8000, sublinear_tf=True)
    xtr = hstack([word.fit_transform([texts[i] for i in train]), char.fit_transform([texts[i] for i in train])], format="csr")
    xva = hstack([word.transform([texts[i] for i in valid]), char.transform([texts[i] for i in valid])], format="csr")
    classifier = LogisticRegression(C=1, max_iter=2000, class_weight="balanced", random_state=SEED+fold).fit(xtr, hard_label[train])
    hard_scores = np.full((len(valid), len(MODELS)), -np.inf)
    hard_scores[:, classifier.classes_] = classifier.predict_proba(xva)
    predictions["hard"][valid] = hard_scores.argmax(axis=1)
    pair_hat = np.clip(Ridge(alpha=20).fit(xtr, pair_prob[train]).predict(xva), 0, 1)
    pred_pair[valid] = pair_hat
    pair_scores = np.zeros((len(valid), len(MODELS)))
    for p, (a, b) in enumerate(PAIRS):
        pair_scores[:, a] += pair_hat[:, p]
        pair_scores[:, b] += 1-pair_hat[:, p]
    predictions["pairwise"][valid] = pair_scores.argmax(axis=1)
    qhat = np.clip(Ridge(alpha=20).fit(xtr, quality_mean[train]).predict(xva), 0, 1)
    pred_quality[valid] = qhat
    predictions["performance"][valid] = qhat.argmax(axis=1)
    baselines[valid] = int(np.argmax(quality_mean[train].mean(axis=0)))

assert all(np.all(x >= 0) for x in predictions.values()) and np.all(baselines >= 0)
rng = np.random.default_rng(SEED)
bootstrap_idx = rng.integers(0, len(ids), size=(10000, len(ids)))
results = {}
pos = np.arange(len(ids))
for name, selected in predictions.items():
    dq = quality_mean[pos, selected] - quality_mean[pos, baselines]
    du = utility_mean[pos, selected] - utility_mean[pos, baselines]
    boot = du[bootstrap_idx].mean(axis=1)
    results[name] = {"quality": float(quality_mean[pos, selected].mean()), "quality_gain_vs_best_single": float(dq.mean()),
                     "utility": float(utility_mean[pos, selected].mean()), "utility_gain_vs_best_single": float(du.mean()),
                     "utility_gain_ci95": [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
                     "probability_utility_gain_positive": float(np.mean(boot > 0)), "oracle_match": float(np.mean(selected == hard_label)),
                     "selection_counts": dict(Counter(MODELS[x] for x in selected))}
results["performance"]["quality_mae"] = float(np.mean(np.abs(pred_quality-quality_mean)))
true_pair_binary = pair_prob > .5
decisive = pair_prob != .5
results["pairwise"]["pairwise_accuracy_on_decisive_pairs"] = float(np.mean((pred_pair[decisive] > .5) == true_pair_binary[decisive]))

report = {"status": "C8_BENCHMARK_COMPLETE", "integrity": {"tasks": len(ids), "matrix_rows": len(data_rows),
          "preference_rows": len(preference_rows), "v3_outcomes_used": False, "gold_or_evidence_features_used": False,
          "external_api_calls": 0, "shared_grouped_oof": True, "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()},
          "best_single_quality": float(quality_mean[pos, baselines].mean()), "best_single_utility": float(utility_mean[pos, baselines].mean()),
          "results": results}
(OUT / "C8_PERFORMANCE_MATRIX.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in data_rows))
(OUT / "C8_SOFT_PREFERENCES.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in preference_rows))
(OUT / "C8_RESULTS.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
targets = (PROTOCOL, OUT/"C8_PERFORMANCE_MATRIX.jsonl", OUT/"C8_SOFT_PREFERENCES.jsonl", OUT/"C8_RESULTS.json")
(OUT / "C8_SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in targets))
print(json.dumps(report, ensure_ascii=False, indent=2))
