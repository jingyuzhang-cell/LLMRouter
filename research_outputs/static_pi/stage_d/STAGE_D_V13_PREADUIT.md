# V1.3 执行前零调用审计（四项 · 2026-11-05）

## 一、Fixed-Composite 执行语义审计

**源码**（`stage_d_executor.py:557-560`）：
```python
elif arm == "Fixed-Composite":
    acts = (([("structure_repair", node)] if node in D2.REPAIR_LIB else [])
            + [("format_repair", "FMT")]
            + ([("swap", node)] if ds_ok else []))
```

**语义**：对每个异常节点，**固定顺序执行** 结构修复(Z)→格式修复→模型切换(π)，不读取故障家族分类信号（`sig`），不根据运行时反馈调整动作集合。

**与 Proposed-Dynamic 的差异**（:561-570）：Proposed 读取 `sig` 的故障家族（structure/format/model_suspect/caliber_suspect），**仅选择匹配该家族的动作**。Fixed-Composite 不做此选择，全部执行。

**审计结论**：
- ✓ 完全不使用运行时反馈调整动作选择
- ✓ 与 Proposed 共享同一初始 DAG、异常检查点、预算与截止期
- ⚠️ **"全部执行" ≠ "最强固定策略"**——固定组合可能包含不必要的动作（如 format_repair 对 structure 故障是浪费），反而引入额外成本/时延。这是**保守方向**的固定对照（做了不该做的），不是"最优固定"（精确知道该做什么但不用反馈选择）。**论文中应标注为"全动作固定组合"而非"最强固定"**。

## 二、主检验/次级检验审计

V1.3.2 冻结的主检验：`Proposed-Dynamic` vs `Simple-Dynamic`（16 对，精确置换）。

**操作员建议改为**：主检验 `Proposed-Dynamic` vs `Fixed-Composite`。

**审计结论**：同意——这直接回答"反馈驱动的动态选择是否优于不选择的全部执行"。但 0.7719 功效基于 Proposed vs Simple 的效应量假设，**不适用于新主检验**。

**新功效估算（零调用近似）**：
- Fixed-Composite 在 S3/S4 场景中的预期 TP：因不选择动作（全执行），效果应介于 Simple-Dynamic（单动作）和 Proposed（精准选择）之间
- 若 Fixed ≈ Simple（全动作不比单动作差多少），新主检验效应量与原设计相近，功效 ≈ 0.77
- 若 Fixed > Simple（全动作确实有额外收益），新主检验效应量缩小，功效下降
- **须用 D2 pilot 数据（35 执行）中 Fixed-Composite 的实际 TP 分布重新估算**

## 三、Q_final 四个 Blocker 核查

执行器使用 `terminal_quality.evaluate_terminal_quality`（v1.2.3，冻结）。Q_final 为 None 的根因：

**`_formal_gold` 要求 `status="GOLD_CONFIRMED"` ∧ `gold_provenance ∈ FORMAL_GOLD_PROVENANCE`**。Stage D 任务合同中的事实槽位不满足这两个条件（Silver 级标注，非人工确认 Gold）。

**四个 Blocker**（P0_QFINAL_SCORING_CONTRACT.md）：
1. Gold 状态非 GOLD_CONFIRMED
2. gold_provenance 缺失或不符
3. 合同级值校验不通过
4. 最小覆盖门限未达标

**零调用可解？** Blocker 1-2 需要将 Silver 标注升级为 GOLD_CONFIRMED——**这是 Gold 变更，需操作员裁决**，不可由执行窗口单方面完成。Blocker 3-4 可能可通过合同修订解决，但同样属 Gold 变更。

**建议**：论文中使用 TP/23 作为**代理质量指标**（明确标注），Q_final blocker 保持透明披露。

## 四、预注册差异报告（V1.3.2 → V1.4 候选）

| 变更项 | V1.3.2 | V1.4 候选 |
|---|---|---|
| 主检验 | Proposed vs Simple | **Proposed vs Fixed-Composite** |
| 次级检验 | 无明确次级 | Proposed vs Simple-Dynamic |
| 功效 | 0.7719（Simple 基线） | **需重新估算**（Fixed 基线） |
| 臂数 | 6 | 6（不变） |
| 执行数 | 192 | 192（不变） |
| 统计方法 | 精确置换 | 不变 |
| Fixed 标注 | — | **"全动作固定组合"（非"最强固定"）** |

## 五、结论与建议

1. **Fixed-Composite 臂已存在且语义清晰**——但应标注为"全动作固定组合"而非"最强固定策略"
2. **主检验建议改为 Proposed vs Fixed**——需重新估算功效（建议用 D2 pilot 数据）
3. **Q_final blocker 需操作员 Gold 裁定**——当前建议用 TP/23 代理
4. **192 执行设计可保留**——基础设施完备，等明确 GO

**待操作员决策**：
- 是否接受主检验改为 Proposed vs Fixed？
- 是否接受 TP/23 作为代理质量指标？
- 确认后形成 V1.4 冻结版，再给 GO。
