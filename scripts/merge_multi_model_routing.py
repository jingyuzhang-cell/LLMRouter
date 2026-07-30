#!/usr/bin/env python3
"""
Merge routing data from multiple models into a single training file.
"""

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data/kqapro/router_data"


def merge_routing_data(models: list[str], output_file: str = "routing_all_models.jsonl"):
    """Merge routing data from multiple models."""
    output_path = OUTPUT_DIR / output_file

    total_entries = 0
    model_counts = {}

    with open(output_path, "w") as out_f:
        for model in models:
            input_file = OUTPUT_DIR / f"routing_train_{model}.jsonl"

            if not input_file.exists():
                print(f"Warning: {input_file} not found, skipping")
                continue

            count = 0
            with open(input_file) as in_f:
                for line in in_f:
                    line = line.strip()
                    if line:
                        out_f.write(line + "\n")
                        count += 1

            print(f"Merged {count} entries from {model}")
            model_counts[model] = count
            total_entries += count

    print(f"\nTotal entries written to {output_path}: {total_entries}")
    print("\nPer-model breakdown:")
    for model, count in model_counts.items():
        percentage = count / total_entries * 100 if total_entries > 0 else 0
        print(f"  {model:12s}: {count:5d} ({percentage:5.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Merge routing data from multiple models")
    parser.add_argument(
        "--models",
        type=str,
        nargs="+",
        default=["deepseek", "qwen", "gemini", "doubao", "zhipu"],
        help="Models to merge (default: all)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="routing_all_models.jsonl",
        help="Output file name (default: routing_all_models.jsonl)",
    )
    args = parser.parse_args()

    merge_routing_data(args.models, args.output)


if __name__ == "__main__":
    main()