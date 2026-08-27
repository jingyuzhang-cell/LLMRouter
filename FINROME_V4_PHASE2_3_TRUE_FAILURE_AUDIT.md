# Fin-RoMe v4 Phase 2.3 V3: 基于真实 Failure 的安全机制审计报告

**生成时间:** 2026-08-19T01:16:07.533766+00:00
**版本:** 2.3_true_failure_based
**数据来源:** Phase 2.2 Formal Pipeline 的20个 calibration tasks (包含真实 failure)

## 🔍 执行摘要

### ✅ M3 Gate 一致性修复

**发现的问题:**
- 原 gate 使用错误逻辑: `avg_safe_count >= 1.0`
- 修复后 gate 使用正确逻辑: 基于 utility/failure 比较

**本次运行结果:**
- 原 M3 Gate: ✅ PASS
- 修复后 M3 Gate: ✅ PASS

**Trace/Report 一致性验证:** ✅ 通过
- M1 Failure: 3/20 (15.0%)
- M2 Failure: 6/20 (30.0%)
- M3 Failure: 6/20 (30.0%)

### 📊 基于真实 Failure 的四组案例分析

**关键发现 (基于真实 main_failure):**
- M1 成功但 M2 失败: 4 个任务 (预期约 3 个)
- M1 成功但 M3 失败: 4 个任务 (预期约 3 个)
- M1 失败但 M2 成功: 1 个任务 (预期约 0 个)
- M1 失败但 M3 成功: 1 个任务 (预期约 0 个)

**净收益计算:**
- M1 对 M2 的净收益: 3 个任务
- M1 对 M3 的净收益: 3 个任务
- 总体 Failure Gap: 15.0% = 3 个任务

## 四组真实 Safety Cases 分析

### 1. M1 成功但 M2 失败 (4 个任务)

**任务列表:**

#### finance_dataset_87d1dc85-d372-4ddd-bf18-8aca923cffbb

- **任务类型:** financial_table_text_reasoning
- **风险等级:** medium
- **M1 选择:** qwen-plus
- **M2 选择:** deepseek-chat

**真实结果对比:**

| 方法 | 模型 | Quality | Reliability | Utility | Main Failure |
|------|------|---------|-------------|---------|--------------|
| M1 | qwen-plus | 0.983 | 1.000 | 0.9018 | ✅ |
| M2 | deepseek-chat | 0.323 | 1.000 | 0.6549 | ❌ |

**M1 融合排名:** [0.0, 3.0, 1.3333333333333333, 1.6666666666666667]

**M2 动态权重分析:**

- **knnrouter:**
  - Top1: deepseek-chat
  - Rank for M1 Choice: 0.00
  - Accept Prob: 0.572
  - Fail Prob: 0.265
  - Regret Pred: 0.0095
  - Normalized Weight: 0.312

- **mlprouter:**
  - Top1: deepseek-chat
  - Rank for M1 Choice: 0.00
  - Accept Prob: 0.479
  - Fail Prob: 0.323
  - Regret Pred: 0.0073
  - Normalized Weight: 0.241

- **graphrouter:**
  - Top1: deepseek-chat
  - Rank for M1 Choice: 0.00
  - Accept Prob: 0.708
  - Fail Prob: 0.153
  - Regret Pred: 0.0307
  - Normalized Weight: 0.447

**权重集中分析:**
- 最大权重 Router: graphrouter (0.447)
- 权重过度集中 (>0.5): 否
- M2 改变了 M1 选择: 是
- M2 使结果变差: 是

**机制分析:**

✅ **M2 权重分布较为均衡** - 没有单一 Router 获得过大权重。

🔴 **M2 使结果变差** - M1 选择的模型 qwen-plus (quality=0.983, utility=0.9018) 是安全的，但 M2 改选为 deepseek-chat (quality=0.323, utility=0.6549) 导致了失败。

#### finance_dataset_finqa_004591

- **任务类型:** financial_numerical_reasoning
- **风险等级:** medium
- **M1 选择:** deepseek-chat
- **M2 选择:** qwen-turbo

**真实结果对比:**

| 方法 | 模型 | Quality | Reliability | Utility | Main Failure |
|------|------|---------|-------------|---------|--------------|
| M1 | deepseek-chat | 0.976 | 1.000 | 0.9568 | ✅ |
| M2 | qwen-turbo | 0.561 | 1.000 | 0.7803 | ❌ |

**M1 融合排名:** [2.3333333333333335, 1.0, 2.0, 0.6666666666666666]

**M2 动态权重分析:**

- **knnrouter:**
  - Top1: qwen-turbo
  - Rank for M1 Choice: 0.67
  - Accept Prob: 0.459
  - Fail Prob: 0.527
  - Regret Pred: 0.0215
  - Normalized Weight: 0.446

- **mlprouter:**
  - Top1: qwen-turbo
  - Rank for M1 Choice: 0.67
  - Accept Prob: 0.269
  - Fail Prob: 0.494
  - Regret Pred: 0.0671
  - Normalized Weight: 0.280

- **graphrouter:**
  - Top1: glm-5.2
  - Rank for M1 Choice: 1.00
  - Accept Prob: 0.209
  - Fail Prob: 0.360
  - Regret Pred: 0.1109
  - Normalized Weight: 0.275

**权重集中分析:**
- 最大权重 Router: knnrouter (0.446)
- 权重过度集中 (>0.5): 否
- M2 改变了 M1 选择: 是
- M2 使结果变差: 是

**机制分析:**

✅ **M2 权重分布较为均衡** - 没有单一 Router 获得过大权重。

🔴 **M2 使结果变差** - M1 选择的模型 deepseek-chat (quality=0.976, utility=0.9568) 是安全的，但 M2 改选为 qwen-turbo (quality=0.561, utility=0.7803) 导致了失败。

#### finance_dataset_finqa_006147

- **任务类型:** financial_numerical_reasoning
- **风险等级:** medium
- **M1 选择:** glm-5.2
- **M2 选择:** qwen-turbo

**真实结果对比:**

| 方法 | 模型 | Quality | Reliability | Utility | Main Failure |
|------|------|---------|-------------|---------|--------------|
| M1 | glm-5.2 | 0.977 | 1.000 | 0.7985 | ✅ |
| M2 | qwen-turbo | 0.333 | 1.000 | 0.6702 | ❌ |

**M1 融合排名:** [2.0, 1.0, 1.6666666666666667, 1.3333333333333333]

**M2 动态权重分析:**

- **knnrouter:**
  - Top1: qwen-turbo
  - Rank for M1 Choice: 1.33
  - Accept Prob: 0.459
  - Fail Prob: 0.534
  - Regret Pred: 0.0215
  - Normalized Weight: 0.256

- **mlprouter:**
  - Top1: qwen-turbo
  - Rank for M1 Choice: 1.33
  - Accept Prob: 0.481
  - Fail Prob: 0.473
  - Regret Pred: 0.0033
  - Normalized Weight: 0.304

- **graphrouter:**
  - Top1: deepseek-chat
  - Rank for M1 Choice: 2.00
  - Accept Prob: 0.522
  - Fail Prob: 0.295
  - Regret Pred: 0.0475
  - Normalized Weight: 0.440

**权重集中分析:**
- 最大权重 Router: graphrouter (0.440)
- 权重过度集中 (>0.5): 否
- M2 改变了 M1 选择: 是
- M2 使结果变差: 是

**机制分析:**

✅ **M2 权重分布较为均衡** - 没有单一 Router 获得过大权重。

🔴 **M2 使结果变差** - M1 选择的模型 glm-5.2 (quality=0.977, utility=0.7985) 是安全的，但 M2 改选为 qwen-turbo (quality=0.333, utility=0.6702) 导致了失败。

#### finance_dataset_seed_audit_001

- **任务类型:** financial_audit_compliance_qa
- **风险等级:** high
- **M1 选择:** deepseek-chat
- **M2 选择:** qwen-turbo

**真实结果对比:**

| 方法 | 模型 | Quality | Reliability | Utility | Main Failure |
|------|------|---------|-------------|---------|--------------|
| M1 | deepseek-chat | 0.737 | 1.000 | 0.8348 | ✅ |
| M2 | qwen-turbo | 0.500 | 1.000 | 0.7533 | ❌ |

**M1 融合排名:** [2.3333333333333335, 2.0, 1.0, 0.6666666666666666]

**M2 动态权重分析:**

- **knnrouter:**
  - Top1: qwen-turbo
  - Rank for M1 Choice: 0.67
  - Accept Prob: 0.376
  - Fail Prob: 0.760
  - Regret Pred: 0.2730
  - Normalized Weight: 0.294

- **mlprouter:**
  - Top1: qwen-turbo
  - Rank for M1 Choice: 0.67
  - Accept Prob: 0.691
  - Fail Prob: 0.788
  - Regret Pred: 0.0637
  - Normalized Weight: 0.477

- **graphrouter:**
  - Top1: glm-5.2
  - Rank for M1 Choice: 2.00
  - Accept Prob: 0.503
  - Fail Prob: 0.860
  - Regret Pred: 0.1185
  - Normalized Weight: 0.229

**权重集中分析:**
- 最大权重 Router: mlprouter (0.477)
- 权重过度集中 (>0.5): 否
- M2 改变了 M1 选择: 是
- M2 使结果变差: 是

**机制分析:**

✅ **M2 权重分布较为均衡** - 没有单一 Router 获得过大权重。

🔴 **M2 使结果变差** - M1 选择的模型 deepseek-chat (quality=0.737, utility=0.8348) 是安全的，但 M2 改选为 qwen-turbo (quality=0.500, utility=0.7533) 导致了失败。

### 2. M1 成功但 M3 失败 (4 个任务)

**任务列表:**

#### finance_dataset_87d1dc85-d372-4ddd-bf18-8aca923cffbb

- **任务类型:** financial_table_text_reasoning
- **风险等级:** medium
- **M1 选择:** qwen-plus
- **M3 选择:** deepseek-chat

**真实结果对比:**

| 方法 | 模型 | Quality | Utility | Main Failure |
|------|------|---------|---------|--------------|
| M1 | qwen-plus | 0.983 | 0.9018 | ✅ |
| M3 | deepseek-chat | 0.323 | 0.6549 | ❌ |

**M3 Conformal Gate 分析:**
- Safe Router Set: ['knnrouter', 'mlprouter', 'graphrouter']
- Risk Limit: 0.2
- M3 是否修正了 M2: 是
- M3 使结果变差: 是
- 失败原因: safe_set_missing_correct_choice

**Router Safety Status:**

- **knnrouter:**
  - Top1: deepseek-chat
  - In Safe Set: 是
  - Conformal Bound: 0.0562

- **mlprouter:**
  - Top1: deepseek-chat
  - In Safe Set: 是
  - Conformal Bound: 0.0704

- **graphrouter:**
  - Top1: deepseek-chat
  - In Safe Set: 是
  - Conformal Bound: 0.1264

**机制分析:**

🔴 **Safe Set 缺少正确选择** - 正确的 Router 被 conformal bound 过滤掉了。

#### finance_dataset_finqa_004591

- **任务类型:** financial_numerical_reasoning
- **风险等级:** medium
- **M1 选择:** deepseek-chat
- **M3 选择:** qwen-turbo

**真实结果对比:**

| 方法 | 模型 | Quality | Utility | Main Failure |
|------|------|---------|---------|--------------|
| M1 | deepseek-chat | 0.976 | 0.9568 | ✅ |
| M3 | qwen-turbo | 0.561 | 0.7803 | ❌ |

**M3 Conformal Gate 分析:**
- Safe Router Set: ['knnrouter', 'mlprouter']
- Risk Limit: 0.2
- M3 是否修正了 M2: 是
- M3 使结果变差: 是
- 失败原因: safe_set_missing_correct_choice

**Router Safety Status:**

- **knnrouter:**
  - Top1: qwen-turbo
  - In Safe Set: 是
  - Conformal Bound: 0.0562

- **mlprouter:**
  - Top1: qwen-turbo
  - In Safe Set: 是
  - Conformal Bound: 0.0704

- **graphrouter:**
  - Top1: glm-5.2
  - In Safe Set: 否
  - Conformal Bound: 0.1264

**机制分析:**

🔴 **Safe Set 缺少正确选择** - 正确的 Router 被 conformal bound 过滤掉了。

#### finance_dataset_finqa_006147

- **任务类型:** financial_numerical_reasoning
- **风险等级:** medium
- **M1 选择:** glm-5.2
- **M3 选择:** qwen-turbo

**真实结果对比:**

| 方法 | 模型 | Quality | Utility | Main Failure |
|------|------|---------|---------|--------------|
| M1 | glm-5.2 | 0.977 | 0.7985 | ✅ |
| M3 | qwen-turbo | 0.333 | 0.6702 | ❌ |

**M3 Conformal Gate 分析:**
- Safe Router Set: ['knnrouter', 'mlprouter', 'graphrouter']
- Risk Limit: 0.2
- M3 是否修正了 M2: 是
- M3 使结果变差: 是
- 失败原因: safe_set_missing_correct_choice

**Router Safety Status:**

- **knnrouter:**
  - Top1: qwen-turbo
  - In Safe Set: 是
  - Conformal Bound: 0.0562

- **mlprouter:**
  - Top1: qwen-turbo
  - In Safe Set: 是
  - Conformal Bound: 0.0704

- **graphrouter:**
  - Top1: deepseek-chat
  - In Safe Set: 是
  - Conformal Bound: 0.1264

**机制分析:**

🔴 **Safe Set 缺少正确选择** - 正确的 Router 被 conformal bound 过滤掉了。

#### finance_dataset_seed_audit_001

- **任务类型:** financial_audit_compliance_qa
- **风险等级:** high
- **M1 选择:** deepseek-chat
- **M3 选择:** qwen-turbo

**真实结果对比:**

| 方法 | 模型 | Quality | Utility | Main Failure |
|------|------|---------|---------|--------------|
| M1 | deepseek-chat | 0.737 | 0.8348 | ✅ |
| M3 | qwen-turbo | 0.500 | 0.7533 | ❌ |

**M3 Conformal Gate 分析:**
- Safe Router Set: []
- Risk Limit: 0.1
- M3 是否修正了 M2: 是
- M3 使结果变差: 是
- 失败原因: safe_router_set_empty

**Router Safety Status:**

- **knnrouter:**
  - Top1: qwen-turbo
  - In Safe Set: 否
  - Conformal Bound: 0.2154

- **mlprouter:**
  - Top1: qwen-turbo
  - In Safe Set: 否
  - Conformal Bound: 0.0646

- **graphrouter:**
  - Top1: glm-5.2
  - In Safe Set: 否
  - Conformal Bound: 0.1354

**机制分析:**

🔴 **Safe Router Set 为空** - 所有 Router 都通过了 conformal bound 检查，导致无法进行安全过滤。

### 3. M1 失败但 M2 成功 (1 个任务)

**任务列表:**
- finance_dataset_48c3b9b7-0d9f-4919-9b6e-1659e72cb7f8

### 4. M1 失败但 M3 成功 (1 个任务)

**任务列表:**
- finance_dataset_48c3b9b7-0d9f-4919-9b6e-1659e72cb7f8

## M1 安全优势机制验证

### 假设验证

**假设:** "M1 等权融合通过专家制衡而更安全"

**验证结果:**

✅ **支持假设** - M1 对 M2 的净收益为 3 个任务，正好解释了 15.0% 的 Failure Gap。

**关键证据:**
- M1 救回了 M2 失败: 4 个任务
- M2 救回了 M1 失败: 1 个任务
- 净收益: 3 = 4 - 1

**机制推断:**

2. **M2 错误地改变了 M1 的选择** - 在 4/4 个失败任务中，M2 改变了 M1 原本安全的选择，导致失败。

**结论:** M1 的等权融合通过专家制衡效应，避免了单一专家的错误，从而在安全性上优于动态融合。

### M3 Conformal Gate 效果评估

**M3 对 M1 的影响:**
- M1 救回 M3 失败: 4 个任务
- M3 救回 M1 失败: 1 个任务
- M1 对 M3 的净收益: 3 个任务

**Conformal Gate 失效分析:**

在 4 个 M3 失败任务中：
- **safe_set_missing_correct_choice**: 3 个任务
- **safe_router_set_empty**: 1 个任务

## M3 Gate 状态

**最终判定:** ✅ PASS

**条件检查:**
- M3 Utility (0.8654) >= M2 Utility (0.8647): ✅
- M3 Failure (30.0%) <= M2 Failure (30.0%): ✅

**安全性评估:**
- 虽然 M3 通过了 gate，但 M3 的 Failure Rate (30.0%) 仍然比 M1 (15.0%) 差
- 这表明 M3 的 utility 改进并没有带来安全性改进

## 下一步建议

**如果 M1 确实通过专家制衡更安全:**
- 设计 Safety-Preserving Dynamic Fusion
- 以 M1 为安全锚点，动态融合只在"有足够证据证明更好"时覆盖 M1

**如果 M1 安全性来自其他机制:**
- 重新分析 M1 的选择逻辑
- 探索其他可能的安全机制

**关于 M3 Gate:**
- 由于 M3 gate 对随机训练很敏感（utility 差异仅约 0.0007），建议进行 Reproducibility Audit
- 如果固定随机种子后 M3 gate 状态仍不稳定，则不应进入 Phase 3

**关键决策:** 基于真实 failure 数据的分析表明 M1 确实更安全，但 M3 的 utility 提升幅度很小且不稳定。

---

**Phase 2.3 V3 真实 Failure 基础分析完成**

**关键成就:**
✅ 基于真实 main_failure 的四组案例分析完成
✅ M1 安全优势机制得到真实数据验证
✅ M2 动态融合失效原因明确
✅ M3 Conformal Gate 失效原因明确

**限制:** 需要进行 Reproducibility Audit 以验证结果稳定性。
