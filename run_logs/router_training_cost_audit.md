# GraphRouter / RouterDC 训练成本与实名裁决准备

- API 调用：0
- GPU：NVIDIA GeForce RTX 4090

## GraphRouter

- 实现/依赖：True / torch-geometric 2.8.0
- demo 权重：224919 bytes，53828 parameters；demo 训练行：8
- 金融嵌入已就绪：True；需构建 400 条任务—模型边。
- 结论：Code and dependencies are ready. Demo weights are incompatible with the 100-task/4-model financial label space; a new leakage-safe graph dataset and training run are required.
- 成本：No API cost and the 100 Longformer embeddings can be reused. Expected compute is a small 30-epoch GNN run; measured wall time is deferred until leakage-safe graph edges are built.

## RouterDC

- 实现/配置/权重：False/True/False
- 结论：Blocked: no RouterDC implementation, config, weights, or cached DeBERTa checkpoint in this checkout.
- 成本：A defensible measured cost is impossible here. Importing and pinning RouterDC plus its encoder may require network access and substantially more GPU memory/time than KNN.

## 高分歧实名人工裁决

- 待裁决：425 条。
- 按模型：{'qwen-plus': 106, 'glm-5.2': 119, 'deepseek-chat': 93, 'qwen-turbo': 107}
- 工作表：`run_logs/judge_disagreement_named_review.csv`
- 必填：reviewer_identity、reviewed_at_utc、verdict、adjudicated_score、reviewer_notes。
- 当前 completed_rows=0；未经真实人员签名，不得标记为人工裁决完成。
