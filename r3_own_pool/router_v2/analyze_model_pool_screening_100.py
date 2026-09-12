"""Analyze the 100-query model-pool capability screening panel."""
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

from .data import read_rows, sha
from .mmlu_learnability import subject_from_query


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/model_pool_screening_100"
OUT = ROOT / "router_v2/model_pool_screening_100"
SLOTS = ["small", "medium", "large", "coder", "math", "reasoning"]


def corr(a, b):
    if np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def main():
    status = json.loads((DATA / "STATUS.json").read_text())
    labels_path = DATA / "SCREENING_LABELS.jsonl"
    if status.get("phase") != "SCREENING_LABELS_COMPLETE":
        raise ValueError(f"Screening incomplete: {status}")
    if sha(labels_path) != status["labels_sha256"]:
        raise ValueError("Screening labels changed")

    panel = {r["query_id"]: r for r in read_rows(DATA / "PANEL.jsonl")}
    rows = read_rows(labels_path)
    ids = [r["query_id"] for r in rows]
    y = np.array([[r["models"][slot] for slot in SLOTS] for r in rows], dtype=float)
    if y.shape != (100, len(SLOTS)) or not np.isfinite(y).all():
        raise ValueError(f"Bad screening matrix shape: {y.shape}")

    means = y.mean(axis=0)
    best_single = int(np.argmax(means))
    oracle = y.max(axis=1)
    baseline = y[:, best_single]
    gap = float((oracle - baseline).mean())

    winners = []
    fractional = Counter()
    for row in y:
        best = row.max()
        ties = [SLOTS[i] for i, value in enumerate(row) if value == best]
        winners.append(ties[0])
        for slot in ties:
            fractional[slot] += 1.0 / len(ties)

    subjects = [subject_from_query(panel[qid]["query"]) for qid in ids]
    subject_rows = []
    for subject in sorted(set(subjects)):
        idx = np.array([i for i, s in enumerate(subjects) if s == subject], dtype=int)
        if len(idx) < 3:
            continue
        subject_mean = y[idx].mean(axis=0)
        subject_oracle = y[idx].max(axis=1).mean()
        subject_rows.append({
            "subject": subject,
            "n": int(len(idx)),
            "best": SLOTS[int(np.argmax(subject_mean))],
            "oracle": float(subject_oracle),
            "means": {slot: float(subject_mean[i]) for i, slot in enumerate(SLOTS)},
        })

    errors = 1.0 - y
    error_correlation = {
        f"{a}:{b}": corr(errors[:, SLOTS.index(a)], errors[:, SLOTS.index(b)])
        for a, b in combinations(SLOTS, 2)
    }
    unique_rescues = {
        slot: int(((y[:, SLOTS.index(slot)] == 1.0) & (np.delete(y, SLOTS.index(slot), axis=1).max(axis=1) == 0.0)).sum())
        for slot in SLOTS
    }
    pair_complementarity = {}
    for a, b in combinations(SLOTS, 2):
        ia, ib = SLOTS.index(a), SLOTS.index(b)
        pair_complementarity[f"{a}:{b}"] = {
            "pair_oracle": float(np.maximum(y[:, ia], y[:, ib]).mean()),
            f"{a}_only_correct": int(((y[:, ia] == 1.0) & (y[:, ib] == 0.0)).sum()),
            f"{b}_only_correct": int(((y[:, ib] == 1.0) & (y[:, ia] == 0.0)).sum()),
        }

    report = {
        "n": len(ids),
        "slots": SLOTS,
        "single_model_accuracy": {slot: float(means[i]) for i, slot in enumerate(SLOTS)},
        "best_single": SLOTS[best_single],
        "best_single_accuracy": float(means[best_single]),
        "oracle_accuracy": float(oracle.mean()),
        "oracle_gap_pp": gap * 100.0,
        "winner_first_tie_break": dict(Counter(winners)),
        "winner_fractional_ties": {slot: float(fractional[slot]) for slot in SLOTS},
        "unique_rescues": unique_rescues,
        "subject_profile": subject_rows,
        "error_correlation": error_correlation,
        "pair_complementarity": pair_complementarity,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RESULTS.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    lines = [
        "# Model Pool Capability Screening 100",
        "",
        f"BestSingle={report['best_single']} ({report['best_single_accuracy']:.2%}); "
        f"Oracle={report['oracle_accuracy']:.2%}; Oracle Gap={report['oracle_gap_pp']:.2f}pp.",
        "",
        "| Model | Accuracy | Fractional winners | Unique rescues |",
        "|---|---:|---:|---:|",
    ]
    for i, slot in enumerate(SLOTS):
        lines.append(
            f"| {slot} | {means[i]:.2%} | {report['winner_fractional_ties'][slot]:.1f} | {unique_rescues[slot]} |"
        )
    lines.extend(["", "## Subject Profile", "", "| Subject | n | Best | Oracle | Model accuracies |", "|---|---:|---|---:|---|"])
    for row in subject_rows:
        acc = ", ".join(f"{slot}={row['means'][slot]:.2f}" for slot in SLOTS)
        lines.append(f"| {row['subject']} | {row['n']} | {row['best']} | {row['oracle']:.2%} | {acc} |")
    lines.extend(["", "## Pair Complementarity", "", "| Pair | Pair oracle | Left-only | Right-only | Error corr |", "|---|---:|---:|---:|---:|"])
    for pair, values in sorted(pair_complementarity.items(), key=lambda kv: kv[1]["pair_oracle"], reverse=True):
        a, b = pair.split(":")
        ec = error_correlation[pair]
        lines.append(
            f"| {pair} | {values['pair_oracle']:.2%} | {values[f'{a}_only_correct']} | "
            f"{values[f'{b}_only_correct']} | {'NA' if ec is None else f'{ec:.3f}'} |"
        )
    lines.append("")
    (OUT / "REPORT.md").write_text("\n".join(lines))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
