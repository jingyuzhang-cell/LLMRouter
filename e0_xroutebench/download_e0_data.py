#!/usr/bin/env python3
"""Download only the immutable xRouteBench assets required by E0."""

from pathlib import Path

from datasets import load_dataset


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    generic = load_dataset("ulab-ai/xRouteBench", "llmrouter_generic")
    candidates = load_dataset("ulab-ai/xRouteBench", "llm_candidates")
    generic["train"].to_parquet(DATA / "llmrouter_generic_train.parquet")
    generic["test"].to_parquet(DATA / "llmrouter_generic_test.parquet")
    candidates["train"].to_parquet(DATA / "llm_candidates.parquet")
    print(generic)
    print(candidates)


if __name__ == "__main__":
    main()
