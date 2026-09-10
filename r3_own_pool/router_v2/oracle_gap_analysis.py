"""Oracle gap and winner distribution diagnostics for a response matrix.

This is a label-only audit script. It reads a train matrix, drops queries with
missing or invalid quality labels, and reports the empirical routing opportunity
against best-single baselines. It does not read validation or test labels.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .core import SLOTS
from .data import load_cohort, read_rows, sha
from .integrity import require_valid_quality


ROOT = Path(__file__).resolve().parents[1]


def finite_quality(row):
    by_slot = {r["slot"]: r for r in row["responses"]}
    values = []
    for slot in SLOTS:
        response = by_slot[slot]
        try:
            require_valid_quality(response)
        except Exception:
            return None
        q = response["quality"]["final"]
        if not isinstance(q, (int, float)) or not np.isfinite(q):
            return None
        values.append(float(q))
    return np.asarray(values, dtype=float)


def winner_set(values):
    best = float(np.max(values))
    return tuple(i for i, value in enumerate(values) if abs(float(value) - best) < 1e-12)


def pctile(values, q):
    if len(values) == 0:
        return None
    return float(np.percentile(values, q))


def summarize_block(records, global_best=None):
    if not records:
        return None
    ids = [r["query_id"] for r in records]
    quality = np.vstack([r["quality"] for r in records])
    best_single = int(quality.mean(0).argmax()) if global_best is None else int(global_best)
    best_values = quality[:, best_single]
    oracle = quality.max(1)
    gaps = oracle - best_values

    strict = Counter()
    fractional = defaultdict(float)
    best_set_sizes = []
    for row in quality:
        winners = winner_set(row)
        best_set_sizes.append(len(winners))
        if len(winners) == 1:
            strict[SLOTS[winners[0]]] += 1
        for idx in winners:
            fractional[SLOTS[idx]] += 1.0 / len(winners)

    pair_lr = quality[:, SLOTS.index("large")] - quality[:, SLOTS.index("reasoning")]
    strict_lr = np.abs(pair_lr) > 1e-12
    lr_summary = {
        "strict_n": int(strict_lr.sum()),
        "tie_n": int((~strict_lr).sum()),
        "large_win_rate_among_strict": float((pair_lr[strict_lr] > 0).mean())
        if strict_lr.any()
        else None,
        "reasoning_win_rate_among_strict": float((pair_lr[strict_lr] < 0).mean())
        if strict_lr.any()
        else None,
        "tie_rate": float((~strict_lr).mean()),
    }

    return {
        "n": int(len(records)),
        "ids_sha256": sha_list(ids),
        "best_single_slot": SLOTS[best_single],
        "best_single_quality": float(best_values.mean()),
        "oracle_quality": float(oracle.mean()),
        "gap": {
            "mean": float(gaps.mean()),
            "median": float(np.median(gaps)),
            "p90": pctile(gaps, 90),
            "nonzero_rate": float((gaps > 1e-12).mean()),
        },
        "winner_distribution": {
            "unique_winner_rate": float((np.asarray(best_set_sizes) == 1).mean()),
            "multi_winner_rate": float((np.asarray(best_set_sizes) > 1).mean()),
            "mean_winner_set_size": float(np.mean(best_set_sizes)),
            "strict_counts": {slot: int(strict.get(slot, 0)) for slot in SLOTS},
            "strict_rate_among_all": {
                slot: float(strict.get(slot, 0) / len(records)) for slot in SLOTS
            },
            "strict_rate_among_unique": {
                slot: float(strict.get(slot, 0) / sum(strict.values()))
                if sum(strict.values())
                else None
                for slot in SLOTS
            },
            "fractional_rate": {
                slot: float(fractional.get(slot, 0.0) / len(records)) for slot in SLOTS
            },
        },
        "large_vs_reasoning": lr_summary,
    }


def sha_list(values):
    payload = "\n".join(values).encode("utf-8")
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def load_records(matrix_path, cohort_dir):
    cohort, split = load_cohort(cohort_dir)
    train = set(split["train"])
    records = []
    missing = Counter()
    for row in read_rows(matrix_path):
        if row["query_id"] not in train:
            raise ValueError("Matrix row is outside original train split: " + row["query_id"])
        if row["query"] != cohort[row["query_id"]]["query"]:
            raise ValueError("Prompt mismatch for " + row["query_id"])
        quality = finite_quality(row)
        dataset = row["dataset"]
        if quality is None:
            missing[dataset] += 1
            continue
        records.append(
            {
                "query_id": row["query_id"],
                "dataset": dataset,
                "task_type": row["task_type"],
                "quality": quality,
            }
        )
    return records, dict(missing)


def run(args):
    matrix_path = Path(args.matrix).resolve()
    cohort_dir = Path(args.cohort).resolve()
    out = Path(args.output).resolve()
    if out.exists():
        raise FileExistsError(out)
    records, missing_by_dataset = load_records(matrix_path, cohort_dir)
    by_dataset = defaultdict(list)
    for row in records:
        by_dataset[row["dataset"]].append(row)

    overall = summarize_block(records)
    global_best = SLOTS.index(overall["best_single_slot"])
    dataset_summary = {}
    for dataset in sorted(set(list(by_dataset) + list(missing_by_dataset))):
        local = summarize_block(by_dataset.get(dataset, []))
        against_global = summarize_block(by_dataset.get(dataset, []), global_best=global_best)
        dataset_summary[dataset] = {
            "missing_or_invalid_queries": int(missing_by_dataset.get(dataset, 0)),
            "local_best_single": local,
            "against_overall_best_single": against_global,
        }

    result = {
        "role": "train_only_oracle_gap_and_winner_distribution",
        "matrix": str(matrix_path),
        "matrix_sha256": sha(matrix_path),
        "cohort": str(cohort_dir),
        "cohort_queries_sha256": sha(cohort_dir / "queries.jsonl"),
        "n_complete": int(len(records)),
        "missing_or_invalid_by_dataset": missing_by_dataset,
        "overall": overall,
        "by_dataset": dataset_summary,
        "limits": [
            "Train split only; validation/test labels are not loaded.",
            "Rows with missing or infrastructure-failure labels are excluded rather than imputed as zero.",
            "ArenaHard is reported only if all four model qualities are available under the selected matrix.",
            "Winner distribution reports strict unique winners and tie-fractional winners; no argmax tie breaking is used.",
        ],
    }

    out.mkdir(parents=True)
    (out / "RESULTS.json").write_text(json.dumps(result, indent=2) + "\n")
    write_report(out, result)
    print(json.dumps({"n_complete": len(records), "overall_gap": overall["gap"]}, indent=2))


def fmt_pct(value):
    return "NA" if value is None else f"{100 * value:.2f}%"


def fmt_pp(value):
    return "NA" if value is None else f"{100 * value:.2f} pp"


def write_report(out, result):
    overall = result["overall"]
    lines = [
        "# Oracle Gap And Winner Distribution",
        "",
        "Scope: original train split only. Missing and infrastructure-failure labels are excluded, not converted to zero.",
        "",
        "## Overall",
        "",
        f"- complete queries: {overall['n']}",
        f"- best single: {overall['best_single_slot']} ({fmt_pct(overall['best_single_quality'])})",
        f"- oracle quality: {fmt_pct(overall['oracle_quality'])}",
        f"- mean gap: {fmt_pp(overall['gap']['mean'])}",
        f"- median gap: {fmt_pp(overall['gap']['median'])}",
        f"- p90 gap: {fmt_pp(overall['gap']['p90'])}",
        f"- nonzero opportunity queries: {fmt_pct(overall['gap']['nonzero_rate'])}",
        "",
        "## Dataset Gap",
        "",
        "| dataset | n | missing | local best | oracle | mean gap | median | p90 | nonzero |",
        "|---|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for dataset, row in result["by_dataset"].items():
        local = row["local_best_single"]
        if local is None:
            lines.append(
                f"| {dataset} | 0 | {row['missing_or_invalid_queries']} | NA | NA | NA | NA | NA | NA |"
            )
            continue
        lines.append(
            f"| {dataset} | {local['n']} | {row['missing_or_invalid_queries']} | "
            f"{local['best_single_slot']} | {fmt_pct(local['oracle_quality'])} | "
            f"{fmt_pp(local['gap']['mean'])} | {fmt_pp(local['gap']['median'])} | "
            f"{fmt_pp(local['gap']['p90'])} | {fmt_pct(local['gap']['nonzero_rate'])} |"
        )

    lines += [
        "",
        "## Winner Distribution",
        "",
        "Strict counts exclude ties. Fractional rates split tied winners equally.",
        "",
        "| scope | unique winner | small | medium | large | reasoning | large+reasoning |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    add_winner_line(lines, "overall", overall)
    for dataset, row in result["by_dataset"].items():
        local = row["local_best_single"]
        if local is not None:
            add_winner_line(lines, dataset, local)

    lines += [
        "",
        "## Large Vs Reasoning",
        "",
        "| scope | strict n | ties | large wins among strict | reasoning wins among strict | tie rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    add_lr_line(lines, "overall", overall)
    for dataset, row in result["by_dataset"].items():
        local = row["local_best_single"]
        if local is not None:
            add_lr_line(lines, dataset, local)
    lines += [
        "",
        "Interpretation: routing is worth studying when the mean gap is material after cleaning. The hard part is not whether an oracle opportunity exists, but whether stable query-level compatibility labels can recover it without creating extra wrong switches.",
        "",
    ]
    (out / "REPORT.md").write_text("\n".join(lines))


def add_winner_line(lines, name, block):
    dist = block["winner_distribution"]
    frac = dist["fractional_rate"]
    lines.append(
        f"| {name} | {fmt_pct(dist['unique_winner_rate'])} | "
        f"{fmt_pct(frac['small'])} | {fmt_pct(frac['medium'])} | "
        f"{fmt_pct(frac['large'])} | {fmt_pct(frac['reasoning'])} | "
        f"{fmt_pct(frac['large'] + frac['reasoning'])} |"
    )


def add_lr_line(lines, name, block):
    lr = block["large_vs_reasoning"]
    lines.append(
        f"| {name} | {lr['strict_n']} | {lr['tie_n']} | "
        f"{fmt_pct(lr['large_win_rate_among_strict'])} | "
        f"{fmt_pct(lr['reasoning_win_rate_among_strict'])} | {fmt_pct(lr['tie_rate'])} |"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--cohort", default=str(ROOT / "data/cohort_full_v2"))
    parser.add_argument("--output", required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
