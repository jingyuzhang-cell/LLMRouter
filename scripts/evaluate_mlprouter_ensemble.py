"""Evaluate probability averaging across structured soft-label MLP checkpoints."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import f1_score

from llmrouter.models.mlprouter.router import MLPClassifierNN
from llmrouter.utils import load_model

CHECKPOINTS = [
    Path(f"llmrouter/saved_models/mlprouter/mlprouter_tie_t003_s{seed}.pkl")
    for seed in (42, 123, 2026)
]


def probabilities(checkpoint, frame, embeddings):
    models = checkpoint["model_names"]
    tasks = checkpoint["task_names"]
    pivot = frame.pivot(index="query", columns="model_name", values="performance").reindex(columns=models)
    metadata = frame.drop_duplicates("query").set_index("query").loc[pivot.index]
    vectors = torch.stack([embeddings[int(index)] for index in metadata["embedding_id"]]).float()
    vectors = (vectors - torch.tensor(checkpoint["embedding_mean"])) / torch.tensor(checkpoint["embedding_std"])
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
        values = torch.softmax(model(features), dim=1).numpy()
    return values, pivot.to_numpy(dtype=np.float32), models


def metrics(averaged, scores):
    predicted = averaged.argmax(axis=1)
    chosen = scores[np.arange(len(scores)), predicted]
    oracle = scores.max(axis=1)
    truth = scores.argmax(axis=1)
    return {
        "optimal_set_accuracy": float(np.isclose(chosen, oracle, atol=1e-8).mean()),
        "mean_regret": float((oracle - chosen).mean()),
        "mean_selected_performance": float(chosen.mean()),
        "macro_f1": float(f1_score(truth, predicted, average="macro", zero_division=0)),
    }


def main():
    embeddings = torch.load(
        "data/example_data/routing_data/query_embeddings_longformer.pt", map_location="cpu", weights_only=False
    )
    checkpoints = [load_model(str(path)) for path in CHECKPOINTS]
    report = {"checkpoints": [str(path) for path in CHECKPOINTS]}
    for split in ("validation", "test"):
        frame = pd.read_json(
            f"data/example_data/routing_data/grouped/default_routing_{split}_data.jsonl", lines=True
        )
        outputs = [probabilities(checkpoint, frame, embeddings) for checkpoint in checkpoints]
        averaged = np.mean([output[0] for output in outputs], axis=0)
        report[split] = metrics(averaged, outputs[0][1])
    report["passes_quality_gate"] = (
        report["test"]["optimal_set_accuracy"] >= 0.85
        and report["test"]["mean_regret"] <= 0.12
    )
    output = Path("run_logs/mlprouter_tie_ensemble.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
