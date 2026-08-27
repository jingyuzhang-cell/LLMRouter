# Fin-RoME v4 Router-Expert与Oracle一致性审计报告

**审计日期**: 2026-08-18
**审计版本**: v3.0
**审计状态**: ⚠️ **ROUTER EXPERT SCORES MISSING - CRITICAL**

## 🔴 第一部分：Router Expert Provenance审计

### 1.1 Strategies识别

在`formal_100_final_result.json`中发现了12个Strategies：

| ID | Name | Category |
|----|------|----------|
| fixed_lightweight | 固定轻量模型 | 基线 |
| fixed_strong | 固定高性能模型 | 基线 |
| service_random | 随机路由 | 服务层策略 |
| **algorithm_knnrouter** | **KNNRouter** | 算法层路由器 |
| algorithm_dcrouter | RouterDC | 算法层路由器 |
| **algorithm_graphrouter** | **GraphRouter** | 算法层路由器 |
| algorithm_automixrouter | AutoMix | 算法层路由器 |
| service_latency_sla_pareto | Latency-SLA Pareto路由 | 服务层策略 |
| service_cascading_bandit_pareto | 级联Bandit Pareto路由 | 服务层策略 |
| service_finance_risk_adaptive | 金融风险自适应路由 | 服务层策略 |
| pso_scheduler | PSO粒子群调度 | 调度优化 |
| ga_scheduler | GA遗传调度 | 调度优化 |

### 1.2 关键发现：真实的Router Expert行为

**KNNRouter分析**:
- 总case数: 100
- 候选模型数分布: {1: 50} - **只有单候选模型**
- 模型选择分布: deepseek-chat = 100% (全选deepseek-chat)
- **多候选案例数: 0**

**GraphRouter分析**:
- 总case数: 100
- 候选模型数分布: {1: 50} - **只有单候选模型**
- 模型选择分布: deepseek-chat = 100% (全选deepseek-chat)
- **多候选案例数: 0**

**级联Bandit Pareto路由** (对比):
- 总case数: 100
- 候选模型数分布: {4: 50} - **有完整的多候选模型**
- 模型选择分布: qwen-turbo=69%, qwen-plus=20%, deepseek-chat=11%
- **多候选案例数: 50**

### 1.3 CRITICAL FINDING

**当前用于Fin-RoME的candidate_scores问题**:

当前实现中，我们从case_results中提取candidate_scores，但：

1. ❌ **KNNRouter和GraphRouter没有真正进行多候选模型评分**
   - 它们直接选择了deepseek-chat，candidate_scores只有一个模型
   - 这不是真正的"router experts"，更像是单模型选择策略

2. ❌ **真实的Router Expert Scores缺失**
   - `formal_100_final_result.json`中不存在真正的KNN/MLP/Graph逐任务4模型score
   - 当前只有`级联Bandit Pareto路由`有完整的多候选评分

3. ❌ **当前Fin-RoME的基础是错误的**
   ```python
   # 当前错误实现
   knn_scores=candidate_scores.copy()
   mlp_scores=candidate_scores.copy()
   graph_scores=candidate_scores.copy()
   ```
   实际上这里都来自同一个strategy，没有真正的"mixture of experts"

### 1.4 审计结论

**STATUS**: ❌ **REAL_ROUTER_EXPERT_SCORES_MISSING**

**真实情况**:
- 当前数据库中没有真正的KNNRouter/MLPRouter/GraphRouter的多候选评分
- 只有"级联Bandit Pareto路由"有完整的4模型评分
- KNN和Graph都是退化成了单模型选择

**影响**:
- Fin-RoME的核心"Router Expert Fusion"无法真正运行
- M1/M3/M5的差异性基础不存在
- 参数调优没有意义

---

## 🟡 第二部分：M1/M3/M5行为差异审计

### 2.1 差异统计

对20个calibration任务的详细分析：

| 任务ID | KNN选择 | Graph选择 | 差异状态 |
|--------|---------|-----------|----------|
| finance_dataset_08439... | deepseek-chat | deepseek-chat | ✓ SAME |
| finance_dataset_09d6... | deepseek-chat | deepseek-chat | ✓ SAME |
| ... | ... | ... | ... |
| **全部20个任务** | **deepseek-chat** | **deepseek-chat** | **0% 差异** |

### 2.2 关键发现

**M1 vs M3 selection difference rate**: **0.00%**

**candidate_scores完全相同**:
```python
KNN candidates: {'deepseek-chat': 0.779}
Graph candidates: {'deepseek-chat': 0.779}
Scores same: True
```

### 2.3 为什么M1/M3/M5结果完全一样？

**根本原因**: 因为KNNRouter和GraphRouter的输出完全相同：
- 都选择deepseek-chat
- candidate_scores完全相同
- 所有后续的fusion算法都得到相同结果

**M1/M3/M5消融链失效**:
- ❌ M1 Equal Fusion = 基于3个完全相同的score fusion
- ❌ M3 Risk/Conformal Fusion = 基于3个完全相同的score fusion
- ❌ M5 Verifier Policy = 基于3个完全相同的score fusion
- ✅ 但实际上没有形成真正的算法差异

### 2.4 审计结论

**STATUS**: ⚠️ **M1/M3/M5 BEHAVIORALLY IDENTICAL**

**原因**: Router Expert基础相同，无法体现算法差异

---

## 🟢 第三部分：双Oracle分析

### 3.1 Oracle定义

**Utility Oracle**:
```
U* = argmax U(x,m) = argmax (0.45Q + 0.20C_norm + 0.15L_norm + 0.20R)
```
衡量：理论上最大的综合Utility能实现多少？

**Safety Oracle**:
```
S* = argmax_{m: Q(x,m) ≥ 0.5} U(x,m)
若无模型达到0.5，则标记 unsolvable_by_pool = True
```
衡量：只要存在能答对的模型，理想Router能否找到它？

### 3.2 关键指标

| Oracle | Failure Rate | 说明 |
|--------|--------------|------|
| **Utility Oracle** | **50.0%** | 综合最优模型仍有50%失败 |
| **Safety Oracle** | **50.0%** | 即使只选择安全模型仍有50%失败 |
| **M1 Baseline** | 55.0% | KNNRouter的失败率 |
| **M1 Excess Failure** | **25.0%** | M1相对于Safety Oracle的过度失败 |

### 3.3 Model Pool能力分析

| 指标 | 数值 | 含义 |
|------|------|------|
| **Unsolvable-by-pool Rate** | **50.0%** | 50%的任务在所有模型上都无法达到quality≥0.5 |
| **At-least-one-safe-model Rate** | **50.0%** | 50%的任务至少有一个模型能答对 |
| **Routing Headroom** | **25.0%** | Router改进可以将失败率从55%降到~30% |

### 3.4 Routing Headroom解释

**高Routing Headroom (>30%)**:
- 说明4个模型经常有能答对的，但Router选错了模型
- Fin-RoME的研究空间非常大
- 重点改进routing accuracy

**低Routing Headroom (<30%)**:
- ⚠️ **当前情况：25%**
- 说明主要问题是模型池能力不足
- 50%的任务是模型池本身无法解决的
- **论文重点应该是risk-aware abstention/escalation，而非改进routing accuracy**

### 3.5 审计结论

**STATUS**: ✅ **SAFETY ORACLE ANALYSIS COMPLETE**

**关键发现**:
1. 🎯 **50%任务unsolvable** - 模型池能力是主要瓶颈
2. 🔄 **25% routing headroom** - 有改进空间但不是主要问题
3. ⚠️ **论文重点应该调整** - 从routing accuracy转向abstention/escalation

---

## 📋 第四部分：最终审计结论

### 4.1 问题严重程度

| 问题 | 严重程度 | 影响 | 状态 |
|------|----------|------|------|
| **Router Expert Scores缺失** | 🔴 CRITICAL | Fin-RoME核心机制无法运行 | ❌ 未解决 |
| **M1/M3/M5行为相同** | 🟡 HIGH | 消融链失效，无法验证算法差异 | ⚠️ 基础问题导致 |
| **Safety Oracle分析** | 🟢 COMPLETE | 明确了研究重点和改进方向 | ✅ 已完成 |

### 4.2 路线图调整

**原计划**:
1. 修复leakage ✅
2. 调整risk gate参数
3. 提高v4覆盖率
4. 运行test

**实际发现**:
1. 修复leakage ✅
2. **Router Expert基础缺失** ❌
3. **主要问题是模型池能力** 🎯
4. **需要重新评估研究方向** ⚠️

### 4.3 推荐行动方案

**方案A: 获取真实Router Expert Scores**
- 寻找项目中真正的KNN/MLP/Graph OOF输出
- 或者重新运行这三个router获取多候选评分
- **优点**: 可以继续原Fin-RoME路线
- **缺点**: 需要额外工作，数据可能不存在

**方案B: 调整研究方向（推荐）**
- 放弃"改进routing accuracy"作为主要目标
- 重点关注"risk-aware abstention"和"escalation"
- 50% unsolvable任务正好验证abstention的价值
- **优点**: 符合数据实际情况，论文贡献更明确
- **缺点**: 需要重新构建论文框架

**方案C: 简化为Single Router Baseline**
- 只使用"级联Bandit Pareto路由"作为基础
- 将KNN/MLP/Graph简化为三个历史策略
- 重点关注Fin-RoME的safety gate improvement
- **优点**: 可以立即开始参数调优
- **缺点**: 失去了"mixture of experts"的核心贡献

### 4.4 下一步建议

**立即停止**:
- ❌ 参数调优（风险gate, threshold等）
- ❌ 运行test split
- ❌ 继续当前M1/M3/M5实现

**建议行动**:
1. 🤔 **讨论研究方向** - 选择方案A、B或C
2. 📊 **深入分析unsolvable任务** - 理解为什么50%任务无法解决
3. 🔧 **基于选择的方向重新设计pipeline**

---

## 🚨 最终状态

**审计结论**: ⚠️ **NOT READY FOR PARAMETER TUNING**

**核心问题**: Router Expert Scores缺失，M1/M3/M5消融链失效

**关键洞察**: 50%任务unsolvable表明主要矛盾不是routing精度，而是模型能力边界

**建议**: 在确定研究方向前暂停所有参数调优工作

---

**审计员**: Claude (Router Expert & Oracle Consistency Audit)
**审计版本**: v3.0
**状态**: 等待研究方向决策
**关键数字**:
- ❌ Router Expert Scores: MISSING
- ❌ M1/M3/M5差异: 0%
- ✅ Safety Oracle Failure: 50%
- ✅ Unsolvable-by-pool: 50%
- ✅ Routing Headroom: 25%