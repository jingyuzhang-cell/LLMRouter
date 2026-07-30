#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

set -a
. ./.env
. ./.nvidia_extra_key.env
set +a

workers="${1:-8}"

exec python -u - "$workers" <<'PY'
import json
import os
import sys

raw = os.environ["API_KEYS"]
extra = os.environ.pop("NVIDIA_EXTRA_KEY")

try:
    keys = json.loads(raw)
except json.JSONDecodeError:
    keys = [part.strip() for part in raw.split(",") if part.strip()]

if isinstance(keys, dict):
    provider = next((name for name in keys if name.lower() == "nvidia"), "NVIDIA")
    current = keys.get(provider, [])
    if isinstance(current, str):
        current = [part.strip() for part in current.split(",") if part.strip()]
    if extra not in current:
        current.append(extra)
    keys[provider] = current
elif isinstance(keys, list):
    if extra not in keys:
        keys.append(extra)
else:
    keys = [str(keys), extra]

os.environ["API_KEYS"] = json.dumps(keys)
os.execvp(
    sys.executable,
    [
        sys.executable,
        "-u",
        "scripts/collect_mlprouter_reevaluations.py",
        "--manifest", "data/nvidia_current_v1/manifest.jsonl",
        "--data", "data/nvidia_current_v1/queries.jsonl",
        "--output", "data/nvidia_current_v1/results.jsonl",
        "--workers", sys.argv[1],
    ],
)
PY
