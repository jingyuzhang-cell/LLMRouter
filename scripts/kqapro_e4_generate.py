#!/usr/bin/env python3
"""Generate the expanded KQAPro E4 routing dataset with resumable inference."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import re
import time
from pathlib import Path

import torch
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from transformers import AutoModelForCausalLM, AutoTokenizer

from llmrouter.utils.embeddings import get_longformer_embedding


DEFAULT_DATASET = PROJECT_ROOT / "data/kqapro/KQAPro_Baselines/dataset"
DEFAULT_DEV = PROJECT_ROOT / "data/kqapro/router_data"
DEFAULT_OUTPUT = PROJECT_ROOT / "data/kqapro/e4"

MODELS = [
    ("qwen2.5-0.5b-instruct", "Qwen/Qwen2.5-0.5B-Instruct", 0.5),
    ("qwen2.5-1.5b-instruct", "Qwen/Qwen2.5-1.5B-Instruct", 1.5),
    ("qwen2.5-3b-instruct", "Qwen/Qwen2.5-3B-Instruct", 3.0),
]


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def value_sha256(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sampled_indices(total: int, count: int, seed: int, excluded=None) -> list[int]:
    excluded = set(excluded or [])
    generator = torch.Generator().manual_seed(seed)
    permutation = torch.randperm(total, generator=generator).tolist()
    selected = [index for index in permutation if index not in excluded]
    if count > len(selected):
        raise ValueError(f"Requested {count} samples but only {len(selected)} are available")
    return selected[:count]


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


def query_row(sample: dict, split: str, source_index: int) -> dict:
    return {
        "task_name": "kqapro",
        "query": sample["question"],
        "ground_truth": choice_label(sample),
        "metric": "em_mc",
        "choices": {
            "text": sample["choices"],
            "labels": [chr(65 + index) for index in range(len(sample["choices"]))],
        },
        "task_id": f"kqapro-e4-{split}-{source_index:06d}",
        "source_index": source_index,
        "source_split": "train" if split == "train" else "val",
    }


def prepare_partitions(dataset_dir: Path, dev_dir: Path, output_dir: Path,
                       train_size: int, final_size: int, seed: int) -> dict:
    manifest_path = output_dir / "partition_manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        expected = {
            "train_size": train_size,
            "dev_size": 100,
            "final_size": final_size,
            "seed": seed,
        }
        actual = {key: manifest[key] for key in expected}
        if actual != expected:
            raise ValueError(
                f"Existing partition manifest does not match requested settings: {actual} != {expected}"
            )
        return manifest

    train_source = read_json(dataset_dir / "train.json")
    val_source = read_json(dataset_dir / "val.json")
    existing_dev = read_jsonl(dev_dir / "query_test.jsonl")
    val_lookup = {sample["question"]: index for index, sample in enumerate(val_source)}
    dev_indices = [val_lookup[row["query"]] for row in existing_dev]
    if len(dev_indices) != len(set(dev_indices)):
        raise ValueError("Existing dev set contains duplicate source questions")

    train_indices = sampled_indices(len(train_source), train_size, seed)
    final_indices = sampled_indices(
        len(val_source), final_size, seed + 2, excluded=dev_indices
    )
    if set(dev_indices).intersection(final_indices):
        raise AssertionError("dev/final overlap")

    manifest = {
        "version": 1,
        "train_size": train_size,
        "dev_size": len(dev_indices),
        "final_size": final_size,
        "seed": seed,
        "train_source": str((dataset_dir / "train.json").relative_to(PROJECT_ROOT)),
        "val_source": str((dataset_dir / "val.json").relative_to(PROJECT_ROOT)),
        "train_source_sha256": file_sha256(dataset_dir / "train.json"),
        "val_source_sha256": file_sha256(dataset_dir / "val.json"),
        "train_indices": train_indices,
        "dev_indices": dev_indices,
        "final_indices": final_indices,
        "train_indices_sha256": value_sha256(train_indices),
        "dev_indices_sha256": value_sha256(dev_indices),
        "final_indices_sha256": value_sha256(final_indices),
        "dev_final_overlap": 0,
    }
    write_json(manifest_path, manifest)
    return manifest


def load_partition_samples(dataset_dir: Path, manifest: dict) -> dict[str, list[tuple[int, dict]]]:
    train_source = read_json(dataset_dir / "train.json")
    val_source = read_json(dataset_dir / "val.json")
    return {
        "train": [(index, train_source[index]) for index in manifest["train_indices"]],
        "dev": [(index, val_source[index]) for index in manifest["dev_indices"]],
        "final": [(index, val_source[index]) for index in manifest["final_indices"]],
    }


def bootstrap_existing_dev(dev_dir: Path, output_dir: Path, model_key: str) -> None:
    destination = output_dir / "partial/dev" / f"{model_key}.jsonl"
    if destination.exists():
        return
    existing = read_jsonl(dev_dir / "routing_test.jsonl")
    rows = [row for row in existing if row["model_name"] == model_key]
    if len(rows) != 100:
        raise ValueError(f"Expected 100 existing dev rows for {model_key}, got {len(rows)}")
    write_jsonl(destination, rows)


def run_resumable_model(model_key: str, repo_id: str, size_b: float,
                        partitions: dict, output_dir: Path, batch_size: int,
                        cost_weight: float) -> None:
    pending_by_split = {}
    for split in ("train", "final"):
        path = output_dir / "partial" / split / f"{model_key}.jsonl"
        completed = {row["source_index"] for row in read_jsonl(path)}
        pending_by_split[split] = [
            item for item in partitions[split] if item[0] not in completed
        ]
        print(
            f"{model_key} {split}: completed={len(completed)} "
            f"pending={len(pending_by_split[split])}",
            flush=True,
        )
    if not any(pending_by_split.values()):
        return

    tokenizer = AutoTokenizer.from_pretrained(repo_id, local_files_only=True)
    tokenizer.padding_side = "left"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    model = AutoModelForCausalLM.from_pretrained(
        repo_id,
        torch_dtype=torch.bfloat16,
        device_map="cuda",
        low_cpu_mem_usage=True,
        local_files_only=True,
    ).eval()

    for split in ("train", "final"):
        pending = pending_by_split[split]
        path = output_dir / "partial" / split / f"{model_key}.jsonl"
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            samples = [sample for _, sample in batch]
            prompts = [prompt_for(sample) for sample in samples]
            texts = [
                tokenizer.apply_chat_template(
                    [{"role": "user", "content": prompt}],
                    tokenize=False,
                    add_generation_prompt=True,
                )
                for prompt in prompts
            ]
            encoded = tokenizer(
                texts, padding=True, truncation=True, max_length=1024, return_tensors="pt"
            )
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
            responses = tokenizer.batch_decode(
                generated[:, prompt_width:], skip_special_tokens=True
            )
            rows = []
            for offset, ((source_index, sample), response) in enumerate(zip(batch, responses)):
                gold = choice_label(sample)
                predicted = parse_label(response, len(sample["choices"]))
                correct = float(predicted == gold)
                rows.append(
                    {
                        **query_row(sample, split, source_index),
                        "model_name": model_key,
                        "response": response.strip(),
                        "predicted_label": predicted,
                        "correct": correct,
                        "performance": correct - cost_weight * (size_b / 3.0),
                        "cost_proxy": size_b,
                        "response_time": elapsed / len(batch),
                        "input_tokens": int(encoded["attention_mask"][offset].sum().item()),
                        "output_tokens": int(
                            (generated[offset, prompt_width:] != tokenizer.pad_token_id).sum().item()
                        ),
                        "embedding_id": None,
                    }
                )
            append_jsonl(path, rows)
            done = start + len(batch)
            if done % (batch_size * 10) == 0 or done == len(pending):
                print(f"  {model_key} {split}: {done}/{len(pending)} new", flush=True)

    del model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()


def finalize_dataset(partitions: dict, output_dir: Path) -> None:
    query_rows = {}
    ordered_queries = []
    for split in ("train", "dev", "final"):
        rows = [query_row(sample, split, index) for index, sample in partitions[split]]
        query_rows[split] = rows
        ordered_queries.extend(rows)
        write_jsonl(output_dir / f"query_{split}.jsonl", rows)

    embeddings_path = output_dir / "query_embeddings_longformer.pt"
    if embeddings_path.exists():
        embeddings = torch.load(embeddings_path, map_location="cpu")
        if len(embeddings) != len(ordered_queries):
            raise ValueError("Existing embedding file has an unexpected size")
    else:
        embeddings = {}
        for start in range(0, len(ordered_queries), 32):
            batch = ordered_queries[start : start + 32]
            vectors = get_longformer_embedding([row["query"] for row in batch])
            for offset, vector in enumerate(vectors):
                embeddings[start + offset] = vector
            print(f"embeddings: {min(start + 32, len(ordered_queries))}/{len(ordered_queries)}")
        torch.save(embeddings, embeddings_path)

    query_to_embedding = {
        row["query"]: index for index, row in enumerate(ordered_queries)
    }
    for split in ("train", "dev", "final"):
        combined = []
        for model_key, _, _ in MODELS:
            rows = read_jsonl(output_dir / "partial" / split / f"{model_key}.jsonl")
            if len(rows) != len(partitions[split]):
                raise ValueError(
                    f"Incomplete {split}/{model_key}: {len(rows)} != {len(partitions[split])}"
                )
            for row in rows:
                row["embedding_id"] = query_to_embedding[row["query"]]
                combined.append(row)
        write_jsonl(output_dir / f"routing_{split}.jsonl", combined)

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
    write_json(output_dir / "llm_candidates.json", llms)
    write_json(
        output_dir / "final_seal.json",
        {
            "routing_final_sha256": file_sha256(output_dir / "routing_final.jsonl"),
            "query_final_sha256": file_sha256(output_dir / "query_final.jsonl"),
            "final_metrics_read": False,
            "note": "Do not evaluate until every E4 policy is frozen.",
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--existing-dev-dir", type=Path, default=DEFAULT_DEV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-size", type=int, default=3000)
    parser.add_argument("--final-size", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--cost-weight", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = prepare_partitions(
        args.dataset_dir, args.existing_dev_dir, args.output_dir,
        args.train_size, args.final_size, args.seed
    )
    partitions = load_partition_samples(args.dataset_dir, manifest)
    for model_key, repo_id, size_b in MODELS:
        bootstrap_existing_dev(args.existing_dev_dir, args.output_dir, model_key)
        run_resumable_model(
            model_key, repo_id, size_b, partitions, args.output_dir,
            args.batch_size, args.cost_weight
        )
    finalize_dataset(partitions, args.output_dir)
    print(f"E4 generation completed: {args.output_dir}")


if __name__ == "__main__":
    main()
