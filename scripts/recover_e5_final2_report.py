#!/usr/bin/env python3
"""Recover E5 report after JSON serialization failed; never retrains policies."""

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from kqapro_e4_generate import file_sha256, read_json, write_json
from train_e5_multitask_router import evaluate_frozen
from train_safe_graphrouter import build_matrices, load_routing
from train_safe_graphrouter_cv import enhanced_features, mean_std


def main():
    output_dir = PROJECT_ROOT / "run_logs/kqapro/e5"
    final2_dir = PROJECT_ROOT / "data/kqapro/e5_final2"
    artifact = joblib.load(output_dir / "multitask_ensemble.joblib")
    frozen = read_json(output_dir / "frozen_policy.json")
    seal_path = final2_dir / "final2_seal.json"
    seal = read_json(seal_path)
    if seal.get("metrics_read"):
        raise RuntimeError("final2 is already marked evaluated")
    if file_sha256(final2_dir / "routing_final2.jsonl") != seal["routing_sha256"]:
        raise RuntimeError("final2 routing hash mismatch")
    if file_sha256(final2_dir / "query_final2.jsonl") != seal["query_sha256"]:
        raise RuntimeError("final2 query hash mismatch")

    model_names = artifact["model_names"]
    sizes = artifact["sizes"]
    strong_idx = artifact["strong_idx"]
    frame = load_routing(final2_dir / "routing_final2.jsonl")
    embeddings = torch.load(
        final2_dir / "query_embeddings_longformer.pt", map_location="cpu"
    )
    queries, raw, correct, performance, _ = build_matrices(
        frame, embeddings, model_names
    )
    features = enhanced_features(queries, raw)
    training = {
        "models": artifact["models"],
        "beta": artifact["beta"],
        "margin": artifact["margin"],
    }
    per_seed, combined = evaluate_frozen(
        training,
        features,
        correct,
        performance,
        sizes,
        strong_idx,
        model_names,
        artifact["seeds"],
    )
    baseline = float(correct[:, strong_idx].mean())
    mean_accuracy = float(
        np.mean([item["answer_accuracy"] for item in per_seed])
    )
    summary = {
        "experiment_id": "kqapro_e5_final2",
        "sealed_hash_verified": True,
        "final2_evaluation_computation_attempts": 2,
        "recovery_note": (
            "The first computation completed but JSON writing failed on numpy.bool_. "
            "This recovery loaded only the already-frozen model artifact; no model "
            "or policy parameter was retrained or changed."
        ),
        "final2_queries": len(queries),
        "always_strong_accuracy": baseline,
        "oracle_accuracy": float(correct.max(axis=1).mean()),
        "beta": artifact["beta"],
        "margin": artifact["margin"],
        "threshold_source": frozen["threshold_source"],
        "per_seed": per_seed,
        "combined": combined,
        "per_seed_accuracy": mean_std(
            [item["answer_accuracy"] for item in per_seed]
        ),
        "pre_registered_goals": {
            "three_seed_mean_gt_strong": bool(mean_accuracy > baseline),
            "every_seed_ge_strong": bool(
                all(item["answer_accuracy"] >= baseline for item in per_seed)
            ),
            "combined_avg_size_lt_3b": bool(combined["avg_size_b"] < 3.0),
            "combined_rescues_gt_harms": bool(
                combined["successful_rescues"] > combined["harmful_downgrades"]
            ),
            "threshold_from_oof_only": True,
            "final2_policy_frozen_before_first_read": True,
        },
    }
    write_json(output_dir / "final2_summary.json", summary)
    seal["metrics_read"] = True
    seal["evaluation_output"] = "run_logs/kqapro/e5/final2_summary.json"
    seal["evaluation_computation_attempts"] = 2
    seal["recovery_note"] = summary["recovery_note"]
    write_json(seal_path, seal)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
