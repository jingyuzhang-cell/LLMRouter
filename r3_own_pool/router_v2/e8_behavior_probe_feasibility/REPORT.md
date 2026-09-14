# E8：Behavior-Probe Feasibility（零新增生成）

问题：Router 看到一个便宜模型的实际行为（probe），能否比只看 query 更准地路由。20个(p,r) rotation：probe特征只取第p次，目标用其余3次定义，只在第r次评估，p≠r。bootstrap单位= query。repeat身份=原始文件行序（已验证精确重现E6 repeat矩阵）。

参照：冻结QueryOnly anchor=73.50%（rotation均值=mean5 EQ）；in-protocol A=73.22%（mean3目标重训）；BestSingle=72.40%。

| 组 | EQ | vs A pp [95% CI] | vs anchor pp [95% CI] | switch精度/召回 | helped/harmed(vs A) | 通过 |
|---|---:|---|---|---|---|---|
| A_query | 73.22% | +0.00 [0.00, 0.00] | -0.28 [-0.83, 0.30] | 0.133/0.168 | 0/0 | 基线 |
| B_medium_probe | 70.80% | -2.43 [-3.38, -1.54] | -2.70 [-3.79, -1.68] | 0.092/0.183 | 24/98 | 否 |
| C_large_probe | 71.29% | -1.94 [-2.95, -1.04] | -2.21 [-3.35, -1.19] | 0.094/0.190 | 20/71 | 否 |
| D_joint_probe | 69.89% | -3.34 [-4.40, -2.26] | -3.61 [-4.83, -2.41] | 0.081/0.224 | 36/128 | 否 |

## 判定

没有组通过 → 最简行为信号无效；按预注册，考虑更强 probe（partial response/self-confidence/verifier）或停线。

## 选择分布（20 rotation合并）

| 组 | medium | large | coder | reasoning | 离开R1的rotation数 |
|---|---:|---:|---:|---:|---:|
| A_query | 20 | 1200 | 0 | 6780 | 1220 |
| B_medium_probe | 207 | 1644 | 66 | 6083 | 1917 |
| C_large_probe | 150 | 1769 | 36 | 6045 | 1955 |
| D_joint_probe | 514 | 1961 | 182 | 5343 | 2657 |

## Probe 成本（原始运行统计，中位数）

| slot | 模型 | tokens_out | latency ms |
|---|---|---:|---:|
| medium | Qwen/Qwen2.5-7B-Instruct | 396 | 6855 |
| large | Qwen/Qwen2.5-14B-Instruct | 406 | 8060 |
| coder | Qwen/Qwen2.5-Coder-7B-Instruct | 441 | 7603 |
| reasoning | deepseek-ai/DeepSeek-R1-Distill-Qwen-14B | 2071 | 65329 |

B/C/D 的 probe 成本 = 每题必付一次 medium（或 large，或两者）的推理；D 为两者之和。路由后的模型成本由选择分布给出。

## 对比

| 对比 | EQ变化 pp [95% CI] |
|---|---|
| D_minus_B | -0.91 [-1.61, -0.20] |
| D_minus_C | -1.40 [-2.18, -0.60] |

## 冻结口径

1. 目标：3个target repeats的 V(q,m)−V(q,R1) 均值；Ridge alpha=1 三个delta头，R1分数恒0，first-max tie order。
2. probe特征18维/模型：parse(2)+选项one-hot(10)+log长度/tokens/latency/tps+finish+status；joint 4维：一致/不一致/有未解析 + token差。全部只用第p次原始输出，无ground truth。
3. anchor= E6 冻结 QueryOnly 选择，同 rotation 评估；其 rotation 均值按构造等于 mean5 EQ（代码内断言验证）。
4. AUC 类指标不进入判据。98.33% Bonferroni 区间在 RESULTS.json 作背景。

## 结论边界

- latency/tokens 来自历史运行，是 probe 成本的代理，非重新测量；部署 probe 看到的是一次 temperature 0.7 的新采样。
- bootstrap 条件于已拟合模型；不含重训不确定性。
- 本版只有最简行为信号；无效不排除更强 probe 形式。

文件：PROTOCOL.json / INPUTS.npz / PREDICTIONS.npz / RESULTS.json。
