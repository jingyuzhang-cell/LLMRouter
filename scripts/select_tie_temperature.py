"""Select tie-aware temperature on validation metrics, then evaluate only the winner on test."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from evaluate_mlprouter_soft_seeds import evaluate
from llmrouter.utils import load_model

TEMPERATURES = {"003": 0.03, "005": 0.05, "010": 0.10, "020": 0.20}
SEEDS = (42, 123, 2026)
OUTPUT = Path("run_logs/mlprouter_tie_temperature_search.json")


def checkpoint_path(code, seed):
    return Path(f"llmrouter/saved_models/mlprouter/mlprouter_tie_t{code}_s{seed}.pkl")


def main():
    validation = {}
    for code, temperature in TEMPERATURES.items():
        runs = []
        for seed in SEEDS:
            checkpoint = load_model(str(checkpoint_path(code, seed)))
            metrics = checkpoint["best_validation_metrics"]
            runs.append({"seed": seed, "best_epoch": checkpoint["best_epoch"], **metrics})
        monitors = [run["optimal_set_accuracy"] - run["mean_regret"] for run in runs]
        validation[code] = {
            "temperature": temperature,
            "mean_monitor": float(np.mean(monitors)),
            "std_monitor": float(np.std(monitors)),
            "runs": runs,
        }
    selected_code = max(validation, key=lambda code: validation[code]["mean_monitor"])

    test_frame = pd.read_json(
        "data/example_data/routing_data/grouped/default_routing_test_data.jsonl", lines=True
    )
    embeddings = torch.load(
        "data/example_data/routing_data/query_embeddings_longformer.pt",
        map_location="cpu", weights_only=False,
    )
    test_runs = [
        evaluate(checkpoint_path(selected_code, seed), test_frame, embeddings, 0.0)
        for seed in SEEDS
    ]
    aggregate = {
        key: {"mean": float(np.mean([run[key] for run in test_runs])), "std": float(np.std([run[key] for run in test_runs]))}
        for key in ("optimal_set_accuracy", "mean_regret", "mean_selected_performance", "macro_f1")
    }
    all_pass = all(
        run["optimal_set_accuracy"] >= 0.85 and run["mean_regret"] <= 0.12
        for run in test_runs
    )
    report = {
        "selection_split": "validation",
        "validation_search": validation,
        "selected_temperature": TEMPERATURES[selected_code],
        "selected_code": selected_code,
        "test_runs": test_runs,
        "test_aggregate": aggregate,
        "all_seeds_pass": all_pass,
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
