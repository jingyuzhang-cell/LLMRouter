#!/usr/bin/env python3
"""Validate two independent human reviews and prepare adjudication; no model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import cohen_kappa_score

ROOT = Path("/root/phase_c9_0/human_judge_calibration")
ORIGINAL_A = ROOT / "C9_HUMAN_REVIEWER_A.jsonl"
ORIGINAL_B = ROOT / "C9_HUMAN_REVIEWER_B.jsonl"


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def index(rows, reviewer: str):
    result = {}
    for row in rows:
        group_id = row.get("group_id")
        if not group_id or group_id in result:
            raise ValueError(f"{reviewer}: missing or duplicate group_id {group_id!r}")
        confidence = row.get("reviewer_confidence")
        if confidence not in {"low", "medium", "high"}:
            raise ValueError(f"{reviewer}: {group_id} reviewer_confidence must be low/medium/high")
        candidates = {}
        for candidate in row.get("candidates", []):
            label, score, reason = candidate.get("label"), candidate.get("score"), candidate.get("reason")
            if label in candidates:
                raise ValueError(f"{reviewer}: duplicate label {group_id}:{label}")
            if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 4:
                raise ValueError(f"{reviewer}: score must be integer 0..4 at {group_id}:{label}")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"{reviewer}: non-empty reason required at {group_id}:{label}")
            candidates[label] = {"score": score, "reason": reason.strip()}
        result[group_id] = {"confidence": confidence, "candidates": candidates}
    return result


def frozen_shape(path: Path):
    return {row["group_id"]: tuple(sorted(candidate["label"] for candidate in row["candidates"])) for row in read_jsonl(path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewer-a", type=Path, default=ROOT / "C9_HUMAN_REVIEWER_A_SCORED.jsonl")
    parser.add_argument("--reviewer-b", type=Path, default=ROOT / "C9_HUMAN_REVIEWER_B_SCORED.jsonl")
    parser.add_argument("--out-dir", type=Path, default=ROOT)
    args = parser.parse_args()
    if not args.reviewer_a.exists() or not args.reviewer_b.exists():
        raise SystemExit("BLOCKED: both independent *_SCORED.jsonl files are required")

    expected_a, expected_b = frozen_shape(ORIGINAL_A), frozen_shape(ORIGINAL_B)
    if expected_a != expected_b:
        raise ValueError("frozen reviewer packet shapes differ")
    review_a, review_b = index(read_jsonl(args.reviewer_a), "reviewer_a"), index(read_jsonl(args.reviewer_b), "reviewer_b")
    shape_a = {g: tuple(sorted(x["candidates"])) for g, x in review_a.items()}
    shape_b = {g: tuple(sorted(x["candidates"])) for g, x in review_b.items()}
    if shape_a != expected_a or shape_b != expected_a:
        raise ValueError("scored packet group/label shape differs from frozen packet")

    scores_a, scores_b, adjudication, provisional = [], [], [], []
    for group_id in sorted(expected_a):
        for label in expected_a[group_id]:
            a, b = review_a[group_id]["candidates"][label], review_b[group_id]["candidates"][label]
            scores_a.append(a["score"]); scores_b.append(b["score"])
            difference = abs(a["score"] - b["score"])
            base = {"group_id": group_id, "label": label, "reviewer_a": a, "reviewer_b": b}
            if difference > 1:
                adjudication.append({**base, "adjudicated_score": None, "adjudicator_reason": ""})
            else:
                # Frozen conservative resolution: floor of the two-score mean.
                provisional.append({"group_id": group_id, "label": label, "human_gold_score": (a["score"] + b["score"]) // 2, "requires_adjudication": False})

    a = np.asarray(scores_a); b = np.asarray(scores_b); rho = spearmanr(a, b).statistic
    report = {
        "status": "HUMAN_REVIEW_COMPLETE_ADJUDICATION_REQUIRED" if adjudication else "HUMAN_REVIEW_COMPLETE_NO_ADJUDICATION_REQUIRED",
        "groups": len(expected_a),
        "candidate_answers": len(a),
        "exact_agreement": float(np.mean(a == b)),
        "within_one_agreement": float(np.mean(np.abs(a - b) <= 1)),
        "mean_absolute_disagreement": float(np.mean(np.abs(a - b))),
        "quadratic_weighted_kappa": float(cohen_kappa_score(a, b, weights="quadratic")),
        "spearman": float(rho) if np.isfinite(rho) else None,
        "adjudication_required": len(adjudication),
        "reviewer_a_sha256": hashlib.sha256(args.reviewer_a.read_bytes()).hexdigest(),
        "reviewer_b_sha256": hashlib.sha256(args.reviewer_b.read_bytes()).hexdigest(),
        "model_identity_accessed": False,
        "model_calls": 0,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "C9_HUMAN_INTER_RATER_RESULTS.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (args.out_dir / "C9_HUMAN_ADJUDICATION_REQUIRED.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in adjudication))
    (args.out_dir / "C9_HUMAN_PROVISIONAL_GOLD.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in provisional))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
