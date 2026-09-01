#!/usr/bin/env python3
"""Analyze base multi-judge calibration without creating formal labels."""
import json
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import cohen_kappa_score

DATA = Path("/root/phase_c9_0")
EVENTS = DATA / "C9_2_MULTI_JUDGE_CALIBRATION_BASE_EVENTS.jsonl"
OUT = DATA / "C9_2_MULTI_JUDGE_CALIBRATION_BASE_ANALYSIS.json"
JUDGES = ("doubao", "qwen-max", "glm-4-flash")

rows = [json.loads(x) for x in EVENTS.read_text().splitlines() if x.strip()]
latest = {(row["group_id"], row["judge_model"]): row for row in rows}
groups = sorted({row["group_id"] for row in rows})
parse = {judge: sum(bool(latest.get((group, judge), {}).get("success")) for group in groups) / 15 for judge in JUDGES}
pairwise = {}
agreement_passes = []
for first, second in combinations(JUDGES, 2):
    a, b = [], []
    for group in groups:
        left, right = latest.get((group, first)), latest.get((group, second))
        if not left or not right or not left["success"] or not right["success"]:
            continue
        shared = sorted(set(left["scores_by_model"]) & set(right["scores_by_model"]))
        a.extend(left["scores_by_model"][model] for model in shared)
        b.extend(right["scores_by_model"][model] for model in shared)
    aa, bb = np.asarray(a), np.asarray(b)
    rho = spearmanr(aa, bb).statistic if len(aa) else np.nan
    metrics = {
        "shared_scores": len(aa),
        "exact_agreement": float(np.mean(aa == bb)) if len(aa) else None,
        "within_one_agreement": float(np.mean(np.abs(aa - bb) <= 1)) if len(aa) else None,
        "mean_absolute_disagreement": float(np.mean(np.abs(aa - bb))) if len(aa) else None,
        "quadratic_weighted_kappa": float(cohen_kappa_score(aa, bb, weights="quadratic")) if len(aa) else None,
        "spearman": float(rho) if np.isfinite(rho) else None,
    }
    metrics["gate_pass"] = bool(len(aa) and metrics["within_one_agreement"] >= .80 and metrics["mean_absolute_disagreement"] <= .75)
    agreement_passes.append(metrics["gate_pass"])
    pairwise[f"{first}__{second}"] = metrics
parse_pass = {judge: value >= .95 for judge, value in parse.items()}
report = {
    "status": "PASS_ADVANCE_TO_STABILITY_CALIBRATION" if all(parse_pass.values()) and all(agreement_passes) else "FAIL_STOP_BEFORE_FORMAL_LABELS",
    "groups_expected": 15,
    "groups_observed": len(groups),
    "parse_success": parse,
    "parse_gate_pass": parse_pass,
    "pairwise": pairwise,
    "formal_labels_created": 0,
}
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
