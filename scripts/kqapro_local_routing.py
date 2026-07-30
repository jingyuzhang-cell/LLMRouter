#!/usr/bin/env python3
"""Build LLMRouter training data from KQA Pro using local Hugging Face models."""

from __future__ import annotations

import argparse
import gc
import json
import re
import time
from pathlib import Path

import torch
import yaml
from transformers import AutoModelForCausalLM, AutoTokenizer
from llmrouter.utils.embeddings import get_longformer_embedding


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "data/kqapro/KQAPro_Baselines/dataset"
DEFAULT_OUTPUT = PROJECT_ROOT / "data/kqapro/router_data"
DEFAULT_EMBED_MODEL = PROJECT_ROOT / "pretrained/bart-base"

MODELS = [
    ("qwen2.5-0.5b-instruct", "Qwen/Qwen2.5-0.5B-Instruct", 0.5),
    ("qwen2.5-1.5b-instruct", "Qwen/Qwen2.5-1.5B-Instruct", 1.5),
    ("qwen2.5-3b-instruct", "Qwen/Qwen2.5-3B-Instruct", 3.0),
]


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def sample_rows(rows: list[dict], count: int, seed: int) -> list[dict]:
    generator = torch.Generator().manual_seed(seed)
    indices = torch.randperm(len(rows), generator=generator)[:count].tolist()
    return [rows[index] for index in indices]


def choice_label(sample: dict) -> str:
    answer = str(sample["answer"]).strip()
    for index, choice in enumerate(sample["choices"]):
        if str(choice).strip() == answer:
            return chr(65 + index)
    raise ValueError(f"Answer not found in choices: {answer!r}")


def prompt_for(sample: dict) -> str:
    choices = "\n".join(
        f"{chr(65 + index)}. {choice}" for index, choice in enumerate(sample["choices"])
    )
    return (
        "Answer this knowledge-base multiple-choice question. "
        "Return exactly one capital letter (A-J) and nothing else.\n\n"
        f"Question: {sample['question']}\nChoices:\n{choices}\nAnswer:"
    )


def parse_label(text: str, choice_count: int) -> str | None:
    match = re.search(r"(?<![A-Z])([A-J])(?![A-Z])", text.upper())
    if not match:
        return None
    label = match.group(1)
    return label if ord(label) - 65 < choice_count else None


def query_rows(samples: list[dict], split: str) -> list[dict]:
    rows = []
    for index, sample in enumerate(samples):
        labels = [chr(65 + i) for i in range(len(sample["choices"]))]
        rows.append(
            {
                "task_name": "kqapro",
                "query": sample["question"],
                "ground_truth": choice_label(sample),
                "metric": "em_mc",
                "choices": {"text": sample["choices"], "labels": labels},
                "task_id": f"kqapro-{split}-{index:05d}",
            }
        )
    return rows


def run_model(
    model_key: str,
    repo_id: str,
    size_b: float,
    samples: list[dict],
    split: str,
    batch_size: int,
    cost_weight: float,
) -> list[dict]:
    print(f"\nLoading {repo_id} for {split} ({len(samples)} samples)", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(repo_id)
    tokenizer.padding_side = "left"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    model = AutoModelForCausalLM.from_pretrained(
        repo_id,
        torch_dtype=torch.bfloat16,
        device_map="cuda",
        low_cpu_mem_usage=True,
    ).eval()

    output_rows = []
    for start in range(0, len(samples), batch_size):
        batch = samples[start : start + batch_size]
        prompts = [prompt_for(sample) for sample in batch]
        chats = [[{"role": "user", "content": prompt}] for prompt in prompts]
        texts = [
            tokenizer.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
            for chat in chats
        ]
        encoded = tokenizer(texts, padding=True, truncation=True, max_length=1024, return_tensors="pt")
        encoded = {key: value.to("cuda") for key, value in encoded.items()}
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                max_new_tokens=4,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
            )
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        prompt_width = encoded["input_ids"].shape[1]
        responses = tokenizer.batch_decode(generated[:, prompt_width:], skip_special_tokens=True)

        for offset, (sample, response) in enumerate(zip(batch, responses)):
            gold = choice_label(sample)
            predicted = parse_label(response, len(sample["choices"]))
            correct = float(predicted == gold)
            # Prefer the smallest correct model. Incorrect answers remain below all correct answers.
            performance = correct - cost_weight * (size_b / 3.0)
            output_rows.append(
                {
                    "task_name": "kqapro",
                    "query": sample["question"],
                    "ground_truth": gold,
                    "metric": "em_mc",
                    "choices": {
                        "text": sample["choices"],
                        "labels": [chr(65 + i) for i in range(len(sample["choices"]))],
                    },
                    "task_id": f"kqapro-{split}-{start + offset:05d}",
                    "model_name": model_key,
                    "response": response.strip(),
                    "predicted_label": predicted,
                    "correct": correct,
                    "performance": performance,
                    "cost_proxy": size_b,
                    "response_time": elapsed / len(batch),
                    "input_tokens": int(encoded["attention_mask"][offset].sum().item()),
                    "output_tokens": int((generated[offset, prompt_width:] != tokenizer.pad_token_id).sum().item()),
                    "embedding_id": None,
                }
            )
        print(f"  {min(start + batch_size, len(samples))}/{len(samples)}", flush=True)

    del model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    return output_rows

def build_embeddings(all_queries: list[dict], model_path: Path, batch_size: int) -> dict[int, torch.Tensor]:
    print(f"\nBuilding Longformer embeddings for {len(all_queries)} queries", flush=True)
    embeddings: dict[int, torch.Tensor] = {}
    for start in range(0, len(all_queries), batch_size):
        batch = all_queries[start : start + batch_size]
        pooled = get_longformer_embedding([row["query"] for row in batch])
        for offset, vector in enumerate(pooled):
            embeddings[start + offset] = vector
    gc.collect()
    torch.cuda.empty_cache()
    return embeddings


def attach_embedding_ids(rows: list[dict], query_to_id: dict[str, int]) -> None:
    for row in rows:
        row["embedding_id"] = query_to_id[row["query"]]


def write_configs(output_dir: Path) -> None:
    relative = output_dir.relative_to(PROJECT_ROOT).as_posix()
    llms = {
        key: {
            "size": f"{size_b:g}B",
            "feature": f"Local Qwen2.5 instruct model ({size_b:g}B parameters)",
            "input_price": 0.0,
            "output_price": 0.0,
            "model": repo_id,
            "service": "local-huggingface",
            "api_endpoint": "local://huggingface",
        }
        for key, repo_id, size_b in MODELS
    }
    (output_dir / "llm_candidates.json").write_text(
        json.dumps(llms, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    config = {
        "data_path": {
            "query_data_train": f"{relative}/query_train.jsonl",
            "query_data_test": f"{relative}/query_test.jsonl",
            "query_embedding_data": f"{relative}/query_embeddings_longformer.pt",
            "routing_data_train": f"{relative}/routing_train.jsonl",
            "routing_data_test": f"{relative}/routing_test.jsonl",
            "llm_data": f"{relative}/llm_candidates.json",
        },
        "model_path": {
            "ini_model_path": "",
            "save_model_path": "saved_models/mlprouter/kqapro_mlprouter.pkl",
            "load_model_path": "saved_models/mlprouter/kqapro_mlprouter.pkl",
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
    config_path = PROJECT_ROOT / "configs/model_config_train/mlprouter_kqapro.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-size", type=int, default=30)
    parser.add_argument("--test-size", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--embedding-batch-size", type=int, default=32)
    parser.add_argument("--cost-weight", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    train_samples = sample_rows(read_json(args.dataset_dir / "train.json"), args.train_size, args.seed)
    test_samples = sample_rows(read_json(args.dataset_dir / "val.json"), args.test_size, args.seed + 1)
    train_queries = query_rows(train_samples, "train")
    test_queries = query_rows(test_samples, "test")
    write_jsonl(args.output_dir / "query_train.jsonl", train_queries)
    write_jsonl(args.output_dir / "query_test.jsonl", test_queries)

    train_routing: list[dict] = []
    test_routing: list[dict] = []
    for model_key, repo_id, size_b in MODELS:
        train_routing.extend(
            run_model(model_key, repo_id, size_b, train_samples, "train", args.batch_size, args.cost_weight)
        )
        test_routing.extend(
            run_model(model_key, repo_id, size_b, test_samples, "test", args.batch_size, args.cost_weight)
        )

    all_queries = train_queries + test_queries
    embeddings = build_embeddings(all_queries, DEFAULT_EMBED_MODEL, args.embedding_batch_size)
    query_to_id = {row["query"]: index for index, row in enumerate(all_queries)}
    attach_embedding_ids(train_routing, query_to_id)
    attach_embedding_ids(test_routing, query_to_id)
    torch.save(embeddings, args.output_dir / "query_embeddings_longformer.pt")
    write_jsonl(args.output_dir / "routing_train.jsonl", train_routing)
    write_jsonl(args.output_dir / "routing_test.jsonl", test_routing)
    write_configs(args.output_dir)

    winners: dict[str, int] = {}
    for query in train_queries:
        candidates = [row for row in train_routing if row["query"] == query["query"]]
        winner = max(candidates, key=lambda row: row["performance"])["model_name"]
        winners[winner] = winners.get(winner, 0) + 1
    print(f"\nWinner distribution: {winners}")
    print(f"Data written to {args.output_dir}")


if __name__ == "__main__":
    main()
