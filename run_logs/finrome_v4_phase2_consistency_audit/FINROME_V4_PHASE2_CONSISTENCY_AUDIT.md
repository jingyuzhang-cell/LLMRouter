# Fin-RoME v4 Phase 2.1: 跨阶段一致性审计报告

**生成时间:** 2026-08-18T15:21:16.962417+00:00
**审计类型:** Phase 2.1 - 跨阶段一致性审计

## 执行摘要

### 关键发现

**Safety Oracle 矛盾:** ❌ 未解决
- Phase 1 Safety Oracle Failure Rate: 15.0%
- Phase 2 Safety Oracle Failure Rate: 5.0%
- 一致性状态: 不一致

**Train/Calibration 隔离:** ✅ 通过
- 分割互斥性: ✅ 完全互斥
- 历史效用一致性: ❌ 不一致

**Router 实现来源:** SURROGATE
- KNN Router: surrogate - 重新实现的 KNNRouterExpert 类
- MLP Router: surrogate - 重新实现的 MLPRouterExpert 类
- Graph Router: surrogate - 重新实现的 GraphRouterExpert 类

**M1/M3 实现类型:** FORMAL
- M1 类型: router_expert_fusion
- M3 类型: formal_m3

## 详细分析

### 1. Safety Oracle 一致性分析

**不一致任务数量:** 12


**不一致任务详情:**

| 任务ID | Phase1 Oracle | Phase2 Oracle | Phase1 失败 | Phase2 失败 | 一致性 |
|--------|---------------|---------------|-------------|-------------|--------|
| finance_dataset_14a221e6-0008-... | deepseek-chat | qwen-turbo | False | False | ❌ |
| finance_dataset_3c4a695b-946c-... | deepseek-chat | qwen-plus | False | False | ❌ |
| finance_dataset_49d7ee2d-93a5-... | glm-5.2 | glm-5.2 | True | False | ❌ |
| finance_dataset_835245df-3585-... | deepseek-chat | glm-5.2 | True | False | ❌ |
| finance_dataset_87d1dc85-d372-... | glm-5.2 | qwen-plus | False | False | ❌ |
| finance_dataset_c6141817-0c1b-... | deepseek-chat | qwen-turbo | False | False | ❌ |
| finance_dataset_finqa_001401... | deepseek-chat | qwen-turbo | False | False | ❌ |
| finance_dataset_finqa_002522... | deepseek-chat | qwen-turbo | False | False | ❌ |
| finance_dataset_finqa_004591... | deepseek-chat | glm-5.2 | False | False | ❌ |
| finance_dataset_finqa_006147... | glm-5.2 | qwen-plus | False | False | ❌ |
| finance_dataset_finreflect_8d4... | deepseek-chat | qwen-plus | False | False | ❌ |
| finance_dataset_finreflect_c07... | deepseek-chat | glm-5.2 | False | False | ❌ |

### 2. Train/Calibration 隔离审计

**分割互斥性检查:**
- Train-Calibration 互斥: ✅
- Train-Test 互斥: ✅
- Calibration-Test 互斥: ✅

**历史效用计算:**
- Phase 2 报告值: {'deepseek-chat': 0.8515722316666668, 'glm-5.2': 0.7487953861111111, 'qwen-plus': 0.7771401116666666, 'qwen-turbo': 0.8312472830555556}
- 重新计算值 (仅训练集): {'deepseek-chat': 0.8049055650000001, 'glm-5.2': 0.7087953861111111, 'qwen-plus': 0.7182512227777778, 'qwen-turbo': 0.7690250608333334}
- 一致性: ❌ 不一致

### 3. Router 实现来源分析

**KNN Router:**
- 原始实现文件: ['scripts/run_offline_knn_baseline.py', 'run_logs/offline_knn_baseline/knnrouter_longformer.pkl']
- 原始类别: KNeighborsClassifier (sklearn)
- Phase 2 实现: surrogate - 重新实现的 KNNRouterExpert 类

**MLP Router:**
- 原始实现文件: ['scripts/evaluate_mlprouter_offline.py', 'llmrouter/models/mlprouter.py']
- 原始类别: MLPRouter (llmrouter.models)
- Phase 2 实现: surrogate - 重新实现的 MLPRouterExpert 类

**Graph Router:**
- 原始实现文件: ['scripts/run_offline_graphrouter_baseline.py', 'run_logs/offline_graphrouter_baseline/graphrouter_finance.pt']
- 原始类别: EncoderDecoderNet (llmrouter.models.graphrouter)
- Phase 2 实现: surrogate - 重新实现的 GraphRouterExpert 类

### 4. M1/M3 定义分析

**M1 定义:**
- 函数名: m1_equal_rank_fusion
- 实现类型: router_expert_fusion
- 使用 Router 专家: 是

**M3 定义:**
- 函数名: m3_weighted_fusion
- 实现类型: formal_m3
- 关键特性: risk_conditioned_weights, confidence_weighted, conformal_weighting

**性能对比:**
- 效用提升: 0.0064
- 失败率改进: 5.0%
- 预测匹配率改进: 30.0%

## 建议和结论

### 关键建议

1. CRITICAL: Safety Oracle 不一致！Phase 1 和 Phase 2 使用了不同的计算方法。
2. HIGH: 历史效用计算不一致，可能包含了非训练集数据。
3. MEDIUM: Phase 2 使用了 surrogate 实现，应该明确标注为原型而非原始 Router 重建。

### 审计结论

**Phase 2 指标有效性:** ❌ 无效
**可以进入 Phase 3:** ❌ 不可以
**关键问题已解决:** ❌ 否
**高优先级问题已解决:** ❌ 否

**总体审计状态:** ❌ FAIL

## 下一步行动

❌ **暂不能进入 Phase 3**

需要先解决以下关键问题：
1. Safety Oracle 一致性问题
2. Train/Calibration 隔离问题
3. Router 实现来源明确问题

修复这些问题后重新运行 Phase 2.1 审计。

---

**审计完成时间:** 2026-08-18T15:21:16.962499+00:00
**审计状态:** FAIL
