#!/usr/bin/env python3
"""Generate the final offline quality audit from frozen experiment artifacts."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESCORED = ROOT / "run_logs/formal_context_v2_rescored_v22_result.json"
RESULT = RESCORED if RESCORED.exists() else ROOT / "run_logs/formal_context_v2_resumed_result.json"
CHECKPOINT = ROOT / "run_logs/llmrouter_experiment_checkpoint_v2.jsonl"
PROGRESS = ROOT / "run_logs/llmrouter_experiment_progress_v2.json"
JUDGE = ROOT / "run_logs/judge_calibration_analysis.json"
POSTHOC = ROOT / "run_logs/posthoc_quality_audit.json"
OUT = ROOT / "run_logs/final_quality_audit.json"
OUT_MD = ROOT / "run_logs/final_quality_audit.md"


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def percentile(values, q):
    values = sorted(number(value) for value in values)
    if not values:
        return 0.0
    position = (len(values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return values[low]
    return values[low] * (high - position) + values[high] * (position - low)


def distribution(values):
    values = [number(value) for value in values]
    q1, q3 = percentile(values, .25), percentile(values, .75)
    fence = q3 + 1.5 * (q3 - q1)
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 6) if values else 0,
        "p50": round(percentile(values, .5), 6),
        "p95": round(percentile(values, .95), 6),
        "p99": round(percentile(values, .99), 6),
        "max": round(max(values), 6) if values else 0,
        "iqr_upper_fence": round(fence, 6),
        "iqr_high_outlier_count": sum(value > fence for value in values),
    }


def case(record):
    return {
        "task_id": record.get("task_id"),
        "model": record.get("model"),
        "repeat": record.get("repeat"),
        "quality": number(record.get("quality")),
        "objective_score": record.get("objective_score"),
        "judge_disagreement": number(record.get("judge_disagreement")),
        "manual_review_required": bool(record.get("manual_review_required")),
        "latency_ms": number(record.get("latency_ms")),
        "raw_cost_usd": number(record.get("raw_cost_usd")),
    }


def main():
    progress = json.loads(PROGRESS.read_text())
    result = json.loads(RESULT.read_text())
    judge_report = json.loads(JUDGE.read_text())
    posthoc_report = json.loads(POSTHOC.read_text()) if POSTHOC.exists() else {}
    signature = progress["signature"]
    checkpoint = [json.loads(line) for line in CHECKPOINT.read_text().splitlines() if line.strip()]
    current = [row for row in checkpoint if row.get("signature") == signature]
    successful = [row for row in current if (row.get("result") or {}).get("ok") is True]
    failed = [row for row in current if (row.get("result") or {}).get("ok") is not True]
    raw = result["raw_model_runs"]
    key = lambda row: (row.get("task_id"), row.get("model"), row.get("repeat"))

    histories = defaultdict(list)
    for row in current:
        histories[key(row)].append(row)
    failed_keys = {key(row) for row in failed}
    recovered_keys = {item for item in failed_keys if any((row.get("result") or {}).get("ok") is True for row in histories[item])}
    error_types = Counter(str((row.get("result") or {}).get("error") or "unknown") for row in failed)
    failed_by_model = Counter(str(row.get("model")) for row in failed)
    failed_by_hour = Counter(datetime.fromtimestamp(number(row.get("saved_at")), timezone.utc).strftime("%Y-%m-%dT%H:00Z") for row in failed)
    api_audit = {
        "failed_attempts": len(failed),
        "failed_unique_calls": len(failed_keys),
        "recovered_unique_calls": len(recovered_keys),
        "retry_recovery_rate": round(len(recovered_keys) / max(1, len(failed_keys)), 6),
        "final_failed_calls": sum(not any((row.get("result") or {}).get("ok") is True for row in rows) for rows in histories.values()),
        "error_types": dict(error_types.most_common()),
        "failed_attempts_by_model": dict(failed_by_model),
        "failed_attempts_by_utc_hour": dict(sorted(failed_by_hour.items())),
        "attempts_per_call": dict(sorted(Counter(len(rows) for rows in histories.values()).items())),
        "max_attempts_per_call": max(map(len, histories.values())),
    }

    attempts = Counter()
    parsed = Counter()
    failed_judges = Counter()
    fallback_responses = 0
    for row in raw:
        judge_attempts = row.get("judge_attempts") or []
        fallback_responses += len(judge_attempts) > 2
        for attempt in judge_attempts:
            model = str(attempt.get("model") or "unknown")
            attempts[model] += 1
            parsed[model] += bool(attempt.get("ok"))
            failed_judges[model] += not bool(attempt.get("ok"))
    dual_coverage = sum(len(row.get("judge_scores") or []) >= 2 for row in raw)
    judge_audit = {
        "attempts_by_judge": {model: {"attempts": attempts[model], "parsed": parsed[model], "failed": failed_judges[model], "parse_rate": round(parsed[model] / max(1, attempts[model]), 6)} for model in sorted(attempts)},
        "glm_parse_summary": {"parsed": parsed["glm-5.2"], "attempts": attempts["glm-5.2"], "parse_rate": round(parsed["glm-5.2"] / max(1, attempts["glm-5.2"]), 6)},
        "responses_requiring_fallback_judge": fallback_responses,
        "fallback_response_rate": round(fallback_responses / len(raw), 6),
        "dual_valid_judge_results": dual_coverage,
        "dual_valid_judge_coverage": round(dual_coverage / len(raw), 6),
        "fallback_preserved_dual_coverage": dual_coverage >= 1198,
        "objective_calibration": judge_report.get("objective_calibration"),
        "interpretation": "GLM judge parsing failed on nearly all attempts; fallback judges preserved final result-level dual coverage. GLM must not be described as a valid scoring contributor.",
    }

    zero = [row for row in raw if number(row.get("quality")) == 0]
    one = [row for row in raw if number(row.get("quality")) == 1]
    disagreement = [row for row in raw if number(row.get("judge_disagreement")) >= .20 - 1e-12]
    manual = [row for row in raw if row.get("manual_review_required")]
    anomaly_audit = {
        "zero_quality_count": len(zero),
        "full_quality_count": len(one),
        "judge_disagreement_ge_0_20_count": len(disagreement),
        "manual_review_required_count": len(manual),
        "zero_quality_examples": [case(row) for row in sorted(zero, key=lambda row: (-number(row.get("judge_disagreement")), str(row.get("task_id"))))[:20]],
        "full_quality_examples": [case(row) for row in sorted(one, key=lambda row: (-number(row.get("judge_disagreement")), str(row.get("task_id"))))[:20]],
        "highest_disagreement_examples": [case(row) for row in sorted(raw, key=lambda row: (-number(row.get("judge_disagreement")), str(row.get("task_id"))))[:20]],
        "manual_review_examples": [case(row) for row in sorted(manual, key=lambda row: (-number(row.get("judge_disagreement")), str(row.get("task_id"))))[:20]],
    }

    model_counts = Counter(str(row.get("model")) for row in raw)
    balance_by_model = {}
    for model in sorted(model_counts):
        rows = [row for row in raw if row.get("model") == model]
        balance_by_model[model] = {
            "final_results": len(rows),
            "latency_ms": distribution([row.get("latency_ms") for row in rows]),
            "raw_cost_usd": distribution([row.get("raw_cost_usd") for row in rows]),
        }
    balance_audit = {
        "model_counts": dict(model_counts),
        "balanced_300_each": len(model_counts) == 4 and set(model_counts.values()) == {300},
        "by_model": balance_by_model,
        "global_latency_ms": distribution([row.get("latency_ms") for row in raw]),
        "global_raw_cost_usd": distribution([row.get("raw_cost_usd") for row in raw]),
        "top_latency_outliers": [case(row) for row in sorted(raw, key=lambda row: number(row.get("latency_ms")), reverse=True)[:20]],
        "top_cost_outliers": [case(row) for row in sorted(raw, key=lambda row: number(row.get("raw_cost_usd")), reverse=True)[:20]],
    }

    repeats = defaultdict(list)
    for row in raw:
        repeats[(str(row.get("task_id")), str(row.get("model")))].append(row)
    repeat_rows = []
    for (task_id, model), rows in repeats.items():
        qualities = [number(row.get("quality")) for row in rows]
        latencies = [number(row.get("latency_ms")) for row in rows]
        costs = [number(row.get("raw_cost_usd")) for row in rows]
        repeat_rows.append({
            "task_id": task_id,
            "model": model,
            "n": len(rows),
            "quality_mean": round(statistics.mean(qualities), 6),
            "quality_std": round(statistics.pstdev(qualities), 6),
            "latency_mean_ms": round(statistics.mean(latencies), 6),
            "latency_std_ms": round(statistics.pstdev(latencies), 6),
            "latency_cv": round(statistics.pstdev(latencies) / max(statistics.mean(latencies), 1e-12), 6),
            "cost_mean_usd": round(statistics.mean(costs), 10),
            "cost_std_usd": round(statistics.pstdev(costs), 10),
            "cost_cv": round(statistics.pstdev(costs) / max(statistics.mean(costs), 1e-12), 6),
        })
    variance_audit = {
        "task_model_groups": len(repeat_rows),
        "all_groups_have_three_repeats": all(row["n"] == 3 for row in repeat_rows),
        "quality_std_ge_0_20_count": sum(row["quality_std"] >= .20 for row in repeat_rows),
        "latency_cv_ge_0_50_count": sum(row["latency_cv"] >= .50 for row in repeat_rows),
        "cost_cv_ge_0_50_count": sum(row["cost_cv"] >= .50 for row in repeat_rows),
        "highest_quality_variance": sorted(repeat_rows, key=lambda row: (-row["quality_std"], row["task_id"], row["model"]))[:20],
        "highest_latency_variance": sorted(repeat_rows, key=lambda row: (-row["latency_cv"], row["task_id"], row["model"]))[:20],
        "highest_cost_variance": sorted(repeat_rows, key=lambda row: (-row["cost_cv"], row["task_id"], row["model"]))[:20],
    }
    scorer_audit = posthoc_report.get("objective_scorer_audit") or {}
    scorer_drift_count = int(scorer_audit.get("changed_records") or 0)
    rescoring = result.get("posthoc_rescoring") or {}
    scorer_drift_resolved = rescoring.get("scorer_version") == scorer_audit.get("new_version") and int(rescoring.get("changed_records") or 0) == scorer_drift_count

    gates = {
        "experiment_completed_1200_of_1200": progress.get("status") == "completed" and progress.get("completed") == progress.get("total") == 1200,
        "result_has_1200_unique_successes": len(raw) == len({key(row) for row in raw}) == 1200 and all(row.get("ok") is True for row in raw),
        "all_failed_calls_recovered": api_audit["final_failed_calls"] == 0 and api_audit["retry_recovery_rate"] == 1,
        "balanced_model_calls": balance_audit["balanced_300_each"],
        "complete_three_repeat_groups": variance_audit["task_model_groups"] == 400 and variance_audit["all_groups_have_three_repeats"],
        "dual_judge_coverage_at_least_99_percent": judge_audit["dual_valid_judge_coverage"] >= .99,
        "glm_judge_limitation_disclosed": judge_audit["glm_parse_summary"]["parsed"] == 3 and judge_audit["glm_parse_summary"]["attempts"] == 601,
        "objective_scorer_drift_resolved": scorer_drift_resolved,
    }
    report = {
        "report_type": "final_quality_audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signature": signature,
        "source_result_sha256": hashlib.sha256(RESULT.read_bytes()).hexdigest(),
        "raw_responses_included": False,
        "api_audit": api_audit,
        "judge_audit": judge_audit,
        "score_anomaly_audit": anomaly_audit,
        "call_balance_and_outliers": balance_audit,
        "three_repeat_variance_audit": variance_audit,
        "objective_scorer_drift_audit": {
            "scorer_version": scorer_audit.get("new_version"),
            "changed_records": scorer_drift_count,
            "up": scorer_audit.get("up"),
            "down": scorer_audit.get("down"),
            "rescoring_metadata": rescoring,
            "requires_offline_metric_recomputation": not scorer_drift_resolved,
            "interpretation": scorer_audit.get("interpretation"),
        },
        "quality_gates": gates,
        "passed": all(gates.values()),
        "warnings": [
            "GLM judge parsing succeeded for only 3/601 attempts; fallback judges, not GLM, supplied valid replacement scores.",
            "Equivalent routing baselines identified in final_paper_analysis must not be interpreted as independent evidence.",
            "Zero/full scores and high-variance groups listed here require paper caveats or targeted manual review; raw response text remains excluded.",
            f"Objective scorer {scorer_audit.get('new_version') or 'post-hoc audit'} changes {scorer_drift_count}/1200 records; strategy metrics and significance must be recomputed before paper claims are final.",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    lines = [
        "# 最终质量审计",
        "",
        f"- 总体门禁：{'通过' if report['passed'] else '未通过'}",
        f"- 实验签名：`{signature}`",
        f"- 最终成功结果：{len(raw)}/1200",
        f"- 历史失败尝试：{len(failed)}；涉及 {len(failed_keys)} 个调用；最终恢复率 {api_audit['retry_recovery_rate']:.2%}",
        f"- 模型分布：{dict(model_counts)}",
        "",
        "## API 审计",
        "",
        f"- 错误类型：{dict(error_types.most_common())}",
        f"- 失败模型分布：{dict(failed_by_model)}",
        f"- 单调用尝试次数分布：{api_audit['attempts_per_call']}；最大 {api_audit['max_attempts_per_call']} 次",
        f"- 最终未恢复调用：{api_audit['final_failed_calls']}",
        "",
        "## Judge 审计",
        "",
        f"- GLM Judge 解析：{parsed['glm-5.2']}/{attempts['glm-5.2']} ({judge_audit['glm_parse_summary']['parse_rate']:.2%})",
        f"- 触发 fallback：{fallback_responses}/{len(raw)} ({judge_audit['fallback_response_rate']:.2%})",
        f"- 最终双有效 Judge 覆盖：{dual_coverage}/{len(raw)} ({judge_audit['dual_valid_judge_coverage']:.2%})",
        "- 结论：GLM 不得表述为有效评分贡献者；最终覆盖由 fallback Judge 保持。",
        "",
        "## 异常分数",
        "",
        f"- 零质量分：{len(zero)}",
        f"- 满质量分：{len(one)}",
        f"- Judge 分歧 ≥ 0.20：{len(disagreement)}",
        f"- 标记人工复核：{len(manual)}",
        "- 具体任务 ID 和统计值见 JSON；未复制原始回答。",
        "",
        "## 调用均衡与异常值",
        "",
        f"- 四模型各 300 条：{balance_audit['balanced_300_each']}",
        f"- 全局延迟 P50/P95/P99/最大值：{balance_audit['global_latency_ms']['p50']:.1f}/{balance_audit['global_latency_ms']['p95']:.1f}/{balance_audit['global_latency_ms']['p99']:.1f}/{balance_audit['global_latency_ms']['max']:.1f} ms",
        f"- 全局成本 P50/P95/P99/最大值：{balance_audit['global_raw_cost_usd']['p50']:.6f}/{balance_audit['global_raw_cost_usd']['p95']:.6f}/{balance_audit['global_raw_cost_usd']['p99']:.6f}/{balance_audit['global_raw_cost_usd']['max']:.6f} USD",
        "",
        "## 三重复方差",
        "",
        f"- 任务-模型组：{len(repeat_rows)}；全部含 3 次重复：{variance_audit['all_groups_have_three_repeats']}",
        f"- 质量标准差 ≥ 0.20：{variance_audit['quality_std_ge_0_20_count']} 组",
        f"- 延迟 CV ≥ 0.50：{variance_audit['latency_cv_ge_0_50_count']} 组",
        f"- 成本 CV ≥ 0.50：{variance_audit['cost_cv_ge_0_50_count']} 组",
        "- 各类最高波动 20 组见 JSON。",
        "",
        "## Objective 评分器漂移",
        "",
        f"- 后验评分器版本：{scorer_audit.get('new_version')}",
        f"- 会改变的记录：{scorer_drift_count}/1200（上调 {scorer_audit.get('up')}，下调 {scorer_audit.get('down')}）",
        f"- 已应用至独立重评分结果：{scorer_drift_resolved}",
        f"- 需要离线重算策略指标与显著性：{not scorer_drift_resolved}",
        "",
        "## 门禁与限制",
        "",
    ]
    lines.extend(f"- {name}: {value}" for name, value in gates.items())
    lines.extend(["", "### 必须披露", ""] + [f"- {warning}" for warning in report["warnings"]])
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(json.dumps({"json": str(OUT), "markdown": str(OUT_MD), "passed": report["passed"], "quality_gates": gates}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
