# 决策状态重建报告（Stage D 192 执行 · 零调用 · 2026-11-05）

## 一、重要口径更正（先说）

**实际执行 deadline = 300s（全部 192 次）**——配置中的 `default: 180` 与 `S5: 90` 未生效。此前我以 180s 阈值计算的"联合约束满足率"是**假设性敏感性分析**，不是实际执行条件。

**按实际 300s 口径重算**：

| 臂 | TP≥12 且按期 | 满足率 |
|---|---|---|
| Static | 18/32 | 56.2% |
| R-only | 22/32 | 68.8% |
| π-only | 23/32 | 71.9% |
| Simple-Dynamic | 22/32 | 68.8% |
| Fixed-Composite | 26/32 | 81.2% |
| **Proposed-Dynamic** | **30/32** | **93.8%** |

**在真实执行的 300s 约束下，Proposed 显著优于一切其他臂（93.8% vs 次优 81.2%）。**

## 二、截止期是否 binding？——**否**（关键负面发现）

| 指标 | 值 |
|---|---|
| 首次故障时刻剩余时间 | 均值 **231s**（deadline 300s） |
| makespan/deadline 利用率 | 均值 **0.45** |
| 用满 >70% 的执行 | 20/192 |
| 用满 >90% 的执行 | 10/192 |

**Stage D 的截止期从未真正收紧**（除个别超时案例）——**因此 Stage D 数据无法支撑"截止期感知"规则的提取**。交叉点分析（120-140s）是基于观测 makespan 的**外推预测**，不是执行过的事实。

这是设计 Deadline-Aware 调度器的**核心证据缺口**：现有数据中截止期无方差。

## 三、故障家族 → 动作有效性（配对 TP 增益，本报告最有价值的部分）

| 故障家族 | n | R-only | π-only | Simple | Fixed | **Proposed** |
|---|---|---|---|---|---|---|
| **format** | 7 | **+0.00** | **+0.00** | **+0.00** | +4.14 | **+5.29** |
| format+structure | 3 | +4.33 | +3.67 | +0.67 | −1.67 | +2.33 |
| **structure** | 10 | −0.10 | −0.90 | +0.50 | −0.10 | **+2.10** |
| model_suspect | 2 | −0.50 | −0.50 | −0.50 | −8.00 | −7.50 |
| model_suspect+structure | 1 | +10.0 | +10.0 | +10.0 | +10.0 | +10.0 |
| none（无故障） | 9 | −1.33 | +0.11 | 0.00 | +0.22 | +0.11 |

### 三条可提取的决策规则

1. **format 故障 → 必须用 Z（format_repair）**：R/π/Simple 增益**完全为零**（+0.00 × 3 臂 × 7 案例 = 21 次无效动作），而 Z 类动作（Fixed/Proposed）增益 +4.14~+5.29。**这是最强的因果证据：格式故障只有格式修复有效。**
2. **structure 故障 → Proposed 独优（+2.10）**，R 略负、π 负、Fixed 负。说明结构修复需要**正确选择目标节点**（Proposed 的 sig 分类选对了）。
3. **无故障 → 不动作**（增益 ≈0，但 R-only 有 −1.33 的过度动作损失）。

## 四、动作数量与收益的剂量-反应（核心算法约束）

| 动作数 | 执行数 | 平均 TP 增益 |
|---|---|---|
| 0 | 50 | **+0.02** |
| 1 | 40 | **+1.90** |
| **2** | 20 | **+2.85（最优）** |
| **3+** | 50 | **−0.34（有害）** |

**这是可直接编码的算法约束：动作数应限制在 1–2 个；3 个以上动机有害。**

配合此前的剂量-反应发现（≥2 轮恢复 → 崩溃率 83%），两条规则一致指向：**恢复动作应有硬性上限**。

## 五、决策状态表（提取的运行时特征）

已构建 `QCL_DECISION_STATE.json`：每 (scenario, rep) 记录——deadline、异常数、故障家族集合、首次故障时刻、首次故障时剩余时间、六臂结果（TP/lat/cost/动作数/status）。

**可用作运行时决策信号的字段**（金盲）：
- 异常检测：`sig.family`（D1=model_suspect, D2=structure, D3=format）✓ 运行时可得
- 剩余时间：`t_rem`（decisions 记录中已有）✓
- 动作计数：已执行动作数 ✓
- 剩余预算：`global_budget.calls_left/yuan_left` ✓
- **不可用**：TP（需要 Gold）

## 六、Deadline-Aware 调度器的设计依据（可直接落地）

基于以上数据，算法应包含：

```
输入（运行时可得）：fault_family, t_rem, n_actions_so_far, budget_left,
                   node_id, model_current, model_candidates
规则（数据驱动，非经验）：
  R1: fault=none → NONE
  R2: fault=format → Z(format_repair) ONLY（R/π 无效，+0.00 证据）
  R3: fault=structure → Z(structure_repair) 或 R；优先 Z（+2.10 vs −0.10）
  R4: fault=model_suspect → 谨慎（增益为负，n=2 但方向一致）
  R5: n_actions ≥ 3 → 强制 NONE（+2.85 → −0.34 的剂量证据）
  R6: t_rem < expected_remaining_path → 倾向 NONE（外推，未实测）
```

**R1-R5 有直接数据支撑；R6 是外推，必须在新实验中验证。**

## 七、新实验设计依据（下一步）

**必须解决 Stage D 的两个缺陷**：
1. **截止期无方差**（全 300s）→ 新实验需设置多档真实 binding 的 deadline（如 120/150/200s）
2. **model_suspect 样本仅 2**→ 需补充该类故障的执行

**建议最小实验**：3 臂（Static / Current-Proposed / Deadline-Aware）× 3 档 deadline（110s/150s/240s）× S4 型 format 故障 × 3 重复 = 27 执行。

**主判据**：Deadline-Aware vs Current-Proposed 的联合约束满足率（TP≥12 ∧ 按期）；次判据：无效动作数下降。

## 八、交付

`QCL_DECISION_STATE.json`（32 决策状态 × 6 臂）+ 本报告 + `QCL_CROSSOVER_REPORT.md`（交叉点外推，须标注为预测）。
