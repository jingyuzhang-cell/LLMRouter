#!/usr/bin/env python3
"""
Convert old routing data format to new format for consistency.

Old format:
- "parsed_answer" -> "predicted_label"
- "model" -> "model_name"
- Missing fields: performance, cost_proxy, response_time, input_tokens, output_tokens, embedding_id

New format:
- "predicted_label" (required)
- "model_name" (required)
- "performance", "cost_proxy", "response_time", "input_tokens", "output_tokens", "embedding_id" (optional)
"""

import argparse
import json
import sys
from pathlib import Path


def convert_entry(entry: dict) -> dict | None:
    """Convert a single entry from old format to new format."""
    try:
        # Map old fields to new format
        converted = {
            "task_name": entry.get("task_name", "kqapro"),
            "query": entry.get("query"),
            "ground_truth": entry.get("ground_truth"),
            "metric": entry.get("metric", "em_mc"),
            "choices": entry.get("choices"),
            "task_id": entry.get("task_id"),
            "response": entry.get("response", ""),
            # Convert old field names
            "predicted_label": entry.get("parsed_answer") or entry.get("predicted_label"),
            "model_name": entry.get("model") or entry.get("model_name"),
            # Use existing fields if present, otherwise defaults
            "correct": float(entry.get("correct", 0)),
            "performance": entry.get("performance", 1.0 if entry.get("correct") else 0.0),
            "cost_proxy": entry.get("cost_proxy", 0.5),
            "response_time": entry.get("response_time", 0.0),
            "input_tokens": entry.get("input_tokens", 0),
            "output_tokens": entry.get("output_tokens", 0),
            "embedding_id": entry.get("embedding_id", 0),
        }

        # Validate required fields
        if not converted["predicted_label"] or converted["predicted_label"] not in "ABCDEFGHIJ":
            return None

        if not converted["model_name"]:
            return None

        return converted

    except (KeyError, TypeError) as e:
        return None


def main():
    parser = argparse.ArgumentParser(description="Convert routing data format")
    parser.add_argument("files", nargs="+", help="JSONL files to convert")
    parser.add_argument("--apply", action="store_true", help="Apply conversion and overwrite files")
    args = parser.parse_args()

    for file_path in args.files:
        path = Path(file_path)
        if not path.exists():
            print(f"Warning: {file_path} does not exist, skipping", file=sys.stderr)
            continue

        print(f"\nProcessing {file_path}...")

        # Read and convert
        converted_lines = []
        original_lines = 0
        successful = 0
        skipped = 0

        with open(path) as f:
            for line in f:
                original_lines += 1
                try:
                    entry = json.loads(line)
                    converted = convert_entry(entry)
                    if converted:
                        converted_lines.append(json.dumps(converted, ensure_ascii=False))
                        successful += 1
                    else:
                        skipped += 1
                except json.JSONDecodeError:
                    skipped += 1

        print(f"  Original lines: {original_lines}")
        print(f"  Successfully converted: {successful}")
        print(f"  Skipped (invalid): {skipped}")

        if args.apply:
            # Backup and write
            backup_path = path.with_suffix(path.suffix + ".bak-format-convert")
            path.rename(backup_path)
            with open(path, "w") as f:
                f.write("\n".join(converted_lines))
            print(f"  ✅ Converted and saved (backup: {backup_path.name})")
        else:
            print(f"  [Preview mode - use --apply to save changes]")


if __name__ == "__main__":
    main()