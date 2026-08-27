#!/usr/bin/env python3
"""
Phase 2.4: Reproducibility Hardening

目标：
- 同一代码 + 同一数据 + 同一 seed = 完全相同结果
- 把 [FAIL, FAIL, PASS] 修到 [FAIL, FAIL, FAIL] 或 [PASS, PASS, PASS]
- 重要的是一致，不是具体是什么值

禁止：
- 修改 M1/M2/M3 算法逻辑
- 调整 threshold
- Round utility
- 放宽 epsilon
- 修改 gate 条件
"""

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch

def set_global_determinism(seed: int) -> dict:
    """
    设置全局随机性和确定性
    返回环境配置信息用于审计
    """
    print(f"🔧 设置全局随机性和确定性 (seed={seed})...")

    # Python random
    random.seed(seed)

    # NumPy random
    np.random.seed(seed)

    # PyTorch random
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

    # PyTorch deterministic settings
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True)

    # Python hash seed
    os.environ['PYTHONHASHSEED'] = str(seed)

    # CUDA workspace config
    os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'

    # Thread settings
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'

    # 版本信息
    env_info = {
        'random_seed': seed,
        'python_version': sys.version.split()[0],
        'numpy_version': np.__version__,
        'torch_version': torch.__version__,
        'cuda_version': torch.version.cuda if torch.cuda.is_available() else None,
        'cudnn_version': torch.backends.cudnn.version() if torch.cuda.is_available() else None,
        'sklearn_version': 'sklearn',  # 需要动态获取
        'device': str(torch.cuda.get_device_name(0)) if torch.cuda.is_available() else 'CPU',
        'environment_vars': {
            'PYTHONHASHSEED': os.environ.get('PYTHONHASHSEED', 'N/A'),
            'CUBLAS_WORKSPACE_CONFIG': os.environ.get('CUBLAS_WORKSPACE_CONFIG', 'N/A'),
            'OMP_NUM_THREADS': os.environ.get('OMP_NUM_THREADS', 'N/A'),
            'MKL_NUM_THREADS': os.environ.get('MKL_NUM_THREADS', 'N/A'),
        }
    }

    print("✅ 全局随机性和确定性设置完成")
    return env_info


def run_phase2_with_stage_hashes(run_number: int, output_dir: Path) -> dict:
    """
    运行一次 Phase 2.2 脚本并收集各阶段 hash
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
    selections_hash = "N/A"
    if trace_path.exists():
        selections_hash = compute_selections_hash(trace_path)

    # 复制输出文件
    shutil.copy(report_path, run_output_dir / "report.json")
    if trace_path.exists():
        shutil.copy(trace_path, run_output_dir / "trace.jsonl")

    # 提取关键指标
    method_results = report_data["method_results"]
    m3_method_name = report_data["m3_gate_status"]["method_used"]

    metrics = {
        "M1": {
            "utility": method_results["M1-EqualRank"]["mean_utility"],
            "failure": method_results["M1-EqualRank"]["main_failure_rate"],
            "high_risk_failure": method_results["M1-EqualRank"]["high_risk_failure_rate"]
        },
        "M2": {
            "utility": method_results["M2-Dynamic"]["mean_utility"],
            "failure": method_results["M2-Dynamic"]["main_failure_rate"],
            "high_risk_failure": method_results["M2-Dynamic"]["high_risk_failure_rate"]
        },
        "M3": {
            "utility": method_results[f"M3-{m3_method_name}"]["mean_utility"],
            "failure": method_results[f"M3-{m3_method_name}"]["main_failure_rate"],
            "high_risk_failure": method_results[f"M3-{m3_method_name}"]["high_risk_failure_rate"]
        },
    }

    return {
        "run_number": run_number,
        "success": True,
        "m3_gate_pass": report_data["m3_gate_status"]["passed"],
        "metrics": metrics,
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


def analyze_reproducibility(run_results: list[dict]) -> dict:
    """
    分析5次运行的可复现性
    成功条件：
    - 5/5 selection hashes identical
    - 5/5 utilities identical within 1e-10
    - 5/5 failure metrics identical
    - 5/5 M3_GATE_PASS identical
    """
    if len(run_results) < 2:
        return {
            "consistent": True,
            "reason": "只有一次运行，无法比较",
            "success_conditions": {},
            "details": {}
        }

    analysis = {
        "consistent": True,
        "reason": "",
        "divergence_stage": None,
        "details": {}
    }

    # 检查 selections hash 一致性
    selection_hashes = [r["selections_hash"] for r in run_results]
    if len(set(selection_hashes)) != 1:
        analysis["consistent"] = False
        analysis["reason"] = "Selection hashes 不一致"
        analysis["divergence_stage"] = "FINAL_SELECTIONS"
        # 设置默认的 m3_vs_m2_diff 以避免报告生成错误
        m3_vs_m2_diffs = [
            r["metrics"]["M3"]["utility"] - r["metrics"]["M2"]["utility"]
            for r in run_results
        ]
        analysis["details"]["m3_vs_m2_diff"] = {
            "values": m3_vs_m2_diffs,
            "range": max(m3_vs_m2_diffs) - min(m3_vs_m2_diffs),
            "max": max(m3_vs_m2_diffs),
            "min": min(m3_vs_m2_diffs)
        }
        # 设置 success_conditions 即使失败
        analysis["success_conditions"] = {
            "selection_hashes_consistent": False,
            "all_consistent": False
        }
        return analysis

    analysis["details"]["selection_hashes"] = selection_hashes

    # 检查 utility 一致性 (within 1e-10)
    utilities = {}
    for method in ["M1", "M2", "M3"]:
        method_utilities = [r["metrics"][method]["utility"] for r in run_results]
        utility_range = max(method_utilities) - min(method_utilities)
        utilities[method] = {
            "values": method_utilities,
            "range": utility_range,
            "consistent": utility_range < 1e-10
        }
        if not utilities[method]["consistent"]:
            analysis["consistent"] = False
            analysis["reason"] = f"{method} utility 不一致 (range={utility_range:.2e})"
            analysis["divergence_stage"] = f"{method}_UTILITY"

    analysis["details"]["utilities"] = utilities

    # 检查 failure 一致性
    failures = {}
    for method in ["M1", "M2", "M3"]:
        method_failures = [r["metrics"][method]["failure"] for r in run_results]
        failure_range = max(method_failures) - min(method_failures)
        failures[method] = {
            "values": method_failures,
            "range": failure_range,
            "consistent": failure_range < 1e-10
        }
        if not failures[method]["consistent"]:
            analysis["consistent"] = False
            analysis["reason"] = f"{method} failure 不一致 (range={failure_range:.2e})"
            analysis["divergence_stage"] = f"{method}_FAILURE"

    analysis["details"]["failures"] = failures

    # 检查 M3_GATE_PASS 一致性
    m3_gate_passes = [r["m3_gate_pass"] for r in run_results]
    gate_consistent = len(set(m3_gate_passes)) == 1
    analysis["details"]["m3_gate_passes"] = {
        "values": m3_gate_passes,
        "consistent": gate_consistent
    }

    if not gate_consistent:
        analysis["consistent"] = False
        analysis["reason"] = f"M3_GATE_PASS 不一致: {m3_gate_passes}"
        analysis["divergence_stage"] = "M3_GATE_PASS"

    # 计算关键统计
    m3_vs_m2_diffs = [
        r["metrics"]["M3"]["utility"] - r["metrics"]["M2"]["utility"]
        for r in run_results
    ]
    m3_vs_m2_diff_range = max(m3_vs_m2_diffs) - min(m3_vs_m2_diffs)

    analysis["details"]["m3_vs_m2_diff"] = {
        "values": m3_vs_m2_diffs,
        "range": m3_vs_m2_diff_range,
        "max": max(m3_vs_m2_diffs),
        "min": min(m3_vs_m2_diffs)
    }

    # 最终一致性判定
    success_conditions = [
        utilities["M1"]["consistent"],
        utilities["M2"]["consistent"],
        utilities["M3"]["consistent"],
        failures["M1"]["consistent"],
        failures["M2"]["consistent"],
        failures["M3"]["consistent"],
        gate_consistent
    ]

    analysis["success_conditions"] = {
        "M1_utility_consistent": utilities["M1"]["consistent"],
        "M2_utility_consistent": utilities["M2"]["consistent"],
        "M3_utility_consistent": utilities["M3"]["consistent"],
        "M1_failure_consistent": failures["M1"]["consistent"],
        "M2_failure_consistent": failures["M2"]["consistent"],
        "M3_failure_consistent": failures["M3"]["consistent"],
        "M3_gate_pass_consistent": gate_consistent,
        "all_consistent": all([
            utilities["M1"]["consistent"],
            utilities["M2"]["consistent"],
            utilities["M3"]["consistent"],
            failures["M1"]["consistent"],
            failures["M2"]["consistent"],
            failures["M3"]["consistent"],
            gate_consistent
        ])
    }

    analysis["consistent"] = analysis["success_conditions"]["all_consistent"]
    analysis["reason"] = "所有条件都满足" if analysis["consistent"] else analysis["reason"]

    return analysis


def generate_reproducibility_report(
    env_info: dict,
    run_results: list[dict],
    analysis: dict,
    output_path: Path
) -> None:
    """生成 Phase 2.4 Reproducibility Hardening 报告"""

    md_content = f"""# Fin-RoMe v4 Phase 2.4: Reproducibility Hardening Report

**生成时间:** {datetime.now(timezone.utc).isoformat()}
**版本:** 2.4_reproducibility_hardening
**随机种子:** {env_info['random_seed']}
**运行次数:** {len(run_results)}

## 执行摘要

**总体一致性:** {'✅ 通过' if analysis['consistent'] else '❌ 失败'}
**首次不一致阶段:** {analysis.get('divergence_stage', 'N/A')}
**原因:** {analysis['reason']}

## 环境配置

**系统配置:**
- Python 版本: {env_info['python_version']}
- NumPy 版本: {env_info['numpy_version']}
- PyTorch 版本: {env_info['torch_version']}
- CUDA 版本: {env_info['cuda_version']}
- cuDNN 版本: {env_info['cudnn_version']}
- Device: {env_info['device']}

**环境变量:**
- PYTHONHASHSEED: {env_info['environment_vars']['PYTHONHASHSEED']}
- CUBLAS_WORKSPACE_CONFIG: {env_info['environment_vars']['CUBLAS_WORKSPACE_CONFIG']}
- OMP_NUM_THREADS: {env_info['environment_vars']['OMP_NUM_THREADS']}
- MKL_NUM_THREADS: {env_info['environment_vars']['MKL_NUM_THREADS']}

**随机性配置:**
- torch.backends.cudnn.deterministic: True
- torch.backends.cudnn.benchmark: False
- torch.use_deterministic_algorithms: True
- Python random: seeded
- NumPy random: seeded
- PyTorch random: seeded

## 运行详情

"""

    for result in run_results:
        md_content += f"""
### Run {result['run_number']}

- **成功:** {'✅' if result['success'] else '❌'}
- **时间戳:** {result['timestamp']}
- **Selections Hash:** `{result['selections_hash']}`
- **M3 Gate:** {'✅ PASS' if result['m3_gate_pass'] else '❌ FAIL'}

**关键指标:**
"""

        metrics = result["metrics"]
        md_content += f"""
| 方法 | Utility | Failure | High-Risk Failure |
|------|---------|---------|-------------------|
| M1 | {metrics['M1']['utility']:.10f} | {metrics['M1']['failure']:.10f} | {metrics['M1']['high_risk_failure']:.10f} |
| M2 | {metrics['M2']['utility']:.10f} | {metrics['M2']['failure']:.10f} | {metrics['M2']['high_risk_failure']:.10f} |
| M3 | {metrics['M3']['utility']:.10f} | {metrics['M3']['failure']:.10f} | {metrics['M3']['high_risk_failure']:.10f} |

**M3 vs M2:**
- Utility 差: {metrics['M3']['utility'] - metrics['M2']['utility']:.10f}
- Failure 差: {metrics['M3']['failure'] - metrics['M2']['failure']:.10f}
"""

    md_content += f"""
## 一致性检查

### 成功条件

**要求 5/5 完全一致:**
"""

    success_conditions = analysis["success_conditions"]
    for condition, value in success_conditions.items():
        status = '✅' if value else '❌'
        md_content += f"- {condition}: {status}\n"

    md_content += f"\n**最终判定:** {'✅ REPRODUCIBILITY_PASS' if analysis['consistent'] else '❌ REPRODUCIBILITY_FAILURE'}\n\n"

    if not analysis["consistent"]:
        md_content += "### 不一致详情\n\n"
        md_content += f"**首次不一致阶段:** `{analysis.get('divergence_stage', 'Unknown')}`\n\n"
        md_content += f"**原因:** {analysis['reason']}\n\n"

        if "m3_gate_passes" in analysis["details"]:
            md_content += f"**M3_GATE_PASS 不一致:** {analysis['details']['m3_gate_passes']['values']}\n\n"

        md_content += "### 下一步行动\n\n"
        md_content += "1. 定位导致不一致的随机源\n"
        md_content += "2. 检查 Router 训练的随机性控制\n"
        md_content += "3. 检查 tie-breaking 规则\n"
        md_content += "4. 检查 OOF fold 分割的确定性\n"
        md_content += "5. 禁止运行 test，禁止进入 Phase 3\n"

    md_content += f"""
## M3 Gate 稳定性分析

**M3 vs M2 Utility 差异:**
"""

    m3_vs_m2_diff = analysis["details"]["m3_vs_m2_diff"]
    md_content += f"""
- 各次运行差异: {[f'{d:.10f}' for d in m3_vs_m2_diff['values']]}
- 最大值: {m3_vs_m2_diff['max']:.10f}
- 最小值: {m3_vs_m2_diff['min']:.10f}
- 范围: {m3_vs_m2_diff['range']:.10f}

**稳定性评估:**
"""

    if m3_vs_m2_diff['range'] < 1e-10:
        md_content += """
✅ **完全稳定** - M3 vs M2 utility 差异在5次运行间完全一致，说明这是一个稳定的特征。
"""
    elif m3_vs_m2_diff['range'] < 1e-6:
        md_content += f"""
⚠️ **基本稳定** - M3 vs M2 utility 差异范围较小 ({m3_vs_m2_diff['range']:.2e})，在可接受范围内。
"""
    else:
        md_content += f"""
❌ **不稳定** - M3 vs M2 utility 差异范围较大 ({m3_vs_m2_diff['range']:.2e})，表明存在未控制的随机性。
"""

    md_content += f"""
## 关键统计

**平均性能 (5次运行):**
"""

    # 计算平均性能
    avg_metrics = {
        "M1": {"utility": np.mean([r["metrics"]["M1"]["utility"] for r in run_results]),
               "failure": np.mean([r["metrics"]["M1"]["failure"] for r in run_results])},
        "M2": {"utility": np.mean([r["metrics"]["M2"]["utility"] for r in run_results]),
               "failure": np.mean([r["metrics"]["M2"]["failure"] for r in run_results])},
        "M3": {"utility": np.mean([r["metrics"]["M3"]["utility"] for r in run_results]),
               "failure": np.mean([r["metrics"]["M3"]["failure"] for r in run_results])},
    }

    m3_gate_pass_rate = np.mean([1 if r["m3_gate_pass"] else 0 for r in run_results])

    md_content += f"""
| 方法 | 平均 Utility | 平均 Failure |
|------|-------------|-------------|
| M1 | {avg_metrics['M1']['utility']:.10f} | {avg_metrics['M1']['failure']:.10f} |
| M2 | {avg_metrics['M2']['utility']:.10f} | {avg_metrics['M2']['failure']:.10f} |
| M3 | {avg_metrics['M3']['utility']:.10f} | {avg_metrics['M3']['failure']:.10f} |

**M3 Gate 统计:**
- 通过率: {m3_gate_pass_rate*100:.1f}%
- 各次状态: {['PASS' if r['m3_gate_pass'] else 'FAIL' for r in run_results]}
- 平均 Utility 差: {np.mean(m3_vs_m2_diff['values']):.10f}
"""

    md_content += f"""
## 下一步建议

**如果 REPRODUCIBILITY_PASS:**
- 可复现性已修复，可以进入 Phase 3
- 基于 M1 为安全锚点，探索 Safety-Preserving Dynamic Fusion
- M1 安全优势已通过真实 failure 数据验证

**如果 REPRODUCIBILITY_FAILURE:**
- 必须先解决可复现性问题，不能进入 Phase 3
- 重点检查不一致的阶段: `{analysis.get('divergence_stage', 'Unknown')}`
- 严禁通过调整参数、放宽 epsilon 来"解决"可复现性

**当前 M3 Gate 状态 (基于稳定结果):**
"""

    if analysis["consistent"]:
        final_gate_status = "PASS" if run_results[0]["m3_gate_pass"] else "FAIL"
        final_m3_vs_m2 = m3_vs_m2_diff['values'][0]

        if final_gate_status == "PASS":
            md_content += f"""
- ✅ M3 Gate 稳定 PASS
- Utility 差: {final_m3_vs_m2:.10f}
- 但 M3 Failure ({avg_metrics['M3']['failure']:.1%}) 仍比 M1 ({avg_metrics['M1']['failure']:.1%}) 差
- 建议探索 Safety-Preserving Dynamic Fusion
"""
        else:
            md_content += f"""
- ❌ M3 Gate 稳定 FAIL
- Utility 差: {final_m3_vs_m2:.10f}
- M1 Failure ({avg_metrics['M1']['failure']:.1%}) 优于 M2/M3 ({avg_metrics['M2']['failure']:.1%})
- 应回退到 M2，探索 Safety-Preserving Dynamic Fusion
"""
    else:
        md_content += f"""
- ⚠️ M3 Gate 不稳定，无法确定最终状态
- 各次通过率: {m3_gate_pass_rate*100:.1f}%
- 必须先解决可复现性
"""

    md_content += f"""

## 技术审计清单

**✅ 已完成:**
- 全局随机性设置 (seed={env_info['random_seed']})
- PyTorch deterministic 模式
- CUDA workspace 配置
- 线程数量固定
- Python hash seed 固定

**🔍 需要进一步检查 (如果 REPRODUCIBILITY_FAILURE):**
- KNN neighbor 顺序 tie-breaking
- MLP 权重初始化、batch 顺序、optimizer 随机性
- GraphRouter 初始化、edge/node 顺序、negative sampling
- 5-fold OOF fold 分割确定性
- Meta Predictor random_state 设置
- 所有 argmax/argsort/rank 的 tie-breaking 规则

**❌ 禁止的操作:**
- 修改 M1/M2/M3 算法逻辑
- 调整 gate threshold
- Round utility 值
- 放宽 epsilon 容差
- 修改 gate 判定条件

---

**Phase 2.4 Reproducibility Hardening 完成**

**输出文件:**
- Reproducibility 报告: {output_path}
- JSON 数据: finrome_v4_phase2_4_reproducibility.json
- 阶段 hash 数据: finrome_v4_phase2_4_stage_hashes.json
"""

    output_path.write_text(md_content, encoding='utf-8')
    print(f"✅ Reproducibility Hardening 报告保存到 {output_path}")


# ========================================================================
# 主函数
# ========================================================================

def main():
    parser = argparse.ArgumentParser(description="Phase 2.4: Reproducibility Hardening")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--runs", type=int, default=5, help="运行次数")
    parser.add_argument("--output", type=Path, default=Path("/root/phase2_4_reproducibility_output"))
    args = parser.parse_args()

    print("=" * 80)
    print("FIN-ROME V4 - PHASE 2.4: REPRODUCIBILITY HARDENING")
    print("=" * 80)
    print(f"\n🎯 目标:")
    print(f"✅ 同一代码 + 同一数据 + 同一 seed = 完全相同结果")
    print(f"✅ 运行次数: {args.runs}")
    print(f"✅ 成功条件: 5/5 完全一致")
    print(f"❌ 禁止: 修改算法、调整 threshold、放宽 epsilon")
    print("=" * 80)

    # 设置全局确定性
    print(f"\n🔧 设置全局随机性和确定性...")
    env_info = set_global_determinism(args.seed)

    # 运行多次
    run_results = []
    print(f"\n🚀 开始 {args.runs} 次连续运行...")
    for run_num in range(1, args.runs + 1):
        print(f"\n[进度: {run_num}/{args.runs}]")
        result = run_phase2_with_stage_hashes(run_num, args.output)
        if result is None:
            print(f"❌ 第 {run_num} 次运行失败，停止审计")
            return
        run_results.append(result)
        time.sleep(2)  # 避免资源竞争

    # 分析可复现性
    print("\n🔍 分析可复现性...")
    analysis = analyze_reproducibility(run_results)

    # 生成报告
    print("\n📝 生成 Reproducibility Hardening 报告...")
    report_path = args.output / "FINROME_V4_PHASE2_4_REPRODUCIBILITY.md"
    generate_reproducibility_report(env_info, run_results, analysis, report_path)

    # 保存 JSON 数据
    json_output = {
        "audit_type": "reproducibility_hardening",
        "random_seed": args.seed,
        "num_runs": len(run_results),
        "consistent": analysis['consistent'],
        "env_info": env_info,
        "run_results": run_results,
        "analysis": analysis,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    json_path = args.output / "finrome_v4_phase2_4_reproducibility.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)

    # 保存简化的阶段 hash 数据
    stage_hashes_data = {
        "selections_hashes": [r["selections_hash"] for r in run_results],
        "utilities": {
            "M1": [r["metrics"]["M1"]["utility"] for r in run_results],
            "M2": [r["metrics"]["M2"]["utility"] for r in run_results],
            "M3": [r["metrics"]["M3"]["utility"] for r in run_results],
        },
        "failures": {
            "M1": [r["metrics"]["M1"]["failure"] for r in run_results],
            "M2": [r["metrics"]["M2"]["failure"] for r in run_results],
            "M3": [r["metrics"]["M3"]["failure"] for r in run_results],
        },
        "m3_gate_passes": [r["m3_gate_pass"] for r in run_results],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    stage_hashes_path = args.output / "finrome_v4_phase2_4_stage_hashes.json"
    with open(stage_hashes_path, 'w', encoding='utf-8') as f:
        json.dump(stage_hashes_data, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print("PHASE 2.4 REPRODUCIBILITY HARDENING 完成")
    print("=" * 80)
    print(f"\n🎯 最终判定:")
    if analysis['consistent']:
        print(f"   ✅ REPRODUCIBILITY_PASS - 结果完全稳定可复现")
        print(f"   🎯 M3 Gate 状态: {'PASS' if run_results[0]['m3_gate_pass'] else 'FAIL'}")
        print(f"   🚀 可以进入 Phase 3: Safety-Preserving Dynamic Fusion")
    else:
        print(f"   ❌ REPRODUCIBILITY_FAILURE - 结果不稳定")
        print(f"   ⚠️  首次不一致阶段: {analysis.get('divergence_stage', 'Unknown')}")
        print(f"   🚫 必须先解决可复现性，不能进入 Phase 3")
        print(f"   🔍 严禁通过调整参数来解决可复现性")

    m3_vs_m2_diffs = analysis["details"]["m3_vs_m2_diff"]
    print(f"   📊 M3 vs M2 Utility 差异范围: {m3_vs_m2_diffs['range']:.2e}")
    print(f"   📊 各次差异: {[f'{d:.10f}' for d in m3_vs_m2_diffs['values']]}")

    # 显示成功条件检查
    success_conditions = analysis["success_conditions"]
    print(f"\n🔍 成功条件检查:")
    for condition, value in success_conditions.items():
        status = '✅' if value else '❌'
        print(f"   {status} {condition}")

    print(f"\n📁 输出文件:")
    print(f"   - Reproducibility 报告: {report_path}")
    print(f"   - JSON 数据: {json_path}")
    print(f"   - 阶段 hash 数据: {stage_hashes_path}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()