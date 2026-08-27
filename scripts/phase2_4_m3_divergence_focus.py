#!/usr/bin/env python3
"""
Phase 2.4 第二轮：M3 Selection Divergence 精确诊断

目标：
- M1/M2 已完全稳定，问题在 M3 FINAL_SELECTIONS
- 重点查 M3 的 safe_router_set → merit → selected_router → selected_model
- 增加分阶段 hash，定位第一个不一致的阶段

禁止：
- 泛化排查 GraphRouter 训练随机性
- 修改算法数学定义
- 运行 test
- 调整 gate threshold
"""

import os
import random
import sys
from pathlib import Path

# 必须在 Python 启动前设置这些环境变量
if 'PYTHONHASHSEED' not in os.environ:
    print("❌ 错误：PYTHONHASHSEED 必须在 Python 启动前设置")
    print("   正确用法：")
    print("   export PYTHONHASHSEED=42")
    print("   export CUBLAS_WORKSPACE_CONFIG=:4096:8")
    print("   export OMP_NUM_THREADS=1")
    print("   export MKL_NUM_THREADS=1")
    print("   python scripts/phase2_formal_router_metrics.py")
    sys.exit(1)

# 验证关键环境变量
required_env = ['PYTHONHASHSEED', 'CUBLAS_WORKSPACE_CONFIG', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS']
for env_var in required_env:
    if env_var not in os.environ:
        print(f"❌ 错误：环境变量 {env_var} 未设置")

print("✅ 环境变量验证通过")
print("=" * 80)
print("FIN-ROME V4 - PHASE 2.4: M3 Selection Divergence 精确诊断")
print("=" * 80)
print("\n🎯 目标：定位 M3 FINAL_SELECTIONS divergence 的根本原因")
print("✅ M1/M2 已完全稳定，问题范围已缩小到 M3 selection")
print("=" * 80)

# 将环境变量传递给子进程
env = os.environ.copy()

# 运行主脚本
import subprocess
result = subprocess.run(
    [sys.executable, "/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/scripts/phase2_formal_router_metrics.py"],
    env=env,
    capture_output=True,
    text=True,
    timeout=300
)

print("\n" + "=" * 80)
print("单次运行完成，输出结果...")
print("=" * 80)
print(f"\nstdout:")
print(result.stdout)

if result.returncode != 0:
    print(f"\n❌ 运行失败:")
    print(result.stderr)
    sys.exit(1)

print("\n✅ Phase 2.4 第一轮环境检查完成")
print("💡 下一步：需要修改 phase2_formal_router_metrics.py")
print("   - 每个 Router/Fold 独立固定 seed")
print("   - 增加分阶段 hash")
print("   - 确定性排序和 tie-breaking")
print("   - 重新运行 5 次验证")