"""Select MLP hyperparameters on validation data and evaluate only the winner."""

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from evaluate_mlprouter_soft_seeds import evaluate
from evaluate_mlprouter_ensemble import metrics as ensemble_metrics
from evaluate_mlprouter_ensemble import probabilities
from llmrouter.utils import load_model


MODEL_DIR = Path("llmrouter/saved_models/mlprouter")
SEEDS = (42, 123, 2026)
SHORTLIST = ("r5_b0_g3", "r10_b0_g3", "r10_b02_g3")


def validation_metrics(path):
    with path.open("rb") as stream:
        checkpoint = pickle.load(stream)
    metrics = checkpoint["best_validation_metrics"]
    return {
        "optimal_set_accuracy": metrics["optimal_set_accuracy"],
        "mean_regret": metrics["mean_regret"],
        "monitor": metrics["optimal_set_accuracy"] - metrics["mean_regret"],
    }


def main():
    initial = []
    for path in sorted(MODEL_DIR.glob("mlprouter_hparam_*_s42.pkl")):
        initial.append({"checkpoint": str(path), **validation_metrics(path)})
    initial.sort(key=lambda row: row["monitor"], reverse=True)

    candidates = []
    for combo in SHORTLIST:
        runs = []
        for seed in SEEDS:
            path = MODEL_DIR / f"mlprouter_hparam_{combo}_s{seed}.pkl"
            runs.append({"seed": seed, "checkpoint": str(path), **validation_metrics(path)})
        aggregate = {
            key: {"mean": float(np.mean([run[key] for run in runs])),
                  "std": float(np.std([run[key] for run in runs]))}
            for key in ("optimal_set_accuracy", "mean_regret", "monitor")
        }
        candidates.append({"combination": combo, "runs": runs, "aggregate": aggregate})
    candidates.sort(key=lambda row: row["aggregate"]["monitor"]["mean"], reverse=True)

    winner = candidates[0]
    frame = pd.read_json(
        "data/example_data/routing_data/grouped/default_routing_test_data.jsonl", lines=True
    )
    embeddings = torch.load(
        "data/example_data/routing_data/query_embeddings_longformer.pt",
        map_location="cpu", weights_only=False,
    )
    test_runs = [
        evaluate(Path(run["checkpoint"]), frame, embeddings, 0.0)
        for run in winner["runs"]
    ]
    winner_checkpoints = [load_model(run["checkpoint"]) for run in winner["runs"]]
    outputs = [probabilities(checkpoint, frame, embeddings) for checkpoint in winner_checkpoints]
    ensemble = ensemble_metrics(np.mean([output[0] for output in outputs], axis=0), outputs[0][1])
    keys = ("optimal_set_accuracy", "mean_regret", "mean_selected_performance", "macro_f1")
    test_aggregate = {
        key: {"mean": float(np.mean([run[key] for run in test_runs])),
              "std": float(np.std([run[key] for run in test_runs]))}
        for key in keys
    }
    ensemble_passes = (
        ensemble["optimal_set_accuracy"] >= 0.85 and ensemble["mean_regret"] <= 0.12
    )
    report = {
        "selection_policy": "validation monitor = optimal_set_accuracy - mean_regret",
        "initial_seed42_ranking": initial,
        "shortlist_validation": candidates,
        "winner": winner["combination"],
        "test_runs": test_runs,
        "test_aggregate": test_aggregate,
        "test_probability_ensemble": ensemble,
        "quality_gate": {"optimal_set_accuracy": 0.85, "mean_regret": 0.12},
        "ensemble_passes": ensemble_passes,
        "proceed_to_cost_search": ensemble_passes,
    }
    output = Path("run_logs/mlprouter_hparam_search.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
