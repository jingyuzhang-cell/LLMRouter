# Residual gating：切换与后悔值

Switch定义为相对Ridge改变模型。准确率=获益切换/(获益+有害切换)，观测tie另报；同时保存包括tie的准确率。Regret=经验Oracle质量−实际路由质量。

| 方法/范围 | Gap Recovery mean±std | 平均切换 | 平均错误切换 | Switch Accuracy(排除tie) | Regret |
|---|---:|---:|---:|---:|---:|
| Residual/panel | 15.20% ± 1.68 pp | 21.33 | 5.67 | 61.27% | 0.077167 |
| Residual/historical_transfer | 6.86% ± 0.68 pp | 34.33 | 4.00 | 53.33% | 0.053221 |
| Gated/panel | 14.29% ± 0.00 pp | 0.00 | 0.00 | N/A（无切换） | 0.078000 |
| Gated/historical_transfer | 6.47% ± 0.00 pp | 0.00 | 0.00 | N/A（无切换） | 0.053445 |

固定100次训练group bootstrap，仅残差头重拟合，保持base Ridge、SVD和OOF标签固定；这衡量条件残差估计不确定性，不是完整或已校准的置信区间。未据结果调整门槛。

E2已经由上一轮Residual实现：目标是真实ΔQ减去内部3折Ridge OOF预测。此处没有把它重复算作新方法。

结果只说明当前特征、数据和估计器的经验收益，不是模型池compatibility上限。15%左右面板收益不能替换2975题历史迁移分母。

结论：固定门禁拒绝所有相对Ridge的切换，不能把错误切换为0解读为准确率100%。收益等于Ridge；不根据该结果继续放宽门槛选最优值。
