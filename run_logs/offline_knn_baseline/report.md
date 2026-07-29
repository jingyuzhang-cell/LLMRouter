# 严格离线 Longformer KNN 基线

- 划分：train/validation/test = 60/20/20
- API 调用：0
- 特征：本地 `allenai/longformer-base-4096`，768 维
- 标签：每题三次冻结回答的平均规范效用最优模型；测试标签不参与训练和调参
- 稀有标签：{'glm-5.2': 1}，仅保留在训练集，不复制样本
- 最优参数：k=3，weights=uniform，metric=cosine
- 测试准确率：55.00%
- 测试平衡准确率：36.11%
- 测试选择分布：{'deepseek-chat': 5, 'qwen-turbo': 15}
- KNN 测试效用：0.855314
- 固定 DeepSeek 测试效用：0.878040
- Oracle 上界效用：0.914395

该结果是独立补充基线，不回写或替换已冻结主实验。
