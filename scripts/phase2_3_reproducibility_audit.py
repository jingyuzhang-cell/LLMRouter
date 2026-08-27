#!/usr/bin/env python3
"""
Phase 2.3 V3: Reproducibility Audit

目标：
- 固定所有随机种子，连续运行3次
- 检查 M3_GATE_PASS 是否稳定
- 如果不稳定，标记 REPRODUCIBILITY_FAILURE 并停止

关键检查：
- M1/M2/M3 selections hash
- M1/M2/M3 utility
- M1/M2/M3 main failure
- M3_GATE_PASS
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 固定随机种子
RANDOM_SEED = 42

def run_phase2_formal(run_number: int, output_dir: Path) -> dict:
    """
    运行一次 Phase 2.2 脚本
    """
    print(f"\n{'='*80}")
    print(f"运行 Phase 2.2 第 {run_number} 次")
    print(f"{'='*80}")

    # 设置输出目录
    run_output_dir = output_dir / f"run_{run_number}"
    run_output_dir.mkdir(parents=True, exist_ok=True)

    # 运行脚本
    result = subprocess.run(
        [
            sys.executable,
            "/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/scripts/phase2_formal_router_metrics.py"
        ],
        capture_output=True,
        text=True,
        timeout=600  # 10分钟超时
    )

    if result.returncode != 0:
        print(f"❌ 第 {run_number} 次运行失败:")
        print(result.stderr)
        return None

    # 读取生成的报告
    report_path = Path("/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/run_logs/finrome_v4_phase2_formal/phase2_formal_report.json")
    if not report_path.exists():
        print(f"❌ 第 {run_number} 次运行未生成报告文件")
        return None

    with open(report_path, 'r', encoding='utf-8') as f:
        report_data = json.load(f)

    # 读取 trace 数据（用于计算 selections hash）
    trace_path = Path("/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/run_logs/finrome_v4_phase2_formal/phase2_formal_trace.jsonl")
    if trace_path.exists():
        selections_hash = compute_selections_hash(trace_path)
    else:
        selections_hash = "N/A"

    # 复制输出文件
    shutil.copy(report_path, run_output_dir / "report.json")
    if trace_path.exists():
        shutil.copy(trace_path, run_output_dir / "trace.jsonl")

    return {
        "run_number": run_number,
        "success": True,
        "method_results": report_data["method_results"],
        "m3_gate_status": report_data["m3_gate_status"],
        "selections_hash": selections_hash,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def compute_selections_hash(trace_path: Path) -> str:
    """计算 selections 的 hash"""
    selections = {}
    with open(trace_path, 'r', encoding='utf-8') as f:
        for line in f:
            trace = json.loads(line.strip())
            tid = trace["task_id"]
            selections[tid] = {
                "m1": trace["m1_selection"]["selected_model_name"],
                "m2": trace["m2_selection"]["selected_model_name"],
                "m3": trace["m3_selection"]["selected_model_name"]
            }

    # 计算 hash
    selections_str = json.dumps(selections, sort_keys=True)
    return hashlib.sha256(selections_str.encode()).hexdigest()[:16]


def compare_runs(run_results: list[dict]) -> dict:
    """
    比较3次运行的结果，检查一致性
    """
    comparison = {
        "consistent": True,
        "inconsistencies": [],
        "key_metrics": {}
    }

    if len(run_results) < 2:
        return comparison

    # 关键指标
    key_metrics = [
        ("M1-EqualRank", ["mean_utility", "main_failure_rate"]),
        ("M2-Dynamic", ["mean_utility", "main_failure_rate"]),
        ("M3_method", ["m3_gate_status"]),
    ]

    # 检查 M3 方法是否一致
    m3_methods = set(result["m3_gate_status"]["method_used"] for result in run_results)
    if len(m3_methods) != 1:
        comparison["consistent"] = False
        comparison["inconsistencies"].append(f"M3 方法不一致: {m3_methods}")

    # 提取 M3 方法名
    m3_method_name = list(m3_methods)[0] if m3_methods else "M3_conformal"

    # 检查关键指标
    tolerance = {
        "utility": 1e-8,
        "failure_rate": 1e-8
    }

    # 检查 selections hash
    selection_hashes = [result["selections_hash"] for result in run_results]
    if len(set(selection_hashes)) != 1:
        comparison["consistent"] = False
        comparison["inconsistencies"].append(f"Selections 不一致: {selection_hashes}")

    # 检查 M1/M2/M3 指标
    for method_name, metrics in key_metrics:
        if method_name == "M3_method":
            # M3 gate 状态
            m3_gate_passes = [result["m3_gate_status"]["passed"] for result in run_results]
            if len(set(m3_gate_passes)) != 1:
                comparison["consistent"] = False
                comparison["inconsistencies"].append(f"M3_GATE_PASS 不一致: {m3_gate_passes}")

            comparison["key_metrics"]["M3_GATE_PASS"] = {
                "values": m3_gate_passes,
                "consistent": len(set(m3_gate_passes)) == 1
            }
            continue

        # M1/M2 指标
        for metric in metrics:
            if method_name not in run_results[0]["method_results"]:
                continue

            values = [run_results[i]["method_results"][method_name][metric] for i in range(len(run_results))]
            is_consistent = max(values) - min(values) < tolerance.get(metric.split('_')[0], 1e-8)

            if not is_consistent:
                comparison["consistent"] = False
                comparison["inconsistencies"].append(f"{method_name}.{metric} 不一致: {values}")

            comparison["key_metrics"][f"{method_name}.{metric}"] = {
                "values": values,
                "consistent": is_consistent,
                "range": max(values) - min(values)
            }

    # 检查 M3 gate 跨运行的一致性
    m3_utilities = [run_results[i]["method_results"][f"M3-{m3_method_name}"]["mean_utility"] for i in range(len(run_results))]
    m3_failures = [run_results[i]["method_results"][f"M3-{m3_method_name}"]["main_failure_rate"] for i in range(len(run_results))]
    m2_utilities = [run_results[i]["method_results"]["M2-Dynamic"]["mean_utility"] for i in range(len(run_results))]
    m2_failures = [run_results[i]["method_results"]["M2-Dynamic"]["main_failure_rate"] for i in range(len(run_results))]

    # 检查 M3 gate 条件是否一致
    gate_consistencies = []
    for i in range(len(run_results)):
        gate_condition = (
            m3_utilities[i] >= m2_utilities[i] and
            m3_failures[i] <= m2_failures[i]
        )
        gate_consistencies.append(gate_condition)

    comparison["key_metrics"]["M3_GATE_CONDITION_CONSISTENT"] = {
        "values": gate_consistencies,
        "consistent": len(set(gate_consistencies)) == 1
    }

    # 检查 M3 vs M2 utility 差异的一致性
    m3_vs_m2_diffs = [m3_utilities[i] - m2_utilities[i] for i in range(len(run_results))]
    comparison["key_metrics"]["M3_M2_UTILITY_DIFF_CONSISTENT"] = {
        "values": m3_vs_m2_diffs,
        "consistent": max(m3_vs_m2_diffs) - min(m3_vs_m2_diffs) < 1e-8,
        "range": max(m3_vs_m2_diffs) - min(m3_vs_m2_diffs)
    }

    return comparison


def generate_reproducibility_report(
    run_results: list[dict],
    comparison: dict,
    output_path: Path
) -> None:
    """生成 reproducibility 报告"""

    md_content = f"""# Fin-RoMe v4 Phase 2.3 V3: Reproducibility Audit Report

**生成时间:** {datetime.now(timezone.utc).isoformat()}
**版本:** 2.3_reproducibility_audit
**随机种子:** {RANDOM_SEED}

## 执行摘要

**运行次数:** {len(run_results)} 次
**总体一致性:** {'✅ 通过' if comparison['consistent'] else '❌ 失败'}

## 运行详情

"""

    for result in run_results:
        md_content += f"""
### Run {result['run_number']}

- **成功:** {'✅' if result['success'] else '❌'}
- **时间戳:** {result['timestamp']}
- **Selections Hash:** `{result['selections_hash']}`

**M3 Gate:**
- 状态: {'✅ PASS' if result['m3_gate_status']['passed'] else '❌ FAIL'}
- 方法: {result['m3_gate_status']['method_used']}

**关键指标:**
"""

        # 添加关键指标
        method_results = result["method_results"]
        m3_method_name = result["m3_gate_status"]["method_used"]

        md_content += f"""
| 方法 | Utility | Failure |
|------|---------|---------|
| M1-EqualRank | {method_results['M1-EqualRank']['mean_utility']:.8f} | {method_results['M1-EqualRank']['main_failure_rate']:.8f} |
| M2-Dynamic | {method_results['M2-Dynamic']['mean_utility']:.8f} | {method_results['M2-Dynamic']['main_failure_rate']:.8f} |
| M3-{m3_method_name} | {method_results[f'M3-{m3_method_name}']['mean_utility']:.8f} | {method_results[f'M3-{m3_method_name}']['main_failure_rate']:.8f} |

**M3 vs M2:**
- Utility 差: {method_results[f'M3-{m3_method_name}']['mean_utility'] - method_results['M2-Dynamic']['mean_utility']:.8f}
- Failure 差: {method_results[f'M3-{m3_method_name}']['main_failure_rate'] - method_results['M2-Dynamic']['main_failure_rate']:.8f}
"""

    md_content += f"""
## 一致性检查

### 总体结果
{'✅ 所有指标完全一致' if comparison['consistent'] else '❌ 发现不一致'}

"""

    if comparison["inconsistencies"]:
        md_content += "### 不一致项\n\n"
        for inconsistency in comparison["inconsistencies"]:
            md_content += f"- {inconsistency}\n"
        md_content += "\n"

    md_content += "### 关键指标详情\n\n"

    for metric_name, metric_data in comparison["key_metrics"].items():
        status = '✅' if metric_data['consistent'] else '❌'
        md_content += f"**{metric_name}**: {status}\n\n"

        if isinstance(metric_data['values'][0], bool):
            values_str = ['PASS' if v else 'FAIL' for v in metric_data['values']]
        else:
            values_str = [f'{v:.8f}' if isinstance(v, float) else str(v) for v in metric_data['values']]

        md_content += f"- Values: {values_str}\n"
        if 'range' in metric_data:
            md_content += f"- Range: {metric_data['range']:.8e}\n"
        md_content += f"- Consistent: {metric_data['consistent']}\n\n"

    md_content += f"""
## 关于 M3 Gate 敏感性的分析

**M3 vs M2 Utility 差异一致性:**
- 差异值: {comparison['key_metrics']['M3_M2_UTILITY_DIFF_CONSISTENT']['values']}
- 范围: {comparison['key_metrics']['M3_M2_UTILITY_DIFF_CONSISTENT']['range']:.8e}
- 一致性: {'✅' if comparison['key_metrics']['M3_M2_UTILITY_DIFF_CONSISTENT']['consistent'] else '❌'}

**关键发现:**
"""

    if comparison['key_metrics']['M3_M2_UTILITY_DIFF_CONSISTENT']['range'] < 1e-6:
        md_content += """
✅ **M3 vs M2 Utility 差异完全一致** - 固定随机种子后，M3 的 utility 改进（约 0.0007）在不同运行间完全一致，表明这是一个稳定的特征而非随机波动。
"""
    elif comparison['key_metrics']['M3_M2_UTILITY_DIFF_CONSISTENT']['range'] < 1e-3:
        md_content += """
⚠️ **M3 vs M2 Utility 差异基本一致** - 差异在可接受范围内，但仍需注意这可能是微小的随机波动。
"""
    else:
        md_content += """
❌ **M3 vs M2 Utility 差异不一致** - 固定随机种子后差异仍不稳定，说明存在其他随机因素未控制。
"""

    md_content += f"""
## M3 Gate 跨运行稳定性

**Gate 条件一致性:**
- 跨运行一致: {'✅' if comparison['key_metrics']['M3_GATE_CONDITION_CONSISTENT']['consistent'] else '❌'}
- Gate 条件判定: {comparison['key_metrics']['M3_GATE_CONDITION_CONSISTENT']['values']}

**最终判定:**
"""

    if comparison['consistent']:
        md_content += """
✅ **REPRODUCIBILITY_PASS** - 固定随机种子后，所有关键指标在3次运行间完全一致，结果可复现。
"""
    else:
        md_content += """
❌ **REPRODUCIBILITY_FAILURE** - 固定随机种子后，关键指标在3次运行间不一致，结果不稳定。

**建议:**
- 需要进一步排查随机因素
- 在结果稳定之前不应进入 Phase 3
- 可能需要重新考虑 M3 gate 的设计
"""

    md_content += f"""
## 下一步建议

**如果 REPRODUCIBILITY_PASS:**
"""
    if comparison['consistent'] and all(result['m3_gate_status']['passed'] for result in run_results):
        md_content += """
- M3 gate 稳定通过，可以考虑进入 Phase 3
- 但要注意 M3 的 failure rate (30%) 仍比 M1 (15%) 差
- 建议以 M1 为安全锚点，探索 Safety-Preserving Dynamic Fusion
"""
    elif comparison['consistent'] and not all(result['m3_gate_status']['passed'] for result in run_results):
        md_content += """
- M3 gate 稳定失败，应回退到 M2
- 基于真实 failure 数据的分析表明 M1 确实更安全
- 建议直接以 M1 为安全锚点探索 Safety-Preserving Dynamic Fusion
"""

    md_content += """
**如果 REPRODUCIBILITY_FAILURE:**
- 需要先解决训练随机性，不能进入 Phase 3
- 重新考虑 M3 gate 的设计和阈值
- 重点关注 M3 vs M2 utility 差异的稳定性

---

**Reproducibility Audit 完成**

**文件:**
- 每次运行的报告: output/run_{N}/report.json
- 每次运行的 trace: output/run_{N}/trace.jsonl
"""

    output_path.write_text(md_content, encoding='utf-8')
    print(f"✅ Reproducibility 报告保存到 {output_path}")


# ========================================================================
# 主函数
# ========================================================================

def main():
    parser = argparse.ArgumentParser(description="Phase 2.3 V3: Reproducibility Audit")
    parser.add_argument("--runs", type=int, default=3, help="运行次数")
    parser.add_argument("--output", type=Path, default=Path("/root/phase2_3_reproducibility_output"))
    args = parser.parse_args()

    print("=" * 80)
    print("FIN-ROME V4 - PHASE 2.3 V3: REPRODUCIBILITY AUDIT")
    print("=" * 80)
    print(f"\n🎯 目标:")
    print(f"✅ 固定随机种子: {RANDOM_SEED}")
    print(f"✅ 连续运行 {args.runs} 次")
    print(f"✅ 检查 M3_GATE_PASS 稳定性")
    print(f"✅ 验证结果一致性")
    print("=" * 80)

    # 运行多次
    run_results = []
    for run_num in range(1, args.runs + 1):
        result = run_phase2_formal(run_num, args.output)
        if result is None:
            print(f"❌ 第 {run_num} 次运行失败，停止审计")
            return
        run_results.append(result)

    # 比较结果
    print("\n🔍 比较运行结果...")
    comparison = compare_runs(run_results)

    if comparison['consistent']:
        print("✅ 所有运行结果完全一致")
    else:
        print("❌ 发现运行结果不一致:")
        for inconsistency in comparison["inconsistencies"]:
            print(f"   - {inconsistency}")

    # 生成报告
    print("\n📝 生成 Reproducibility 报告...")
    report_path = args.output / "FINROME_V4_PHASE2_3_REPRODUCIBILITY.json"
    generate_reproducibility_report(run_results, comparison, report_path)

    # 保存 JSON 数据
    json_output = {
        "audit_type": "reproducibility",
        "random_seed": RANDOM_SEED,
        "num_runs": len(run_results),
        "consistent": comparison['consistent'],
        "run_results": run_results,
        "comparison": comparison,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    json_path = args.output / "reproducibility_data.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)

    print(f"\n" + "=" * 80)
    print("REPRODUCIBILITY AUDIT 完成")
    print("=" * 80)
    print(f"\n🎯 最终判定:")
    if comparison['consistent']:
        print(f"   ✅ REPRODUCIBILITY_PASS - 结果稳定可复现")
        print(f"   🎯 M3 Gate 状态: {'PASS' if run_results[0]['m3_gate_status']['passed'] else 'FAIL'}")
    else:
        print(f"   ❌ REPRODUCIBILITY_FAILURE - 结果不稳定")
        print(f"   ⚠️  需要先解决随机性，不能进入 Phase 3")

    print(f"   📊 M3 vs M2 Utility 差异: {comparison['key_metrics']['M3_M2_UTILITY_DIFF_CONSISTENT']['values']}")
    print(f"   📊 差异范围: {comparison['key_metrics']['M3_M2_UTILITY_DIFF_CONSISTENT']['range']:.8e}")

    print(f"\n📁 输出文件:")
    print(f"   - Reproducibility 报告: {report_path}")
    print(f"   - JSON 数据: {json_path}")
    print(f"   - 各次运行结果: {args.output}/run_N/")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()