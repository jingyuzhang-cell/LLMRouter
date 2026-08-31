# C8 路由专家评估

## 判断

建议的三层解耦架构可行，应保留为后续技术架构；但现有数据不支持把任何学习路由器部署为默认策略，也不支持现在接入 DAG 或级联。

## 公平比较结果

三种方法使用相同的 419 个开发任务、相同请求时输入、相同 TF-IDF 表示和相同分组 OOF 划分。未使用 v3、gold/evidence、回答文本或外部 API。

| 方法 | Quality 相对最佳单模型 | Utility 相对最佳单模型 | P(Utility gain > 0) | 结论 |
|---|---:|---:|---:|---|
| Hard 5-class | -0.004557 | +0.001846 | 0.6283 | 降低质量，收益不可靠 |
| Pairwise soft preference | 0 | -0.000241 | 0 | 几乎退化为 Qwen-plus |
| N-way performance prediction | +0.003250 | +0.000946 | 0.7417 | 方向最好，但不显著 |

Performance predictor 的质量 MAE 为 0.24199。Pairwise 在非平局模型对上的方向准确率为 75.30%，但这种局部准确率没有转化成任务级路由收益，说明大量可预测模型对并不是影响最终选择的关键边界。

## 执行决策

1. 保留 `Performance Learning → Decision Optimizer → Fallback Orchestrator` 的职责分离。
2. 后续优先使用连续 N-way performance target；硬分类只保留为基线，pairwise 只作为辅助损失或诊断，不能单独作为选择器。
3. 不在 C8 结果上继续调正则、阈值、权重或模型池，也不使用 v3 选参。
4. 暂不触发 DAG/级联。当前置信度还不能可靠识别“哪一个替代模型会带来净收益”。
5. 下一轮数据收集应主动增加 Qwen-plus 与 specialist 表现反转、且反转能由请求时特征识别的任务；新建开发集并预留未触碰的 v4 holdout。

因此，这份建议的架构判断成立，但一个月路线中的关键前置条件不是换更大的 Encoder，而是补充具有稳定、可观察能力差异的新数据。
