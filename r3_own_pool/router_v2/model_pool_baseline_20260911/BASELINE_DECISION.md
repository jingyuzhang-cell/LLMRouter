# 同类模型池局限：baseline与单模型替换pilot

## 保留范围
原四模型池：Qwen2.5-7B-Instruct、Qwen2.5-14B-Instruct（历史GPTQ-Int8部署）、DeepSeek-R1-Distill-Qwen-14B、GLM-4-9B-chat-hf。原始及修正评分分析、120题冻结面板、GLM/Coder原文与评分均已复制归档；原文件未删除。

## 已完成的单模型替换
只以Qwen2.5-Coder-7B-Instruct替换GLM，其余三个模型沿用相同120题历史记录。知识40、数学40、代码40；单次生成，无repeat，无新增400题采集。

| 指标 | 原四模型（含GLM） | 替换为Coder的四模型 |
|---|---:|---:|
| Oracle | 89.17% | 89.17% |
| DatasetBest（折外） | 85.00% | 85.00% |
| Oracle−DatasetBest | 4.17 pp | 4.17 pp |
| Ridge（折外） | 83.33% | 83.33% |
| 新候选独有正确 | GLM 1/120 | Coder 1/120 |

Coder代码30/40；旧reasoning代码39/40。Coder独有正确是mmlupro_0576，不是代码题。未观察到预期的代码任务优势或8%–15%的Oracle Gap。

## 结论与边界
符合本轮情况B：Coder独有正确0.83%<5%，替换前后gap未增加。因此不启动400题repeat或MA。后续应先检查benchmark任务难度/覆盖和候选模型能力差异，而不是增加同类模型数量。

可作为“homogeneous model pool limitation”的探索性baseline，不作为论文主结果或对所有同类模型池的普遍证明。观察到的是这批题上正确集合高度重叠；未据此声称已计算统计相关系数。

“GLM提升单模型能力”不受现有数据支持。准确表述为：评分提取修复使GLM实测正确数43→53/120；这不是模型能力发生提升，且没有超过现有最强单模型。原始生成/部署异常尚未完全排除。

旧Qwen/R1评分与新模型修正提取存在协议差异；这是训练集开发pilot，没有独立确认性证据。所有winner计数区分并列正确与严格独有正确，详见WINNER_DISTRIBUTIONS.json。
