# FEEDBACK_CONTROLLER_V1 — 反馈感知联合控制器 A+B+C（2026-10-30，零调用完成）

> 按 operator 裁决：A（联合效用）+ B（真实预算约束，条件采用）+ C（节点
> 类型级画像）合并为一次完整控制器改进。零模型调用。

## 核心验证：反馈更新现在真正改变调度决策

**测试场景**：f3(timeline) + f4(entity) + f5(factcheck) + f6(report)，
预算 8000 token，已花费 2000。

| 画像 | π 分配 | 效用 |
|---|---|---|
| frozen | glm53, glm53, **flash**, glm53 | 0.174 |
| feedback | glm53, glm53, **glm53**, glm53 | 0.165 |

**差异原因**（从决策细节可证）：
- frozen 画像：factcheck Flash 质量 0.80 vs GLM 0.83（差距小）+
  Flash 成本 1063 < GLM 1362 → **Flash 胜出**（成本效用补偿了 0.03
  质量差距）
- feedback 画像：factcheck Flash 质量降至 0.72 + 成本升至 1595 →
  **GLM 胜出**（质量差距 0.11 + 成本差距缩小）

**这正是"反馈使调度器在确实不再是最优选择时正确改变决策"的行为。**

## 控制器架构（feedback_joint_controller.py）

```
CapabilityProfile（机制 C）
  ├── per (node_type, model) 质量估计（贝叶斯收缩）
  ├── per (node_type, model) 成本估计（token 实测）
  ├── per (node_type, model) 时延估计（秒实测）
  ├── per (node_type, model) 可靠性估计（合同通过率）
  └── update_from_execution(): 从真实执行反馈更新

plan_utility（机制 A）
  ├── U(π) = w_Q × Q̂ − w_C × Ĉ/C_max − w_L × L̂/D_remaining
  ├── Q̂ 含可靠性加权（质量 × 合同通过率）
  └── 不可行 → U = −9（硬约束过滤）

optimize_pi（机制 A + B）
  ├── ≤6 节点：穷举 2^n 组合（最多 64）
  └── >6 节点：贪心降级

decide() — 全联合决策入口
  ├── 枚举 (Z, R, π) 候选
  ├── 对每个候选调用 optimize_pi 计算联合效用
  ├── 选择 argmax U
  └── 输出决策理由（含"保持相同动作因为它仍然最优"的情形）
```

## 权重冻结（不做事后调参）

```python
JointWeights(w_Q=1.0, w_C=0.5, w_L=0.5)
```

## 预算来源（机制 B：来自真实任务约束，非人工收紧）

```python
Constraints(budget_tokens=<from task contract>,
            deadline_s=<from task contract>,
            budget_cash=0.0)  # subscription
```

**注意**：如果任务允许全 GLM 且预测表明全 GLM 是最优的，控制器将正确
保持全 GLM——不为产生差异而差异。

## 下一步（需授权后一次性执行）

在新的独立任务上完整比较：
- 原控制器（naive greedy）vs 反馈控制器（A+B+C）
- 六策略完整对照
- ≥3 重复/条件
- 独立终端 Q/C/L

**付费 HOLD 维持。论文暂停。**
