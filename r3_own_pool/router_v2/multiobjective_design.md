# P3 多目标决策设计（只设计，不实验）

前置：MA 单目标 (quality) 学得动之前，不跑任何多目标实验。本文档冻结决策形式，等信号。

## 决策规则

```
Score(q, m) = Û(q, m) − λc · Ĉ(q, m) − λl · L̂(q, m)
选择 argmax_m Score(q, m)
```

- `Û(q,m)`：共享效用预测器（router_v2/shared_utility_ma.py 的 U 头）
- `Ĉ, L̂`：成本/延迟。第一版不预测——直接用每个模型的边际常数（每 token 单价 × 历史均值长度；延迟同理）。模型内方差显著时才升级为 q 条件预测
- `λc, λl`：单位归一后待定。**禁止**在开发集上扫描 λ 挑最优——λ 在 utility_distributions.py 的分布分析出来后一次性定档，敏感性只报曲线不选点

## 与既有口径的衔接

- 成本：`r3_own_pool/collect/price_table.json`（r1-distill 为真实 API 价，本地槽为部署代理价，不混称 billing）
- 延迟：历史记录含本地/API 混合口径，只作 exploratory（clean matrix limitation 已声明）
- 目标量：`ΔU = U(q,R1) − U(q,Large)` 反号对称；扩模型池 = 加一行 embedding，不改形式

## 顺序与门控

1. P0 三基线（mmlu_learnability）：GTE > Task > Shuffle 且 CI 不含 0 → 才进 MA
2. MA 单目标 OOF 超过 DatasetBest（区间不覆盖 0）→ 才进多目标
3. 多目标只报告 Quality/Cost/Latency 三轴 + Pareto 点，不宣称单标量最优
