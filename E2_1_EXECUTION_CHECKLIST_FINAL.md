# E2.1 最终执行检查清单

## ✅ 已修正的关键问题

### 1. ✅ 样本量计算规则
- **修正**: 60题是候选规模，需要事前power/precision检查
- **冻结**: 最小效应量0.03，不能基于+0.117启发式结果估算power
- **规则**: 如果60题统计功效不足，在模型调用前调整到80或100题

### 2. ✅ N1输出格式严格化
- **修正**: 禁止自由文本输出，必须输出结构化证据ID
- **格式**: `{"evidence_ids": ["docX_pY_sZ", "tableA_rB_cC"]}`
- **目的**: 测量证据ID检索能力，而非语言生成质量

### 3. ✅ 评分体系明确化
- **修正**: 明确Precision/Recall/F1计算公式
- **多可接受集合**: `Q(x,m) = max_{g∈GoldSets} F1(Predicted, g)`
- **避免**: 模型找到等价正确证据被错误扣分

### 4. ✅ IAA定义具体化
- **修正**: 不再笼统说IAA≥0.85
- **冻结**: Mean Evidence F1 between annotators ≥ 0.85
- **处理**: 低于阈值的任务进入adjudication

### 5. ✅ 主要端点唯一化
- **修正**: 明确主要端点为Stable Semantic Oracle Gap (G_N1)
- **主门控**: G_N1 ≥ 0.03
- **次要端点**: S_N1 ≥ 10%, Median Margin > 0（支持性证据）

### 6. ✅ 3重复计算规则具体化
- **修正**: 不再只写"3 repeats"
- **冻结**: 三轮轮换设计：(1,2)→3, (1,3)→2, (2,3)→1
- **平均**: 对所有轮换方案求平均，避免单次重复偏差

### 7. ✅ Tie处理规则明确化
- **修正**: 提前定义tie判断规则
- **冻结**: ε = 0.01，|Q₁ - Q₂| < ε视为tie
- **报告**: 正式报告Tie Rate，不人为指定winner

### 8. ✅ E2.1-B成本计算修正
- **修正**: 区分实验分支和API调用
- **实际调用**: N1: 270次, N2-N4: 1080次, 总计~1350次
- **成本估算**: $4-6（原$1-2估算偏低）

### 9. ✅ 下游噪声控制
- **修正**: 冻结downstream设置避免随机噪声
- **冻结**: temperature、seed、prompts、repeats
- **分析**: Task-level paired comparison

### 10. ✅ 增加Gold Evidence控制臂
- **新增**: Arm D - Gold Evidence @ N1
- **目的**: 测量N1改进的理论上限
- **价值**: 如果Gold Evidence都不提升，说明N1不是系统瓶颈

### 11. ✅ 删除过度声明
- **修正**: 删除"首个完整因果链"表述
- **改为**: "We establish a controlled decomposition-to-routing causal chain"
- **避免**: 无文献支撑的"first"声明

### 12. ✅ 删除主观概率
- **修正**: 删除40-50%、30-40%等成功概率
- **改为**: 三种预注册结果（A/B/C outcome）
- **更科学**: 基于明确条件的决策树

## 🎯 最终实验设置摘要

### E2.1-A 核心参数
| 项目 | 正式设置 |
|------|----------|
| Tasks | Fresh 60（事前power检查，必要时调整）|
| Models | Qwen+ / GLM-5.2 / DeepSeek |
| Repeats | 3（三轮轮换设计）|
| Primary Node | N1 Evidence Localization |
| Gold | Evidence IDs + acceptable alternatives |
| Primary Quality | Evidence F1 |
| Primary Metric | Stable Semantic Oracle Gap |
| Secondary | Stable Specialist Opportunity Rate |
| Stability | Held-out Top1–Top2 Reversal Rate |
| Separation | Mean/Median Margin + Tie Rate |
| Primary Gate | G_N1 ≥ 0.03 |
| Secondary Support | S_N1 ≥ 10%, MedianMargin > 0 |

### E2.1-B 核心参数
| 项目 | 正式设置 |
|------|----------|
| Tasks | 30（从60题中确定性选择）|
| Arms | 4个（Qwen+ / GLM / DeepSeek / Gold Evidence）|
| Downstream | 完全相同（Qwen+ for N2-N4）|
| API Calls | ~1350次（N1: 270, N2-N4: 1080）|
| Estimated Cost | $4-6 |
| Primary Question | ΔQ_final > 0 with 95% CI not including 0? |

## 🚀 立即执行步骤

### TODAY: 协议最终冻结
- [ ] 最终审查E2.1_PROTOCOL_FINAL.json
- [ ] 确认所有12个修正点都已包含
- [ ] 计算SHA256并归档
- [ ] 创建protocol版本标签

### THIS WEEK: 事前Power分析
- [ ] 基于最小效应量0.03进行power计算
- [ ] 确定60题是否足够，必要时调整到80/100题
- [ ] 在任何模型调用前完成样本量确认

### THIS WEEK: 开始数据准备
- [ ] 开始收集多样化金融任务
- [ ] 建立证据标注界面（支持结构化ID输出）
- [ ] 创建标注指南（包含IAA计算方法）
- [ ] 准备gold evidence schema

### NEXT WEEK: 基础设施准备
- [ ] 设置成本监控（新的$4-6预算）
- [ ] 准备N1结构化输出解析器
- [ ] 建立三轮轮换设计的执行逻辑
- [ ] 准备Gold Evidence控制臂的输入格式

## 🛡️ 质量控制检查点

### 执行前检查
- [ ] Power分析完成并确认样本量
- [ ] 所有frozen parameters已记录
- [ ] IAA计算方法已明确定义
- [ ] Tie处理规则已冻结
- [ ] E2.1-B的4个arm设计已确认

### 执行中检查
- [ ] N1输出格式严格遵循结构化ID
- [ ] 3重复轮换设计正确实施
- [ ] Downstream设置在所有arm间完全相同
- [ ] 成本监控在$4-6预算范围内
- [ ] 无任何事后参数调整

### 分析前检查
- [ ] 主要端点G_N1计算正确
- [ ] 次要端点仅作为支持性证据
- [ ] Bootstrap CI计算包含所有轮换方案
- [ ] Tie Rate正确计算和报告
- [ ] Gold Evidence控制臂结果正确分析

## 🎯 核心科学问题

**E2.1将回答两个硬问题：**

1. **客观Evidence F1上，模型专长是否仍然存在？**
   - 不是启发式评分的+0.117
   - 而是客观的P/R/F1指标
   - 严格的C10兼容指标（G, S, R, Margin）

2. **这种节点专长是否真的改变最终答案质量？**
   - 不是理论上的可能性
   - 而是实测的ΔQ_final
   - 包含Gold Evidence理论上限对照

**只有这两个答案都是"是"，我们才真正拥有：**

```
Decomposition → Stable Node Specialization →
Routing Opportunity → End-to-End Value
```

## 📊 预注册结果框架

### Outcome A: Full Support
- **条件**: E2.1-A PASS AND E2.1-B PASS
- **解释**: 节点专长存在且提供端到端价值
- **行动**: 进入E2.2路由器训练（高置信度）

### Outcome B: Node-Only Support
- **条件**: E2.1-A PASS AND E2.1-B FAIL/MIXED
- **解释**: 专长存在但最终质量增益未确立
- **行动**: 调查瓶颈传递，不训练完整路由器

### Outcome C: No Confirmation
- **条件**: E2.1-A FAIL
- **解释**: 客观节点级专长未确认
- **行动**: 停止N1假设，探索性信号是启发式驱动的

## 🏁 最终状态

**协议状态**: ✅ E2.1_PROTOCOL_FINAL.json 已创建并包含所有12个修正点

**准备状态**: 🔄 准备最终审查和SHA256归档

**执行状态**: ⏸️ 等待协议最终冻结后开始执行

**科学价值**: 🎯 将决定43.3%探索性信号是否为真正的科学发现

---

**这个检查清单确保E2.1真正成为"确认性实验"而非"更严谨的探索实验"。所有关键细节都已修正，准备最终冻结协议。**