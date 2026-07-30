#!/usr/bin/env python3
"""
Generate KQA routing training data using multiple LLM providers.
This script annotates KQA validation set with multiple models for training router.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import hashlib
import random
import re

import requests


# ============================================================
# Configuration
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
NVIDIA_ENV_FILE = PROJECT_ROOT / ".nvidia_extra_key.env"
KQA_VAL_FILE = PROJECT_ROOT / "data/kqapro/KQAPro_Baselines/dataset/val.json"
OUTPUT_DIR = PROJECT_ROOT / "data/kqapro/router_data"

# Model configurations
MODELS = {
    "qwen-3b-local": {
        "name": "qwen-2.5-3b",
        "api_url": "http://localhost:8000/v1/chat/completions",
        "input_price": 0.0,  # Free local model
        "output_price": 0.0,
        "cost_proxy_scale": 1.5,  # Low cost proxy
    },
    "deepseek": {
        "name": "deepseek-chat",
        "api_url": "https://api.deepseek.com/v1/chat/completions",
        "input_price": 0.14,  # per 1M tokens (RMB)
        "output_price": 0.28,
        "cost_proxy_scale": 10.0,
    },
    "qwen": {
        "name": "qwen-plus",
        "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "input_price": 0.40,
        "output_price": 2.00,
        "cost_proxy_scale": 15.0,
    },
    "gemini": {
        "name": "gemini-3.5-flash",
        "data_name": "gemini-3.5-flash",
        "output_slug": "gemini-3.5-flash",
        "api_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "input_price": 0.075,
        "output_price": 0.30,
        "cost_proxy_scale": 10.0,
    },
    "doubao": {
        "name": "ep-m-20260630101726-sd682",
        "data_name": "doubao-seed-2-1-turbo-260628",
        "output_slug": "doubao-seed-2-1-turbo-260628",
        "api_url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "input_price": 0.40,
        "output_price": 1.00,
        "cost_proxy_scale": 12.0,
    },
    "zhipu": {
        "name": "glm-4-flash",
        "api_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "input_price": 0.15,
        "output_price": 0.60,
        "cost_proxy_scale": 10.0,
    },
    "llama-3.3-70b-nvidia": {
        "name": "meta/llama-3.3-70b-instruct",
        "data_name": "llama-3.3-70b-instruct",
        "output_slug": "llama-3.3-70b-instruct",
        "api_url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "api_key_env": "NVIDIA_EXTRA_KEY",
        "input_price": 0.0,
        "output_price": 0.0,
        "cost_proxy_scale": 70.0,
    },
}

# Retry configuration
MAX_RETRIES = 6
RETRY_BACKOFF_SECONDS = (5, 15, 30, 60, 120, 120)

# Batch size for saving
SAVE_BATCH_SIZE = 50

# Thread-safe counters and locks
progress_lock = Lock()
model_progress = {model: {"total": 0, "correct": 0, "errors": 0} for model in MODELS}
print_lock = Lock()


# ============================================================
# Load Environment
# ============================================================

def load_env(selected_models: list[str] | None = None) -> dict[str, str]:
    """Load environment variables from .env file."""
    env_vars = {}
    if not ENV_FILE.exists():
        raise FileNotFoundError(f".env file not found: {ENV_FILE}")

    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip().strip('"').strip("'")
    if NVIDIA_ENV_FILE.exists():
        with open(NVIDIA_ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip().strip('"').strip("'")
    # Check required API keys (skip local models)
    selected_models = selected_models or list(MODELS)
    cloud_models = [m for m in selected_models if "localhost" not in MODELS[m]["api_url"]]
    required_keys = {
        model: MODELS[model].get("api_key_env", model.upper() + "_API_KEY")
        for model in cloud_models
    }
    missing = [key for key in required_keys.values() if key not in env_vars]
    if missing:
        raise ValueError(f"Missing API keys in .env file: {missing}")

    return env_vars


# ============================================================
# API Call Functions
# ============================================================

def build_prompt(question: str, choices: list[str]) -> str:
    """Build prompt for KQA question answering."""
    choices_text = "\n".join([f"{chr(65+i)}. {choice}" for i, choice in enumerate(choices)])
    return f"""Select the correct option for this multiple-choice question.
Your entire response MUST be exactly one uppercase letter from A through J.
It must match this regular expression: ^[A-J]$
Do not explain, restate the question, add punctuation, or write the answer text.

Question: {question}

{choices_text}

Answer:"""


def call_api(
    env: dict[str, str],
    model_key: str,
    question: str,
    choices: list[str],
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """
    Call API for a specific model.

    Args:
        env: Environment variables
        model_key: Model key in MODELS dict
        question: The question text
        choices: List of choice options
        max_retries: Maximum number of retries

    Returns:
        Dictionary with response, tokens, time, etc.
    """
    model_config = MODELS[model_key]
    api_url = model_config["api_url"]
    model_name = model_config["name"]

    prompt = build_prompt(question, choices)

    # Build headers (model-specific)
    headers = {"Content-Type": "application/json"}

    # Skip auth for local models
    if "localhost" not in api_url:
        api_key = env[model_config.get("api_key_env", model_key.upper() + "_API_KEY")]
        headers["Authorization"] = f"Bearer {api_key}"

    # Build payload
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return exactly one uppercase option letter from A through J. "
                    "Your complete response must match ^[A-J]$. Never explain."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,  # Deterministic for consistent routing labels
        "max_tokens": 4,
        "stop": ["\n"],
    }

    def provider_refusal(response: requests.Response) -> dict[str, Any] | None:
        """Return metadata for deterministic provider content refusals."""
        if response.status_code != 400:
            return None
        lowered = response.text.casefold()
        markers = (
            "data_inspection_failed", "contentfilter", "content_filter",
            '"code":"1301"', "inappropriate content", "不安全或敏感内容",
        )
        if not any(marker in lowered for marker in markers):
            return None
        provider_code = None
        try:
            error = response.json().get("error", {})
            provider_code = error.get("code") or error.get("type")
        except (ValueError, AttributeError):
            pass
        return {
            "response": None, "input_tokens": 0, "output_tokens": 0,
            "response_time": response_time, "success": False,
            "status": "provider_refusal", "error_type": "content_filter",
            "provider_error_code": provider_code,
            "provider_http_status": response.status_code,
        }

    # Model-specific adjustments
    if model_key == "doubao":
        payload["top_p"] = 0.9
        payload["max_tokens"] = 4
    elif model_key == "gemini":
        payload["max_tokens"] = 128
        payload["reasoning_effort"] = "low"
        payload.pop("stop", None)
    elif model_key == "qwen":
        # Avoid a reasoning preamble consuming the short answer budget.
        payload["enable_thinking"] = False
    elif model_key == "zhipu":
        # GLM may begin with an internal/newline token; allow a small response
        # window and let the strict parser reject any ambiguous explanation.
        payload["max_tokens"] = 16
        payload.pop("stop", None)

    for attempt in range(max_retries):
        retry_wait = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
        try:
            start_time = time.time()
            request_timeout = {
                "doubao": 60,
                "gemini": 90,
                "llama-3.3-70b-nvidia": 120,
            }.get(model_key, 60)
            response = requests.post(api_url, headers=headers, json=payload, timeout=request_timeout)
            response_time = time.time() - start_time

            if response.status_code == 200:
                data = response.json()

                # Handle different response formats
                if "choices" in data and len(data["choices"]) > 0:
                    content = str(data["choices"][0]["message"].get("content") or "").strip()
                else:
                    content = data.get("output", {}).get("text", "unknown")

                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
                output_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0))

                return {
                    "response": content,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "response_time": response_time,
                    "success": True,
                    "status": "ok",
                }
            elif response.status_code in (429, 503):
                # Respect provider guidance, then add jitter to avoid synchronized retries.
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        retry_wait = max(retry_wait, float(retry_after))
                    except ValueError:
                        pass
                with print_lock:
                    print(
                        f"  [{model_key}] API busy ({response.status_code}). "
                        f"Retrying after backoff..."
                    )
            else:
                refusal = provider_refusal(response)
                if refusal is not None:
                    with print_lock:
                        print(
                            f"  [{model_key}] Provider refusal "
                            f"({refusal['provider_error_code'] or response.status_code})"
                        )
                    return refusal
                with print_lock:
                    print(f"  [{model_key}] API error: {response.status_code} - {response.text[:200]}")

        except requests.exceptions.Timeout:
            with print_lock:
                print(f"  [{model_key}] Timeout. Retrying...")
        except Exception as e:
            with print_lock:
                print(f"  [{model_key}] Error: {e}")

        if attempt < max_retries - 1:
            time.sleep(retry_wait + random.uniform(0, min(5.0, retry_wait * 0.2)))

    # All retries failed
    return {
        "response": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "response_time": 0,
        "success": False,
        "status": "request_failed",
        "error_type": "retry_exhausted",
    }


# ============================================================
# Label Processing
# ============================================================

def extract_choice_label(response: str | None, choices: list[str]) -> str | None:
    """Extract an unambiguous A-J label; never guess or default to A."""
    if response is None:
        return None
    text = response.strip()
    patterns = (
        r"^\s*\**(?:answer\s*[:=-]?\s*)?\**\(?([A-J])\)?(?:\s*$|\s*[.、:)\-*])",
        r"\b(?:correct\s+answer|answer|option|choice)\s*(?:is|[:=])?\s*\**\(?([A-J])\)?\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    matches = {
        chr(65 + i)
        for i, choice in enumerate(choices)
        if str(choice).strip() and str(choice).casefold() in text.casefold()
    }
    return next(iter(matches)) if len(matches) == 1 else None


def compute_cost_proxy(
    model_key: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Compute cost proxy based on tokens."""
    model_config = MODELS[model_key]
    base_cost = (
        input_tokens * model_config["input_price"]
        + output_tokens * model_config["output_price"]
    ) / 1_000_000
    # Scale to match existing cost_proxy range (0.5 - 10.0)
    return min(max(base_cost * model_config["cost_proxy_scale"], 0.5), 10.0)


# ============================================================
# Data Generation
# ============================================================

def generate_routing_entry(
    env: dict[str, str],
    model_key: str,
    item: dict[str, Any],
    idx: int,
) -> dict[str, Any] | None:
    """Generate a single routing entry for a model."""
    question = item["question"]
    choices = item["choices"]
    answer = item["answer"]
    task_id = f"kqapro-val-{idx:05d}"

    # Call API
    result = call_api(env, model_key, question, choices)

    if not result["success"] and result.get("status") != "provider_refusal":
        with progress_lock:
            model_progress[model_key]["errors"] += 1
        return None

    base_entry = {
        "task_name": "kqapro", "query": question, "ground_truth": answer,
        "metric": "em_mc",
        "choices": {
            "text": choices,
            "labels": [chr(65 + i) for i in range(len(choices))],
        },
        "task_id": task_id,
        "model_name": MODELS[model_key].get("data_name", model_key),
        "_model_key": model_key, "embedding_id": 0,
    }

    if result.get("status") == "provider_refusal":
        with progress_lock:
            model_progress[model_key]["errors"] += 1
        return {
            **base_entry, "response": None, "predicted_label": None,
            "correct": 0.0, "performance": 0.0,
            "status": "provider_refusal",
            "error_type": result["error_type"],
            "provider_error_code": result.get("provider_error_code"),
            "provider_http_status": result.get("provider_http_status"),
            "cost_proxy": 0.0, "response_time": result["response_time"],
            "input_tokens": 0, "output_tokens": 0,
        }

    # Extract predicted label
    predicted_label = extract_choice_label(result["response"], choices)
    if predicted_label is None:
        with progress_lock:
            model_progress[model_key]["errors"] += 1
        return {
            **base_entry, "response": result["response"],
            "predicted_label": None, "correct": 0.0, "performance": 0.0,
            "status": "invalid_response", "error_type": "unparseable_label",
            "provider_error_code": None, "provider_http_status": 200,
            "cost_proxy": compute_cost_proxy(
                model_key, result["input_tokens"], result["output_tokens"]
            ),
            "response_time": result["response_time"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
        }

    # Check correctness
    try:
        answer_index = choices.index(answer)
        is_correct = (predicted_label == chr(65 + answer_index))
    except ValueError:
        is_correct = False

    # Compute performance and cost
    performance = 1.0 if is_correct else 0.0
    cost_proxy = compute_cost_proxy(model_key, result["input_tokens"], result["output_tokens"])

    # Create routing entry
    return {
        **base_entry,
        "response": result["response"],
        "predicted_label": predicted_label,
        "correct": float(is_correct),
        "performance": performance,
        "cost_proxy": cost_proxy,
        "response_time": result["response_time"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "status": "ok",
    }


def process_item(
    env: dict[str, str],
    item: dict[str, Any],
    idx: int,
    models: list[str],
) -> list[dict[str, Any]]:
    """Process a single KQA item with all models."""
    results = []
    for model_key in models:
        entry = generate_routing_entry(env, model_key, item, idx)
        if entry:
            results.append(entry)
            with progress_lock:
                model_progress[model_key]["total"] += 1
                if entry["correct"]:
                    model_progress[model_key]["correct"] += 1
    return results


def print_progress():
    """Print current progress for all models."""
    with print_lock:
        print("\n" + "=" * 60)
        print("Progress:")
        print("-" * 60)
        for model, stats in model_progress.items():
            total = stats["total"]
            correct = stats["correct"]
            errors = stats["errors"]
            accuracy = correct / total * 100 if total > 0 else 0
            print(f"  {model:12s}: {total:5d} total, {correct:5d} correct, {errors:4d} errors, {accuracy:5.1f}% accuracy")
        print("=" * 60)


def generate_multi_model_routing_data(
    env: dict[str, str],
    models: list[str],
    limit: int | None = None,
    concurrency: int = 3,
) -> None:
    """Generate routing training data for KQA validation set with multiple models."""
    # Load KQA validation data
    print(f"Loading KQA validation set from {KQA_VAL_FILE}...")
    with open(KQA_VAL_FILE) as f:
        kqa_data = json.load(f)

    total = len(kqa_data)
    if limit:
        kqa_data = kqa_data[:limit]
        print(f"Limited to {limit} examples (total available: {total})")

    print(f"Loaded {len(kqa_data)} examples")
    print(f"Models to run: {', '.join(models)}")
    print(f"Concurrency: {concurrency}")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Resume by valid task IDs; line counts are unsafe with duplicate runs.
    completed_ids: dict[str, set[str]] = {model: set() for model in models}
    for model in models:
        output_slug = MODELS[model].get("output_slug", model)
        output_file = OUTPUT_DIR / f"routing_train_{output_slug}.jsonl"
        if output_file.exists():
            with open(output_file) as f:
                for line in f:
                    try:
                        row = json.loads(line)
                        stored_label = str(row.get("predicted_label", "")).strip().upper()
                        parsed_label = extract_choice_label(
                            row.get("response", ""), row["choices"]["text"]
                        )
                        if (
                            stored_label in "ABCDEFGHIJ"
                            or parsed_label
                            or row.get("status") in {
                                "provider_refusal", "invalid_response"
                            }
                        ):
                            completed_ids[model].add(row["task_id"])
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue
            print(f"Found {len(completed_ids[model])} valid unique {model} task IDs")

    # Output files for each model
    output_files = {}
    for model in models:
        output_slug = MODELS[model].get("output_slug", model)
        output_files[model] = open(OUTPUT_DIR / f"routing_train_{output_slug}.jsonl", "a")

    # Process items in parallel
    print(f"Starting processing with {concurrency} workers...\n")

    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {}
            for idx, item in enumerate(kqa_data):
                task_id = f"kqapro-val-{idx:05d}"
                pending_models = [m for m in models if task_id not in completed_ids[m]]
                if pending_models:
                    futures[executor.submit(process_item, env, item, idx, pending_models)] = idx
            print(f"Pending examples: {len(futures)} (model subsets may differ)")

            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results = future.result()

                    # Save results to respective model files
                    for result in results:
                        model = result.pop("_model_key")
                        output_files[model].write(json.dumps(result, ensure_ascii=False) + "\n")
                        output_files[model].flush()

                except Exception as e:
                    print(f"Error processing item {idx}: {e}")

                # Print progress every 50 items
                if idx % 50 == 0:
                    print(f"Progress: {idx}/{len(kqa_data)}")
                    print_progress()

    finally:
        # Close all output files
        for f in output_files.values():
            f.close()

    # Final summary
    print("\n" + "=" * 60)
    print("Generation Complete!")
    print("=" * 60)
    print(f"Total examples processed: {len(kqa_data)}")
    print()
    print("Per-model results:")
    for model in models:
        stats = model_progress[model]
        total = stats["total"]
        correct = stats["correct"]
        errors = stats["errors"]
        accuracy = correct / total * 100 if total > 0 else 0
        print(f"  {model:12s}: {total:5d} total, {correct:5d} correct, {errors:4d} errors, {accuracy:5.1f}% accuracy")
        output_slug = MODELS[model].get("output_slug", model)
        print(f"    Output: {OUTPUT_DIR}/routing_train_{output_slug}.jsonl")
    print("=" * 60)


# ============================================================
# CLI Entry Point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate KQA routing training data using multiple LLM providers"
    )
    parser.add_argument(
        "--models",
        type=str,
        nargs="+",
        default=list(MODELS.keys()),
        choices=list(MODELS.keys()),
        help="Models to run (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of examples to process (for testing)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Number of concurrent API calls (default: 3)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: process only 10 examples with 1 model",
    )
    args = parser.parse_args()

    if args.test:
        args.limit = 10
        # Only override models if not explicitly specified
        if not any(arg for arg in sys.argv if arg.startswith("--models")):
            args.models = ["deepseek"]
        args.concurrency = 1
        print(f"TEST MODE: Processing only 10 examples with {', '.join(args.models)}\n")

    try:
        env = load_env(args.models)
        generate_multi_model_routing_data(env, args.models, args.limit, args.concurrency)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
