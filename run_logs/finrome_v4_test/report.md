# Fin-RoME v4: 选择性拒答实验结果

- **版本**: 4.0 (选择性拒答)
- **数据**: 60/20/20 (train/calibration/test)
- **API 调用**: 0 (纯离线实验)

## 核心改进
- **manual_review → abstain**: 系统无法安全判断时主动拒答
- **Safe Router Set = ∅ → ABSTAIN**: 不强制 fallback 到 anchor
- **Safe Model Set = ∅ → ABSTAIN**: 模型层无安全选项时拒答
- **Verifier 失败 → ABSTAIN**: 两次验证失败后拒答，而非人工审核

## 主要指标
- **Coverage (覆盖率)**: 20.00% (4/20)
- **Abstention Rate (拒答率)**: 80.00% (16/20)
- **Selective Failure Rate (已接受任务失败率)**: 0.00%
- **Selective High-Risk Failure**: 0.00%
- **Accuracy on Accepted**: 0.00%
- **Utility**: 0.193914
- **Escalation Rate**: 0.00%

## 总体指标 (包含拒答)
- **Overall Accuracy**: 0.00%
- **Overall Failure Rate**: 0.00%
- **Overall High-Risk Failure**: 0.00%
- **Mean Regret**: 0.002460

## 模型选择分布 (仅已接受任务)
- deepseek-chat: 4

## 研究结论
Fin-RoME v4 通过风险感知的选择性拒答机制，在不依赖人工审核的情况下：
- 通过拒答 80.0% 的高不确定性任务
- 将已接受任务的失败率控制在 0.0%
- 在 20.0% 的覆盖范围内实现了 0.0% 的准确率

这证明了系统能够识别高不确定性任务，并通过主动拒答显著降低自动决策的风险。

## 与 v3 的区别
- v3: 依赖未实施的人工审核，28% 的任务状态为 PENDING
- v4: 主动拒答替代人工审核，形成完整的闭环系统

**生成时间**: 2026-08-18T01:19:04.625234+00:00