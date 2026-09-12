# MMLU-Pro 400题四模型MA

Oracle=84.75%；DatasetBest=76.00%；Gap=8.75%。

| 方法 | Accuracy | 相对DatasetBest | Gap Recovery | 95%区间 |
|---|---:|---:|---:|---|
| BestSingle | 76.00% | +0.00 pp | 0.00% | [0.0, 0.0] |
| DatasetBest | 76.00% | +0.00 pp | 0.00% | [0.0, 0.0] |
| QueryOnlyRidge | 75.00% | -1.00 pp | -11.43% | [-0.3142857196379682, 0.08571428717399132] |
| MA_seed42 | 76.00% | +0.00 pp | 0.00% | [0.0, 0.0] |
| MA_seed43 | 76.00% | +0.00 pp | 0.00% | [0.0, 0.0] |
| MA_seed44 | 76.00% | +0.00 pp | 0.00% | [0.0, 0.0] |
| MA_seed_mean | 76.00% | +0.00 pp | 0.00% | [0.0, 0.0] |

BestSingle与DatasetBest在单一MMLU-Pro数据集上定义相同，并均只用训练折选择。
20%-30% Gap Recovery是合理目标区间，不是预注册成功门槛。全部固定seed均报告，不选择最好seed。
这是原train开发实验；同一400题先触发门禁再评估MA，因此需要新的独立面板才能形成论文主结论。
