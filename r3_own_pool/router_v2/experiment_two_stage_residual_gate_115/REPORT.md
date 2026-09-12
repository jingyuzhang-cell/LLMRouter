# Two-stage Residual Gate（115题方法开发诊断）

Oracle=88.00%；R1=76.17%；Gap=11.83%。

| 方法 | Expected quality | Gap Recovery | 95%区间 | 选择分布 |
|---|---:|---:|---|---|
| DatasetBest | 76.17% | 0.00% | [0.0, 0.0] | {'medium': 0, 'large': 0, 'coder': 0, 'reasoning': 115} |
| TwoStageResidualGate | 76.87% | 5.88% | [0.0, 0.16176471167492165] | {'medium': 0, 'large': 3, 'coder': 0, 'reasoning': 112} |

阈值仅由每个外层折的内部验证集选择。该115题集合按先前单次分歧富集，只用于方法开发；需要新的冻结样本确认。
