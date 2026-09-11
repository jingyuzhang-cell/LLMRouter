"""Freeze a uniform 400-query MMLU-Pro diagnostic panel without reading outcomes."""
import json
from pathlib import Path

import numpy as np

from .data import load_cohort, read_rows, sha


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "router_v2/knowledge_validation_400"
SEED = 20260915


def main():
    if OUT.exists():
        raise FileExistsError(OUT)
    cohort, split = load_cohort(ROOT / "data/cohort_full_v2")
    pilot = {
        row["query_id"]
        for row in read_rows(ROOT / "router_v2/pool4_pilot_120/PANEL.jsonl")
    }
    # Access only IDs and pre-existing group-isolated fold assignments. The NPZ also
    # contains outcomes, but this selector never loads those arrays.
    source = ROOT / "router_v2/objective_verified_20260910/OOF.npz"
    with np.load(source, allow_pickle=False) as saved:
        ids = saved["ids"]
        folds = saved["folds"]
    fold_by_id = dict(zip(ids.tolist(), folds.astype(int).tolist()))
    eligible = sorted(
        q for q in split["train"]
        if cohort[q]["dataset"] == "mmlupro" and q not in pilot and q in fold_by_id
    )
    if len(eligible) < 400:
        raise ValueError(f"Only {len(eligible)} eligible MMLU-Pro queries")
    selected = sorted(np.random.default_rng(SEED).choice(eligible, 400, replace=False).tolist())
    groups_path = ROOT / "router_v2/contamination_audit_20260910b/PROMPT_GROUPS.json"
    groups = json.loads(groups_path.read_text())["groups"]
    rows = []
    for index, qid in enumerate(selected):
        source_row = cohort[qid]
        rows.append({
            **{k: source_row[k] for k in ("query_id", "query", "dataset", "task_type")},
            "panel_index": index,
            "fold": fold_by_id[qid],
            "prompt_group": groups[qid],
        })
    if set(selected) & pilot or len({r["prompt_group"] for r in rows}) != len(rows):
        raise ValueError("Pilot overlap or duplicate prompt group")
    OUT.mkdir(parents=True)
    panel = OUT / "PANEL.jsonl"
    panel.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    protocol = {
        "role": "train-only expanded knowledge routability diagnostic",
        "seed": SEED,
        "n": 400,
        "dataset": "mmlupro",
        "selection": "uniform random from original train MMLU-Pro, excluding all 120 pilot IDs; no outcomes read",
        "slots": ["medium", "large", "coder", "reasoning"],
        "generation": "single response per model/query; reuse existing single responses for medium/large/reasoning; generate coder only",
        "coder_temperature": 0.0,
        "coder_top_p": 1.0,
        "gate": {"oracle_gap_strictly_greater_than": 0.08, "winner_entropy_strictly_greater_than": 0.7},
        "gate_action": "READY_FOR_MA only if both pass; never train MA in this stage",
        "panel_sha256": sha(panel),
        "cohort_sha256": sha(ROOT / "data/cohort_full_v2/queries.jsonl"),
        "split_sha256": sha(ROOT / "data/cohort_full_v2/split.json"),
        "fold_source_sha256": sha(source),
        "groups_sha256": sha(groups_path),
        "pilot_panel_sha256": sha(ROOT / "router_v2/pool4_pilot_120/PANEL.jsonl"),
        "limits": [
            "Development diagnostic drawn from original train, not an independent paper test set.",
            "Historical responses and Coder generation use different collection dates and serving stacks.",
            "All four MMLU-Pro answers are rescored with the same explicit-option parser.",
        ],
    }
    (OUT / "PROTOCOL.json").write_text(json.dumps(protocol, indent=2) + "\n")
    print(json.dumps({"eligible": len(eligible), "selected": len(rows), "folds": {
        str(f): sum(r["fold"] == f for r in rows) for f in sorted(set(fold_by_id[q] for q in selected))
    }}, indent=2))


if __name__ == "__main__":
    main()
