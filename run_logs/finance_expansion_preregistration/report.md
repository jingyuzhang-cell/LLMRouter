# 金融任务扩展离线预注册

- 状态：preregistered_no_api_calls
- 原任务/新增/合计：100/40/140
- 新增分布：{'FinQA': 10, 'TAT-QA': 10, 'ObliQA': 10, 'FinReflectKG-EvalBench-derived': 10}
- 固定划分：{'train': 84, 'validation': 28, 'test': 28}
- 新任务已有四模型回答：0/40
- 若执行需新增回答调用：480；最低双 Judge 尝试：960
- 当前不允许 API 执行；不能仅凭任务文本声称 GLM 最优标签增加。
- 40 个任务在答案生成前已锁定；后续不得根据结果换题或换划分。
- 完整候选内容保存在 local JSONL，不进入 Git。
