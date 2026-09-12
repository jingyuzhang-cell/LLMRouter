# 400题五次重复标签：四模型兼容性路由

Oracle=81.00%；DatasetBest=72.40%；Gap=8.60%。

| 方法 | Expected quality | Gap Recovery | 95%区间 | Rescued/Harmed | 选择分布 |
|---|---:|---:|---|---:|---|
| BestSingle | 72.40% | 0.00% | [0.0, 0.0] | 0/0 | {'medium': 0, 'large': 0, 'coder': 0, 'reasoning': 400} |
| DatasetBest | 72.40% | 0.00% | [0.0, 0.0] | 0/0 | {'medium': 0, 'large': 0, 'coder': 0, 'reasoning': 400} |
| QueryOnlyRidge | 73.50% | 12.79% | [0.005813953377560325, 0.2616279028565612] | 14/7 | {'medium': 1, 'large': 53, 'coder': 0, 'reasoning': 346} |
| PairwiseRidge | 73.50% | 12.79% | [0.005813953377560325, 0.2616279028565612] | 14/7 | {'medium': 1, 'large': 53, 'coder': 0, 'reasoning': 346} |
| TwoStageResidualGate | 71.90% | -5.81% | [-0.21511627108200185, 0.08139535118440404] | 8/13 | {'medium': 0, 'large': 56, 'coder': 0, 'reasoning': 344} |
| RepeatPairwiseMA_seed42 | 72.50% | 1.16% | [-0.0930232523082721, 0.10479651516431265] | 7/6 | {'medium': 0, 'large': 29, 'coder': 0, 'reasoning': 371} |
| RepeatPairwiseMA_seed43 | 72.40% | 0.00% | [-0.1162790675512065, 0.11627906668485995] | 6/7 | {'medium': 1, 'large': 34, 'coder': 0, 'reasoning': 365} |
| RepeatPairwiseMA_seed44 | 72.40% | 0.00% | [-0.09883721089474107, 0.09898255745501956] | 5/6 | {'medium': 1, 'large': 25, 'coder': 0, 'reasoning': 374} |
| RepeatPairwiseMA_seed_mean | 72.43% | 0.39% | [-0.08144380281735898, 0.08725774845194674] | -/- | - |

该面板按训练折机会富集，只用于方法开发。外层训练使用冻结 allowlist，内部验证选择 epoch/门限；需要新的代表性冻结 panel 做确认。
