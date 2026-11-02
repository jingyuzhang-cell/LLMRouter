# M6-3: 奖励函数与约束机制设计（2026-10-31，零调用）

基于 M6-4 归因结果设计。核心原则：**奖励必须反映实际收益结构，不预设策略偏好。**

---

## 一、设计原则（从 M6-4 归因结果推导）

| M6-4 发现 | 奖励设计含义 |
|---|---|
| Z 的效果取决于故障层级 | 奖励不能给 Z 固定正/负分，必须条件化于故障类型 |
| R 在持久故障下是纯浪费 | R 的奖励应包含"无效重试惩罚" |
| π 在差距<0.15 时不激活是正确的 | 不激活的 π 不应被惩罚（正确的 keep） |
| Joint 效果完全来自 Z | 不能给 Joint 一个"额外联合奖励" |
| Z 成本效应是双向的 | 成本奖励必须拆分为新增成本−避免浪费 |
| INCOMPLETE ≠ Q=0 | 恢复奖励用完成率，质量奖励用 Q|COMPLETE |

---

## 二、奖励体系架构

### 2.1 总体结构：约束式多目标，不做线性加权

```
maximize: Q_terminal | COMPLETE
subject to:
    C_total ≤ B (budget hard cap)
    L_total ≤ D (deadline hard cap)
    reliability ≥ R_min (minimum reliability, soft)
```

**不使用** `R = αQ − βC − γL` 的线性加权，因为：
- 不同指标量纲不可比
- 权重选择本身就是研究方向（不能预设立场）
- 线性加权鼓励奖励投机（如牺牲质量换低成本）

### 2.2 四维独立信号

每个 run 产生一个**奖励向量**而非标量：

```json
{
  "quality_reward": 0.444,        // Q_terminal | COMPLETE
  "cost_reward": -0.123,          // ΔC relative to baseline (negative = cheaper)
  "latency_reward": -0.31,        // ΔL relative to baseline
  "reliability_reward": 1.0       // COMPLETE=1, DEGRADED=0.5, INCOMPLETE=0
}
```

**关键规则**：
- INCOMPLETE 时 `quality_reward = null`（不是 0）
- `cost_reward` 和 `latency_reward` 以基线为参照（可正可负）
- `reliability_reward` 独立计量，不与 Q 混合

### 2.3 调度动作的条件化奖励

#### Z（结构重构）

| 状态条件 | 正确动作 | 奖励 |
|---|---|---|
| fault_layer=merge_interface + hetero_parents + persistent | 执行 Z | +recovery_bonus + cost_saving |
| fault_layer=merge_interface + hetero_parents + persistent | 不执行 Z | −missed_recovery_penalty |
| fault_layer=node_logic 或 inherited | 不执行 Z | +correct_rejection_bonus |
| fault_layer=node_logic 或 inherited | 执行 Z | −wasted_restructure_penalty |
| fault_layer=none（无故障） | 不执行 Z | +correct_inaction_bonus |
| fault_layer=none（无故障） | 执行 Z | −unnecessary_restructure_penalty |

**Z 的成本奖励拆分**（从 M6-4 悖论解决推导）：

```
Z_cost_reward = C(避免的无效重试) − C(新增拆分节点)
             = (无Z组的重试浪费) − (拆分新增的执行成本)

H1 SC-E1 例：7400 − 2800 = +4600 tok（正奖励，Z 节省了资源）
R9B 例：     0 − 5600 = −5600 tok（负奖励，Z 增加了成本）
```

#### R（执行恢复）

| 状态条件 | 正确动作 | 奖励 |
|---|---|---|
| fault.persistence=transient | 执行 R（重试） | +recovery_bonus |
| fault.persistence=transient | 不重试直接放弃 | −missed_recovery_penalty |
| fault.persistence=persistent | **不重试**（识别为无效） | +correct_early_exit_bonus |
| fault.persistence=persistent | 重试（无效浪费） | −wasted_retry_penalty × attempts |

**R 的核心学习目标**：识别故障的持久性，避免在持久故障上浪费重试。

#### π（模型重分配）

| 状态条件 | 正确动作 | 奖励 |
|---|---|---|
| capability_gap ≥ threshold + weak_model_assigned | 切换到强模型 | +quality_improvement − switch_cost |
| capability_gap ≥ threshold + weak_model_assigned | 保持弱模型 | −missed_improvement_penalty |
| capability_gap < threshold | **保持原模型** | +correct_inaction_bonus |
| capability_gap < threshold | 切换模型 | −unnecessary_switch_penalty |

**π 的核心学习目标**：识别有真实能力差距的节点，在差距不足时不浪费切换。

### 2.4 交互效应奖励

| 交互类型 | 奖励处理 |
|---|---|
| Z×R 正向交互（Z 创造 R 的恢复机会） | 不单独奖励——包含在 Z+R 组合效果中 |
| Z×π 交互（π 在 Z 恢复后提升质量） | 需 Z 先恢复 → π 质量增量单独计量 |
| R×π 交互 | 当前无证据，不预设奖励 |

**原则**：交互效应不单独设奖励项，避免重复计算。

---

## 三、奖励数值设计

### 3.1 质量奖励

```
quality_reward = Q_terminal | COMPLETE
               = (covered_facts / total_reference_facts) × fact_weight
```

- 直接使用 terminal_quality v1.2.3 的输出
- INCOMPLETE 时为 null（不评分）
- 关键事实额外加权（critical gate 已在 v1.2.3 中实现）

### 3.2 成本奖励

```
cost_reward = (C_baseline − C_treatment) / C_baseline
```

- 以同 cell 的 Static 基线为参照
- 正值 = 比基线便宜，负值 = 比基线贵
- 需标注 C_baseline 来源（同 cell / 跨 cell / 估算）

### 3.3 时延奖励

```
latency_reward = (L_baseline − L_treatment) / L_baseline
```

- 同上，以基线 makespan 为参照

### 3.4 可靠性奖励

```
reliability_reward = 1.0  if COMPLETE
                   = 0.5  if COMPLETE with degradation
                   = 0.0  if INCOMPLETE
```

- **注意**：这是执行可靠性的简化计量，不能替代质量
- INCOMPLETE 的 reliability=0 是正确语义（执行失败），不同于 Q=0

---

## 四、与 P0 评价器的关系

| 维度 | 使用 P0 quality_v4 | 使用 Schema V1 |
|---|---|---|
| Q_terminal | ✓ 主评分器（六维） | 从 execution_results.terminal 读取 |
| 节点级质量 | ✓ fact_coverage | 从 per_node.quality_signal 读取 |
| 成本/时延 | ✗ P0 不管 C/L | 从 cost_latency 独立读取 |
| 可靠性 | ✓ delivery 分离 | 从 terminal.reliability_status 读取 |
| 归因 | ✗ P0 不做归因 | 从 attribution 数组读取 |

**P0 管质量，Schema V1 管全维度记录，M6-3 的奖励函数消费两者。**

---

## 五、防止奖励投机

| 投机行为 | 防护机制 |
|---|---|
| 牺牲质量换低成本 | 约束式（max Q s.t. C≤B），不是线性权衡 |
| 无限重试刷质量 | 持久故障下重试有 waste_penalty |
| 不必要的 Z/π 动作 | 正确不作为有 bonus（correct_inaction） |
| INCOMPLETE 被惩罚为 Q=0 | INCOMPLETE 的 Q=null，可靠性单独计量 |
| 单次成功被过度奖励 | evidence_status 标记 PRELIMINARY，策略更新有置信度折扣 |
| 交互效应重复计算 | 交互不单独奖励，包含在组合效果中 |

---

## 六、策略更新规则（从奖励到学习）

### 短期（现有数据可提取的规则）

```
RULE Z_1: IF fault_layer == merge_interface
          AND hetero_parents_exist
          AND persistence == persistent
          THEN z_action = SPLIT_VERIFY
          BASIS: H1 (A-level, n=1 cell) + R9B (A-level, n=3 cells)

RULE R_1: IF persistence == persistent
          AND retry_attempts >= 1
          AND fault_layer != transient
          THEN r_action = early_exit
          BASIS: H1 G2/G3/G4 (A-level, n=3 groups all failed)

RULE PI_1: IF capability_gap < 0.15
           THEN pi_action = keep
           BASIS: H1 G6 (A-level, gap=0.03, correct keep)
                   DYNPI (A-level, 14 no-fault runs, correct keep)

RULE PI_2: IF capability_gap >= 0.15
           AND weak_model_assigned
           THEN pi_action = switch_to_strong
           BASIS: DYNPI T1-r2 (A-level, n=1, +0.167 Q)
           CONFIDENCE: LOW (single cell, needs replication)
```

### 中期（需 MVR_V1 或新实验数据）

- 模型画像在线更新：用节点级 F1 修正 PROFILE_Q
- 成本预测：根据节点类型 + 模型 + 输入长度预估 token
- 策略组合收益矩阵：不同异常 × 不同策略的期望收益向量

### 长期（需完整系统闭环）

- 在线策略优化：贝叶斯更新或 bandit 方法
- 端到端学习：从 DAG 生成到调度决策的联合优化
- 多任务迁移：在一个任务学到的规则是否泛化到其他任务

---

## 七、M6-3 交付物清单

| 文件 | 状态 | 内容 |
|---|---|---|
| M6_REWARD_MODEL.md | ✓ 本文件 | 奖励体系架构 + 条件化规则 + 防投机 |
| FEEDBACK_SCHEMA_V1.json | ✓ M6-2 | 数据结构（已含奖励向量字段） |
| M6_CONDITIONAL_ATTRIBUTION_REPORT.md | ✓ M6-4 | 归因结果（奖励设计的输入） |
| 短期可提取规则 | ✓ 4条 | Z_1, R_1, PI_1, PI_2（附证据等级） |
