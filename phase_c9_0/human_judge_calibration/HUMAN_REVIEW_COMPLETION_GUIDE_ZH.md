# 人工评分填写说明

当前状态：PENDING_HUMAN_REVIEW。原始 A/B 模板保留不变。

每位 reviewer 独立完成自己的 30 组、123 个候选答案。分别另存为 C9_HUMAN_REVIEWER_A_SCORED.jsonl 和 C9_HUMAN_REVIEWER_B_SCORED.jsonl，放在本目录。

每个 candidates 项填写：
- score：0–4 整数。
- reason：非空、基于题目证据的评分理由。

每个 group 填写 reviewer_confidence：low、medium 或 high。reviewer_notes 可选。

评分标准：
- 4：完全正确，关键结论和推理有证据支持。
- 3：基本正确，仅有不影响主要结论的小遗漏。
- 2：部分正确，但有实质遗漏或局部错误。
- 1：少量内容正确，主要结论错误。
- 0：错误、无关、无证据支持或没有有效答案。

只依据模板中的 question、context、table、reference_answer 和候选 answer 独立打分；不要相对排名或推断模型身份。不要修改 group_id、label、候选答案及来源内容。A/B 在提交前不能互看分数、讨论个案或共享理由，不能用 LLM 代填。提交后才比较两份评分。

按冻结协议，分差大于 1 的答案交第三位 adjudicator 仲裁；其余取两分均值向下取整。自动验证和汇总不替代人工评分。两份文件完成并通过后续校准前，不冻结最终 scorer，不启动正式 E4 semantic scoring 或 RequestOnly/StateAware 训练。
