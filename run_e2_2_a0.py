#!/usr/bin/env python3
"""E2.2-A0 leakage-controlled retrospective selective-routing feasibility.

This script is deliberately offline: it reads only frozen E2.1-A artifacts and
local source documents.  It never imports or calls a provider client.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "e2_1_protocol"
OUT = ROOT / "e2_2_a0"
TASKS = DATA / "E2_1_A_FRESH_360_TASKS.jsonl"
GOLD = DATA / "E2_1_NATIVE_PAGE_GOLD_360.jsonl"
RESPONSES = DATA / "E2_1_A_RESPONSES.jsonl"
EVENTS = DATA / "E2_1_A_EVENTS.jsonl"
E21_RESULTS = DATA / "E2_1_A_RESULTS.json"
ANCHOR = "deepseek"
SPECIALISTS = ("glm-5.2", "qwen-plus")
MODELS = (ANCHOR,) + SPECIALISTS
REPEATS = (0, 1, 2)
SEED = 20260905
BOOTSTRAPS = 4000
POWER_SIMS = 2000
N_CANDIDATES = (60, 80, 100, 120, 150, 200)
TOKEN = re.compile(r"[A-Za-z0-9]+")
NUMERIC = re.compile(r"(?<![A-Za-z])[-+]?[$€£]?\d[\d,]*(?:\.\d+)?%?")
DATE = re.compile(r"\b(?:19|20)\d{2}\b")
TABLE = re.compile(r"(?m)^\s*\|.*\|\s*$")
COMPARISON = re.compile(r"\b(?:compare|comparison|difference|versus|vs\.?|higher|lower|increase|decrease|ratio|percent)\b", re.I)
AGGREGATION = re.compile(r"\b(?:total|sum|average|mean|aggregate|combined|ratio|percentage|percent)\b", re.I)
TEMPORAL = re.compile(r"\b(?:year|quarter|month|annual|during|between|from|to|change|growth|prior|previous)\b", re.I)
MULTIHOP = re.compile(r"\b(?:and|then|respectively|difference|ratio|percentage|compared|relative)\b", re.I)


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def prf(predicted: set[str], gold: set[str]) -> float:
    if not predicted:
        return 0.0
    overlap = len(predicted & gold)
    precision = overlap / len(predicted)
    recall = overlap / len(gold)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def feature_row(task: dict, document_text: str) -> dict[str, float]:
    question = str(task["question"])
    qtokens = [x.lower() for x in TOKEN.findall(question)]
    dtokens = [x.lower() for x in TOKEN.findall(document_text)]
    qset, dcount = set(qtokens), Counter(dtokens)
    overlap = sum(dcount[x] for x in qset)
    candidates = task["candidate_page_ids"]
    return {
        "query_token_count": len(qtokens),
        "query_unique_token_count": len(qset),
        "document_token_count": len(dtokens),
        "document_char_count": len(document_text),
        "candidate_page_count": len(candidates),
        "candidate_page_fraction_proxy": len(candidates) / max(1, document_text.count("# Page ")),
        "numeric_count": len(NUMERIC.findall(document_text)),
        "numeric_density": len(NUMERIC.findall(document_text)) / max(1, len(dtokens)),
        "date_count": len(DATE.findall(document_text)),
        "table_line_count": len(TABLE.findall(document_text)),
        "question_document_lexical_overlap": overlap / max(1, len(dtokens)),
        "question_type_table": float(task.get("task_type") == "table"),
        "question_type_text": float(task.get("task_type") == "text"),
        "question_type_mixed": float(task.get("task_type") == "mixed"),
        "comparison_indicator": float(bool(COMPARISON.search(question))),
        "aggregation_indicator": float(bool(AGGREGATION.search(question))),
        "temporal_indicator": float(bool(TEMPORAL.search(question))),
        "multihop_proxy": float(bool(MULTIHOP.search(question))),
        "question_numeric_count": len(NUMERIC.findall(question)),
        "question_date_count": len(DATE.findall(question)),
    }


def ridge(alpha: float):
    return make_pipeline(SimpleImputer(), StandardScaler(), Ridge(alpha=alpha))


def hgb(l2: float, leaves: int):
    return make_pipeline(SimpleImputer(), HistGradientBoostingRegressor(
        learning_rate=0.05, max_iter=150, max_leaf_nodes=leaves,
        l2_regularization=l2, random_state=SEED,
    ))


CONFIGS = [
    (f"ridge_alpha_{a:g}", lambda a=a: ridge(a)) for a in (0.1, 1.0, 10.0, 100.0)
] + [
    (f"hgb_l2_{l2:g}_leaves_{leaves}", lambda l2=l2, leaves=leaves: hgb(l2, leaves))
    for l2 in (0.1, 1.0, 10.0) for leaves in (7, 15)
]
QUANTILES = (0.10, 0.20, 0.30)
TAUS = (0.0, 0.01, 0.03, 0.05)


def fit_ensemble(factory, X, y, groups, X_test):
    unique = np.unique(groups)
    splits = min(4, len(unique))
    predictions = []
    for train, _ in GroupKFold(splits).split(X, y, groups):
        model = factory()
        model.fit(X[train], y[train])
        predictions.append(model.predict(X_test))
    return np.asarray(predictions)


def inner_predictions(factory, X, ys, groups):
    pred = {m: np.full(len(X), np.nan) for m in SPECIALISTS}
    splits = min(4, len(np.unique(groups)))
    for train, test in GroupKFold(splits).split(X, ys[SPECIALISTS[0]], groups):
        for model_name in SPECIALISTS:
            model = factory()
            model.fit(X[train], ys[model_name][train])
            pred[model_name][test] = model.predict(X[test])
    return pred


def policy(pred, q, tau):
    # Across-model ensemble quantile is a conservative empirical lower estimate.
    lower = np.column_stack([np.quantile(pred[m], q, axis=0) for m in SPECIALISTS])
    chosen_idx = np.argmax(lower, axis=1)
    chosen_lcb = lower[np.arange(len(lower)), chosen_idx]
    chosen = np.asarray([SPECIALISTS[i] for i in chosen_idx], dtype=object)
    return np.where(chosen_lcb > tau, chosen, ANCHOR), chosen_lcb


def evaluate_policy(chosen, quality, opportunity, predicted_advantage=None):
    n = len(chosen)
    anchor = quality[ANCHOR]
    selected = np.asarray([quality[str(m)][i] for i, m in enumerate(chosen)])
    realized = selected - anchor
    switched = chosen != ANCHOR
    harmful = realized < -0.05
    oracle = np.max(np.column_stack([quality[m] for m in MODELS]), axis=1)
    oracle_gap = float(np.mean(oracle - anchor))
    out = {
        "anchor_f1": float(np.mean(anchor)),
        "selective_f1": float(np.mean(selected)),
        "selective_gain": float(np.mean(realized)),
        "coverage": float(np.mean(switched)),
        "switch_count": int(np.sum(switched)),
        "harmful_switch_rate": float(np.mean(harmful[switched])) if np.any(switched) else None,
        "oracle_gap": oracle_gap,
        "oracle_gap_recovery": float(np.mean(realized) / oracle_gap) if oracle_gap > 0 else None,
        "opportunity_prevalence": float(np.mean(opportunity)),
    }
    if predicted_advantage is not None:
        out["predicted_advantage_mean"] = float(np.mean(predicted_advantage))
    return out, realized, switched, harmful


def grouped_bootstrap(values, groups, statistic=np.mean, seed=SEED, n_boot=BOOTSTRAPS):
    rng = np.random.default_rng(seed)
    unique = np.unique(groups)
    by_group = {g: np.flatnonzero(groups == g) for g in unique}
    draws = []
    for _ in range(n_boot):
        picked = rng.choice(unique, len(unique), replace=True)
        idx = np.concatenate([by_group[g] for g in picked])
        draws.append(statistic(values[idx]))
    return np.asarray(draws)


def wilson_upper(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    den = 1 + z*z/n
    return float((p + z*z/(2*n) + z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / den)


def matched_random(quality, coverage, specialist_probs, seed=SEED, simulations=2000):
    rng = np.random.default_rng(seed)
    gains, hsrs = [], []
    n = len(quality[ANCHOR])
    for _ in range(simulations):
        switch = rng.random(n) < coverage
        specialist = rng.choice(SPECIALISTS, n, p=specialist_probs)
        realized = np.asarray([quality[str(m)][i] - quality[ANCHOR][i] for i, m in enumerate(specialist)])
        gains.append(float(np.mean(np.where(switch, realized, 0.0))))
        hsrs.append(float(np.mean(realized[switch] < -0.05)) if np.any(switch) else 0.0)
    return {
        "simulations": simulations,
        "matched_coverage": coverage,
        "mean_gain": float(np.mean(gains)),
        "gain_95_interval": [float(x) for x in np.percentile(gains, [2.5, 97.5])],
        "mean_harmful_switch_rate": float(np.mean(hsrs)),
        "hsr_95_interval": [float(x) for x in np.percentile(hsrs, [2.5, 97.5])],
    }


def power_analysis(realized, switched, harmful, groups):
    rng = np.random.default_rng(SEED + 41)
    unique = np.unique(groups)
    by_group = {g: np.flatnonzero(groups == g) for g in unique}
    result = {}
    for target_n in N_CANDIDATES:
        pass_gain = pass_cov = pass_hsr = joint = 0
        for _ in range(POWER_SIMS):
            idx = []
            while len(idx) < target_n:
                g = rng.choice(unique)
                idx.extend(by_group[g].tolist())
            idx = np.asarray(idx[:target_n])
            vals = realized[idx]
            cov = float(np.mean(switched[idx]))
            k = int(np.sum(harmful[idx] & switched[idx])); ns = int(np.sum(switched[idx]))
            # Cluster-resampling SE approximation, using the A0 empirical group law.
            sample_groups = groups[idx]
            group_means = np.asarray([np.mean(vals[sample_groups == g]) for g in np.unique(sample_groups)])
            lower = float(np.mean(vals) - 1.96 * np.std(group_means, ddof=1) / math.sqrt(len(group_means))) if len(group_means) > 1 else -math.inf
            a = lower > 0; b = cov >= 0.10; c = (wilson_upper(k, ns) or 1.0) <= 0.15
            pass_gain += a; pass_cov += b; pass_hsr += c; joint += a and b and c
        result[str(target_n)] = {
            "p_gain_ci_lower_gt_zero": pass_gain / POWER_SIMS,
            "p_coverage_ge_0_10": pass_cov / POWER_SIMS,
            "p_hsr_ucb_le_0_15": pass_hsr / POWER_SIMS,
            "p_all_formal_gates": joint / POWER_SIMS,
        }
    eligible = [n for n in N_CANDIDATES if result[str(n)]["p_gain_ci_lower_gt_zero"] >= 0.8]
    return {
        "status": "RETROSPECTIVE_PLANNING_ONLY",
        "simulation_replicates": POWER_SIMS,
        "candidate_n": list(N_CANDIDATES),
        "results": result,
        "recommended_n_quality_power_only": min(eligible) if eligible else None,
        "warning": "Empirical A0 resampling informs design but is not confirmatory; formal joint safety power may require more than 200 tasks.",
    }


def main():
    OUT.mkdir(exist_ok=True)
    tasks = rows(TASKS); task_ids = [t["task_id"] for t in tasks]
    task_by_id = {t["task_id"]: t for t in tasks}
    gold = {r["task_id"]: set(r["dataset_page_evidence_ids"]) for r in rows(GOLD)}
    response_rows = rows(RESPONSES)
    by_key = {(r["task_id"], r["model"], int(r["repeat"])): r for r in response_rows}
    expected = {(tid, m, r) for tid in task_ids for m in MODELS for r in REPEATS}
    if set(by_key) != expected:
        raise RuntimeError(f"frozen response matrix mismatch: missing={len(expected-set(by_key))}, extra={len(set(by_key)-expected)}")

    quality = {m: np.zeros(len(tasks)) for m in MODELS}
    repeat_quality = {m: np.zeros((len(tasks), len(REPEATS))) for m in MODELS}
    costs = {m: np.zeros(len(tasks)) for m in MODELS}
    latency = {m: np.zeros(len(tasks)) for m in MODELS}
    event_latest = {(r["task_id"], r["model"], int(r["repeat"])): r for r in rows(EVENTS)}
    for i, tid in enumerate(task_ids):
        for m in MODELS:
            for r in REPEATS:
                row = by_key[(tid, m, r)]
                pred = set(row.get("predicted_evidence_ids", [])) if row.get("format_valid") else set()
                repeat_quality[m][i, r] = prf(pred, gold[tid])
                costs[m][i] += float(row.get("cost_usd") or 0) / len(REPEATS)
                latency[m][i] += float(event_latest[(tid, m, r)].get("latency_ms") or 0) / len(REPEATS)
            quality[m][i] = np.mean(repeat_quality[m][i])

    document_cache = {}
    feature_dicts = []
    for task in tasks:
        path = ROOT / task["document_path"]
        document_cache.setdefault(path, path.read_text(encoding="utf-8"))
        feature_dicts.append(feature_row(task, document_cache[path]))
    feature_names = list(feature_dicts[0])
    X = np.asarray([[row[name] for name in feature_names] for row in feature_dicts], dtype=float)
    groups = np.asarray([task_by_id[tid]["company"] for tid in task_ids], dtype=object)
    advantages = {m: quality[m] - quality[ANCHOR] for m in SPECIALISTS}
    opportunity_by_model = {
        m: (np.all(repeat_quality[m] - repeat_quality[ANCHOR] > 0, axis=1) & (advantages[m] >= 0.05))
        for m in SPECIALISTS
    }
    opportunity = np.logical_or.reduce(list(opportunity_by_model.values()))

    outer = GroupKFold(5)
    oof_pred = {m: np.full((4, len(tasks)), np.nan) for m in SPECIALISTS}
    chosen = np.empty(len(tasks), dtype=object)
    chosen_lcb = np.full(len(tasks), np.nan)
    fold_records = []
    for fold, (train, test) in enumerate(outer.split(X, advantages[SPECIALISTS[0]], groups)):
        candidates = []
        for config_name, factory in CONFIGS:
            inner = inner_predictions(factory, X[train], {m: advantages[m][train] for m in SPECIALISTS}, groups[train])
            stacked = {m: np.tile(inner[m], (4, 1)) for m in SPECIALISTS}
            # Inner OOF point predictions have no ensemble dispersion. Apply a
            # training-only one-sided residual penalty as the LCB calibration.
            residual_penalty = {
                m: {q: float(np.quantile(inner[m] - advantages[m][train], 1-q)) for q in QUANTILES}
                for m in SPECIALISTS
            }
            for q in QUANTILES:
                lower = np.column_stack([inner[m] - residual_penalty[m][q] for m in SPECIALISTS])
                best = np.argmax(lower, axis=1); base_choice = np.asarray([SPECIALISTS[j] for j in best], dtype=object)
                for tau in TAUS:
                    inner_choice = np.where(lower[np.arange(len(train)), best] > tau, base_choice, ANCHOR)
                    ev, _, sw, harm = evaluate_policy(inner_choice, {m: quality[m][train] for m in MODELS}, opportunity[train])
                    hsr = ev["harmful_switch_rate"] if ev["harmful_switch_rate"] is not None else 1.0
                    feasible = ev["coverage"] >= 0.10 and hsr <= 0.30
                    candidates.append((feasible, ev["selective_gain"], -hsr, config_name, factory, q, tau, residual_penalty))
        selected = max(candidates, key=lambda x: (x[0], x[1], x[2], x[3], -x[5], -x[6]))
        _, inner_gain, _, config_name, factory, q, tau, residual_penalty = selected
        ensemble = {m: fit_ensemble(factory, X[train], advantages[m][train], groups[train], X[test]) for m in SPECIALISTS}
        for m in SPECIALISTS:
            oof_pred[m][:, test] = ensemble[m]
        lower = np.column_stack([np.mean(ensemble[m], axis=0) - residual_penalty[m][q] for m in SPECIALISTS])
        best = np.argmax(lower, axis=1); fold_choice = np.asarray([SPECIALISTS[j] for j in best], dtype=object)
        chosen[test] = np.where(lower[np.arange(len(test)), best] > tau, fold_choice, ANCHOR)
        chosen_lcb[test] = lower[np.arange(len(test)), best]
        fold_records.append({
            "outer_fold": fold, "train_n": len(train), "test_n": len(test),
            "train_groups": len(set(groups[train])), "test_groups": len(set(groups[test])),
            "selected_model": config_name, "lcb_quantile": q, "tau": tau,
            "inner_selective_gain": inner_gain,
        })

    point_pred = {m: np.mean(oof_pred[m], axis=0) for m in SPECIALISTS}
    predicted_best = np.max(np.column_stack([point_pred[m] for m in SPECIALISTS]), axis=1)
    result, realized, switched, harmful = evaluate_policy(chosen, quality, opportunity, chosen_lcb)
    gain_boot = grouped_bootstrap(realized, groups)
    result["grouped_bootstrap_95_ci"] = [float(x) for x in np.percentile(gain_boot, [2.5, 97.5])]
    result["harmful_switch_95_ucb_wilson"] = wilson_upper(int(np.sum(harmful & switched)), int(np.sum(switched)))
    result["opportunity_auprc"] = float(average_precision_score(opportunity, predicted_best))
    all_true_adv = np.max(np.column_stack([advantages[m] for m in SPECIALISTS]), axis=1)
    rho = spearmanr(predicted_best, all_true_adv)
    result["advantage_spearman"] = float(rho.statistic)
    result["advantage_mae"] = float(np.mean(np.abs(predicted_best - all_true_adv)))

    counts = Counter(chosen[switched])
    probs = np.asarray([counts[m] for m in SPECIALISTS], dtype=float)
    probs = probs / probs.sum() if probs.sum() else np.asarray([0.5, 0.5])
    random_result = matched_random(quality, result["coverage"], probs)
    result["matched_random"] = random_result
    result["harmful_switch_improves_over_random"] = (
        result["harmful_switch_rate"] is not None and
        result["harmful_switch_rate"] < random_result["hsr_95_interval"][0]
    )
    result["harmful_switch_comparison_rule"] = "learned HSR < matched-random 95% simulation interval lower bound"
    result["predictability_above_no_information"] = (
        result["opportunity_auprc"] > result["opportunity_prevalence"] or result["advantage_spearman"] > 0
    )
    result["go_conditions"] = {
        "oof_selective_gain_gt_zero": result["selective_gain"] > 0,
        "coverage_ge_0_10": result["coverage"] >= 0.10,
        "harmful_switch_better_than_matched_random": result["harmful_switch_improves_over_random"],
        "predictability_above_no_information": result["predictability_above_no_information"],
    }
    result["decision"] = "GO_TO_POWER_DESIGN" if all(result["go_conditions"].values()) else "STOP_E2_2"

    selected_cost = np.asarray([costs[str(m)][i] for i, m in enumerate(chosen)])
    selected_latency = np.asarray([latency[str(m)][i] for i, m in enumerate(chosen)])
    delta_cost = selected_cost - costs[ANCHOR]
    delta_latency_sec = (selected_latency - latency[ANCHOR]) / 1000
    result["resources"] = {
        "mean_cost_delta_usd": float(np.mean(delta_cost)),
        "mean_latency_delta_seconds": float(np.mean(delta_latency_sec)),
        "utility_sensitivity": [
            {"lambda_cost_per_usd": lc, "lambda_latency_per_second": lt,
             "mean_utility_delta": float(np.mean(realized - lc*delta_cost - lt*delta_latency_sec))}
            for lc in (0.0, 1.0, 5.0) for lt in (0.0, 0.001, 0.005)
        ],
        "note": "No single utility scalar is selected because lambda_cost and lambda_latency were not prospectively frozen.",
    }
    result.update({
        "experiment": "E2.2-A0", "status": "RETROSPECTIVE_DEVELOPMENT",
        "confirmatory_claim_allowed": False, "new_api_calls": 0,
        "anchor": ANCHOR, "specialists": list(SPECIALISTS), "grouping_unit": "company",
        "tasks": len(tasks), "groups": len(set(groups)), "outer_folds": fold_records,
    })

    leakage_rows = []
    for name in feature_names:
        source = "frozen task manifest" if name.startswith(("query_", "candidate_", "question_type")) else "local source document or question"
        leakage_rows.append({"feature": name, "source": source, "availability_time": "before_candidate_llm_invocation", "uses_gold": False, "uses_candidate_output": False, "allowed": True})
    leakage = {
        "experiment": "E2.2-A0", "status": "PASS", "grouping_key": "company",
        "features": leakage_rows,
        "explicitly_forbidden": ["gold evidence span/distance", "model answer", "model confidence", "model correctness", "winner", "judge score", "post-action state"],
        "gold_used_only_for_outcome": True, "candidate_outputs_used_only_for_outcome": True,
    }
    protocol = {
        "experiment": "E2.2-A0", "version": "1.0", "status": "RETROSPECTIVE_DEVELOPMENT",
        "created_at": datetime.now(timezone.utc).isoformat(), "new_provider_calls_permitted": False,
        "source_experiment_status": "CONFIRMATORY_FAIL", "source_data": str(TASKS.relative_to(ROOT)),
        "anchor": ANCHOR, "specialists": list(SPECIALISTS),
        "target": "mean three-repeat strict N1 Evidence-F1 advantage relative to deepseek",
        "evaluation": "5-fold outer GroupKFold by company; all selection in 4-fold inner GroupKFold",
        "policy": "switch to specialist with maximal training-calibrated lower advantage estimate iff it exceeds inner-selected tau; otherwise anchor",
        "models": [name for name, _ in CONFIGS], "lcb_quantiles": list(QUANTILES), "tau_candidates": list(TAUS),
        "go_rule": list(result["go_conditions"]), "confirmatory_claim_allowed": False,
        "utility": "sensitivity grid only because resource tradeoff weights were not prospectively frozen",
    }
    power = power_analysis(realized, switched, harmful, groups) if result["decision"] == "GO_TO_POWER_DESIGN" else {
        "status": "NOT_RUN_STOP_E2_2", "reason": "A0 GO conditions were not all satisfied", "candidate_n": list(N_CANDIDATES)
    }

    write_json(OUT / "E2_2_A0_PROTOCOL.json", protocol)
    write_json(OUT / "E2_2_A0_FEATURE_LEAKAGE_AUDIT.json", leakage)
    write_json(OUT / "E2_2_A0_RESULTS.json", result)
    write_json(OUT / "E2_2_A0_POWER_ANALYSIS.json", power)
    summary = f"""# E2.2-A0 Expert Summary

Status: **{result['status']}**  
Decision: **{result['decision']}**  
New provider/API calls: **0**

E2.1-A remains a confirmatory failure. This analysis is retrospective development only.

## Leakage-controlled OOF result

- Anchor: `{ANCHOR}`
- Grouping: company ({len(set(groups))} groups; 5 outer folds)
- Selective gain: {result['selective_gain']:.4f}
- Grouped bootstrap 95% CI: [{result['grouped_bootstrap_95_ci'][0]:.4f}, {result['grouped_bootstrap_95_ci'][1]:.4f}]
- Coverage: {result['coverage']:.3f} ({result['switch_count']} switches)
- Harmful-switch rate: {result['harmful_switch_rate']}
- Harmful-switch 95% Wilson UCB: {result['harmful_switch_95_ucb_wilson']}
- Opportunity prevalence: {result['opportunity_prevalence']:.3f}
- Opportunity AUPRC: {result['opportunity_auprc']:.3f}
- Advantage Spearman: {result['advantage_spearman']:.3f}
- Oracle-gap recovery: {result['oracle_gap_recovery']}
- Matched-random mean gain: {random_result['mean_gain']:.4f}
- Mean cost delta: ${result['resources']['mean_cost_delta_usd']:.6f} per task
- Mean latency delta: {result['resources']['mean_latency_delta_seconds']:.3f}s per task

## Interpretation

The frozen A0 GO rule was applied once to fully out-of-fold predictions. A GO result only authorizes prospective design; it is not confirmatory evidence. A STOP result ends E2.2 without retrospective threshold rescue.
"""
    (OUT / "E2_2_A0_EXPERT_SUMMARY.md").write_text(summary, encoding="utf-8")
    print(json.dumps({"decision": result["decision"], "selective_gain": result["selective_gain"], "coverage": result["coverage"], "hsr": result["harmful_switch_rate"], "auprc": result["opportunity_auprc"]}, indent=2))


if __name__ == "__main__":
    main()
