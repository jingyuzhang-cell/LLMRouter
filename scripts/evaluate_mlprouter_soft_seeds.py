"""Evaluate structured soft-label MLP checkpoints on the isolated test split."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import f1_score

from llmrouter.models.mlprouter.router import MLPClassifierNN
from llmrouter.utils import load_model


def evaluate(checkpoint_path, frame, embeddings, cost_lambda):
    checkpoint = load_model(str(checkpoint_path))
    models = checkpoint["model_names"]
    tasks = checkpoint["task_names"]
    pivot = frame.pivot(index="query", columns="model_name", values="performance").reindex(columns=models)
    metadata = frame.drop_duplicates("query").set_index("query").loc[pivot.index]
    vectors = torch.stack([embeddings[int(index)] for index in metadata["embedding_id"]]).float()
    mean = torch.tensor(checkpoint["embedding_mean"])
    std = torch.tensor(checkpoint["embedding_std"])
    vectors = (vectors - mean) / std
    task_features = torch.zeros((len(metadata), len(tasks)))
    task_index = {task: index for index, task in enumerate(tasks)}
    for row, task in enumerate(metadata["task_name"]):
        if task in task_index:
            task_features[row, task_index[task]] = 1
    features = torch.cat([vectors, task_features], dim=1)
    model = MLPClassifierNN(
        checkpoint["input_dim"], checkpoint["hidden_layer_sizes"], len(models), checkpoint["activation"]
    )
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    with torch.no_grad():
        probabilities = torch.softmax(model(features), dim=1).numpy()
    utilities = probabilities - cost_lambda * np.asarray(checkpoint["normalized_costs"])
    predicted = utilities.argmax(axis=1)
    scores = pivot.to_numpy(dtype=np.float32)
    chosen = scores[np.arange(len(scores)), predicted]
    oracle = scores.max(axis=1)
    arbitrary_truth = scores.argmax(axis=1)
    return {
        "seed": checkpoint["seed"],
        "checkpoint": str(checkpoint_path),
        "best_epoch": checkpoint["best_epoch"],
        "optimal_set_accuracy": float(np.isclose(chosen, oracle, atol=1e-8).mean()),
        "mean_regret": float((oracle - chosen).mean()),
        "mean_selected_performance": float(chosen.mean()),
        "macro_f1": float(f1_score(arbitrary_truth, predicted, average="macro", zero_division=0)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cost-lambda", type=float, default=0.0)
    parser.add_argument("--output", default="run_logs/mlprouter_soft_seed_summary.json")
    args = parser.parse_args()
    frame = pd.read_json(
        "data/example_data/routing_data/grouped/default_routing_test_data.jsonl", lines=True
    )
    embeddings = torch.load(
        "data/example_data/routing_data/query_embeddings_longformer.pt", map_location="cpu", weights_only=False
    )
    paths = [
        Path(f"llmrouter/saved_models/mlprouter/mlprouter_soft_seed{seed}.pkl")
        for seed in (42, 123, 2026)
    ]
    runs = [evaluate(path, frame, embeddings, args.cost_lambda) for path in paths]
    keys = ("optimal_set_accuracy", "mean_regret", "mean_selected_performance", "macro_f1")
    aggregate = {
        key: {"mean": float(np.mean([run[key] for run in runs])), "std": float(np.std([run[key] for run in runs]))}
        for key in keys
    }
    passed = all(
        run["optimal_set_accuracy"] >= 0.85 and run["mean_regret"] <= 0.12 for run in runs
    )
    report = {
        "cost_lambda": args.cost_lambda,
        "thresholds": {"optimal_set_accuracy": 0.85, "mean_regret": 0.12},
        "all_seeds_pass": passed,
        "runs": runs,
        "aggregate": aggregate,
    }
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
