# Fin-RoME v4 Phase 3.1: Baseline Fidelity + SPDF Reproducibility Audit

**生成时间:** 2026-08-19T13:29:58.946087+00:00
**版本:** 3.1_fidelity_audit

## Audit 概述

Phase 3.1 专注于验证 Baseline Fidelity，确保 Phase 3 严格继承 Phase 2 已冻结的 M1/M2/M3 selection。

### 关键原则

1. **禁止重新计算 M1/M2/M3**
   - Phase 3 必须直接加载 Phase 2 冻结的 selection
   - 禁止重新训练 Router 后重新生成 calibration baseline

2. **强制 Baseline Fidelity Assertions**
   - Phase3 task_ids == Phase2 calibration task_ids
   - Phase3 M1 selections hash == Phase2 M1 selections hash
   - Phase3 M2 selections hash == Phase2 M2 selections hash
   - Phase3 M3 selections hash == Phase2 M3 selections hash

3. **精确指标匹配**
   - M1: utility = 0.8350752467, failure = 3/20 = 15%
   - M2: utility = 0.8654756200, failure = 6/20 = 30%
   - M3: utility = 0.8656190733, failure = 6/20 = 30%

4. **修复 Override Metrics**
   - beneficial_override: proposal utility > anchor utility AND proposal failure <= anchor failure
   - safety_harmful_override: anchor failure = 0 AND proposal failure = 1
   - utility_harmful_override: proposal utility < anchor utility AND no safety_harm
   - neutral_override: 其余情况

5. **可复现性检查**
   - 固定相同 frozen inputs 后连续运行 5 次
   - 必须满足 anchor_hash identical 5/5
   - 必须满足 proposal_hash identical 5/5
   - 必须满足 M1/M3 metrics identical 5/5

## Phase 2 冻结 Baseline

| Method | Utility | Main Failure | Strict Failure | Oracle Match | Selection Counts |
|--------|---------|--------------|-----------------|---------------|------------------|
| M1 | 0.8350752467 | 15.00% | 20.00% | 20.00% | {'deepseek-chat': 6, 'qwen-plus': 6, 'glm-5.2': 8} |
| M2 | 0.8654756200 | 30.00% | 30.00% | 50.00% | {'qwen-plus': 2, 'deepseek-chat': 8, 'qwen-turbo': 10} |
| M3 | 0.8656190733 | 30.00% | 30.00% | 55.00% | {'qwen-plus': 2, 'qwen-turbo': 13, 'deepseek-chat': 5} |

## 可复现性检查结果

**总运行次数:** 5
**成功运行次数:** 5
**可复现性:** ✅ PASSED

### Anchor (M1) Hash 一致性

- **全部相同:** ✅ 是
- **唯一 hash 数量:** 1
- **Hash:** `0c847a5375ec299c...`

### Proposal (M3) Hash 一致性

- **全部相同:** ✅ 是
- **唯一 hash 数量:** 1
- **Hash:** `e117c79edf91b16e...`

### M1 指标一致性

- **Utility 范围:** [0.8350752467, 0.8350752467]
- **Failure 范围:** [0.1500000000, 0.1500000000]
- **全部相同:** ✅ 是

### M3 指标一致性

- **Utility 范围:** [0.8656190733, 0.8656190733]
- **Failure 范围:** [0.3000000000, 0.3000000000]
- **全部相同:** ✅ 是

## Audit 结论

✅ **BASELINE FIDELITY AUDIT PASSED**

Phase 3.1 验证了以下关键要求：

1. ✅ Phase 3 正确加载了 Phase 2 冻结的 M1/M2/M3 selection
2. ✅ M1/M2/M3 指标与 Phase 2 冻结 baseline 完全一致
3. ✅ 5 次运行结果完全可复现（hashes 和 metrics 相同）

现在可以安全进入下一步：
- Phase 3.2: 在冻结 baseline 上实现 SPDF Gate
- Phase 3.3: Threshold tuning（使用冻结的 selection）

## 下一步行动

根据 Phase 3.1 Audit 结果：
- **如果 PASSED:** 继续实现 Phase 3.2 SPDF Gate（基于冻结 baseline）
- **如果 FAILED:** 修复 baseline fidelity 问题后重新运行 Phase 3.1

### 禁止的操作（直到 Phase 3.1 PASSED）
- ❌ 运行 test
- ❌ 进入 Phase 4
- ❌ 调整 SPDF 阈值
- ❌ 重新训练 Router/M1/M2/M3
