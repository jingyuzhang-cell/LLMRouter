# Experiment D：拟合诊断与Pairwise对照

R²为三折×三seed的均值，val是开发训练分区内部的折外评估，不是原validation/test。

| 方法 | train ΔQ R² | val ΔQ R² |
|---|---:|---:|
| experiment_B_simple_quality_ma | 0.0088 | -0.0098 |
| experiment_C_quality_plus_delta_ma | 0.7433 | -0.0668 |
| experiment_D_pairwise_regression | 0.9926 | -0.2329 |
| experiment_D_pairwise_ranking | 0.9910 | -0.2417 |

| 方法 | 400题Gap Recovery | 历史2975题迁移 |
|---|---:|---:|
| Ridge ΔQ | 14.29% | 6.47% |
| C：质量+ΔQ | 8.97% | 1.57% |
| experiment_D_pairwise_regression | -0.92% | 1.96% |
| experiment_D_pairwise_ranking | -0.73% | 1.76% |

Pairwise模型直接学习反对称差值。固定ranking权重0/0.1，margin加权softplus温度0.2；tie保留回归、ranking权重为零。全部固定50epochs、3seeds、相同折名单，未按最佳seed选结果。

B训练ΔQ也拟合很弱；C及pairwise训练拟合强而折外R²为负，主要证据指向泛化/过拟合瓶颈，不支持继续简单扩大容量。当前对照未超过Ridge，区间覆盖0。

下一步应在训练折内部比较收缩/低维线性模型或早停；不能在同一外折上反复试验后声称独立确认。所有结果仍是富集面板开发诊断；未获20–30%净Gap Recovery证据。
