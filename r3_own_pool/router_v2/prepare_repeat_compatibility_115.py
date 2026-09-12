"""Freeze the overlap of current disagreements and an existing five-repeat panel."""
import json
from pathlib import Path

import numpy as np

from .data import load_cohort, read_rows, sha


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "router_v2/repeat_compatibility_115"


def main():
    if OUT.exists():
        raise FileExistsError(OUT)
    current_path = ROOT / "router_v2/knowledge_validation_400/PANEL.jsonl"
    repeat_path = ROOT / "router_v2/mmlu_utility_panel_400/PANEL.jsonl"
    current = {r["query_id"]: r for r in read_rows(current_path)}
    repeat_ids = {r["query_id"] for r in read_rows(repeat_path)}
    diagnostic_path = ROOT / "router_v2/knowledge_validation_400_results/DIAGNOSTIC.npz"
    with np.load(diagnostic_path, allow_pickle=False) as saved:
        ids = saved["ids"]
        quality = saved["quality"]
    disagreements = {
        str(ids[i]) for i in range(len(ids)) if len(set(quality[i].tolist())) > 1
    }
    selected = sorted(disagreements & repeat_ids)
    if len(selected) != 115:
        raise ValueError(f"Expected 115 reusable disagreement queries, got {len(selected)}")
    cohort, split = load_cohort(ROOT / "data/cohort_full_v2")
    rows = []
    for index, qid in enumerate(selected):
        if qid not in split["train"] or cohort[qid]["dataset"] != "mmlupro":
            raise ValueError("Target outside train MMLU-Pro")
        source = cohort[qid]
        rows.append({
            **{k: source[k] for k in ("query_id", "query", "dataset", "task_type")},
            "panel_index": index,
            "fold": current[qid]["fold"],
            "prompt_group": current[qid]["prompt_group"],
            "planned_repeats_per_model": 5,
        })
    OUT.mkdir(parents=True)
    panel = OUT / "PANEL.jsonl"
    panel.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    protocol = {
        "role": "outcome-enriched repeat-label training diagnostic",
        "selection": "intersection of current 400-query model-disagreement set and prior complete large/reasoning five-repeat panel",
        "n": 115,
        "models": ["medium", "large", "coder", "reasoning"],
        "repeats": 5,
        "temperature": 0.7,
        "top_p": 1.0,
        "reuse": "all five large/reasoning generations; rescore raw answers with common explicit-option parser",
        "new_generation": "five medium and five coder responses per query; bounded two transport attempts",
        "target": "continuous empirical quality and pair preference 0.5 + (mean_i-mean_j)/2",
        "panel_sha256": sha(panel),
        "current_panel_sha256": sha(current_path),
        "prior_repeat_panel_sha256": sha(repeat_path),
        "diagnostic_sha256": sha(diagnostic_path),
        "cohort_sha256": sha(ROOT / "data/cohort_full_v2/queries.jsonl"),
        "split_sha256": sha(ROOT / "data/cohort_full_v2/split.json"),
        "limits": [
            "Queries are deliberately selected using observed single-generation disagreement; this is training enrichment, not representative evaluation.",
            "Repeated labels reduce outcome noise but do not increase query diversity beyond 115.",
            "No inference latency or monetary-cost comparison across different serving stacks.",
        ],
    }
    (OUT / "PROTOCOL.json").write_text(json.dumps(protocol, indent=2) + "\n")
    print(json.dumps({"selected": len(rows), "folds": {
        str(f): sum(r["fold"] == f for r in rows) for f in sorted({r["fold"] for r in rows})
    }}, indent=2))


if __name__ == "__main__":
    main()
