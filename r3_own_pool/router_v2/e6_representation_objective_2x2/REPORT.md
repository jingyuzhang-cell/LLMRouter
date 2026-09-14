# E6：Representation × Objective 2×2

只运行四组固定实验，使用原始提示GTE、400-query×4-model×5-repeat corrected labels和原有三个frozen outer folds。每折development168/168/167题，outer test不变。无新回答、编码、扩数据、MLP或超参数搜索。

| 模型表示 | 当前等权目标 | 稳定性加权目标 |
|---|---|---|
| 原始独立输出坐标 | A：QueryOnlyRidge | C：Stability |
| development区域能力画像 | B：Capability | D：Capability + Stability |

## Outer-test结果

BestSingle=72.40%；经验五重复均值Oracle=81.00%。

| 组 | EQ | Gap Recovery | 对A增益 pp [95% paired CI] | 达到冻结成功标准 |
|---|---:|---:|---|---|
| A_QueryOnly | 73.50% | 12.79% | +0.00 [0.00, 0.00] | 基线 |
| B_Capability | 72.35% | -0.58% | -1.15 [-2.25, -0.15] | 否 |
| C_Stability | 73.45% | 12.21% | -0.05 [-0.65, 0.55] | 否 |
| D_Capability_Stability | 72.40% | -0.00% | -1.10 [-2.15, -0.10] | 否 |

成功标准严格为EQ>A且配对query bootstrap CI95下界>0。使用10000次固定种子query重采样；GapRecovery的分子和分母同步重算。RESULTS.json另报三个与A比较的98.333% Bonferroni区间作为多重比较背景，不改变用户冻结判据。

## 2×2效应与交互

| 对比 | EQ变化 pp [95% CI] |
|---|---|
| B_minus_A | -1.15 [-2.25, -0.15] |
| C_minus_A | -0.05 [-0.65, 0.55] |
| D_minus_A | -1.10 [-2.15, -0.10] |
| D_minus_B | +0.05 [-0.65, 0.80] |
| D_minus_C | -1.05 [-1.95, -0.25] |
| interaction_D_minus_B_minus_C_plus_A | +0.10 [-0.85, 1.10] |
| representation_average_effect | -1.10 [-1.98, -0.32] |
| objective_average_effect | -0.00 [-0.48, 0.50] |

## 判定

B、C、D均未通过成功标准。本次行为画像和稳定性权重未证明能改善QueryOnly，不扩大这些方案。没有显著差异不等同于证明四组等价。

未启动扩大采集或任何后续实验。

## 冻结实现与隔离

1. 所有组预测ΔQ(q,m)=mean5(q,m)−mean5(q,R1)，R1分数为0。相同设计矩阵、alpha与截距下，等权Ridge的质量差预测等于直接对质量差做Ridge；A须精确复现历史400题QueryOnly选择。这样A/C和B/D的objective差异只有权重。
2. KMeans只拟合development GTE，固定K=8、random_state=42、n_init=10。c_m为8个region的平均质量，固定5个全局development均值伪样本作收缩。记录原始与收缩画像、区域大小及中心；outer特征不参与聚类，outer标签不参与画像。
3. B/D用d_m=c_m−c_R1，并将全部三个d_m共同缩放到平方范数和3，与A/C的单位模型核trace3一致。使用线性双线性交互e_q⊗d_m的Ridge，alpha=1。没有简单加法拼接或神经网络。模型特征满秩时只是不同的参数共享/正则化几何，不能声称增加了query信息或识别了旧learned-ID的因果缺陷。
4. S(q,m)=clip(1−2[Var5(m)+Var5(R1)],0,1)，方差ddof=0；raw w=0.05+0.95|ΔQ|S。按每个alternative在development内归一化到均值1，C和D共享完全相同的权重。所有tie保留且raw w=0.05。重复编号之间不假定模型配对。
5. 四组使用同一个凸线性求解器，截距在各自模型特征张成空间内不受惩罚。固定K/alpha/收缩/权重下限与随机种子，不用outer结果重试或选择参数。只报告outer质量作为效果证据；求解残差仅用于数值检查。

## 选择分布

| 组 | medium | large | coder | reasoning |
|---|---:|---:|---:|---:|
| A_QueryOnly | 1 | 53 | 0 | 346 |
| B_Capability | 0 | 20 | 3 | 377 |
| C_Stability | 0 | 39 | 0 | 361 |
| D_Capability_Stability | 1 | 8 | 4 | 387 |

## 结论边界

- 本实验是已使用、机会富集面板上的开发诊断。bootstrap条件于拟合后的模型与区域，不含完整重训不确定性。
- 五次重复构造的S是经验一致性指标，不是稳定偏好的真概率。旧E2不能识别精确的生成噪声占比，也不能预先保证加权有效。
- 以QueryOnly为A的2×2检验两项具体干预；不能单凭它确定旧非线性MA失败的唯一原因。
- 单次固定K和权重定义不成功，不等于排除所有行为表示、目标函数或编码器；不再在此面板盲搜配置。

文件：PROTOCOL.json保存冻结方案；PREDICTIONS.npz保存逐题预测；fold*/保存能力画像、权重、线性系数和来源；PER_FOLD.jsonl保存逐折outer指标。
