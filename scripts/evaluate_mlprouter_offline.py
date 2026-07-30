"""Evaluate a trained MLP router without calling any model API."""

import argparse
import json
from pathlib import Path

import pandas as pd
import torch
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score

from llmrouter.models import MLPRouter


def best_routes(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"query", "performance", "model_name", "embedding_id"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Routing data is missing columns: {sorted(missing)}")
    return frame.loc[frame.groupby("query")["performance"].idxmax()].reset_index(drop=True)


def predict_split(router, model, frame, device):
    best = best_routes(frame)
    unknown = sorted(set(best["model_name"]) - set(router.model_to_idx))
    if unknown:
        raise ValueError(f"Test labels were not present in training data: {unknown}")

    embeddings = torch.stack(
        [router.query_embedding_data[int(index)] for index in best["embedding_id"]]
    ).float().to(device)
    truth = [router.model_to_idx[name] for name in best["model_name"]]

    with torch.no_grad():
        predicted = model.predict(embeddings).cpu().tolist()
    return best, truth, predicted


def split_metrics(truth, predicted, labels, names):
    recalls = recall_score(truth, predicted, labels=labels, average=None, zero_division=0)
    matrix = confusion_matrix(truth, predicted, labels=labels)
    return {
        "samples": len(truth),
        "accuracy": accuracy_score(truth, predicted),
        "macro_f1": f1_score(truth, predicted, labels=labels, average="macro", zero_division=0),
        "recall_by_model": {name: float(value) for name, value in zip(names, recalls)},
        "confusion_matrix": matrix.tolist(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/model_config_test/mlprouter.yaml")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--training-accuracy", type=float, default=0.9757)
    parser.add_argument("--output", default="run_logs/mlprouter_offline_eval.json")
    args = parser.parse_args()

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")

    router = MLPRouter(args.config)
    package_root = Path(__file__).resolve().parents[1] / "llmrouter"
    router.load_model_path = str(package_root / router.cfg["model_path"].get("load_model_path", router.cfg["model_path"].get("save_model_path")))
    model, model_type = router._load_mlp_model(device=args.device)
    if model_type != "pytorch":
        raise TypeError("This evaluator expects the PyTorch MLP state-dict format")

    labels = list(range(router.num_classes))
    names = [router.idx_to_model[index] for index in labels]
    report = {"model_path": router.load_model_path, "labels": names}

    for split, frame in (
        ("train", router.routing_data_train),
        ("test", router.routing_data_test),
    ):
        _, truth, predicted = predict_split(router, model, frame, args.device)
        report[split] = split_metrics(truth, predicted, labels, names)

    report["training_log_accuracy"] = args.training_accuracy
    report["generalization_gap"] = report["train"]["accuracy"] - report["test"]["accuracy"]
    report["logged_training_gap"] = args.training_accuracy - report["test"]["accuracy"]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Model: {report['model_path']}")
    print(f"Train Accuracy: {report['train']['accuracy']:.4f}")
    print(f"Test Accuracy:  {report['test']['accuracy']:.4f}")
    print(f"Test Macro-F1:  {report['test']['macro_f1']:.4f}")
    print(f"Generalization Gap: {report['generalization_gap']:.4f}")
    print("\nRecall by model:")
    for name, value in report["test"]["recall_by_model"].items():
        print(f"  {name}: {value:.4f}")

    print("\nConfusion matrix (rows=true, columns=predicted):")
    print(pd.DataFrame(report["test"]["confusion_matrix"], index=names, columns=names))
    print(f"\nJSON report: {output}")


if __name__ == "__main__":
    main()
