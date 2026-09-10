"""Prepare a blind train-only repeat-stability panel for large vs reasoning.

The panel is selected before any repeat collection. It targets three sources of
uncertainty: observed large/reasoning disagreements, predicted near ties, and
high-regret routing misses. It does not call model or judge APIs.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from .core import SLOTS
from .data import load_cohort, sha
from .diagnose_rank_signal import load_inputs

LARGE = SLOTS.index("large")
REASONING = SLOTS.index("reasoning")


def add_ranked(selected, candidates, stratum, limit):
    added = 0
    for idx in candidates:
        rec = selected.setdefault(int(idx), {"strata": []})
        if stratum not in rec["strata"]:
            rec["strata"].append(stratum)
        added += 1
        if added >= limit:
            break


def balanced_strict_indices(pair_diff, pred_diff, per_side):
    left = np.flatnonzero(pair_diff > 0)
    right = np.flatnonzero(pair_diff < 0)
    left = left[np.argsort(np.abs(pred_diff[left]))]
    right = right[np.argsort(np.abs(pred_diff[right]))]
    return list(left[:per_side]) + list(right[:per_side])


def run(args):
    source = Path(args.source).resolve()
    out = Path(args.output).resolve()
    if out.exists():
        raise FileExistsError(out)
    frozen, _x, _datasets = load_inputs(source)
    protocol = json.loads((source / "PROTOCOL.json").read_text())
    cohort_path = next(Path(p).parent for p in protocol["input_sha256"] if Path(p).name == "queries.jsonl")
    cohort, split = load_cohort(cohort_path)
    ids = frozen["ids"].tolist()
    if not set(ids) <= set(split["train"]):
        raise ValueError("Repeat panel must stay on original train IDs")
    y = frozen["quality"]
    pred = frozen["predicted_quality"]
    dataset_best = frozen["DatasetBest"].astype(int)
    oracle = y.max(1)
    oracle_sets = [np.flatnonzero(np.abs(row - row.max()) < 1e-12).tolist() for row in y]
    pair_diff = y[:, REASONING] - y[:, LARGE]
    pred_diff = pred[:, REASONING] - pred[:, LARGE]
    regret = oracle - y[np.arange(len(y)), dataset_best]

    selected = {}
    add_ranked(
        selected,
        balanced_strict_indices(pair_diff, pred_diff, args.strict_per_side),
        "large_reasoning_observed_strict_balanced",
        args.strict_per_side * 2,
    )
    near = np.arange(len(y))
    near = near[np.lexsort((-regret, np.abs(pred_diff)))]
    add_ranked(selected, near, "predicted_near_tie", args.near_tie)
    high = np.flatnonzero(regret > 0)
    preferred = [i for i in high if LARGE in oracle_sets[i] or REASONING in oracle_sets[i]]
    preferred = np.array(preferred, dtype=int)
    preferred = preferred[np.lexsort((np.abs(pred_diff[preferred]), -regret[preferred]))]
    add_ranked(selected, preferred, "high_regret_large_or_reasoning_oracle", args.high_regret)

    ordered = sorted(selected, key=lambda i: (-regret[i], abs(pred_diff[i]), ids[i]))
    blind_rows = []
    private_rows = []
    for panel_index, i in enumerate(ordered):
        qid = ids[i]
        c = cohort[qid]
        blind_rows.append(
            {
                "panel_index": panel_index,
                "query_id": qid,
                "dataset": c["dataset"],
                "task_type": c["task_type"],
                "query": c["query"],
                "target_slots": ["large", "reasoning"],
                "planned_repeats_per_slot": args.repeats,
                "strata": selected[i]["strata"],
            }
        )
        private_rows.append(
            {
                "panel_index": panel_index,
                "query_id": qid,
                "strata": selected[i]["strata"],
                "current_large_quality": float(y[i, LARGE]),
                "current_reasoning_quality": float(y[i, REASONING]),
                "current_pair_label": "reasoning>large"
                if pair_diff[i] > 0
                else ("large>reasoning" if pair_diff[i] < 0 else "tie"),
                "ridge_pred_reasoning_minus_large": float(pred_diff[i]),
                "dataset_best_slot": SLOTS[int(dataset_best[i])],
                "oracle_slots": [SLOTS[j] for j in oracle_sets[i]],
                "regret_vs_dataset_best": float(regret[i]),
            }
        )
    out.mkdir(parents=True, exist_ok=False)
    with (out / "PANEL.jsonl").open("w") as f:
        for row in blind_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out / "PRIVATE_KEY.jsonl").open("w") as f:
        for row in private_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "role": "train_only_repeat_stability_panel_large_vs_reasoning",
        "source": str(source),
        "source_files": {name: sha(source / name) for name in ("PROTOCOL.json", "RESULTS.json", "OOF.npz")},
        "n_panel": len(blind_rows),
        "target_slots": ["large", "reasoning"],
        "planned_repeats_per_slot": args.repeats,
        "selection": {
            "strict_per_side": args.strict_per_side,
            "near_tie": args.near_tie,
            "high_regret": args.high_regret,
            "sorts": [
                "observed strict pair labels balanced by side, closest predicted pair margin first",
                "near tie by absolute Ridge predicted reasoning-large margin, high regret as tie-breaker",
                "high regret where large or reasoning is in the current oracle set",
            ],
        },
        "collection_warning": "The existing production client uses temperature=0.0. Temperature-0 repeats measure backend/judge stability; stochastic repeat labels require an explicit nonzero sampling protocol and are not directly the same deployment distribution.",
        "limits": [
            "Panel selection uses original train objective labels only and is for development.",
            "PANEL.jsonl is blind to current labels; PRIVATE_KEY.jsonl must not be used by repeat collection workers.",
            "No model generation, judge call, validation label, or test label is used by this script.",
        ],
        "files": {},
    }
    for name in ("PANEL.jsonl", "PRIVATE_KEY.jsonl"):
        manifest["files"][name] = sha(out / name)
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"n_panel": len(blind_rows), "files": manifest["files"]}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--strict-per-side", type=int, default=20)
    parser.add_argument("--near-tie", type=int, default=40)
    parser.add_argument("--high-regret", type=int, default=40)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
