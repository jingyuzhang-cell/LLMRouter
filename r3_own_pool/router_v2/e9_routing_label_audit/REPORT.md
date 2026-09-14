# E9：Routing Label Learnability Audit（零生成）

每个query-model的5次binary repeat上放Jeffreys后验，配对比较 P(θ_m>θ_R1)（1-D quadrature，不假定repeat配对）。冻结层级：switch(任一 p_win>0.9) → stay(min p_stay>0.9) → tie(P(|θ_best−θ_R1|<0.1)>0.9) → uncertain。

## 四个数字

1. 最佳模型统计上明确：**114/400**（switch 50 + stay 64）
2. 实际是 tie：**0/400**
3. 5次repeat无法判断：**286/400**
4. 可靠switch样本：Bayesian **50**，δ-margin严格版（P(θ_m−θ_R1>0.1)>0.9）**31**，E7频繁主义规则 77（与Bayesian重合 50）

## 每折有效正样本

| fold | dev n | switch | stay | tie | uncertain | switch按模型 |
|---|---:|---:|---:|---:|---:|---|
| 0 | 168 | 20 | 24 | 0 | 124 | medium:7, large:11, coder:2 |
| 1 | 168 | 23 | 25 | 0 | 120 | medium:6, large:11, coder:6 |
| 2 | 167 | 25 | 31 | 0 | 111 | medium:11, large:11, coder:3 |

## 加repeat能买到什么（后验预测，500 draws，种子冻结）

| 加repeat数 | switch | stay | unresolved(全量) | unresolved(当前uncertain子集内) |
|---|---:|---:|---:|---:|
| +5 | 0.205 | 0.197 | 0.598 | 0.795 |
| +10 | 0.232 | 0.201 | 0.567 | 0.748 |
| +15 | 0.272 | 0.221 | 0.507 | 0.669 |

## 决策映射（预注册）

- uncertain 占比高（>30–40%）→ 先加 repeats（标签精度不足是主因）；
- 标签已稳定但 switch 少 → 加 opportunity-enriched 新 query；
- 标签稳定且 switch 不少 → representation/架构才可能是瓶颈。

## 边界

- 独立Beta后验未建模模型间相关；0.9/0.1为冻结常数非调参。
- 预测模拟假设未来repeat与现有5次同分布（temp 0.7）。
- tie类的层级判定用了 p_win/p_stay 的补集近似（保守）。

文件：RESULTS.json / PER_QUERY.jsonl / PROTOCOL.json。
