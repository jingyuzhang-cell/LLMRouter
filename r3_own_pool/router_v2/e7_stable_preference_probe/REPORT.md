# E7：稳定偏好表示探针（Representation Probe）

问题：题目表示里是否有足够信息判断“何时应离开 R1、切给谁”。两段式分解 ShouldSwitch→WhichAlternative，分解oracle=81.00%，与hindsight oracle相等，分解本身不损失上限。四种表示、dev-fold标准化+L2 logistic(C=1.0)、阈值0.5冻结、E6 frozen folds、零生成（仅本地Qwen2.5-7B forward）。

参照：BestSingle=72.40%；QueryOnly(A)=73.50%；分解oracle=81.00%。

| 表示 | Switch ROC-AUC | PR-AUC | Recall@0.5 | Stage2 Acc(未闸门) | Macro-F1 | EQ | vs A pp [95% CI] | 通过 |
|---|---:|---:|---:|---:|---:|---:|---|---|
| R0_gte | 0.602 | 0.273 | 0.117 | 0.338 | 0.259 | 72.25% | -1.25 [-2.35, -0.20] | 否 |
| R1_gte_struct | 0.602 | 0.274 | 0.130 | 0.325 | 0.252 | 72.05% | -1.45 [-2.65, -0.35] | 否 |
| R2_qwen | 0.500 | 0.225 | 0.117 | 0.403 | 0.363 | 71.50% | -2.00 [-3.45, -0.70] | 否 |
| R3_all | 0.581 | 0.263 | 0.091 | 0.364 | 0.286 | 72.05% | -1.45 [-2.65, -0.30] | 否 |

真实switch query：77/400；各表示预测switch数：R0_gte=28，R1_gte_struct=29，R2_qwen=33，R3_all=27。
成功判据唯一：EQ>73.50% 且相对A的配对bootstrap CI95下界>0。AUC/PR-AUC/F1只是诊断——switch AUC更高但EQ未超过QueryOnly不算Router改善。98.75% Bonferroni区间在RESULTS.json中作背景。

## 判定

没有任何表示通过 → 停止纯query-only静态Router；下一步转向 query→cheap model probe/partial response→routing（分支二，未启动）。

## 选择分布与switch行为

| 表示 | medium | large | coder | reasoning | 离开R1题数 | helped/harmed vs A |
|---|---:|---:|---:|---:|---:|---|
| R0_gte | 9 | 17 | 2 | 372 | 28 | 7/17 |
| R1_gte_struct | 9 | 17 | 3 | 371 | 29 | 7/18 |
| R2_qwen | 8 | 21 | 4 | 367 | 33 | 5/17 |
| R3_all | 8 | 17 | 2 | 373 | 27 | 5/14 |

## 敏感性（非判据）

阈值=dev内switch基础率的路由EQ（仅报告，不参与判定）：R0_gte=71.75%，R1_gte_struct=71.55%，R2_qwen=71.20%，R3_all=71.45%。

## 冻结口径

1. 标签：mean5(m)−mean5(R1)>0 且 ≥4/5 repeats ≥ R1 → stable advantage；WhichAlt取稳定者中mean5差最大。77/400 switch，medium 27/large 36/coder 14。
2. 表示：R0=E6冻结GTE；R1=R0+15个确定性结构特征+14 subject one-hot（control）；R2=Qwen2.5-7B-Instruct末层masked-mean hidden state（原文、无chat template、无生成）；R3=全拼接。
3. 分类器：StandardScaler(仅dev)+L2 logistic C=1.0，阈值0.5；无PCA/无MLP/无阈值搜索/无类权重。所有表示同一管线。
4. 折：E6三个frozen outer folds原样复用；A的选择取自E6 PREDICTIONS.npz。

## 结论边界

- 阈值0.5与19%正类率：stage1可能极端保守（几乎不switch），此时EQ≈BestSingle本身就是“可预测性不足”的诊断。
- 77个switch query的stage2只有约50个dev样本，macro-F1的CI很宽；F1不进入成功判据。
- 本实验不训练Router、不调权重、不扩K；R2只做forward提取，与API/生成无关。
- 未通过≠证明query-only永远不可行；按预注册分支转向行为信号路由。

文件：PROTOCOL.json / EMBEDDINGS_QWEN.npz / INPUTS.npz / PREDICTIONS.npz / FIT_AUDIT.json / RESULTS.json。
