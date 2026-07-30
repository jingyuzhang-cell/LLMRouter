#!/usr/bin/env python3
"""Generate a new sealed KQAPro final3 split, excluding all prior eval sets."""

import argparse
import json
import sys
from pathlib import Path

import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from kqapro_e4_generate import (
    DEFAULT_DATASET,
    MODELS,
    file_sha256,
    query_row,
    read_json,
    read_jsonl,
    run_resumable_model,
    sampled_indices,
    value_sha256,
    write_json,
    write_jsonl,
)
from llmrouter.utils.embeddings import get_longformer_embedding


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--e4-manifest",
        type=Path,
        default=PROJECT_ROOT / "data/kqapro/e4/partition_manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data/kqapro/e6_final3",
    )
    parser.add_argument("--size", type=int, default=1900)
    parser.add_argument("--seed", type=int, default=46)
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "partition_manifest.json"
    val_source = read_json(args.dataset_dir / "val.json")
    e4_manifest = read_json(args.e4_manifest)
    excluded = set(e4_manifest["dev_indices"]) | set(e4_manifest["final_indices"])

    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if manifest["size"] != args.size or manifest["seed"] != args.seed:
            raise ValueError("Existing final3 manifest settings differ")
        final3_indices = manifest["final3_indices"]
    else:
        final3_indices = sampled_indices(
            len(val_source), args.size, args.seed, excluded=excluded
        )
        if excluded.intersection(final3_indices):
            raise AssertionError("final3 overlaps a previous evaluation split")
        manifest = {
            "version": 1,
            "size": args.size,
            "seed": args.seed,
            "excluded_dev_count": len(e4_manifest["dev_indices"]),
            "excluded_final_count": len(e4_manifest["final_indices"]),
            "overlap_with_prior_eval": 0,
            "final3_indices": final3_indices,
            "final3_indices_sha256": value_sha256(final3_indices),
            "val_source_sha256": e4_manifest["val_source_sha256"],
        }
        write_json(manifest_path, manifest)

    samples = [(index, val_source[index]) for index in final3_indices]
    # Reuse the E4 resumable engine. This isolated output directory contains
    # only the new final3 split; its internal partial name is "final".
    partitions = {"train": [], "final": samples}
    for model_key, repo_id, size_b in MODELS:
        run_resumable_model(
            model_key,
            repo_id,
            size_b,
            partitions,
            args.output_dir,
            args.batch_size,
            0.05,
        )

    queries = [query_row(sample, "final3", index) for index, sample in samples]
    write_jsonl(args.output_dir / "query_final3.jsonl", queries)
    embeddings_path = args.output_dir / "query_embeddings_longformer.pt"
    if not embeddings_path.exists():
        embeddings = {}
        for start in range(0, len(queries), 32):
            batch = queries[start : start + 32]
            vectors = get_longformer_embedding([row["query"] for row in batch])
            for offset, vector in enumerate(vectors):
                embeddings[offset + start] = vector
            print(f"embeddings: {min(start + 32, len(queries))}/{len(queries)}")
        torch.save(embeddings, embeddings_path)
    else:
        embeddings = torch.load(embeddings_path, map_location="cpu")
        if len(embeddings) != len(queries):
            raise ValueError("Unexpected final3 embedding count")

    query_to_id = {row["query"]: index for index, row in enumerate(queries)}
    routing = []
    for model_key, _, _ in MODELS:
        rows = read_jsonl(args.output_dir / "partial/final" / f"{model_key}.jsonl")
        if len(rows) != len(queries):
            raise ValueError(f"Incomplete final3 rows for {model_key}: {len(rows)}")
        for row in rows:
            row["embedding_id"] = query_to_id[row["query"]]
            row["task_id"] = row["task_id"].replace("-final-", "-final3-")
            routing.append(row)
    write_jsonl(args.output_dir / "routing_final3.jsonl", routing)

    e4_llms = read_json(PROJECT_ROOT / "data/kqapro/e4/llm_candidates.json")
    write_json(args.output_dir / "llm_candidates.json", e4_llms)
    write_json(
        args.output_dir / "final3_seal.json",
        {
            "routing_sha256": file_sha256(args.output_dir / "routing_final3.jsonl"),
            "query_sha256": file_sha256(args.output_dir / "query_final3.jsonl"),
            "metrics_read": False,
            "note": "Evaluate only after every E6 policy is frozen.",
        },
    )
    print(f"E6 final3 generated and sealed: {args.output_dir}")


if __name__ == "__main__":
    main()
