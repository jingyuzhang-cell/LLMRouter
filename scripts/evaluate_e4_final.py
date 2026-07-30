#!/usr/bin/env python3
"""Evaluate all frozen E4 policies on the sealed final split exactly once."""

import argparse
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

from llmrouter.models.graphrouter import GraphRouter
from kqapro_e4_generate import file_sha256, read_json, write_json
from train_safe_graphrouter import (
    build_matrices,
    load_routing,
    parse_size,
    policy_metrics,
    rescue_metrics,
    select_models,
)
from train_safe_graphrouter_cv import (
    enhanced_features,
    ensemble_probabilities,
    mean_std,
)


def graphrouter_predictions(router, frame):
    queries = frame["query"].drop_duplicates().tolist()
    embedding_ids = [
        int(frame[frame["query"] == query]["embedding_id"].iloc[0])
        for query in queries
    ]
    raw = np.asarray(
        [router.query_embedding_data[index].cpu().numpy() for index in embedding_ids]
    )
    test_features = router.query_scaler.transform(raw)
    num_test = len(test_features)
    num_queries = router.num_queries_train + num_test
    all_performance = np.concatenate(
        [router.performance_list, np.zeros(num_test * router.num_llms)]
    )
    origins = [
        query for query in range(num_queries) for _ in range(router.num_llms)
    ]
    destinations = list(range(router.num_llms)) * num_queries
    num_edges = num_queries * router.num_llms
    train_mask = torch.zeros(num_edges)
    train_end = router.num_queries_train * router.num_llms
    train_mask[:train_end] = 1
    test_mask = torch.zeros(num_edges)
    test_mask[train_end:] = 1
    data = router.form_data.formulation(
        np.vstack([router.query_embedding_list, test_features]),
        router.llm_embedding,
        origins,
        destinations,
        all_performance,
        np.zeros((num_edges, 1)),
        test_mask,
        train_mask,
        torch.zeros(num_edges),
        test_mask,
    )
    return router.gnn_predictor.predict(data).cpu().numpy()


def detailed_metrics(predictions, correct, performance, latency, sizes,
                     model_names, strong_idx, experiment_id):
    metrics = policy_metrics(
        predictions, correct, performance, latency, sizes
    )
    rows = np.arange(len(predictions))
    rescued = (
        (predictions != strong_idx)
        & (correct[rows, strong_idx] == 0)
        & (correct[rows, predictions] == 1)
    )
    harmed = (
        (predictions != strong_idx)
        & (correct[rows, strong_idx] == 1)
        & (correct[rows, predictions] == 0)
    )
    metrics.update(
        {
            "experiment_id": experiment_id,
            "test_queries": len(predictions),
            "always_strong_accuracy": float(correct[:, strong_idx].mean()),
            "oracle_answer_accuracy": float(correct.max(axis=1).mean()),
            "successful_rescues": int(rescued.sum()),
            "harmful_downgrades": int(harmed.sum()),
            "predicted_models": {
                model_names[index]: int((predictions == index).sum())
                for index in range(len(model_names))
            },
        }
    )
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/kqapro/e4")
    parser.add_argument(
        "--graph-config",
        default="configs/model_config_test/graphrouter_kqapro_e4.yaml",
    )
    parser.add_argument(
        "--graph-checkpoint",
        type=Path,
        default=PROJECT_ROOT / "saved_models/graphrouter/kqapro_e4_e0_seed42.pt",
    )
    parser.add_argument(
        "--ensemble-dir",
        type=Path,
        default=PROJECT_ROOT / "run_logs/kqapro/e4/e3_dev",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "run_logs/kqapro/e4/final_summary.json",
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 43, 44])
    args = parser.parse_args()

    seal_path = args.data_dir / "final_seal.json"
    seal = read_json(seal_path)
    if seal.get("final_metrics_read"):
        raise RuntimeError("Final metrics have already been read; refusing a second evaluation")
    actual_routing_hash = file_sha256(args.data_dir / "routing_final.jsonl")
    actual_query_hash = file_sha256(args.data_dir / "query_final.jsonl")
    if actual_routing_hash != seal["routing_final_sha256"]:
        raise RuntimeError("Sealed routing_final.jsonl hash mismatch")
    if actual_query_hash != seal["query_final_sha256"]:
        raise RuntimeError("Sealed query_final.jsonl hash mismatch")

    # Load sealed final outcomes once, after all policy artifacts already exist.
    frame = load_routing(args.data_dir / "routing_final.jsonl")
    embeddings = torch.load(
        args.data_dir / "query_embeddings_longformer.pt", map_location="cpu"
    )
    llm_data = read_json(args.data_dir / "llm_candidates.json")
    model_names = list(llm_data)
    sizes = np.asarray([parse_size(llm_data[name]["size"]) for name in model_names])
    strong_idx = int(sizes.argmax())
    small_indices = [index for index in range(len(model_names)) if index != strong_idx]
    queries, raw, correct, performance, latency = build_matrices(
        frame, embeddings, model_names
    )

    graphrouter = GraphRouter(args.graph_config)
    graphrouter.gnn_predictor.model.load_state_dict(
        torch.load(args.graph_checkpoint, map_location="cpu")
    )
    graph_predictions = graphrouter_predictions(graphrouter, frame)
    graph_result = detailed_metrics(
        graph_predictions,
        correct,
        performance,
        latency,
        sizes,
        model_names,
        strong_idx,
        "kqapro_e4_graphrouter_e0_seed42",
    )

    features = enhanced_features(queries, raw)
    ensemble_results = []
    for seed in args.seeds:
        artifact_path = args.ensemble_dir / f"seed{seed}/safe_gate_ensemble.joblib"
        if not artifact_path.exists():
            raise FileNotFoundError(f"Frozen ensemble missing: {artifact_path}")
        artifact = joblib.load(artifact_path)
        probabilities = ensemble_probabilities(artifact["fold_models"], features)
        predictions = select_models(
            probabilities,
            artifact["threshold"],
            artifact["strong_idx"],
            artifact["small_indices"],
        )
        result = detailed_metrics(
            predictions,
            correct,
            performance,
            latency,
            sizes,
            model_names,
            strong_idx,
            f"kqapro_e4_safe_gate_seed{seed}",
        )
        result.update(
            {
                "seed": seed,
                "threshold": artifact["threshold"],
                "threshold_source": "training_oof_only",
                "rescue_classifier": rescue_metrics(
                    probabilities,
                    artifact["threshold"],
                    correct,
                    strong_idx,
                    small_indices,
                ),
            }
        )
        ensemble_results.append(result)

    summary = {
        "experiment_id": "kqapro_e4_final",
        "sealed_hash_verified": True,
        "final_evaluated_once": True,
        "final_query_count": len(queries),
        "graphrouter_e0": graph_result,
        "safe_gate": {
            "answer_accuracy": mean_std(
                [result["answer_accuracy"] for result in ensemble_results]
            ),
            "performance_score": mean_std(
                [result["performance_score"] for result in ensemble_results]
            ),
            "avg_size_b": mean_std(
                [result["avg_size_b"] for result in ensemble_results]
            ),
            "successful_rescues": mean_std(
                [result["successful_rescues"] for result in ensemble_results]
            ),
            "harmful_downgrades": mean_std(
                [result["harmful_downgrades"] for result in ensemble_results]
            ),
            "per_seed": ensemble_results,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, summary)
    seal["final_metrics_read"] = True
    seal["evaluation_output"] = str(args.output.relative_to(PROJECT_ROOT))
    seal["evaluated_policy_ids"] = [
        graph_result["experiment_id"],
        *[result["experiment_id"] for result in ensemble_results],
    ]
    write_json(seal_path, seal)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
