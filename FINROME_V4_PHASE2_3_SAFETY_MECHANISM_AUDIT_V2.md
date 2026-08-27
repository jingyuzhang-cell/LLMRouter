# Fin-RoME v4 Phase 2.3: 基于真实 Trace 的安全机制审计报告 V2

**生成时间:** 2026-08-19T01:04:48.031065+00:00
**版本:** 2.3_real_trace_based
**数据来源:** Phase 2.2 Formal Pipeline 的20个 calibration tasks

## 执行摘要

### 🔧 M3 Gate 一致性修复

**发现的问题:**
- 原 gate 使用错误逻辑: `avg_safe_count >= 1.0`
- 修复后 gate 使用正确逻辑: 基于 utility/failure 比较

**本次运行结果:**
- 原 M3 Gate: ✅ PASS
- 修复后 M3 Gate: ✅ PASS

### 🔍 M1 安全优势的真实证据

**关键指标 (本次运行):**
- M1 Failure Rate: 15.0% (预期 3 个失败任务)
- M2 Failure Rate: 30.0% (预期 6 个失败任务)
- M3 Failure Rate: 30.0% (预期 6 个失败任务)

**核心问题:** 如果预期 M1=15% failure、M2/M3=30% failure，则：
- M1 应救回 M2 约 3 个任务
- M1 应救回 M3 约 3 个任务

## 四组关键案例分析

### 1. M1 成功但 M2 失败 (8 个任务)

**任务列表:**

#### finance_dataset_08439cc4-cc83-400e-ae6e-0550c2a91344

- **任务类型:** financial_audit_compliance_qa
- **风险等级:** high
- **M1 选择:** deepseek-chat
- **M2 选择:** qwen-plus

**M1 融合排名:** [1.6666666666666667, 2.6666666666666665, 1.0, 0.6666666666666666]

**M2 动态权重分析:**

- **knnrouter:**
  - Top1: qwen-plus
  - Accept Prob: 0.354
  - Fail Prob: 0.785
  - Regret Pred: 0.0266
  - Normalized Weight: 0.283

- **mlprouter:**
  - Top1: qwen-plus
  - Accept Prob: 0.654
  - Fail Prob: 0.817
  - Regret Pred: 0.0120
  - Normalized Weight: 0.445

- **graphrouter:**
  - Top1: glm-5.2
  - Accept Prob: 0.362
  - Fail Prob: 0.797
  - Regret Pred: 0.0790
  - Normalized Weight: 0.272

**权重集中分析:**
- 最大权重 Router: mlprouter (0.445)
- 权重过度集中: 否

#### finance_dataset_49d7ee2d-93a5-4ed7-9fe9-030ead91c8d2

- **任务类型:** financial_table_text_reasoning
- **风险等级:** medium
- **M1 选择:** glm-5.2
- **M2 选择:** qwen-turbo

**M1 融合排名:** [2.0, 1.0, 1.6666666666666667, 1.3333333333333333]

**M2 动态权重分析:**

- **knnrouter:**
  - Top1: qwen-turbo
  - Accept Prob: 0.522
  - Fail Prob: 0.250
  - Regret Pred: 0.0532
  - Normalized Weight: 0.335

- **mlprouter:**
  - Top1: qwen-turbo
  - Accept Prob: 0.585
  - Fail Prob: 0.502
  - Regret Pred: 0.0052
  - Normalized Weight: 0.249

- **graphrouter:**
  - Top1: deepseek-chat
  - Accept Prob: 0.663
  - Fail Prob: 0.264
  - Regret Pred: 0.0119
  - Normalized Weight: 0.417

**权重集中分析:**
- 最大权重 Router: graphrouter (0.417)
- 权重过度集中: 否

#### finance_dataset_835245df-3585-4913-a460-730158048891

- **任务类型:** financial_audit_compliance_qa
- **风险等级:** high
- **M1 选择:** deepseek-chat
- **M2 选择:** qwen-plus

**M1 融合排名:** [1.6666666666666667, 1.6666666666666667, 2.0, 0.6666666666666666]

**M2 动态权重分析:**

- **knnrouter:**
  - Top1: qwen-plus
  - Accept Prob: 0.359
  - Fail Prob: 0.788
  - Regret Pred: 0.0426
  - Normalized Weight: 0.360

- **mlprouter:**
  - Top1: qwen-plus
  - Accept Prob: 0.622
  - Fail Prob: 0.831
  - Regret Pred: 0.0262
  - Normalized Weight: 0.497

- **graphrouter:**
  - Top1: glm-5.2
  - Accept Prob: 0.175
  - Fail Prob: 0.827
  - Regret Pred: 0.1110
  - Normalized Weight: 0.143

**权重集中分析:**
- 最大权重 Router: mlprouter (0.497)
- 权重过度集中: 否

#### finance_dataset_c6141817-0c1b-44f6-bbbf-4f64c5ede190

- **任务类型:** financial_audit_compliance_qa
- **风险等级:** high
- **M1 选择:** deepseek-chat
- **M2 选择:** qwen-turbo

**M1 融合排名:** [2.3333333333333335, 2.0, 1.0, 0.6666666666666666]

**M2 动态权重分析:**

- **knnrouter:**
  - Top1: qwen-turbo
  - Accept Prob: 0.367
  - Fail Prob: 0.777
  - Regret Pred: 0.0206
  - Normalized Weight: 0.323

- **mlprouter:**
  - Top1: qwen-turbo
  - Accept Prob: 0.683
  - Fail Prob: 0.806
  - Regret Pred: 0.0649
  - Normalized Weight: 0.522

- **graphrouter:**
  - Top1: glm-5.2
  - Accept Prob: 0.249
  - Fail Prob: 0.842
  - Regret Pred: 0.1317
  - Normalized Weight: 0.155

**权重集中分析:**
- 最大权重 Router: mlprouter (0.522)
- 权重过度集中: 是

#### finance_dataset_ef754689-a758-4cce-9fb8-1efecaec496e

- **任务类型:** financial_table_text_reasoning
- **风险等级:** medium
- **M1 选择:** deepseek-chat
- **M2 选择:** qwen-turbo

**M1 融合排名:** [2.3333333333333335, 1.3333333333333333, 1.3333333333333333, 1.0]

**M2 动态权重分析:**

- **knnrouter:**
  - Top1: qwen-turbo
  - Accept Prob: 0.523
  - Fail Prob: 0.258
  - Regret Pred: 0.0252
  - Normalized Weight: 0.378

- **mlprouter:**
  - Top1: qwen-turbo
  - Accept Prob: 0.586
  - Fail Prob: 0.534
  - Regret Pred: 0.0036
  - Normalized Weight: 0.266

- **graphrouter:**
  - Top1: glm-5.2
  - Accept Prob: 0.577
  - Fail Prob: 0.365
  - Regret Pred: 0.0685
  - Normalized Weight: 0.356

**权重集中分析:**
- 最大权重 Router: knnrouter (0.378)
- 权重过度集中: 否

... 还有 3 个任务

### 2. M1 成功但 M3 失败 (8 个任务)

**任务列表:**

#### finance_dataset_08439cc4-cc83-400e-ae6e-0550c2a91344

- **任务类型:** financial_audit_compliance_qa
- **风险等级:** high
- **M2 选择:** qwen-plus
- **M3 选择:** qwen-plus

**M3 Conformal 分析:**
- Safe Router Set: ['mlprouter']
- Risk Limit: N/A
- M3 是否修正了 M2: 否
- Safe Set 是否包含正确选择: 否

**Router Safety Status:**

- **knnrouter:**
  - In Safe Set: 否
  - Conformal Bound: 0.2154

- **mlprouter:**
  - In Safe Set: 是
  - Conformal Bound: 0.0646

- **graphrouter:**
  - In Safe Set: 否
  - Conformal Bound: 0.1265

#### finance_dataset_49d7ee2d-93a5-4ed7-9fe9-030ead91c8d2

- **任务类型:** financial_table_text_reasoning
- **风险等级:** medium
- **M2 选择:** qwen-turbo
- **M3 选择:** qwen-turbo

**M3 Conformal 分析:**
- Safe Router Set: ['knnrouter', 'mlprouter', 'graphrouter']
- Risk Limit: N/A
- M3 是否修正了 M2: 否
- Safe Set 是否包含正确选择: 是

**Router Safety Status:**

- **knnrouter:**
  - In Safe Set: 是
  - Conformal Bound: 0.0562

- **mlprouter:**
  - In Safe Set: 是
  - Conformal Bound: 0.0704

- **graphrouter:**
  - In Safe Set: 是
  - Conformal Bound: 0.1176

#### finance_dataset_835245df-3585-4913-a460-730158048891

- **任务类型:** financial_audit_compliance_qa
- **风险等级:** high
- **M2 选择:** qwen-plus
- **M3 选择:** qwen-plus

**M3 Conformal 分析:**
- Safe Router Set: ['mlprouter']
- Risk Limit: N/A
- M3 是否修正了 M2: 否
- Safe Set 是否包含正确选择: 否

**Router Safety Status:**

- **knnrouter:**
  - In Safe Set: 否
  - Conformal Bound: 0.2154

- **mlprouter:**
  - In Safe Set: 是
  - Conformal Bound: 0.0646

- **graphrouter:**
  - In Safe Set: 否
  - Conformal Bound: 0.1265

#### finance_dataset_c6141817-0c1b-44f6-bbbf-4f64c5ede190

- **任务类型:** financial_audit_compliance_qa
- **风险等级:** high
- **M2 选择:** qwen-turbo
- **M3 选择:** qwen-turbo

**M3 Conformal 分析:**
- Safe Router Set: []
- Risk Limit: N/A
- M3 是否修正了 M2: 否
- Safe Set 是否包含正确选择: 否

**Router Safety Status:**

- **knnrouter:**
  - In Safe Set: 否
  - Conformal Bound: 0.2154

- **mlprouter:**
  - In Safe Set: 否
  - Conformal Bound: 0.0646

- **graphrouter:**
  - In Safe Set: 否
  - Conformal Bound: 0.1265

#### finance_dataset_ef754689-a758-4cce-9fb8-1efecaec496e

- **任务类型:** financial_table_text_reasoning
- **风险等级:** medium
- **M2 选择:** qwen-turbo
- **M3 选择:** qwen-turbo

**M3 Conformal 分析:**
- Safe Router Set: ['knnrouter', 'mlprouter', 'graphrouter']
- Risk Limit: N/A
- M3 是否修正了 M2: 否
- Safe Set 是否包含正确选择: 是

**Router Safety Status:**

- **knnrouter:**
  - In Safe Set: 是
  - Conformal Bound: 0.0562

- **mlprouter:**
  - In Safe Set: 是
  - Conformal Bound: 0.0704

- **graphrouter:**
  - In Safe Set: 是
  - Conformal Bound: 0.1176

... 还有 3 个任务

### 3. M1 失败但 M2 成功 (8 个任务)

**任务列表:**
- finance_dataset_14a221e6-0008-4445-8672-38ece52f2dbe
- finance_dataset_3c4a695b-946c-46b9-a0b7-3eea80e93955
- finance_dataset_48c3b9b7-0d9f-4919-9b6e-1659e72cb7f8
- finance_dataset_716dff82-ebc4-46b9-89f5-4f7f49c92548
- finance_dataset_9654e872-339e-4caa-a704-e9d5ca78a3e2

### 4. M1 失败但 M3 成功 (6 个任务)

**任务列表:**
- finance_dataset_14a221e6-0008-4445-8672-38ece52f2dbe
- finance_dataset_3c4a695b-946c-46b9-a0b7-3eea80e93955
- finance_dataset_48c3b9b7-0d9f-4919-9b6e-1659e72cb7f8
- finance_dataset_finqa_001593
- finance_dataset_finqa_002522

## M1 安全优势机制分析

### 关键发现

**待验证假设:** "M1 等权融合通过专家制衡而更安全"

**证据评估:**
- M1_safe_M2_fail 任务数: 8 (预期约 3 个)
- M1_safe_M3_fail 任务数: 8 (预期约 3 个)

### M2 动态权重分析

**M2 失败任务的共同特征:**

- 平均最大权重: 0.453
- 权重过度集中 (>0.5) 的任务: 1/8
- 最常被过度加权的 Router: mlprouter (4 次)

### M3 Conformal Gate 分析

**M3 失败任务的共同特征:**

- Safe Set 为空的任务: 2/8
- Safe Set 包含正确选择但仍失败的任务: 2/8

## 结论

### M1 安全优势机制验证

**假设:** "M1 等权融合通过专家制衡而更安全"

**验证结果:**

✅ **部分支持** - 存在 M1 救回 M2 失败的任务，但需要更多证据

**潜在机制:**
1. 等权融合避免了单一专家的错误
2. 三个专家的排名互相抵消了极端错误
3. 动态权重过度集中在某个专家导致 M2 失败

### M3 Gate 状态

**最终判定:** ✅ PASS

**条件检查:**
- M3 Utility (0.8654) >= M2 Utility (0.8647): ✅
- M3 Failure (30.0%) <= M2 Failure (30.0%): ✅

**安全性评估:**
- 虽然本次运行 M3 通过了 gate，但 M3 的 Failure Rate (30.0%) 仍然比 M1 (15.0%) 差
- 这表明 M3 的 utility 改进并没有带来安全性改进

## 下一步建议

**如果 M1 确实通过专家制衡更安全:**
- 设计 Safety-Preserving Dynamic Fusion
- 以 M1 为安全锚点，动态融合只在"有足够证据证明更好"时覆盖 M1

**如果 M1 安全性来自其他机制:**
- 重新分析 M1 的选择逻辑
- 探索其他可能的安全机制

**关键决策:** 需要基于真实 failure 数据而非 Oracle 匹配进行最终判断。

---

**Phase 2.3 真实 Trace 基础分析完成**

**限制:** 本分析基于 Oracle 匹配代理指标，需要基于真实 failure 数据重新验证。
