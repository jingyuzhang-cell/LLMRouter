#!/usr/bin/env python3
"""Offline-only baseline, judge-recovery, and high-variance supplemental audit."""
from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from openclaw_router.judge_utils import parse_judge_payload

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT.parents[1] / "frozen-archives/finance-router-context-v2-1200-final-20260729T072524Z"
RESULT = ARCHIVE / "run_logs/formal_context_v2_rescored_v22_result.json"
QUALITY = ARCHIVE / "run_logs/final_quality_audit.json"
OUT_JSON = ROOT / "run_logs/supplemental_validity_audit.json"
OUT_MD = ROOT / "run_logs/supplemental_validity_audit.md"
OUT_CSV = ROOT / "run_logs/high_variance_manual_review.csv"
BASELINES = (
    "algorithm_automixrouter", "algorithm_dcrouter", "algorithm_graphrouter",
    "algorithm_knnrouter", "fixed_strong",
)


def f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def main():
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    quality = json.loads(QUALITY.read_text(encoding="utf-8"))
    tasks = {row["id"]: row for row in result["sampled_task_set"]}
    raw = result["raw_model_runs"]
    bench = result["routerbench_rows"]

    selections = {}
    reasons = {}
    for strategy in BASELINES:
        rows = [row for row in bench if row.get("strategy_id") == strategy]
        selections[strategy] = dict(Counter(row.get("selected_model") for row in rows))
        reasons[strategy] = dict(Counter(row.get("reason") for row in rows))
    vectors = defaultdict(list)
    for strategy in BASELINES:
        for row in sorted((x for x in bench if x.get("strategy_id") == strategy), key=lambda x: x["task_id"]):
            vectors[tuple([row["task_id"], row.get("selected_model")])].append(strategy)
    expected_first = Counter((task.get("expected") or [None])[0] for task in tasks.values())

    # Frozen outcomes show whether diverse task-wise selection was possible, without
    # pretending that an oracle is a deployable baseline.
    by_task_model = defaultdict(list)
    for row in raw:
        by_task_model[(row["task_id"], row["model"])].append(row)
    oracle = Counter()
    oracle_ties = 0
    for task_id in tasks:
        values = {}
        for (tid, model), rows in by_task_model.items():
            if tid != task_id:
                continue
            values[model] = statistics.mean(f(x.get("quality")) for x in rows)
        best = max(values.values())
        winners = sorted(model for model, value in values.items() if abs(value - best) < 1e-12)
        oracle[winners[0]] += 1
        oracle_ties += len(winners) > 1

    glm_failed = []
    recovered = []
    for row in raw:
        for attempt in row.get("judge_attempts") or []:
            if attempt.get("model") != "glm-5.2" or attempt.get("ok"):
                continue
            text = attempt.get("raw_response") or attempt.get("raw_excerpt") or ""
            parsed = parse_judge_payload(text)
            glm_failed.append({
                "task_id": row["task_id"], "candidate_model": row["model"],
                "stored_chars": len(text), "has_full_raw_response": bool(attempt.get("raw_response")),
                "reparsed": bool(parsed),
            })
            if parsed:
                recovered.append({"task_id": row["task_id"], "candidate_model": row["model"], **parsed})

    variance = quality["three_repeat_variance_audit"]
    flagged = {}
    for kind, source in (
        ("quality", variance["highest_quality_variance"]),
        ("latency", variance["highest_latency_variance"]),
    ):
        threshold_key = "quality_std" if kind == "quality" else "latency_cv"
        threshold = .20 if kind == "quality" else .50
        for item in source:
            if f(item.get(threshold_key)) >= threshold:
                key = (item["task_id"], item["model"])
                flagged.setdefault(key, {**item, "flags": []})["flags"].append(kind)

    # Audit JSON stores only top 20 per category. Recompute all 51 flagged groups.
    groups = defaultdict(list)
    for row in raw:
        groups[(row["task_id"], row["model"])].append(row)
    review_rows = []
    for (task_id, model), rows in sorted(groups.items()):
        if len(rows) != 3:
            continue
        qualities = [f(x.get("quality")) for x in rows]
        latencies = [f(x.get("latency_ms")) for x in rows]
        qstd = statistics.pstdev(qualities)
        lmean = statistics.mean(latencies)
        lcv = statistics.pstdev(latencies) / lmean if lmean else 0
        flags = []
        if qstd >= .20 - 1e-12: flags.append("quality")
        if lcv >= .50 - 1e-12: flags.append("latency")
        if not flags: continue
        task = tasks[task_id]
        review_rows.append({
            "priority": "both" if len(flags) == 2 else flags[0],
            "task_id": task_id, "dataset": task.get("dataset"), "model": model,
            "query": str(task.get("query") or "").replace("\n", " "),
            "quality_values": ";".join(f"{x:.6f}" for x in qualities),
            "quality_mean": round(statistics.mean(qualities), 6), "quality_std": round(qstd, 6),
            "latency_values_ms": ";".join(f"{x:.2f}" for x in latencies),
            "latency_mean_ms": round(lmean, 6), "latency_cv": round(lcv, 6),
            "objective_values": ";".join(str(x.get("objective_score")) for x in rows),
            "judge_disagreement_values": ";".join(str(x.get("judge_disagreement")) for x in rows),
            "response_excerpts": " || ".join(str(x.get("response") or "")[:500].replace("\n", " ") for x in rows),
            "manual_verdict": "", "reviewer_notes": "",
        })
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(review_rows[0]))
        writer.writeheader(); writer.writerows(review_rows)

    report = {
        "report_type": "offline_supplemental_validity_audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "offline_only": True,
        "api_calls": 0,
        "source_archive": str(ARCHIVE),
        "source_result_sha256": hashlib.sha256(RESULT.read_bytes()).hexdigest(),
        "baseline_audit": {
            "selection_counts": selections,
            "expected_first_counts": dict(expected_first),
            "all_five_select_deepseek_for_all_tasks": all(x == {"deepseek-chat": 100} for x in selections.values()),
            "root_cause": "Four named algorithm rows use compatibility simulation; graph/KNN/DC return expected[0], while sampled tasks all have deepseek-chat first. AutoMix also upgrades every sampled high-complexity/verification task to expected[0]. fixed_strong is explicitly deepseek-chat.",
            "trained_router_artifacts_used_in_frozen_run": False,
            "can_relabel_as_independent_baselines": False,
            "oracle_quality_selection_counts": dict(oracle),
            "oracle_tied_tasks": oracle_ties,
            "interpretation": "Frozen outcomes contain model-performance diversity, but the five published rows do not measure five trained routing algorithms. They require separate training/evaluation, not a threshold-only rewrite.",
        },
        "judge_reparse_audit": {
            "glm_failed_attempts": len(glm_failed),
            "stored_full_raw_responses": sum(x["has_full_raw_response"] for x in glm_failed),
            "offline_reparsed": len(recovered),
            "all_failed_text_lengths": dict(Counter(x["stored_chars"] for x in glm_failed)),
            "recoverable_without_api": bool(recovered),
            "root_cause": "The frozen run retained only a 1000-character prefix for failed judge output; prefixes end before the final score/JSON.",
            "future_fix": "Future failed attempts now retain raw_response in local raw logs; raw_excerpt remains for compact audits.",
        },
        "high_variance_review": {
            "rows": len(review_rows),
            "quality_flagged": sum("quality" in row["priority"] or row["priority"] == "both" for row in review_rows),
            "latency_flagged": sum("latency" in row["priority"] or row["priority"] == "both" for row in review_rows),
            "both_flagged": sum(row["priority"] == "both" for row in review_rows),
            "flags_by_model": dict(Counter(row["model"] for row in review_rows)),
            "flags_by_dataset": dict(Counter(str(row["dataset"]) for row in review_rows)),
            "review_packet": str(OUT_CSV.relative_to(ROOT)),
            "manual_adjudication_complete": False,
        },
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 离线补强有效性审计", "", "- API 调用：0", f"- 数据源：`{ARCHIVE}`",
        f"- 结果 SHA256：`{report['source_result_sha256']}`", "", "## 基线有效性",
        "", "- 五个策略均为 DeepSeek Chat 100/100。", f"- sampled_task_set 的 expected 首位：{dict(expected_first)}。",
        "- 根因：四个命名算法行使用兼容模拟而非训练权重；固定强模型显式固定为 DeepSeek。",
        f"- 冻结回答按逐题质量 oracle 的模型分布（仅诊断，不是可部署基线）：{dict(oracle)}；并列任务 {oracle_ties}。",
        "- 结论：不能通过改阈值把原五行追认为独立基线；需另行训练并建立补充实验归档。",
        "", "## Judge 离线重解析", "", f"- GLM 失败：{len(glm_failed)}；保存完整原文：0；离线恢复：{len(recovered)}。",
        "- 现有归档只保留失败输出前 1000 字符，最终 JSON 已丢失；不调用 API 无法恢复 598 个分数。",
        "- 已修复未来记录：解析失败时在本地原始日志保留完整 `raw_response`。",
        "", "## 高方差复核", "", f"- 已生成 {len(review_rows)} 行完整复核包：`{OUT_CSV.relative_to(ROOT)}`。",
        f"- 质量高方差：{report['high_variance_review']['quality_flagged']}；延迟高方差：{report['high_variance_review']['latency_flagged']}；同时命中：{report['high_variance_review']['both_flagged']}。",
        f"- 按模型：{report['high_variance_review']['flags_by_model']}。",
        f"- 按数据集：{report['high_variance_review']['flags_by_dataset']}。",
        "- CSV 含三次质量、objective、Judge 分歧、延迟和回答节选；`manual_verdict` 与 `reviewer_notes` 留待实名人工裁决。",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(OUT_JSON), "markdown": str(OUT_MD), "review_csv": str(OUT_CSV), "report": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
