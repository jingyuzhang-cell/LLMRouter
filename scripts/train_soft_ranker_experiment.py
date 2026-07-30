"""Train soft-label and model-feature ranking experiments offline."""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, f1_score

BASE = Path("data/example_data/routing_data/grouped")
EMBEDDINGS = Path("data/example_data/routing_data/query_embeddings_longformer.pt")
LLMS = Path("data/example_data/llm_candidates/default_llm.json")
OUTPUT = Path("run_logs/mlprouter_soft_ranker_experiment.json")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def size_billions(value):
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*B", str(value), re.I)
    return np.log1p(float(match.group(1))) if match else 0.0


def prepare_split(frame, embeddings, models, tasks):
    pivot = frame.pivot(index="query", columns="model_name", values="performance")
    pivot = pivot.reindex(columns=models)
    if pivot.isna().any().any():
        raise ValueError("Every query must have a performance value for every model")
    first = frame.drop_duplicates("query").set_index("query").loc[pivot.index]
    vectors = np.stack([embeddings[int(index)].numpy() for index in first["embedding_id"]])
    one_hot = np.zeros((len(first), len(tasks)), dtype=np.float32)
    task_index = {task: index for index, task in enumerate(tasks)}
    for row, task in enumerate(first["task_name"]):
        one_hot[row, task_index[task]] = 1.0
    features = np.concatenate([vectors, one_hot], axis=1).astype(np.float32)
    return features, pivot.to_numpy(dtype=np.float32), first["task_name"].tolist()


class SoftClassifier(nn.Module):
    def __init__(self, input_dim, outputs):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(input_dim, 128), nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(128, 64), nn.ReLU(), nn.Linear(64, outputs),
        )

    def forward(self, x):
        return self.network(x)


class PointwiseRanker(nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(input_dim, 128), nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(128, 32), nn.ReLU(), nn.Linear(32, 1),
        )

    def forward(self, x):
        return self.network(x).squeeze(-1)


def fit(model, train_x, train_y, val_x, val_y, loss_fn, epochs=100, patience=12):
    model = model.to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    train_x, train_y = train_x.to(DEVICE), train_y.to(DEVICE)
    val_x, val_y = val_x.to(DEVICE), val_y.to(DEVICE)
    best_loss, best_state, stale, best_epoch = float("inf"), None, 0, 0
    for epoch in range(1, epochs + 1):
        model.train()
        optimizer.zero_grad()
        loss = loss_fn(model(train_x), train_y)
        loss.backward()
        optimizer.step()
        model.eval()
        with torch.no_grad():
            val_loss = float(loss_fn(model(val_x), val_y))
        if val_loss < best_loss - 1e-5:
            best_loss = val_loss
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            best_epoch, stale = epoch, 0
        else:
            stale += 1
        if stale >= patience:
            break
    model.load_state_dict(best_state)
    return model, best_epoch, best_loss


def routing_metrics(score_predictions, true_scores, models):
    predicted = np.argmax(score_predictions, axis=1)
    arbitrary_truth = np.argmax(true_scores, axis=1)
    chosen = true_scores[np.arange(len(true_scores)), predicted]
    oracle = true_scores.max(axis=1)
    optimal = np.isclose(chosen, oracle, atol=1e-8)
    return {
        "hard_accuracy": float(accuracy_score(arbitrary_truth, predicted)),
        "hard_macro_f1": float(f1_score(arbitrary_truth, predicted, average="macro", zero_division=0)),
        "optimal_set_accuracy": float(optimal.mean()),
        "mean_selected_performance": float(chosen.mean()),
        "mean_oracle_performance": float(oracle.mean()),
        "mean_regret": float((oracle - chosen).mean()),
        "selection_counts": {models[i]: int((predicted == i).sum()) for i in range(len(models))},
    }


def main():
    frames = {s: pd.read_json(BASE / f"default_routing_{s}_data.jsonl", lines=True) for s in ("train", "validation", "test")}
    embeddings = torch.load(EMBEDDINGS, map_location="cpu", weights_only=False)
    llms = json.loads(LLMS.read_text(encoding="utf-8"))
    models = sorted(frames["train"]["model_name"].unique())
    tasks = sorted(frames["train"]["task_name"].unique())
    data = {s: prepare_split(frames[s], embeddings, models, tasks) for s in frames}

    tensors = {s: (torch.tensor(data[s][0]), torch.tensor(data[s][1])) for s in data}
    temperature = 0.10
    soft_targets = {s: torch.softmax(tensors[s][1] / temperature, dim=1) for s in tensors}
    soft_model, soft_epoch, soft_loss = fit(
        SoftClassifier(tensors["train"][0].shape[1], len(models)),
        tensors["train"][0], soft_targets["train"],
        tensors["validation"][0], soft_targets["validation"],
        lambda logits, targets: -(targets * torch.log_softmax(logits, dim=1)).sum(dim=1).mean(),
    )
    soft_model.eval()
    with torch.no_grad():
        soft_predictions = soft_model(tensors["test"][0].to(DEVICE)).cpu().numpy()

    model_features = []
    for name in models:
        info = llms.get(name, {})
        model_features.append([
            size_billions(info.get("size", name)),
            float(info.get("input_price", 0.0)),
            float(info.get("output_price", 0.0)),
        ])
    model_features = np.asarray(model_features, dtype=np.float32)
    means, stds = model_features.mean(0), model_features.std(0)
    model_features = (model_features - means) / np.where(stds == 0, 1, stds)

    def rank_data(split):
        query_x, scores, _ = data[split]
        repeated_q = np.repeat(query_x, len(models), axis=0)
        tiled_m = np.tile(model_features, (len(query_x), 1))
        return torch.tensor(np.concatenate([repeated_q, tiled_m], axis=1)), torch.tensor(scores.reshape(-1))

    rank = {s: rank_data(s) for s in data}
    ranker, rank_epoch, rank_loss = fit(
        PointwiseRanker(rank["train"][0].shape[1]),
        *rank["train"], *rank["validation"], nn.MSELoss(),
    )
    ranker.eval()
    with torch.no_grad():
        rank_predictions = ranker(rank["test"][0].to(DEVICE)).cpu().numpy().reshape(-1, len(models))

    report = {
        "device": DEVICE,
        "models": models,
        "soft_label_classifier": {
            "best_epoch": soft_epoch,
            "validation_loss": soft_loss,
            **routing_metrics(soft_predictions, data["test"][1], models),
        },
        "pointwise_ranker_with_task_model_features": {
            "best_epoch": rank_epoch,
            "validation_loss": rank_loss,
            **routing_metrics(rank_predictions, data["test"][1], models),
        },
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Report: {OUTPUT}")


if __name__ == "__main__":
    main()
