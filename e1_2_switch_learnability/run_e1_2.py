#!/usr/bin/env python3
"""Nested-OOF learnability test for high-confidence anchor-to-specialist switches."""

import hashlib
import json
import re
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler


ROOT = Path("/root")
OUT = ROOT / "e1_2_switch_learnability"
EXP = ROOT / "target_support_expansion_v1"
PROTOCOL = OUT / "E1_2_PROTOCOL.json"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
ANCHOR = MODELS.index("qwen-plus")
SEED = 20260901
THRESHOLDS = np.arange(.50, .951, .05)


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render(task):
    table = task.get("table") or []
    table_text = "\n".join(" | ".join(map(str, row)) for row in table if isinstance(row, list))
    return f"[QUESTION] {task.get('question') or ''}\n[CONTEXT] {task.get('context') or ''}\n[TABLE] {table_text}"


def structure(task):
    question = str(task.get("question") or "")
    context = str(task.get("context") or "")
    text = question + " " + context
    table = task.get("table") or []
    rows = len(table)
    cols = max([len(x) for x in table if isinstance(x, list)] or [0])
    words = text.split()
    digits = len(re.findall(r"\d", text))
    return [
        len(question.split()), len(context.split()), len(words), len(text), rows, cols, rows * cols,
        digits, digits / max(len(text), 1), len(re.findall(r"\b(?:19|20)\d{2}\b", text)),
        len(re.findall(r"[%$£€¥]", text)), len(re.findall(r"(?i)percent|ratio|difference|increase|decrease|calculate|total|average|growth|margin", text)),
        len(re.findall(r"(?i)shall|required|regulation|compliance|penalt|audit|obligation|appeal", text)),
        int(bool(table)), int("why" in question.lower()), int("how" in question.lower()),
        int("what" in question.lower()), int("which" in question.lower()), int("compare" in question.lower()),
        question.count("?"), text.count("\n"),
    ]


def make_features(texts, structures, train, valid, variant):
    parts_train, parts_valid = [], []
    if variant in ("tfidf", "combined"):
        word = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=12000, sublinear_tf=True)
        char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, max_features=8000, sublinear_tf=True)
        parts_train += [word.fit_transform([texts[i] for i in train]), char.fit_transform([texts[i] for i in train])]
        parts_valid += [word.transform([texts[i] for i in valid]), char.transform([texts[i] for i in valid])]
    if variant in ("structure", "combined"):
        scaler = StandardScaler()
        tr = scaler.fit_transform(structures[train])
        va = scaler.transform(structures[valid])
        parts_train.append(csr_matrix(tr)); parts_valid.append(csr_matrix(va))
    return hstack(parts_train, format="csr"), hstack(parts_valid, format="csr")


def fit_predict(texts, structures, labels, train, valid, variant, seed):
    xtr, xva = make_features(texts, structures, train, valid, variant)
    model = LogisticRegression(C=1.0, max_iter=3000, class_weight="balanced", solver="liblinear", random_state=seed)
    model.fit(xtr, labels[train])
    return model.predict_proba(xva)[:, 1]


def choose_threshold(prob, advantage, train_indices):
    best = None
    min_switches = max(5, int(np.ceil(.02 * len(train_indices))))
    for threshold in THRESHOLDS:
        selected = prob >= threshold
        count = int(selected.sum())
        if count < min_switches:
            continue
        harm = float(np.mean(advantage[selected] < -.05))
        gain = float(np.mean(np.where(selected, advantage, 0.0)))
        if harm <= .25:
            candidate = (gain, threshold, -harm)
            if best is None or candidate > best:
                best = candidate
    return float(best[1]) if best is not None else .95


def main():
    protocol = json.loads(PROTOCOL.read_text())
    old = json.loads((ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text())
    new = json.loads((EXP / "EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
    ids = sorted(set(old["train_task_ids"] + old["validation_task_ids"] + new["train_task_ids"]))
    assert len(ids) == 419 and not set(ids) & set(new["validation_task_ids"])
    task_map = {x["id"]: x for x in read_jsonl(EXP / "combined_509_tasks_frozen.jsonl")}
    texts = [render(task_map[x]) for x in ids]
    structures = np.asarray([structure(task_map[x]) for x in ids], dtype=float)
    rows = read_jsonl(ROOT / "five_model_routability_audit/five_model_training_repeats_frozen.jsonl")
    rows += read_jsonl(EXP / "expanded_five_model_repeats_frozen.jsonl")
    lookup = {(x["task_id"], x["model"], int(x["repeat"])): x for x in rows if x["task_id"] in ids}
    quality = np.asarray([[[float(lookup[(tid, model, r)]["quality"]) for r in range(3)]
                           for model in MODELS] for tid in ids])
    advantage_repeats = quality - quality[:, ANCHOR:ANCHOR + 1, :]
    mean_advantage = advantage_repeats.mean(axis=2)
    rng = np.random.default_rng(SEED)
    boot_idx = rng.integers(0, len(ids), size=(10000, len(ids)))
    results = {}
    decisions = []
    passing = []
    for m, specialist in enumerate(MODELS):
        if m == ANCHOR:
            continue
        labels = (np.sum(advantage_repeats[:, m, :] > .05, axis=1) >= 2).astype(int)
        if labels.sum() < 5:
            continue
        results[specialist] = {}
        outer = StratifiedKFold(5, shuffle=True, random_state=SEED)
        folds = list(outer.split(np.arange(len(ids)), labels))
        for variant in ("structure", "tfidf", "combined"):
            probabilities = np.zeros(len(ids))
            selected = np.zeros(len(ids), dtype=bool)
            thresholds = []
            for fold, (train, valid) in enumerate(folds):
                inner_prob = np.zeros(len(train))
                inner = StratifiedKFold(3, shuffle=True, random_state=SEED + fold)
                for inner_train_local, inner_valid_local in inner.split(train, labels[train]):
                    inner_train = train[inner_train_local]
                    inner_valid = train[inner_valid_local]
                    inner_prob[inner_valid_local] = fit_predict(texts, structures, labels, inner_train, inner_valid, variant, SEED + fold)
                threshold = choose_threshold(inner_prob, mean_advantage[train, m], train)
                thresholds.append(threshold)
                fold_prob = fit_predict(texts, structures, labels, train, valid, variant, SEED + fold)
                probabilities[valid] = fold_prob
                selected[valid] = fold_prob >= threshold
            action_gain = np.where(selected, mean_advantage[:, m], 0.0)
            boot = action_gain[boot_idx].mean(axis=1)
            switch_count = int(selected.sum())
            harm = float(np.mean(mean_advantage[selected, m] < -.05)) if switch_count else 0.0
            prevalence = float(labels.mean())
            pr_auc = float(average_precision_score(labels, probabilities))
            roc_auc = float(roc_auc_score(labels, probabilities))
            checks = {
                "switch_rate_ge_0.02": float(selected.mean()) >= .02,
                "pr_auc_lift_ge_1.25": pr_auc / prevalence >= 1.25,
                "action_gain_positive": float(action_gain.mean()) > 0,
                "gain_ci95_lower_ge_0": float(np.quantile(boot, .025)) >= 0,
                "harmful_switch_rate_le_0.25": harm <= .25,
            }
            passed = all(checks.values())
            if passed:
                passing.append((float(action_gain.mean()), variant, specialist))
            results[specialist][variant] = {
                "positive_prevalence": prevalence, "pr_auc": pr_auc, "pr_auc_lift": pr_auc / prevalence,
                "roc_auc": roc_auc, "fold_thresholds": thresholds, "switches": switch_count,
                "switch_rate": float(selected.mean()), "action_gain": float(action_gain.mean()),
                "gain_ci95": [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
                "probability_gain_positive": float(np.mean(boot > 0)),
                "harmful_switch_rate": harm, "gate": {**checks, "pass": passed},
            }
            for i, tid in enumerate(ids):
                decisions.append({"task_id": tid, "specialist": specialist, "feature_variant": variant,
                                  "oof_probability": float(probabilities[i]), "selected_switch": bool(selected[i]),
                                  "stable_positive_label": int(labels[i]), "mean_advantage": float(mean_advantage[i, m])})
    preference = {"structure": 2, "combined": 1, "tfidf": 0}
    passing.sort(key=lambda x: (x[0], preference[x[1]]), reverse=True)
    selected_configuration = None if not passing else {"specialist": passing[0][2], "feature_variant": passing[0][1], "action_gain": passing[0][0]}
    report = {
        "status": "E1_2_PASS" if passing else "E1_2_FAIL_ADVANCE_TARGETED_DECOMPOSITION",
        "integrity": {"tasks": len(ids), "outer_oof": True, "inner_oof_thresholds": True, "external_api_calls": 0,
                      "untouched_validation_accessed": False, "c9_accessed": False, "protocol_sha256": sha(PROTOCOL)},
        "results": results, "passing_configurations": len(passing), "selected_configuration": selected_configuration,
        "gate_pass": bool(passing),
    }
    result = OUT / "E1_2_RESULTS.json"
    decision_path = OUT / "E1_2_OOF_DECISIONS.jsonl"
    result.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    decision_path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in decisions))
    (OUT / "E1_2_SHA256SUMS").write_text(
        f"{sha(PROTOCOL)}  {PROTOCOL.name}\n{sha(result)}  {result.name}\n{sha(decision_path)}  {decision_path.name}\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
