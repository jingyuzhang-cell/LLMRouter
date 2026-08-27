#!/usr/bin/env python3
"""
Phase 2.4: 快速验证 M3 selection 的确定性

运行 5 次，检查 M3 stage hashes 是否一致
"""

import hashlib
import json
import subprocess
import sys
from collections import defaultdict

def extract_stage_hashes(stdout: str) -> dict:
    """从 stdout 中提取 stage hashes"""
    stage_hashes = {}

    lines = stdout.split('\n')
    for line in lines:
        if 'Safe Router Sets Hash:' in line:
            stage_hashes['safe_router_sets'] = line.split('Safe Router Sets Hash:')[1].strip()
        elif 'Router Merits Hash:' in line:
            stage_hashes['router_merits'] = line.split('Router Merits Hash:')[1].strip()
        elif 'Selected Routers Hash:' in line:
            stage_hashes['selected_routers'] = line.split('Selected Routers Hash:')[1].strip()
        elif 'Selected Models Hash:' in line:
            stage_hashes['selected_models'] = line.split('Selected Models Hash:')[1].strip()

    return stage_hashes

def extract_m3_gate_status(stdout: str) -> bool:
    """提取 M3 gate 状态"""
    lines = stdout.split('\n')
    for line in lines:
        if '修复后 M3 Gate (基于 utility/failure):' in line:
            return 'PASS' in line
    return False

def extract_utility_diff(stdout: str) -> float:
    """提取 M3 vs M2 utility 差异"""
    lines = stdout.split('\n')
    for line in lines:
        if 'M3 Utility (' in line and '>= M2 Utility (' in line:
            # 从行中提取两个 utility 值
            import re
            matches = re.findall(r'Utility \(([\d.]+)\)', line)
            if len(matches) == 2:
                m3_utility = float(matches[0])
                m2_utility = float(matches[1])
                return m3_utility - m2_utility
    return 0.0

def main():
    print("=" * 80)
    print("FIN-ROME V4 - PHASE 2.4: M3 Selection 确定性验证")
    print("=" * 80)

    # 设置环境变量
    env = {
        'PYTHONHASHSEED': '42',
        'CUBLAS_WORKSPACE_CONFIG': ':4096:8',
        'OMP_NUM_THREADS': '1',
        'MKL_NUM_THREADS': '1',
    }

    # 运行 5 次
    results = []
    for run_num in range(1, 6):
        print(f"\n{'='*80}")
        print(f"运行 {run_num}/5")
        print(f"{'='*80}")

        result = subprocess.run(
            [sys.executable, "/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/scripts/phase2_formal_router_metrics.py"],
            capture_output=True,
            text=True,
            timeout=300,
            env={**subprocess.os.environ, **env}
        )

        if result.returncode != 0:
            print(f"❌ 运行失败: {result.stderr}")
            continue

        stage_hashes = extract_stage_hashes(result.stdout)
        m3_gate_pass = extract_m3_gate_status(result.stdout)
        utility_diff = extract_utility_diff(result.stdout)

        print(f"M3 Stage Hashes:")
        for key, value in stage_hashes.items():
            print(f"  - {key}: {value}")
        print(f"M3 Gate: {'PASS' if m3_gate_pass else 'FAIL'}")
        print(f"Utility Diff (M3-M2): {utility_diff:.10f}")

        results.append({
            'run': run_num,
            'stage_hashes': stage_hashes,
            'm3_gate_pass': m3_gate_pass,
            'utility_diff': utility_diff
        })

    # 验证一致性
    print(f"\n{'='*80}")
    print("确定性验证")
    print(f"{'='*80}")

    all_hashes = defaultdict(list)
    for result in results:
        for key, value in result['stage_hashes'].items():
            all_hashes[key].append(value)

    consistent = True
    for key, values in all_hashes.items():
        unique_values = set(values)
        if len(unique_values) == 1:
            print(f"✅ {key}: 完全一致 ({values[0]})")
        else:
            print(f"❌ {key}: 不一致 {unique_values}")
            consistent = False

    # M3 gate 状态一致性
    m3_gate_values = [r['m3_gate_pass'] for r in results]
    if all(m3_gate_values) or not any(m3_gate_values):
        gate_status = "PASS" if m3_gate_values[0] else "FAIL"
        print(f"✅ M3 Gate: 完全一致 ({gate_status})")
    else:
        gate_counts = sum(m3_gate_values)
        print(f"❌ M3 Gate: 不一致 ({gate_counts}/5 PASS)")
        consistent = False

    # Utility 差异一致性
    utility_diffs = [r['utility_diff'] for r in results]
    if max(utility_diffs) - min(utility_diffs) < 1e-10:
        print(f"✅ Utility Diff: 完全一致 ({utility_diffs[0]:.10f})")
    else:
        diff_range = max(utility_diffs) - min(utility_diffs)
        print(f"❌ Utility Diff: 不一致 (范围: {diff_range:.10f})")
        print(f"   值: {[f'{d:.10f}' for d in utility_diffs]}")
        consistent = False

    print(f"\n{'='*80}")
    if consistent:
        print("✅ PHASE 2.4 确定性验证通过：所有 hashes 完全一致")
    else:
        print("❌ PHASE 2.4 确定性验证失败：发现不一致")
    print(f"{'='*80}")

    return 0 if consistent else 1

if __name__ == "__main__":
    sys.exit(main())