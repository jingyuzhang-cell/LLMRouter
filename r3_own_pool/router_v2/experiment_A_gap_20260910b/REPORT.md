# 实验A：净Gap Recovery

固定MA实现；原训练集相似题分组OOF开发比较。三seed取平均，不挑最高seed。

Oracle=92.840%，DatasetBest=87.126%，Gap=5.714个百分点；严格机会题170道。

`Gap Recovery=(Q方法−QDatasetBest)/(QOracle−QDatasetBest)`，允许负值。

| 方法 | Quality | 净增益(pp) | Gap Recovery | Recovery 95%区间 |
|---|---:|---:|---:|---:|
| DatasetBest | 87.126% | +0.000 | 0.00% | [0.00%, 0.00%] |
| Ridge | 87.193% | +0.067 | 1.18% | [-7.52%, 9.30%] |
| MA(raw) | 87.317% | +0.190 | 3.33% | [-3.73%, 9.73%] |
| MA(original winner) | 83.574% | -3.552 | -62.16% | [-82.12%, -46.63%] |
| MA(stable) | 87.126% | +0.000 | 0.00% | [0.00%, 0.00%] |
| MA(raw matched stable queries) | 87.126% | +0.000 | 0.00% | [0.00%, 0.00%] |
| MA(repeat mean) | 87.115% | -0.011 | -0.20% | [-2.73%, 2.33%] |

当前MA(raw)为折内面板原pair监督；原winner另列。MA(stable)未运行时不得填0%冒充结果。
区间按相似题组配对重采样，同一重采样同时计算净增益和Oracle gap；仍是条件于既有OOF拟合的开发区间。
严格机会子集之外的误切换同样计入损失。该统计口径不会因只挑救回题而虚增恢复率。
