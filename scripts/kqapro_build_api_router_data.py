#!/usr/bin/env python3
"""Merge KQA Pro API evaluations into trainable LLMRouter data."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import torch
import yaml



ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from llmrouter.utils.embeddings import get_longformer_embedding
DEFAULT_INPUT = ROOT / "data/kqapro/api_routing"
DEFAULT_OUTPUT = ROOT / "data/kqapro/api_router_data"


def read_valid(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not path.exists():
        raise FileNotFoundError(path)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") == "ok" and row.get("predicted_label") is not None:
            rows[row["task_id"]] = row
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def query_row(row: dict, split: str, position: int) -> dict:
    return {
        "task_name": "kqapro",
        "query": row["question"],
        "ground_truth": row["ground_truth"],
        "metric": "em_mc",
        "choices": {
            "text": row["choices"],
            "labels": [chr(65 + i) for i in range(len(row["choices"]))],
        },
        "task_id": f"kqapro-api-{split}-{position:05d}",
    }


def build_embeddings(queries: list[dict], batch_size: int) -> dict[int, torch.Tensor]:
    result: dict[int, torch.Tensor] = {}
    for start in range(0, len(queries), batch_size):
        batch = queries[start : start + batch_size]
        vectors = get_longformer_embedding([row["query"] for row in batch])
        for offset, vector in enumerate(vectors):
            result[start + offset] = vector.cpu()
        print(f"embeddings {min(start + batch_size, len(queries))}/{len(queries)}", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--providers", nargs="+", default=["deepseek", "qwen", "zhipu"])
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--embedding-batch-size", type=int, default=32)
    parser.add_argument("--latency-tiebreak", type=float, default=1e-4)
    args = parser.parse_args()

    provider_rows = {
        provider: read_valid(args.input_dir / f"{provider}.jsonl")
        for provider in args.providers
    }
    common = set.intersection(*(set(rows) for rows in provider_rows.values()))
    if len(common) < 2:
        raise RuntimeError(f"Need at least two common samples, found {len(common)}")
    task_ids = sorted(common)
    random.Random(args.seed).shuffle(task_ids)
    split_at = max(1, min(len(task_ids) - 1, round(len(task_ids) * args.train_ratio)))
    split_ids = {"train": task_ids[:split_at], "test": task_ids[split_at:]}

    queries: list[dict] = []
    routing_by_split: dict[str, list[dict]] = {"train": [], "test": []}
    for split in ("train", "test"):
        for position, source_id in enumerate(split_ids[split]):
            exemplar = provider_rows[args.providers[0]][source_id]
            query = query_row(exemplar, split, position)
            embedding_id = len(queries)
            queries.append(query)
            for provider in args.providers:
                source = provider_rows[provider][source_id]
                routing_by_split[split].append(
                    {
                        **query,
                        "source_task_id": source_id,
                        "model_name": provider,
                        "response": source.get("response", ""),
                        "predicted_label": source["predicted_label"],
                        "correct": float(source.get("correct", 0)),
                        "performance": float(source.get("correct", 0))
                        - args.latency_tiebreak * float(source.get("response_time", 0)),
                        "response_time": float(source.get("response_time", 0)),
                        "usage": source.get("usage", {}),
                        "embedding_id": embedding_id,
                    }
                )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    train_count = len(split_ids["train"])
    write_jsonl(args.output_dir / "query_train.jsonl", queries[:train_count])
    write_jsonl(args.output_dir / "query_test.jsonl", queries[train_count:])
    write_jsonl(args.output_dir / "routing_train.jsonl", routing_by_split["train"])
    write_jsonl(args.output_dir / "routing_test.jsonl", routing_by_split["test"])
    embeddings = build_embeddings(queries, args.embedding_batch_size)
    torch.save(embeddings, args.output_dir / "query_embeddings_longformer.pt")

    candidates = {
        provider: {
            "feature": f"KQA Pro API candidate: {provider}",
            "service": provider,
            "model": provider_rows[provider][task_ids[0]]["model_name"],
        }
        for provider in args.providers
    }
    (args.output_dir / "llm_candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    config = {
        "data_path": {
            "query_data_train": "data/kqapro/api_router_data/query_train.jsonl",
            "query_data_test": "data/kqapro/api_router_data/query_test.jsonl",
            "query_embedding_data": "data/kqapro/api_router_data/query_embeddings_longformer.pt",
            "routing_data_train": "data/kqapro/api_router_data/routing_train.jsonl",
            "routing_data_test": "data/kqapro/api_router_data/routing_test.jsonl",
            "llm_data": "data/kqapro/api_router_data/llm_candidates.json",
        },
        "model_path": {
            "ini_model_path": "",
            "save_model_path": "saved_models/mlprouter/kqapro_api_mlprouter.pkl",
            "load_model_path": "saved_models/mlprouter/kqapro_api_mlprouter.pkl",
        },
        "metric": {"weights": {"performance": 1, "cost": 0, "llm_judge": 0}},
        "hparam": {
            "hidden_layer_sizes": [128, 64],
            "activation": "relu",
            "lr": 0.001,
            "epochs": 100,
            "batch_size": 32,
            "alpha": 0.0001,
        },
    }
    config_path = ROOT / "configs/model_config_train/mlprouter_kqapro_api.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print(
        f"built {len(task_ids)} common samples: {train_count} train, "
        f"{len(task_ids) - train_count} test; providers={args.providers}"
    )


if __name__ == "__main__":
    main()
