#!/usr/bin/env python3
"""Run the preregistered xRouteBench E0 implementation sanity check."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PROTOCOL_PATH = ROOT / "E0_PROTOCOL.json"
RESULTS_PATH = ROOT / "E0_RESULTS.json"
DECISIONS_PATH = ROOT / "E0_TEST_DECISIONS.jsonl"
SEEDS = (20260901, 20260902, 20260903, 20260904, 20260905)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matrix(frame: pd.DataFrame, models: list[str]) -> tuple[pd.DataFrame, np.ndarray]:
    queries = (
        frame[["embedding_id", "query"]]
        .drop_duplicates("embedding_id")
        .sort_values("embedding_id")
        .reset_index(drop=True)
    )
    scores = frame.pivot(index="embedding_id", columns="model_name", values="performance")
    scores = scores.reindex(index=queries.embedding_id, columns=models)
    if scores.isna().any().any():
        raise ValueError("Incomplete query-model matrix for frozen candidate pool")
    return queries, scores.to_numpy(dtype=float)


def evaluate(name: str, selected: np.ndarray, scores: np.ndarray, best: int) -> dict:
    positions = np.arange(len(scores))
    realized = scores[positions, selected]
    baseline = scores[:, best]
    oracle = scores.max(axis=1)
    delta = realized - baseline
    denominator = float(np.mean(oracle - baseline))
    tied_oracle = scores == oracle[:, None]
    return {
        "method": name,
        "mean_performance": float(realized.mean()),
        "gain_vs_best_single": float(delta.mean()),
        "gap_recovery": float(delta.mean() / denominator) if denominator > 0 else None,
        "canonical_oracle_accuracy": float(np.mean(selected == scores.argmax(axis=1))),
        "tie_aware_oracle_accuracy": float(np.mean(tied_oracle[positions, selected])),
        "selection_counts": dict(Counter(int(x) for x in selected)),
    }


def bootstrap(selected: np.ndarray, scores: np.ndarray, best: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    positions = np.arange(len(scores))
    delta = scores[positions, selected] - scores[:, best]
    oracle_delta = scores.max(axis=1) - scores[:, best]
    indices = rng.integers(0, len(scores), size=(10000, len(scores)))
    gains = delta[indices].mean(axis=1)
    denominators = oracle_delta[indices].mean(axis=1)
    recoveries = np.divide(gains, denominators, out=np.full_like(gains, np.nan), where=denominators > 0)
    return {
        "seed": seed,
        "gain_ci95": [float(np.quantile(gains, 0.025)), float(np.quantile(gains, 0.975))],
        "gap_recovery_ci95": [float(np.nanquantile(recoveries, 0.025)), float(np.nanquantile(recoveries, 0.975))],
        "probability_gain_positive": float(np.mean(gains > 0)),
    }


def main() -> None:
    protocol = json.loads(PROTOCOL_PATH.read_text())
    expected = protocol["data_sha256"]
    for filename, digest in expected.items():
        if sha256(DATA / filename) != digest:
            raise ValueError(f"Hash mismatch: {filename}")

    models = protocol["candidate_models"]
    train_raw = pd.read_parquet(DATA / "llmrouter_generic_train.parquet")
    test_raw = pd.read_parquet(DATA / "llmrouter_generic_test.parquet")
    train_raw = train_raw[train_raw.model_name.isin(models)].copy()
    test_raw = test_raw[test_raw.model_name.isin(models)].copy()
    train_queries, y_train = matrix(train_raw, models)
    test_queries, y_test = matrix(test_raw, models)
    if set(train_queries["query"]) & set(test_queries["query"]):
        raise ValueError("Exact query text overlap between train and test")

    word = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=12000, sublinear_tf=True)
    char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, max_features=8000, sublinear_tf=True)
    x_train = hstack([
        word.fit_transform(train_queries["query"].astype(str)),
        char.fit_transform(train_queries["query"].astype(str)),
    ], format="csr")
    x_test = hstack([
        word.transform(test_queries["query"].astype(str)),
        char.transform(test_queries["query"].astype(str)),
    ], format="csr")

    best = int(np.argmax(y_train.mean(axis=0)))
    hard_labels = y_train.argmax(axis=1)
    majority = int(np.argmax(np.bincount(hard_labels, minlength=len(models))))
    classifier = LogisticRegression(
        C=1.0, max_iter=3000, class_weight="balanced", solver="lbfgs",
        random_state=SEEDS[0],
    ).fit(x_train, hard_labels)
    hard_probability = np.zeros((len(y_test), len(models)))
    hard_probability[:, classifier.classes_] = classifier.predict_proba(x_test)
    hard_selected = hard_probability.argmax(axis=1)
    predicted = np.clip(Ridge(alpha=20.0).fit(x_train, y_train).predict(x_test), 0, 1)
    performance_selected = predicted.argmax(axis=1)

    selections = {
        "best_single": np.full(len(y_test), best, dtype=int),
        "majority_winner": np.full(len(y_test), majority, dtype=int),
        "hard_classification": hard_selected,
        "performance_prediction": performance_selected,
        "oracle": y_test.argmax(axis=1),
    }
    method_results = {name: evaluate(name, selected, y_test, best) for name, selected in selections.items()}
    random_results = []
    for seed in SEEDS:
        random_selection = np.random.default_rng(seed).integers(0, len(models), size=len(y_test))
        random_results.append(evaluate(f"random_seed_{seed}", random_selection, y_test, best))
    method_results["random"] = {
        "mean_performance": float(np.mean([x["mean_performance"] for x in random_results])),
        "mean_gap_recovery": float(np.mean([x["gap_recovery"] for x in random_results])),
        "per_seed": random_results,
    }

    for name in ("hard_classification", "performance_prediction"):
        method_results[name]["bootstrap"] = [bootstrap(selections[name], y_test, best, seed) for seed in SEEDS]
        method_results[name]["mean_bootstrap_probability_gain_positive"] = float(np.mean([
            x["probability_gain_positive"] for x in method_results[name]["bootstrap"]
        ]))

    oracle_gap = float(np.mean(y_test.max(axis=1) - y_test[:, best]))
    learned = [method_results["hard_classification"], method_results["performance_prediction"]]
    best_learned = max(learned, key=lambda x: x["gap_recovery"])
    gate_checks = {
        "oracle_gap_ge_0.03": oracle_gap >= protocol["gate"]["minimum_oracle_gap"],
        "best_learned_gap_recovery_ge_0.15": best_learned["gap_recovery"] >= protocol["gate"]["minimum_mean_gap_recovery"],
        "best_learned_bootstrap_probability_ge_0.90": best_learned["mean_bootstrap_probability_gain_positive"] >= protocol["gate"]["minimum_bootstrap_probability_gain_positive"],
    }
    passed = all(gate_checks.values())

    decisions = []
    for i, row in test_queries.iterrows():
        decisions.append({
            "embedding_id": row.embedding_id,
            "selected": {name: models[int(values[i])] for name, values in selections.items()},
            "observed_performance": {model: float(y_test[i, j]) for j, model in enumerate(models)},
            "performance_prediction": {model: float(predicted[i, j]) for j, model in enumerate(models)},
        })
    DECISIONS_PATH.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in decisions))

    report = {
        "status": "E0_PASS" if passed else "E0_FAIL_STOP_BEFORE_E1",
        "integrity": {
            "train_queries": len(train_queries), "test_queries": len(test_queries),
            "candidate_models": models, "official_split": True, "exact_text_overlap": 0,
            "external_api_calls": 0, "financial_assets_modified": False,
            "protocol_sha256": sha256(PROTOCOL_PATH),
        },
        "train_diagnostics": {
            "mean_performance_by_model": {m: float(y_train[:, j].mean()) for j, m in enumerate(models)},
            "canonical_winner_counts": {models[k]: int(v) for k, v in Counter(hard_labels).items()},
            "best_single": models[best], "majority_winner": models[majority],
        },
        "test_oracle_gap": oracle_gap,
        "methods": method_results,
        "best_learned_method": best_learned["method"],
        "gate": {**gate_checks, "pass": passed},
    }
    RESULTS_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    targets = [PROTOCOL_PATH, *sorted(DATA.glob("*.parquet")), DECISIONS_PATH, RESULTS_PATH]
    (ROOT / "E0_SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(ROOT)}\n" for p in targets))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
