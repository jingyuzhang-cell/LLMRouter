# 离线补强有效性审计

- API 调用：0
- 数据源：`/root/autodl-tmp/LLMRouter-extracted/frozen-archives/finance-router-context-v2-1200-final-20260729T072524Z`
- 结果 SHA256：`e82409ecf3e7cf4ced0d2825aa45a6d8b2154b5a6e1f601e91975f38441ffcde`

## 基线有效性

- 五个策略均为 DeepSeek Chat 100/100。
- sampled_task_set 的 expected 首位：{'deepseek-chat': 100}。
- 根因：四个命名算法行使用兼容模拟而非训练权重；固定强模型显式固定为 DeepSeek。
- 冻结回答按逐题质量 oracle 的模型分布（仅诊断，不是可部署基线）：{'qwen-plus': 32, 'deepseek-chat': 33, 'glm-5.2': 22, 'qwen-turbo': 13}；并列任务 23。
- 结论：不能通过改阈值把原五行追认为独立基线；需另行训练并建立补充实验归档。

## Judge 离线重解析

- GLM 失败：598；保存完整原文：0；离线恢复：0。
- 现有归档只保留失败输出前 1000 字符，最终 JSON 已丢失；不调用 API 无法恢复 598 个分数。
- 已修复未来记录：解析失败时在本地原始日志保留完整 `raw_response`。

## 高方差复核

- 已生成 51 行完整复核包：`run_logs/high_variance_manual_review.csv`。
- 质量高方差：41；延迟高方差：10；同时命中：0。
- 按模型：{'glm-5.2': 18, 'qwen-plus': 10, 'qwen-turbo': 12, 'deepseek-chat': 11}。
- 按数据集：{'TAT-QA': 18, 'ObliQA': 13, 'FinQA': 17, 'FinReflectKG-EvalBench-derived': 3}。
- CSV 含三次质量、objective、Judge 分歧、延迟和回答节选；`manual_verdict` 与 `reviewer_notes` 留待实名人工裁决。
