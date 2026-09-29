# 统一算法表（SA-PGFS vs 外部基线，冻结 cube 上零调用 reveal/replay）

协议：PROTOCOL_SAPGFS_FREEZE_v1 (frozen harness, 200 paired seeds)；同初始设计/同噪声抽样/预算 8；G_collab 15 配置。

冻结可复现性：PASS (rerun reproduces frozen SA-PGFS summaries bit-for-bit)。

| Method | 类型 | Final HV gap (mean/median) | AUC-HV | N95 达标 | Recall (dedup) |
|---|---|---|---|---|---|
| Random | 无模型 | +0.0852 / +0.0591 | 0.842 | 91/200 | 0.133 |
| Greedy-Q | 单目标贪心 | +0.0698 / +0.0382 | 0.840 | 107/200 | 0.233 |
| NSGA-II | MOEA | +0.0813 / +0.0407 | 0.828 | 109/200 | 0.158 |
| qNParEGO | MOBO | +0.0583 / +0.0319 | 0.857 | 117/200 | 0.217 |
| qNEHVI | noisy MOBO | -0.0062 / -0.0008 | 0.922 | 165/200 | 0.177 |
| AFlow-style MCTS | workflow search | +0.0143 / -0.0004 | 0.881 | 140/200 | 0.218 |
| SA-PGFS (EHVI) | state-cond. surrogate Pareto (SA-PGFS) | -0.0060 / -0.0008 | 0.922 | 160/200 | 0.173 |
| SA-PGFS (cost-aware EHVI) | state-cond. surrogate Pareto (SA-PGFS) | -0.0062 / -0.0008 | 0.922 | 162/200 | 0.158 |


## 配对置换检验（10,000 次符号置换，p 值）

- ehvi_vs_nsga2:regret: p = 0.0000
- ehvi_vs_nsga2:auc: p = 0.0000
- ehvi_vs_qnparego:regret: p = 0.0000
- ehvi_vs_qnparego:auc: p = 0.0000
- ehvi_vs_qnehvi:regret: p = 0.8851
- ehvi_vs_qnehvi:auc: p = 0.4568
- ehvi_vs_aflow_mcts:regret: p = 0.0000
- ehvi_vs_aflow_mcts:auc: p = 0.0000
- ehvi_vs_random:regret: p = 0.0000
- ehvi_vs_random:auc: p = 0.0000
- ehvi_vs_greedy_q:regret: p = 0.0000
- ehvi_vs_greedy_q:auc: p = 0.0000
- cost_aware_ehvi_vs_nsga2:regret: p = 0.0000
- cost_aware_ehvi_vs_nsga2:auc: p = 0.0000
- cost_aware_ehvi_vs_qnparego:regret: p = 0.0000
- cost_aware_ehvi_vs_qnparego:auc: p = 0.0000
- cost_aware_ehvi_vs_qnehvi:regret: p = 0.9794
- cost_aware_ehvi_vs_qnehvi:auc: p = 0.5808
- cost_aware_ehvi_vs_aflow_mcts:regret: p = 0.0000
- cost_aware_ehvi_vs_aflow_mcts:auc: p = 0.0000
- cost_aware_ehvi_vs_random:regret: p = 0.0000
- cost_aware_ehvi_vs_random:auc: p = 0.0000
- cost_aware_ehvi_vs_greedy_q:regret: p = 0.0000
- cost_aware_ehvi_vs_greedy_q:auc: p = 0.0000

注：nsga2/qnparego/qnehvi/aflow_mcts 为搜索机制的诚实适配（同一冻结空间、执行结果固定），非原系统完整复现；论文表述见 naming 字段。