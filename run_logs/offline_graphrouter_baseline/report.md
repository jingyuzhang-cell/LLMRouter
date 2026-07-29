# 严格离线金融 GraphRouter 基线

- 划分：{'train': 60, 'validation': 20, 'test': 20}（与 KNN 完全相同）
- 设备：cuda；调参耗时：6.115 秒
- 图边：train 240 / validation 80 / test 80
- 验证边和测试边在训练消息传递中均不可见
- 最优参数：hidden=32，lr=0.001，seed=17，epoch=25
- 测试准确率：50.00%
- 选择分布：{'deepseek-chat': 9, 'qwen-turbo': 9, 'qwen-plus': 1, 'glm-5.2': 1}
- GraphRouter 效用：0.885855
- KNN 效用：0.855314
- 固定 DeepSeek 效用：0.878041
- Oracle 上界：0.914395

本结果是独立补充实验，不覆盖冻结主实验。

## 配对显著性
- vs fixed_strong: Δ=0.007815, CI=[-0.029085, 0.051152], Holm t=0.712328, Holm W=0.666601, significant=False
- vs knn: Δ=0.030542, CI=[-0.016597, 0.089777], Holm t=0.568635, Holm W=0.927279, significant=False
