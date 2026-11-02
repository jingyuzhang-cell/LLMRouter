# M6-1: 历史实验反馈数据盘点（2026-10-31，零调用）

---

## 数据总量

6 轮实验，485 次真实调用，涵盖 3 种异常类型 × 3 种调度维度（Z/R/π）× 多种策略对照。

---

## 可用于反馈学习的数据清单

### A. 模型能力画像更新数据

| 来源 | 调用数 | 数据内容 | 更新目标 |
|---|---|---|---|
| Stage-B | 124 | arm 级 Q/cov/cite/tok/wall | 全局画像（无节点级分解） |
| DYNPI | 61 | 节点级成功/失败 + 模型切换记录 | reasoning 节点 flash vs glm53 |
| H1 | 79 | 节点级执行轨迹（含 split 节点） | verification 节点能力 |

**局限**：Stage-B 无节点级数据；DYNPI/H1 的节点级数据仅覆盖部分节点类型。

### B. R（执行恢复）收益归因数据

| 来源 | 配对设计 | 关键证据 |
|---|---|---|
| R6 | 恢复臂 vs Static | 恢复臂 Q_terminal > Static |
| DYNPI | R-only vs Static | R-only 全 COMPLETE（瞬态可恢复） |
| H1 | G2(R-only) vs G1(Static) | 两者均 INCOMPLETE（持久故障不可恢复） |

**条件化学习**：
- 瞬态故障 → R 可恢复（R6/DYNPI）
- 持久合并合同故障 → R 不可恢复（H1）
- **系统应学习**：故障类型决定 R 的有效性

### C. Z（结构重构）收益归因数据

| 来源 | 配对设计 | 关键证据 |
|---|---|---|
| R9B | Joint(Z,R,π) vs Joint(R,π) | Z 3/3 COMPLETE vs 0/3 INCOMPLETE |
| H1 | G5/G6(有Z) vs G1-G4(无Z) | Z 2/2 COMPLETE vs 0/4 INCOMPLETE |
| 故障继承测试 | 正常 vs 继承故障 | Z 在继承故障下也失败 |

**条件化学习**：
- 合并合同故障 + 异类双亲存在 → Z 有效
- 验证逻辑级故障（继承） → Z 无效
- **系统应学习**：Z 的有效性取决于故障层级（接口级 vs 逻辑级）

### D. π（模型重分配）收益归因数据

| 来源 | 配对设计 | 关键证据 |
|---|---|---|
| DYNPI | π-only vs Static-π | ΔQ=0.000 整体；T1-r2 单例 +0.167 |
| DYNPI 节点级 | — | 3/5 runs 实际切换了模型（flash→glm53） |
| H1 | G3(π-only) vs G1(Static) | 两者均 INCOMPLETE（持久故障非 π 可解） |
| H1 G6 | G6(全空间π) 内部 | π 未激活（差距 0.03 太小） |

**条件化学习**：
- 能力差距 ≥0.15 + 弱模型已分配 → π 激活且可能有益
- 能力差距 <0.15 → π 不应激活
- 持久合同故障 → π 无法解决
- **系统应学习**：π 的有效性取决于能力差距 + 故障类型

### E. 成本与时延反馈数据

| 来源 | 关键发现 |
|---|---|
| H1 SC-E1 | Z 组 token 比无 Z 组低 12-22%（避免无效重试） |
| R9B | B 臂成本 +39.6%（split 增加节点数） |
| DYNPI | π 平均成本 +13.2% |

**矛盾**：R9B 中 Z 增加成本，H1 中 Z 降低成本。原因是 R9B 的对照组（A 臂）已经用较少重试退出，而 H1 的对照组浪费了大量 token 重试。

**条件化学习**：Z 的成本效应取决于对照组是否在无效重试上浪费——如果无 Z 组会浪费，Z 就是负成本；如果无 Z 组快速失败，Z 是正成本。

---

## 数据可用性限制

| 限制 | 影响 | 解决方案 |
|---|---|---|
| 评分口径不统一 | 不同实验的 Q 不可直接比较 | 统一用 H1 的 6 组同 cell 数据做归因 |
| 节点级数据不完整 | Stage-B 无节点级分解 | 补充 MVR_V1 校准阶段数据 |
| 配对设计不一致 | 各实验对照组结构不同 | 仅用 H1 的完整 6 组配对做主归因 |
| 重复次数不足 | 多数 1-2 次，不可靠 | 需更多重复（等 GO 或新预算） |

---

## M6 反馈学习可行路径

### 短期（现有数据可做）

1. **Z 的条件化规则**：从 H1 SC-E1 + 故障继承测试中提取
   - IF fault_type == merge_contract AND node_has_hetero_parents THEN Z_effective = True
   - IF fault_type == logic_level THEN Z_effective = False

2. **R 的条件化规则**：从 R6/DYNPI/H1 中提取
   - IF fault_type == transient THEN R_effective = True
   - IF fault_type == persistent THEN R_effective = False

3. **π 的激活条件**：从 PROFILE_Q + DYNPI 中提取
   - IF capability_gap >= 0.15 AND weak_model_assigned THEN π_activate = True
   - IF capability_gap < 0.15 THEN π_activate = False

### 中期（需 MVR_V1 或新实验数据）

4. **模型画像在线更新**：用 MVR_V1 校准阶段产出的节点级 F1 更新画像
5. **成本预测模型**：根据节点类型和模型预测 token 消耗
6. **策略组合收益矩阵**：不同异常 × 不同策略的期望收益

### 长期（需完整系统闭环）

7. **在线策略优化**：根据历史反馈调整调度决策偏好
8. **DAG 结构学习**：从执行反馈中学习什么结构更适合什么任务

---

## 对 M6-2（Feedback Schema）的建议

基于以上盘点，反馈数据结构应包含：

```json
{
  "run_context": {
    "task_id": "...", "dag_snapshot": {...}, "initial_pi": {...},
    "budget_remaining": ..., "deadline_remaining": ...,
    "anomaly": {"node_id": "...", "type": "...", "scope": "merge|logic|transient"}
  },
  "scheduling_actions": [
    {"dimension": "Z|R|π", "action": "...", "decision_rationale": "...",
     "state_at_decision": {...}, "expected_outcome": "...", "actual_outcome": "..."}
  ],
  "execution_results": {
    "per_node": [{"node_id": "...", "model": "...", "status": "...",
                   "quality_signal": ..., "tokens": ..., "latency_s": ...}],
    "terminal": {"report_generated": true/false, "Q_terminal": ...,
                  "Q_reference": "...", "key_fact_results": [...]}
  },
  "cost_latency": {"total_tokens": ..., "per_model_tokens": {...},
                    "makespan_s": ..., "within_budget": ..., "within_deadline": ...},
  "attribution": {"Z_contribution": ..., "R_contribution": ..., "pi_contribution": ...,
                   "interaction_effects": ...}
}
```

**关键设计原则**：
- 质量/可靠性/成本/时延分别记录，不混合
- 每个 Z/R/π 决策都有决策时的状态快照
- INCOMPLETE 的 Q 不自动为 0
- 归因字段是 M6 的核心研究内容，不是简单的字段
