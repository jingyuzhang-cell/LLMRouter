#!/usr/bin/env python3
"""Collect resumable KQA Pro routing labels from OpenAI-compatible APIs."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data/kqapro/KQAPro_Baselines/dataset/val.json"
DEFAULT_OUTPUT = ROOT / "data/kqapro/api_routing"


@dataclass(frozen=True)
class Provider:
    key_env: str
    base_url: str
    model: str
    extra: dict | None = None


PROVIDERS = {
    "openai": Provider("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-5-nano"),
    "deepseek": Provider(
        "DEEPSEEK_API_KEY",
        "https://api.deepseek.com",
        "deepseek-v4-flash",
        {"thinking": {"type": "disabled"}},
    ),
    "qwen": Provider(
        "QWEN_API_KEY",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen3.5-flash",
        {"enable_thinking": False},
    ),
    "gemini": Provider(
        "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-3.5-flash",
        {"reasoning_effort": "low"},
    ),
    "doubao": Provider(
        "DOUBAO_API_KEY",
        "https://ark.cn-beijing.volces.com/api/v3",
        "doubao-seed-2-0-lite-260215",
    ),
    "zhipu": Provider(
        "ZHIPU_API_KEY",
        "https://open.bigmodel.cn/api/paas/v4",
        "glm-4-flash",
    ),
}


def load_env(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Environment file not found: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


def setting(provider_name: str, provider: Provider) -> Provider:
    prefix = provider_name.upper()
    return Provider(
        provider.key_env,
        os.getenv(f"{prefix}_BASE_URL", provider.base_url).rstrip("/"),
        os.getenv(f"{prefix}_MODEL", provider.model),
        provider.extra,
    )


def gold_label(sample: dict) -> str:
    answer = str(sample["answer"]).strip()
    for index, choice in enumerate(sample["choices"]):
        if str(choice).strip() == answer:
            return chr(65 + index)
    raise ValueError("answer is absent from choices")


def prompt(sample: dict) -> str:
    choices = "\n".join(
        f"{chr(65 + i)}. {choice}" for i, choice in enumerate(sample["choices"])
    )
    return (
        "Answer the multiple-choice question using the supplied options. "
        "Return exactly one capital letter and no explanation.\n\n"
        f"Question: {sample['question']}\nOptions:\n{choices}\nAnswer:"
    )


def parse_label(text: str, choice_count: int) -> str | None:
    match = re.search(r"(?<![A-Z])([A-J])(?![A-Z])", text.upper())
    if not match:
        return None
    label = match.group(1)
    return label if ord(label) - 65 < choice_count else None


def completed_ids(path: Path) -> set[str]:
    done = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("status") == "ok" and row.get("predicted_label") is not None:
                done.add(row["task_id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return done


def safe_error(response: requests.Response) -> str:
    try:
        body = response.json()
        if not isinstance(body, dict):
            return str(body)[:500]
        message = body.get("error", body)
        if isinstance(message, dict):
            message = message.get("message", message.get("code", str(message)))
        return str(message)[:500]
    except ValueError:
        return response.text[:500]


def call(provider: Provider, api_key: str, sample: dict, timeout: int) -> tuple[str, dict]:
    payload = {
        "model": provider.model,
        "messages": [{"role": "user", "content": prompt(sample)}],
        "temperature": 0,
        "max_tokens": 128,
    }
    if provider.extra:
        payload.update(provider.extra)
    response = requests.post(
        f"{provider.base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    if not response.ok:
        raise RuntimeError(f"HTTP {response.status_code}: {safe_error(response)}")
    data = response.json()
    return data["choices"][0]["message"].get("content", ""), data.get("usage", {})


def append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--split", default="val")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--providers", nargs="+", choices=PROVIDERS, default=list(PROVIDERS))
    parser.add_argument("--per-provider", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--delay", type=float, default=0.0)
    args = parser.parse_args()

    load_env(args.env_file)
    samples = json.loads(args.data.read_text(encoding="utf-8"))
    indices = list(range(len(samples)))
    random.Random(args.seed).shuffle(indices)
    indices = indices[: args.per_provider]

    for name in args.providers:
        cfg = setting(name, PROVIDERS[name])
        key = os.getenv(cfg.key_env, "").strip()
        output = args.output_dir / f"{name}.jsonl"
        done = completed_ids(output)
        print(f"\n{name}: model={cfg.model}, completed={len(done)}", flush=True)
        if not key:
            print(f"  SKIP: {cfg.key_env} is missing", flush=True)
            continue
        for position, source_index in enumerate(indices, 1):
            task_id = f"kqapro-{args.split}-{source_index:05d}"
            if task_id in done:
                print(f"  {position}/{len(indices)} resume-skip", flush=True)
                continue
            sample = samples[source_index]
            started = time.perf_counter()
            row = {
                "task_id": task_id,
                "provider": name,
                "model_name": cfg.model,
                "question": sample["question"],
                "choices": sample["choices"],
                "ground_truth": gold_label(sample),
            }
            try:
                response, usage = call(cfg, key, sample, args.timeout)
                predicted = parse_label(response, len(sample["choices"]))
                row.update(
                    status="ok",
                    response=response.strip(),
                    predicted_label=predicted,
                    correct=float(predicted == row["ground_truth"]),
                    usage=usage,
                )
                print(f"  {position}/{len(indices)} ok label={predicted}", flush=True)
            except (requests.RequestException, RuntimeError, KeyError, ValueError) as exc:
                row.update(status="error", error=str(exc)[:600])
                print(f"  {position}/{len(indices)} ERROR {exc}", flush=True)
                if "HTTP 429" in str(exc):
                    retry = re.search(r"retry in ([0-9.]+)s", str(exc), re.IGNORECASE)
                    wait_seconds = float(retry.group(1)) + 2.0 if retry else 65.0
                    print(f"  rate-limited; sleeping {wait_seconds:.1f}s", flush=True)
                    time.sleep(wait_seconds)
            row["response_time"] = time.perf_counter() - started
            append_row(output, row)
            if args.delay > 0:
                time.sleep(args.delay)


if __name__ == "__main__":
    main()
