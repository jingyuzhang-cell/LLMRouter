#!/usr/bin/env python3
"""
Generate KQA routing training data using DeepSeek API.
This script annotates KQA validation set with DeepSeek responses
for training the router model.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
import hashlib

import requests


# ============================================================
# Configuration
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
KQA_VAL_FILE = PROJECT_ROOT / "data/kqapro/KQAPro_Baselines/dataset/val.json"
OUTPUT_DIR = PROJECT_ROOT / "data/kqapro/router_data"
OUTPUT_FILE = OUTPUT_DIR / "routing_train_deepseek.jsonl"

# DeepSeek API Configuration
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"  # or "deepseek-coder" for code tasks

# Pricing (per 1M tokens, in RMB)
DEEPSEEK_INPUT_PRICE = 0.14
DEEPSEEK_OUTPUT_PRICE = 0.28

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2

# Batch size for saving
SAVE_BATCH_SIZE = 100


# ============================================================
# Load Environment
# ============================================================

def load_env() -> dict[str, str]:
    """Load environment variables from .env file."""
    env_vars = {}
    if not ENV_FILE.exists():
        raise FileNotFoundError(f".env file not found: {ENV_FILE}")

    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip()

    if "DEEPSEEK_API_KEY" not in env_vars:
        raise ValueError("DEEPSEEK_API_KEY not found in .env file")

    return env_vars


# ============================================================
# DeepSeek API Calls
# ============================================================

def call_deepseek(
    api_key: str,
    question: str,
    choices: list[str],
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """
    Call DeepSeek API for KQA question answering.

    Args:
        api_key: DeepSeek API key
        question: The question text
        choices: List of choice options
        max_retries: Maximum number of retries

    Returns:
        Dictionary with response, tokens, time, etc.
    """
    # Build choices as formatted text
    choices_text = "\n".join([f"{chr(65+i)}. {choice}" for i, choice in enumerate(choices)])

    prompt = f"""Answer the following multiple-choice question by selecting the correct option (A, B, C, D, E, F, G, H, I, or J).

Question: {question}

{choices_text}

Answer:"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that answers multiple-choice questions accurately."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,  # Deterministic for consistent routing labels
        "max_tokens": 10,  # Only need the letter
    }

    for attempt in range(max_retries):
        try:
            start_time = time.time()
            response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
            response_time = time.time() - start_time

            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                usage = data.get("usage", {})

                return {
                    "response": content,
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "response_time": response_time,
                    "success": True,
                }
            elif response.status_code == 429:
                # Rate limited, wait and retry
                wait_time = RETRY_DELAY * (2 ** attempt)
                print(f"Rate limited. Waiting {wait_time}s before retry {attempt + 1}/{max_retries}...")
                time.sleep(wait_time)
            else:
                print(f"API error: {response.status_code} - {response.text}")

        except requests.exceptions.Timeout:
            print(f"Timeout. Retrying {attempt + 1}/{max_retries}...")
        except Exception as e:
            print(f"Error: {e}")

        if attempt < max_retries - 1:
            time.sleep(RETRY_DELAY * (2 ** attempt))

    # All retries failed
    return {
        "response": "unknown",
        "input_tokens": 0,
        "output_tokens": 0,
        "response_time": 0,
        "success": False,
    }


# ============================================================
# Label Processing
# ============================================================

def extract_choice_label(response: str, choices: list[str]) -> str:
    """
    Extract the choice label (A-J) from the model response.
    Fallback to matching content if letter not found.
    """
    response = response.upper().strip()

    # Try to extract single letter
    for char in response:
        if char in "ABCDEFGHIJ":
            return char

    # Fallback: try to match against choices
    for i, choice in enumerate(choices):
        if choice.lower() in response.lower():
            return chr(65 + i)

    # Default to A if no match
    return "A"


def compute_cost_proxy(input_tokens: int, output_tokens: int) -> float:
    """Compute cost proxy based on tokens."""
    # Normalize to similar scale as existing data (Qwen 0.5B = 0.5)
    # DeepSeek is more expensive but cheaper than GPT
    base_cost = (input_tokens * DEEPSEEK_INPUT_PRICE + output_tokens * DEEPSEEK_OUTPUT_PRICE) / 1_000_000
    # Scale to match existing cost_proxy range (0.5 - 10.0)
    return min(max(base_cost * 10, 0.5), 10.0)


# ============================================================
# Main Generation Loop
# ============================================================

def generate_routing_data(env: dict[str, str], limit: int | None = None) -> None:
    """Generate routing training data for KQA validation set."""
    api_key = env["DEEPSEEK_API_KEY"]

    # Load KQA validation data
    print(f"Loading KQA validation set from {KQA_VAL_FILE}...")
    with open(KQA_VAL_FILE) as f:
        kqa_data = json.load(f)

    total = len(kqa_data)
    if limit:
        kqa_data = kqa_data[:limit]
        print(f"Limited to {limit} examples (total available: {total})")

    print(f"Loaded {len(kqa_data)} examples")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Check if file exists and count existing lines
    existing_count = 0
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            existing_count = sum(1 for _ in f)
        print(f"Found existing file with {existing_count} lines")

    # Generate routing data
    results = []
    correct_count = 0

    for i, item in enumerate(kqa_data[existing_count:], start=existing_count):
        task_id = f"kqapro-train-{i:05d}"
        question = item["question"]
        choices = item["choices"]
        answer = item["answer"]

        # Print progress
        if i % 10 == 0:
            print(f"[{i}/{len(kqa_data)}] Processing: {question[:60]}...")

        # Call DeepSeek
        result = call_deepseek(api_key, question, choices)

        if not result["success"]:
            print(f"  [!] API call failed for {task_id}, skipping...")
            continue

        # Extract predicted label
        predicted_label = extract_choice_label(result["response"], choices)

        # Check correctness
        is_correct = (predicted_label == chr(65 + choices.index(answer))) if answer in choices else 0.0
        if is_correct:
            correct_count += 1

        # Compute performance (simple accuracy)
        performance = 1.0 if is_correct else 0.0

        # Compute cost proxy
        cost_proxy = compute_cost_proxy(result["input_tokens"], result["output_tokens"])

        # Create routing data entry
        routing_entry = {
            "task_name": "kqapro",
            "query": question,
            "ground_truth": answer,
            "metric": "em_mc",
            "choices": {
                "text": choices,
                "labels": [chr(65 + i) for i in range(len(choices))],
            },
            "task_id": task_id,
            "model_name": "deepseek-chat",
            "response": result["response"],
            "predicted_label": predicted_label,
            "correct": float(is_correct),
            "performance": performance,
            "cost_proxy": cost_proxy,
            "response_time": result["response_time"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "embedding_id": 0,  # Will be updated later
        }

        results.append(routing_entry)

        # Save in batches
        if len(results) >= SAVE_BATCH_SIZE:
            with open(OUTPUT_FILE, "a") as f:
                for r in results:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"  [+] Saved {len(results)} entries")
            results = []

    # Save remaining results
    if results:
        with open(OUTPUT_FILE, "a") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[+] Saved final {len(results)} entries")

    # Print summary
    total_processed = existing_count + len(kqa_data)
    accuracy = correct_count / total_processed if total_processed > 0 else 0

    print("\n" + "=" * 50)
    print("Generation Complete!")
    print("=" * 50)
    print(f"Total examples: {total_processed}")
    print(f"Correct: {correct_count}")
    print(f"Accuracy: {accuracy:.2%}")
    print(f"Output: {OUTPUT_FILE}")
    print("=" * 50)


# ============================================================
# CLI Entry Point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate KQA routing training data using DeepSeek API"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of examples to process (for testing)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: process only 10 examples",
    )
    args = parser.parse_args()

    if args.test:
        args.limit = 10
        print("TEST MODE: Processing only 10 examples\n")

    try:
        env = load_env()
        generate_routing_data(env, limit=args.limit)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()