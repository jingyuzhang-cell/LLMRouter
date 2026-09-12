"""Analyze the stratified 180-query model-pool capability screening panel."""
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

from .data import read_rows, sha


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/model_pool_screening_stratified_180"
OUT = ROOT / "router_v2/model_pool_screening_stratified_180"
SLOTS = ["small", "medium", "large", "coder", "math", "reasoning"]
SUBPOOLS = {
    "R1+Large": ["reasoning", "large"],
    "R1+Math": ["reasoning", "math"],
    "R1+Coder": ["reasoning", "coder"],
    "R1+Math+Coder": ["reasoning", "math", "coder"],
    "R1+Large+Math+Coder": ["reasoning", "large", "math", "coder"],
    "Full": SLOTS,
}


def corr(a, b):
    if np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def mean_or_none(values):
    values = [v for v in values if v is not None]
    return float(np.mean(values)) if values else None


def main():
    status = json.loads((DATA / "STATUS.json").read_text())
    if status.get("phase") != "SCREENING_LABELS_COMPLETE":
        raise ValueError(f"Screening incomplete: {status}")
    labels_path = DATA / "SCREENING_LABELS.jsonl"
    if sha(labels_path) != status["labels_sha256"]:
        raise ValueError("Screening labels changed")

    rows = read_rows(labels_path)
    ids = [r["query_id"] for r in rows]
    domains = [r["domain"] for r in rows]
    datasets = [r["dataset"] for r in rows]
    y = np.array([[r["models"][slot]["quality"] for slot in SLOTS] for r in rows], dtype=float)
    costs = np.array([[r["models"][slot]["cost_usd"] or np.nan for slot in SLOTS] for r in rows], dtype=float)
    latency = np.array([[r["models"][slot]["latency_ms"] or np.nan for slot in SLOTS] for r in rows], dtype=float)
    if y.shape != (180, len(SLOTS)) or not np.isfinite(y).all():
        raise ValueError(f"Bad screening matrix shape: {y.shape}")

    means = y.mean(axis=0)
    best_idx = int(np.argmax(means))
    oracle = y.max(axis=1)
    gap = float((oracle - y[:, best_idx]).mean())

    strict_winners = Counter()
    fractional_winners = Counter()
    unique_winners = Counter()
    winner_domain = defaultdict(Counter)
    for i, row in enumerate(y):
        best = row.max()
        winners = [SLOTS[j] for j, value in enumerate(row) if value == best]
        if len(winners) == 1:
            strict_winners[winners[0]] += 1
            winner_domain[winners[0]][domains[i]] += 1
        for slot in winners:
            fractional_winners[slot] += 1.0 / len(winners)
        for j, slot in enumerate(SLOTS):
            if row[j] == 1.0 and np.delete(row, j).max() == 0.0:
                unique_winners[slot] += 1

    quality_by_domain = {}
    for domain in sorted(set(domains)):
        idx = np.array([i for i, d in enumerate(domains) if d == domain], dtype=int)
        quality_by_domain[domain] = {
            "n": int(len(idx)),
            "best": SLOTS[int(np.argmax(y[idx].mean(axis=0)))],
            "oracle": float(y[idx].max(axis=1).mean()),
            "model_quality": {slot: float(y[idx, j].mean()) for j, slot in enumerate(SLOTS)},
        }

    quality_by_dataset = {}
    for dataset in sorted(set(datasets)):
        idx = np.array([i for i, d in enumerate(datasets) if d == dataset], dtype=int)
        quality_by_dataset[dataset] = {
            "n": int(len(idx)),
            "best": SLOTS[int(np.argmax(y[idx].mean(axis=0)))],
            "oracle": float(y[idx].max(axis=1).mean()),
            "model_quality": {slot: float(y[idx, j].mean()) for j, slot in enumerate(SLOTS)},
        }

    r1 = SLOTS.index("reasoning")
    versus_r1 = {}
    for j, slot in enumerate(SLOTS):
        if slot == "reasoning":
            continue
        better = y[:, j] > y[:, r1]
        worse = y[:, j] < y[:, r1]
        tied = y[:, j] == y[:, r1]
        versus_r1[slot] = {
            "better_than_r1": int(better.sum()),
            "worse_than_r1": int(worse.sum()),
            "tie_with_r1": int(tied.sum()),
            "better_by_domain": {d: int((better & (np.array(domains) == d)).sum()) for d in sorted(set(domains))},
        }

    error = 1.0 - y
    correctness_correlation = {}
    error_correlation = {}
    pair_complementarity = {}
    for a, b in combinations(SLOTS, 2):
        ia, ib = SLOTS.index(a), SLOTS.index(b)
        key = f"{a}:{b}"
        correctness_correlation[key] = corr(y[:, ia], y[:, ib])
        error_correlation[key] = corr(error[:, ia], error[:, ib])
        pair_complementarity[key] = {
            "pair_oracle": float(np.maximum(y[:, ia], y[:, ib]).mean()),
            f"{a}_only_correct": int(((y[:, ia] == 1.0) & (y[:, ib] == 0.0)).sum()),
            f"{b}_only_correct": int(((y[:, ib] == 1.0) & (y[:, ia] == 0.0)).sum()),
        }

    subpool_oracle = {}
    r1_oracle = y[:, r1]
    for name, slots in SUBPOOLS.items():
        idx = [SLOTS.index(s) for s in slots]
        values = y[:, idx].max(axis=1)
        subpool_oracle[name] = {
            "slots": slots,
            "oracle": float(values.mean()),
            "gain_vs_r1_pp": float((values - r1_oracle).mean() * 100.0),
            "gain_vs_best_single_pp": float((values - y[:, best_idx]).mean() * 100.0),
        }

    best_per_query_cost = []
    best_per_query_latency = []
    small_near = {}
    small_idx = SLOTS.index("small")
    for eps in [0.0, 0.05, 0.10, 0.20]:
        mask = y[:, small_idx] >= oracle - eps
        chosen_best = []
        for i in range(len(rows)):
            best_slots = np.where(y[i] == oracle[i])[0]
            finite_cost = [(costs[i, j], j) for j in best_slots if np.isfinite(costs[i, j])]
            chosen = min(finite_cost)[1] if finite_cost else int(best_slots[0])
            chosen_best.append(chosen)
            best_per_query_cost.append(costs[i, chosen])
            best_per_query_latency.append(latency[i, chosen])
        best_cost = np.array([costs[i, chosen_best[i]] for i in range(len(rows))])
        best_lat = np.array([latency[i, chosen_best[i]] for i in range(len(rows))])
        small_cost = costs[:, small_idx]
        small_lat = latency[:, small_idx]
        small_near[str(eps)] = {
            "count": int(mask.sum()),
            "ratio": float(mask.mean()),
            "mean_cost_saving_vs_best_quality": mean_or_none((best_cost[mask] - small_cost[mask]).tolist()),
            "mean_latency_saving_ms_vs_best_quality": mean_or_none((best_lat[mask] - small_lat[mask]).tolist()),
            "by_domain": {d: int((mask & (np.array(domains) == d)).sum()) for d in sorted(set(domains))},
        }

    report = {
        "n": len(rows),
        "slots": SLOTS,
        "single_model_accuracy": {slot: float(means[i]) for i, slot in enumerate(SLOTS)},
        "best_single": SLOTS[best_idx],
        "best_single_accuracy": float(means[best_idx]),
        "oracle_accuracy": float(oracle.mean()),
        "oracle_gap_pp": gap * 100.0,
        "quality_by_domain": quality_by_domain,
        "quality_by_dataset": quality_by_dataset,
        "strict_winners": {slot: int(strict_winners[slot]) for slot in SLOTS},
        "fractional_winners": {slot: float(fractional_winners[slot]) for slot in SLOTS},
        "unique_winners": {slot: int(unique_winners[slot]) for slot in SLOTS},
        "winner_domain_distribution": {slot: dict(winner_domain[slot]) for slot in SLOTS},
        "versus_r1": versus_r1,
        "correctness_correlation": correctness_correlation,
        "error_correlation": error_correlation,
        "pair_complementarity": pair_complementarity,
        "subpool_oracle": subpool_oracle,
        "small_near_best": small_near,
        "notes": [
            "Strict winner requires exactly one top-quality model for the query.",
            "Unique winner requires this model correct and every other model wrong.",
            "small_near_best uses quality epsilon on binary task scores; eps=0.0 means tied with the best observed quality.",
        ],
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RESULTS.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    lines = [
        "# Stratified Model Pool Capability Screening 180",
        "",
        f"BestSingle={report['best_single']} ({report['best_single_accuracy']:.2%}); "
        f"Oracle={report['oracle_accuracy']:.2%}; Oracle Gap={report['oracle_gap_pp']:.2f}pp.",
        "",
        "## Domain Quality",
        "",
        "| Domain | n | Best | Oracle | small | medium | large | coder | math | reasoning |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for domain, row in quality_by_domain.items():
        mq = row["model_quality"]
        lines.append(
            f"| {domain} | {row['n']} | {row['best']} | {row['oracle']:.2%} | "
            + " | ".join(f"{mq[s]:.2%}" for s in SLOTS)
            + " |"
        )
    lines += [
        "",
        "## Winners",
        "",
        "| Model | Accuracy | Strict winners | Fractional winners | Unique winners | > R1 | = R1 | < R1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, slot in enumerate(SLOTS):
        vr = versus_r1.get(slot, {"better_than_r1": 0, "tie_with_r1": 180, "worse_than_r1": 0})
        lines.append(
            f"| {slot} | {means[i]:.2%} | {strict_winners[slot]} | {fractional_winners[slot]:.1f} | "
            f"{unique_winners[slot]} | {vr['better_than_r1']} | {vr['tie_with_r1']} | {vr['worse_than_r1']} |"
        )
    lines += [
        "",
        "## Subpool Oracle",
        "",
        "| Subpool | Oracle | Gain vs R1 | Gain vs BestSingle |",
        "|---|---:|---:|---:|",
    ]
    for name, row in subpool_oracle.items():
        lines.append(f"| {name} | {row['oracle']:.2%} | {row['gain_vs_r1_pp']:.2f}pp | {row['gain_vs_best_single_pp']:.2f}pp |")
    lines += [
        "",
        "## 1.5B Near Best",
        "",
        "| Quality epsilon | Count | Ratio | Mean cost saving | Mean latency saving |",
        "|---:|---:|---:|---:|---:|",
    ]
    for eps, row in small_near.items():
        cost = row["mean_cost_saving_vs_best_quality"]
        lat = row["mean_latency_saving_ms_vs_best_quality"]
        lines.append(
            f"| {eps} | {row['count']} | {row['ratio']:.2%} | "
            f"{'NA' if cost is None else f'${cost:.6f}'} | {'NA' if lat is None else f'{lat:.1f} ms'} |"
        )
    lines += [
        "",
        "## Pairwise Complementarity",
        "",
        "| Pair | Pair oracle | Left-only | Right-only | Correct corr | Error corr |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for pair, values in sorted(pair_complementarity.items(), key=lambda kv: kv[1]["pair_oracle"], reverse=True):
        a, b = pair.split(":")
        cc = correctness_correlation[pair]
        ec = error_correlation[pair]
        lines.append(
            f"| {pair} | {values['pair_oracle']:.2%} | {values[f'{a}_only_correct']} | "
            f"{values[f'{b}_only_correct']} | {'NA' if cc is None else f'{cc:.3f}'} | "
            f"{'NA' if ec is None else f'{ec:.3f}'} |"
        )
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
