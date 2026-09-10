"""P2: where does the Oracle-DatasetBest gap live? Descriptive, no training.

Per-dataset decomposition on the clean development OOF inputs: gap in percentage
points, share of the total gap, opportunity-query counts, and how much of each
dataset's gap the Large-vs-Reasoning pair oracle could recover (first-paper
2-model routing scope). Point estimates only; no CI claims, no test labels.
"""
import json
from pathlib import Path

import numpy as np

from .data import load_cohort, sha
from .diagnose_rank_signal import load_inputs

ROOT = Path(__file__).resolve().parents[1]
LARGE, REASONING = 2, 3


def main():
    source = ROOT / "router_v2/objective_verified_20260910"
    out = ROOT / "router_v2/gap_by_task_20260910"
    out.mkdir(exist_ok=True)
    frozen, _, _ = load_inputs(source)
    ids = frozen["ids"]
    y = frozen["quality"]
    db = frozen["DatasetBest"]
    cohort, _ = load_cohort(ROOT / "data/cohort_full_v2")
    datasets = np.array([cohort[q]["dataset"] for q in ids])

    index = np.arange(len(ids))
    baseline = y[index, db]
    oracle = y.max(1)
    gap = oracle - baseline
    pair = np.maximum(y[:, LARGE], y[:, REASONING])
    pair_gain = pair - baseline

    total_gap = gap.sum()
    rows = []
    for name in sorted(set(datasets)):
        m = datasets == name
        rows.append(dict(
            dataset=name, n=int(m.sum()),
            dataset_best_quality=float(baseline[m].mean()),
            oracle_quality=float(oracle[m].mean()),
            gap_pp=float(gap[m].mean() * 100),
            gap_share_pct=float(gap[m].sum() / total_gap * 100),
            opportunity_queries=int((gap[m] > 0).sum()),
            pair_oracle_gain_pp=float(pair_gain[m].mean() * 100),
            pair_gap_queries=int((pair_gain[m] > 0).sum()),
            pair_recovery_of_dataset_gap=float(pair_gain[m].sum() / gap[m].sum()) if gap[m].sum() > 0 else None,
        ))
    overall = dict(
        n=len(ids), dataset_best_quality=float(baseline.mean()), oracle_quality=float(oracle.mean()),
        gap_pp=float(gap.mean() * 100), opportunity_queries=int((gap > 0).sum()),
        pair_oracle_gain_pp=float(pair_gain.mean() * 100), pair_gap_queries=int((pair_gain > 0).sum()),
        pair_recovery_of_total_gap=float(pair_gain.sum() / total_gap),
    )
    report = dict(role="gap_by_task_descriptive", source=str(source),
                  source_results_sha256=sha(source / "RESULTS.json"),
                  slots=("large", "reasoning"), note="2-model pair oracle = max(large, reasoning)",
                  overall=overall, by_dataset=rows, implementation_sha256=sha(Path(__file__)))
    (out / "RESULTS.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    lines = ["# Gap 按任务分解（开发集，描述性）", "",
             f"整体：DatasetBest {overall['dataset_best_quality']*100:.3f}%，Oracle {overall['oracle_quality']*100:.3f}%，"
             f"Gap {overall['gap_pp']:.3f} pp；Large-vs-Reasoning pair oracle 可净回收 {overall['pair_oracle_gain_pp']:.3f} pp"
             f"（总 gap 的 {overall['pair_recovery_of_total_gap']*100:.1f}%）。", "",
             "| 数据集 | n | Gap (pp) | 占总 Gap | 机会题 | Pair 可回收 (pp) | Pair 机会题 | Pair 回收率 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        rec = "—" if r["pair_recovery_of_dataset_gap"] is None else f"{r['pair_recovery_of_dataset_gap']*100:.1f}%"
        lines.append(f"| {r['dataset']} | {r['n']} | {r['gap_pp']:.3f} | {r['gap_share_pct']:.1f}% | "
                     f"{r['opportunity_queries']} | {r['pair_oracle_gain_pp']:.3f} | {r['pair_gap_queries']} | {rec} |")
    lines += ["", "PP 为该数据集内逐题 (Oracle−DatasetBest) 的均值；Pair=双模型取优。描述性统计，无区间，无测试标签。"]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
