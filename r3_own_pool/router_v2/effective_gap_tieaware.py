"""Effective gap and tie-aware decision diagnostics on frozen objective-train OOF data.

This is a train-only development experiment. It redefines routing opportunity by
requiring a positive quality margin and evaluates a decision layer that chooses
the cheapest model among near-tied predicted-quality candidates.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from .core import SLOTS, paired_ci
from .data import read_rows, sha
from .diagnose_rank_signal import load_inputs

DEFAULT_EPS = (0.0, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2)
DEFAULT_DELTAS = (0.0, 0.05, 0.1)


def matrix_path_from_source(source):
    protocol = json.loads((source / "PROTOCOL.json").read_text())
    return Path(next(p for p in protocol["input_sha256"] if Path(p).name == "TRAIN_MATRIX.jsonl"))


def cost_latency_for_ids(matrix_path, ids):
    rows = {row["query_id"]: row for row in read_rows(matrix_path)}
    costs = np.zeros((len(ids), len(SLOTS)), dtype=float)
    latencies = np.zeros_like(costs)
    for i, qid in enumerate(ids):
        by_slot = {r["slot"]: r for r in rows[qid]["responses"]}
        for j, slot in enumerate(SLOTS):
            cost = by_slot[slot]["cost"].get("usd")
            latency = by_slot[slot]["latency"].get("total_ms")
            costs[i, j] = np.nan if cost is None else float(cost)
            latencies[i, j] = np.nan if latency is None else float(latency)
    return costs, latencies


def tieaware_choice(pred, costs, eps):
    choices = np.zeros(len(pred), dtype=int)
    for i, row in enumerate(pred):
        best = row.max()
        candidates = np.flatnonzero(row >= best - eps)
        candidate_costs = costs[i, candidates]
        if np.isfinite(candidate_costs).any():
            choices[i] = int(candidates[np.nanargmin(candidate_costs)])
        else:
            choices[i] = int(candidates[0])
    return choices


def chosen(values, choices):
    return values[np.arange(len(values)), choices]


def effective_gap_report(y, choices, baseline, deltas):
    actual = chosen(y, choices)
    base = chosen(y, baseline)
    oracle = y.max(1)
    result = {}
    for delta in deltas:
        mask = (oracle - base) > delta
        gain = actual[mask] - base[mask]
        gap = oracle[mask] - base[mask]
        result[str(delta)] = {
            "opportunity_n": int(mask.sum()),
            "opportunity_rate": float(mask.mean()),
            "conditional_oracle_gap": float(gap.mean()) if mask.any() else None,
            "conditional_gain": float(gain.mean()) if mask.any() else None,
            "conditional_gap_recovery": float(gain.mean() / gap.mean()) if mask.any() and gap.mean() > 1e-12 else None,
            "all_query_effective_gap": float((oracle[mask] - base[mask]).sum() / len(y)),
            "all_query_effective_gain": float((actual[mask] - base[mask]).sum() / len(y)),
        }
    return result


def policy_report(y, costs, latencies, choices, baseline, deltas):
    q = chosen(y, choices)
    c = chosen(costs, choices)
    l = chosen(latencies, choices)
    bq = chosen(y, baseline)
    bc = chosen(costs, baseline)
    bl = chosen(latencies, baseline)
    cost_mask = np.isfinite(c) & np.isfinite(bc)
    latency_mask = np.isfinite(l) & np.isfinite(bl)
    cost_saving = bc[cost_mask] - c[cost_mask]
    latency_delta = l[latency_mask] - bl[latency_mask]
    mean_c = float(c[cost_mask].mean()) if cost_mask.any() else None
    mean_bc = float(bc[cost_mask].mean()) if cost_mask.any() else None
    mean_l = float(l[latency_mask].mean()) if latency_mask.any() else None
    return {
        "quality": float(q.mean()),
        "cost": mean_c,
        "latency_ms": mean_l,
        "cost_evaluable_rate": float(cost_mask.mean()),
        "latency_evaluable_rate": float(latency_mask.mean()),
        "selected_missing_cost_rate": float((~np.isfinite(c)).mean()),
        "quality_delta_vs_baseline": float((q - bq).mean()),
        "quality_delta_ci95": paired_ci(q - bq),
        "cost_saving_vs_baseline": float(cost_saving.mean()) if cost_mask.any() else None,
        "cost_saving_fraction_vs_baseline": float(1.0 - mean_c / mean_bc) if mean_bc else None,
        "latency_delta_ms_vs_baseline": float(latency_delta.mean()) if latency_mask.any() else None,
        "routing_fraction": (np.bincount(choices, minlength=len(SLOTS)) / len(choices)).tolist(),
        "effective_gap": effective_gap_report(y, choices, baseline, deltas),
    }


def pair_margin_report(y, costs, pair, deltas):
    left, right = pair
    diff = y[:, left] - y[:, right]
    cheaper = np.where(costs[:, left] <= costs[:, right], left, right)
    pair_best = np.where(diff >= 0, left, right)
    result = {}
    for delta in deltas:
        stable = np.abs(diff) > delta
        if stable.any():
            stable_best = np.where(diff[stable] > 0, left, right)
            stable_cheaper = cheaper[stable]
            quality_gain_vs_cheaper = y[np.flatnonzero(stable), stable_best] - y[np.flatnonzero(stable), stable_cheaper]
        result[str(delta)] = {
            "stable_n": int(stable.sum()),
            "stable_rate": float(stable.mean()),
            "left_win_rate_when_stable": float((diff[stable] > 0).mean()) if stable.any() else None,
            "pair_oracle_gain_vs_cheaper": float(quality_gain_vs_cheaper.mean()) if stable.any() else None,
            "tie_or_near_tie_rate": float((~stable).mean()),
        }
    return result


def select_eps(reports, max_quality_loss):
    eligible = []
    for key, row in reports.items():
        if not key.startswith("tieaware_eps"):
            continue
        if row["quality_delta_vs_baseline"] >= -max_quality_loss:
            eligible.append((row["cost_saving_fraction_vs_baseline"], key))
    if not eligible:
        return None
    return max(eligible)[1]


def write_report(out, result):
    lines = [
        "# Effective Gap and Tie-Aware Decision",
        "",
        "Scope: frozen original-train objective subset only. Validation and test labels were not loaded.",
        "",
        "## Effective Gap",
        "",
        "Baseline is dataset-best on the same frozen OOF folds.",
        "",
        "| delta | opportunity n | opportunity rate | conditional oracle gap |",
        "|---:|---:|---:|---:|",
    ]
    base_gap = result["policies"]["query_ridge_argmax"]["effective_gap"]
    for delta, row in base_gap.items():
        lines.append(
            f"| {delta} | {row['opportunity_n']} | {100*row['opportunity_rate']:.2f}% | "
            f"{100*row['conditional_oracle_gap']:.2f} pp |"
        )
    lines += [
        "",
        "## Tie-Aware Grid",
        "",
        "| policy | quality | quality delta | cost saving | latency delta | routing small/medium/large/reasoning |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for key, row in result["policies"].items():
        if key == "dataset_best_baseline":
            continue
        route = "/".join(f"{100*x:.1f}" for x in row["routing_fraction"])
        lines.append(
            f"| {key} | {100*row['quality']:.3f}% | {100*row['quality_delta_vs_baseline']:+.3f} pp | "
            f"{100*row['cost_saving_fraction_vs_baseline']:.2f}% | {row['latency_delta_ms_vs_baseline']:+.1f} ms | {route} |"
        )
    chosen = result["selected_tieaware_policy"]
    lines += [
        "",
        f"Selected exploratory policy under max quality loss {100*result['selection']['max_quality_loss']:.2f} pp: `{chosen}`.",
        "",
        "## Large vs Reasoning Effective Pair Gap",
        "",
        "| delta | stable n | stable rate | reasoning win rate when stable | pair oracle gain vs cheaper | near tie rate |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    pair = result["large_vs_reasoning_effective_pair_gap"]
    for delta, row in pair.items():
        left = "NA" if row["left_win_rate_when_stable"] is None else f"{100*row['left_win_rate_when_stable']:.2f}%"
        gain = "NA" if row["pair_oracle_gain_vs_cheaper"] is None else f"{100*row['pair_oracle_gain_vs_cheaper']:.2f} pp"
        lines.append(
            f"| {delta} | {row['stable_n']} | {100*row['stable_rate']:.2f}% | "
            f"{left} | {gain} | {100*row['tie_or_near_tie_rate']:.2f}% |"
        )
    lines += [
        "",
        "Interpretation: tie-aware routing is the right decision-layer change when most apparent winner gaps are ties. Repeat-stability labels remain necessary before treating pairwise stable edges as paper-grade training targets.",
        "",
    ]
    (out / "REPORT.md").write_text("\n".join(lines))


def run(args):
    source = Path(args.source).resolve()
    out = Path(args.output).resolve()
    if out.exists():
        raise FileExistsError(out)
    frozen, _x, _datasets = load_inputs(source)
    ids = frozen["ids"].tolist()
    y = frozen["quality"]
    pred = frozen["predicted_quality"]
    baseline = frozen["DatasetBest"].astype(int)
    matrix_path = matrix_path_from_source(source)
    costs, latencies = cost_latency_for_ids(matrix_path, ids)
    out.mkdir(parents=True, exist_ok=False)
    protocol = {
        "role": "exploratory_train_only_effective_gap_tieaware",
        "source": str(source),
        "source_files": {name: sha(source / name) for name in ("PROTOCOL.json", "RESULTS.json", "OOF.npz")},
        "matrix_sha256": sha(matrix_path),
        "implementation_sha256": sha(__file__),
        "epsilons": args.eps,
        "effective_gap_deltas": args.deltas,
        "selection": f"largest cost saving among tie-aware eps policies with mean quality loss <= {args.max_quality_loss}",
        "limits": [
            "Original train objective subset only; no validation/test labels loaded.",
            "Cost and latency are the existing matrix fields and remain proxy/provenance-limited for local models.",
            "Epsilon is selected on train OOF outcomes for development, not as independent confirmation.",
            "Binary objective scores make delta>0 equivalent to strict accuracy improvement for quality labels.",
        ],
    }
    (out / "PROTOCOL.json").write_text(json.dumps(protocol, indent=2) + "\n")
    choices = {
        "dataset_best_baseline": baseline,
        "query_ridge_argmax": pred.argmax(1).astype(int),
    }
    for eps in args.eps:
        choices[f"tieaware_eps{eps}"] = tieaware_choice(pred, costs, eps)
    reports = {key: policy_report(y, costs, latencies, choice, baseline, args.deltas) for key, choice in choices.items()}
    selected = select_eps(reports, args.max_quality_loss)
    result = {
        "role": protocol["role"],
        "n": int(len(y)),
        "baseline": "dataset_best_baseline",
        "policies": reports,
        "selected_tieaware_policy": selected,
        "selection": {"max_quality_loss": args.max_quality_loss},
        "large_vs_reasoning_effective_pair_gap": pair_margin_report(y, costs, (3, 2), args.deltas),
        "validation_labels_loaded": False,
        "test_labels_loaded": False,
        "files": {"PROTOCOL.json": sha(out / "PROTOCOL.json")},
    }
    np.savez_compressed(out / "CHOICES.npz", ids=frozen["ids"], **choices)
    result["files"]["CHOICES.npz"] = sha(out / "CHOICES.npz")
    (out / "RESULTS.json").write_text(json.dumps(result, indent=2) + "\n")
    write_report(out, result)
    result["files"]["REPORT.md"] = sha(out / "REPORT.md")
    (out / "RESULTS.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in reports.items() if k != "dataset_best_baseline"}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--eps", type=float, nargs="+", default=list(DEFAULT_EPS))
    parser.add_argument("--deltas", type=float, nargs="+", default=list(DEFAULT_DELTAS))
    parser.add_argument("--max-quality-loss", type=float, default=0.005)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
