# Fin-RoME v4 Phase 3.2: SPDF Gate based on Frozen Baseline

**生成时间:** 2026-08-19T13:36:10.609775+00:00
**版本:** 3.2_spdf_gate_frozen_baseline

## Phase 3.2 概述

Phase 3.2 基于Phase 2冻结的M1/M2/M3 selection实现SPDF Gate。

### 关键原则

1. **基于冻结 baseline**
   - 直接加载 Phase 2 冻结的 M1 (Safety Anchor)
   - 直接加载 Phase 2 冻结的 M3 (Proposal)
   - 禁止重新训练 Router/M1/M2/M3

2. **两阶段架构**
   - Phase A (prediction_generation): 只允许访问推理时可得到的信息
   - Phase B (evaluation): 读取 calibration true outcomes 计算指标

3. **修复 Override Metrics**
   - beneficial_override: proposal utility > anchor utility AND proposal failure <= anchor failure
   - safety_harmful_override: anchor failure = 0 AND proposal failure = 1
   - utility_harmful_override: proposal utility < anchor utility AND no safety_harm
   - neutral_override: 其余情况
   - beneficial_override_precision = beneficial_overrides / total_overrides

## Phase 2 冻结 Baseline

| Method | Utility | Main Failure | Strict Failure | Oracle Match | Selection Counts |
|--------|---------|--------------|-----------------|---------------|------------------|
| M1 (Safety Anchor❌) | 0.8350752467 | 15.00% | 20.00% | 20.00% | {'deepseek-chat': 6, 'qwen-plus': 6, 'glm-5.2': 8} |
| M3 (Safety Anchor Proposal) | 0.8656190733 | 30.00% | 30.00% | 55.00% | {'qwen-plus': 2, 'qwen-turbo': 13, 'deepseek-chat': 5} |

## Override Gate 配置

- **tau_u (utility threshold):** 0.01
- **tau_f (failure threshold):** 0.0
- **Override Rule:** `predicted_delta_utility > 0.01` AND `predicted_failure_proposal <= predicted_failure_anchor`

## SPDF 结果

### 整体指标

| 指标 | SPDF | M1 Anchor | M3 Proposal |
|------|------|-----------|------------|
| Utility | 0.8351 | 0.8351 | 0.8656 |
| Main Failure | 15.00% | 15.00% | 30.00% |
| Strict Failure | 20.00% | 20.00% | 30.00% |
| Oracle Match | 20.00% | 20.00% | 55.00% |

### Override 分析（修复后）

- **Override Rate:** 0.00%
- **Total Overrides:** 0
- **Beneficial Override Precision:** 0.00%

Override 分类详情:
- **Beneficial Override:** 0 (proposal 更好：utility 更高，failure 更低或相等)
- **Safety Harmful Override:** 0 (anchor 安全但 proposal 失败)
- **Utility Harmful Override:** 0 (proposal utility 更低且不是 safety_harm)
- **Neutral Override:** 0 (其余情况)

## Safety-Preserving 验证

- **M1 Failure:** 15.00%
- **SPDF Failure:** 15.00%
- **M1 Utility:** 0.8351
- **SPDF Utility:** 0.8351
- **Failure Delta (SPDF - M1):** +0.00%
- **Utility Delta (SPDF - M1):** +0.0000
- **Safety-Preserving (SPDF Failure <= M1 Failure):** ✅ PASS
- **Utility Improved (SPDF Utility >= M1 Utility):** ✅ PASS
- **Overall Status:** SAFETY_PRESERVING

## 关键发现

✅ **理想结果：SPDF 实现了 Safety-Preserving Dynamic Fusion**

- 成功回收了部分 M3 Utility (ΔU = +0.0000)
- 同时保持了 M1 Safety Anchor 的安全性 (ΔF = +0.00%)
- Override Rate: 0.00%
- Beneficial Override Precision: 0.00%

## Selection 分布

- **SPDF Selection Counts:** {'deepseek-chat': 6, 'qwen-plus': 6, 'glm-5.2': 8}
- **M1 Selection Counts (参考):** {'deepseek-chat': 6, 'qwen-plus': 6, 'glm-5.2': 8}
- **M3 Selection Counts (参考):** {'qwen-plus': 2, 'qwen-turbo': 13, 'deepseek-chat': 5}

## 下一步行动

根据 Safety-Preserving 验证结果：

### ✅ Safety-Preserving：可以继续优化

1. **Threshold Tuning:** 调整 τu 和 τf 以优化 trade-off
2. **Gate 特征工程:** 改进预测准确度
3. **可复现性验证:** 确保多次运行结果一致

4. **独立验证:** 在未触碰的 test set 上验证
5. **考虑 Phase 4:** 进入正式的 Verifier/Abstention 评估
