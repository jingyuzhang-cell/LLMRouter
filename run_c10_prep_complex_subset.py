#!/usr/bin/env python3
"""Freeze an input-only top-quartile complex subset from C9 development."""
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path("/root")
SOURCE = ROOT / "phase_c9_0/C9_DEV_TASKS.jsonl"
OUT = ROOT / "c10_prep"
SIZE = 120
FEATURES = (
    "query_token_count", "context_token_count", "table_cell_count",
    "numeric_count", "reasoning_cue_count", "cross_reference_count",
    "context_dispersion_proxy",
)

rows = [json.loads(x) for x in SOURCE.read_text().splitlines() if x.strip()]
rows = sorted((r for r in rows if r.get("split") == "development_train"), key=lambda r: r["task_id"])
assert len(rows) == 480
values = np.asarray([[np.log1p(float(r["observable_features"].get(f, 0))) for f in FEATURES] for r in rows])
ranks = np.empty_like(values)
for column in range(values.shape[1]):
    order = np.argsort(values[:, column], kind="stable")
    ranks[order, column] = np.arange(len(rows)) / (len(rows) - 1)
scores = ranks.mean(axis=1)
ranked = sorted(zip(rows, scores), key=lambda x: (-x[1], hashlib.sha256(x[0]["task_id"].encode()).hexdigest()))
selected = ranked[:SIZE]
manifest = [{
    "task_id": row["task_id"],
    "complexity_score": float(score),
    "observable_features": {f: row["observable_features"].get(f, 0) for f in FEATURES},
} for row, score in selected]
protocol = {
    "version": "C10-prep-input-complexity-v1",
    "status": "FROZEN_WITHOUT_MODEL_OUTPUTS",
    "population": "480 C9 development_train tasks",
    "selection_size": SIZE,
    "selection_fraction": SIZE / len(rows),
    "features": list(FEATURES),
    "transform": "log1p then within-development empirical percentile rank per feature",
    "score": "unweighted mean of seven percentile ranks",
    "selection": "highest 120 scores; SHA-256(task_id) ascending tie break",
    "forbidden_inputs": ["candidate response", "quality label", "provider success", "model identity", "cost", "latency"],
    "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
}
OUT.mkdir(exist_ok=True)
(OUT / "C10_PREP_COMPLEX_SUBSET.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in manifest))
(OUT / "C10_PREP_COMPLEX_SUBSET_PROTOCOL.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
for name in ("C10_PREP_COMPLEX_SUBSET.jsonl", "C10_PREP_COMPLEX_SUBSET_PROTOCOL.json"):
    path = OUT / name
    print(hashlib.sha256(path.read_bytes()).hexdigest(), name)
