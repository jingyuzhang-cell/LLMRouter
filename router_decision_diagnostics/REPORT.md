# 419-query 决策诊断（只读后处理）

Best Single (qwen-plus): 0.802866; 三重复均值 Oracle: 0.880707; empirical gap: 0.077841。

## Margin 与模型贡献

| ε | Top-2 margin≤ε | 所有模型质量范围≤ε |
|---|---:|---:|
| 0 | 53.22% | 24.11% |
| 0.001 | 53.70% | 24.11% |
| 0.01 | 55.37% | 24.11% |
| 0.05 | 66.11% | 24.11% |

Top-2 tie 不表示全部模型相同，也不证明 ranking 必优。

| 模型 | 移除后的质量 Oracle 损失 | 移除后的 Zero Router AIQ 损失 |
|---|---:|---:|
| deepseek-chat | 0.016785 | 0.000000 |
| glm-5.2 | 0.006520 | 0.000000 |
| qwen-plus | 0.046342 | 0.057469 |
| qwen-turbo | 0.005337 | 0.011143 |
| gemini-2.5-flash | 0.000778 | 0.000000 |

## AIQ 与同质量成本（描述性开发集曲线）

积分区间为各固定模型平均成本的最小到最大值，所有方法共用；null 插值扩展低成本端，高成本端保持最高质量。Zero Router 为固定模型的概率混合，不是永远调用最强模型。

| 曲线 | AIQ | ΔAIQ vs Zero | 同质量节省：离散策略 | 同质量节省：凸包混合 |
|---|---:|---:|---:|---:|
| zero_router | 0.800957 | +0.000000 | 0.00% | 0.00% |
| knn_utility_mu0 | 0.800138 | -0.000819 | 不可达 | 不可达 |
| knn_utility_all24 | 0.800138 | -0.000819 | 不可达 | 不可达 |
| component_ridge_mu0 | 0.804182 | +0.003225 | -90.82% | -43.42% |
| component_ridge_all24 | 0.804182 | +0.003225 | -90.82% | -43.42% |
| oracle_mu0 | 0.879115 | +0.078158 | 73.16% | 78.87% |
| oracle_all24 | 0.879115 | +0.078158 | 73.16% | 78.87% |

μ=0 为主展示；all24 是不同延迟偏好的投影，不能声称同延迟公平比较。Oracle 行属于事后上界。

固定 OOF 的 AIQ 增益 95% 区间：
- knn_utility_mu0: [-0.020424, 0.020054]
- component_ridge_mu0: [-0.001966, 0.010540]

## 重复稳定性与样本量

单重复事后 Oracle 平均 0.889853；两次重复选模型、第三次评分 0.857408；三重复均值上取最大 0.880707。三次重复不足以提供认证去偏上界，不能套用其他论文的噪声百分比。

实际 ridge 配对差的 SD=0.062723。固定当前效应和方差的正态近似，需要约 2924 个独立测试 query 才有 80% 功效；这不是所需训练集大小，也不证明扩大训练集无效。

## 限制

- Exploratory reuse of 419 development queries, no untouched evaluation.
- Convex mixtures and same-quality point selection are post-hoc descriptive envelopes, not validation-selected deployed policies.
- All24 is a projection over different latency preferences, not a latency-constrained quality-cost comparison.
- Cost currency/price and latency deployment comparability inherited from historical data, not independently verified.
- Task bootstrap conditions on fitted OOF models, omits retraining variation; no multiple-testing correction.
- No new model fitting. OOF predicted Q/C/L scores were not saved, so learned epsilon tie breaking cannot be reconstructed from argmax decisions.

AIQ 定义来源：[RouterBench §3](https://arxiv.org/html/2403.12031v2#S3)。其余文献核查与执行计划见 EXECUTION_PLAN.md。
