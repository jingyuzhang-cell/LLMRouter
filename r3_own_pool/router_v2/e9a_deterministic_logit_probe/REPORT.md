# E9a：Deterministic Logit Probe（零生成）

本地Qwen2.5-7B-Instruct单次确定性forward：原文+冻结后缀`Answer:`，取该位置10个选项字母token的next-token softmax。无采样、无CoT、无ground truth。三臂冻结，E6折，mean5目标与评估（与73.50% anchor同尺度）；A在代码内断言逐题复现E6 QueryOnly。

参照：anchor=73.50%；BestSingle=72.40%；Oracle=81.00%（GAP 8.60pp）。probe top-1与medium多数采样选项一致率=0.229（多数存在比例=0.917）。

| 组 | EQ | Gap Recovery | vs anchor pp [95% CI] | 离开R1 | stable-switch P/R | helped/harmed | 通过 |
|---|---:|---:|---|---|---|---|---|
| A_query | 73.50% | 12.79% | +0.00 [0.00, 0.00] | 13.5% | 0.259/0.182 | 0/0 | 基线 |
| B_logit_stats | 72.55% | 1.74% | -0.95 [-2.25, 0.35] | 20.0% | 0.212/0.221 | 11/20 | 否 |
| C_prob_vector | 72.65% | 2.91% | -0.85 [-2.05, 0.30] | 17.2% | 0.275/0.247 | 5/12 | 否 |

## 判定

没有组通过 → deterministic logit信号无效。按预注册：只剩一次小规模E9b pilot（cheap partial response + verifier/confidence）；E9b再失败则停止信号搜索、重定论文定位。

## 选择分布

| 组 | medium | large | coder | reasoning |
|---|---:|---:|---:|---:|
| A_query | 1 | 53 | 0 | 346 |
| B_logit_stats | 6 | 68 | 6 | 320 |
| C_prob_vector | 3 | 65 | 1 | 331 |

## 冻结口径

1. probe分布：softmax仅归一在10个字母token上（截断式读出），非全词表归一；这是设计选择并已冻结。
2. B特征16维：top-1 one-hot(10)+top1概率+top2 margin+熵+方差+多数存在+与多数一致；C为完整10维概率向量。
3. 主判据唯一：EQ>73.50%且配对bootstrap CI95下界>0；97.5% Bonferroni区间在RESULTS.json作背景。
4. 一致性特征用medium历史5次采样的多数选项（无GT）；部署时对应一次新鲜采样。

## 结论边界

- 分布读自无CoT的原文prompt；CoT条件化的分布可能不同（E9b范畴）。
- probe是medium槽位模型；未测large/coder的logit profile。
- 400题面板已多次复用，非独立确认。

文件：PROTOCOL.json / LOGIT_PROBES.npz / PREDICTIONS.npz / RESULTS.json。
