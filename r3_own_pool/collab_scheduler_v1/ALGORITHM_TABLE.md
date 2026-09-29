# 统一算法表（SA-PGFS vs 外部基线，冻结 cube 上零调用 reveal/replay）

协议：PROTOCOL_SAPGFS_FREEZE_v1 (frozen harness, 200 paired seeds)；同初始设计/同噪声抽样/预算 8；G_collab 15 配置。

冻结可复现性：PASS (rerun reproduces frozen SA-PGFS summaries bit-for-bit)。

| Method | 类型 | Signed normalized HV gap (mean/median) | AUC-HV | N95 达标 | Recall (dedup) |
|---|---|---|---|---|---|
| Random | 无模型 | +0.0852 / +0.0591 | 0.842 | 91/200 | 0.133 |
| Greedy-Q | 单目标贪心 | +0.0698 / +0.0382 | 0.840 | 107/200 | 0.233 |
| NSGA-II | MOEA | +0.0813 / +0.0407 | 0.828 | 109/200 | 0.158 |
| qNParEGO | MOBO | +0.0583 / +0.0319 | 0.857 | 117/200 | 0.217 |
| qNEHVI | noisy MOBO | -0.0062 / -0.0008 | 0.922 | 165/200 | 0.177 |
| AFlow-style MCTS | workflow search | +0.0143 / -0.0004 | 0.881 | 140/200 | 0.218 |
| SA-PGFS (EHVI) | state-cond. surrogate Pareto (SA-PGFS) | -0.0060 / -0.0008 | 0.922 | 160/200 | 0.173 |
| SA-PGFS (cost-aware EHVI) | state-cond. surrogate Pareto (SA-PGFS) | -0.0062 / -0.0008 | 0.922 | 162/200 | 0.158 |


## 配对置换检验（10,000 次符号置换；解析下限 p = 1/10001，故报 p < 10⁻⁴）

- ehvi_vs_nsga2:regret: p < 1e-4
- ehvi_vs_nsga2:auc: p < 1e-4
- ehvi_vs_qnparego:regret: p < 1e-4
- ehvi_vs_qnparego:auc: p < 1e-4
- ehvi_vs_qnehvi:regret: p = 0.8851
- ehvi_vs_qnehvi:auc: p = 0.4568
- ehvi_vs_aflow_mcts:regret: p < 1e-4
- ehvi_vs_aflow_mcts:auc: p < 1e-4
- ehvi_vs_random:regret: p < 1e-4
- ehvi_vs_random:auc: p < 1e-4
- ehvi_vs_greedy_q:regret: p < 1e-4
- ehvi_vs_greedy_q:auc: p < 1e-4
- cost_aware_ehvi_vs_nsga2:regret: p < 1e-4
- cost_aware_ehvi_vs_nsga2:auc: p < 1e-4
- cost_aware_ehvi_vs_qnparego:regret: p < 1e-4
- cost_aware_ehvi_vs_qnparego:auc: p < 1e-4
- cost_aware_ehvi_vs_qnehvi:regret: p = 0.9794
- cost_aware_ehvi_vs_qnehvi:auc: p = 0.5808
- cost_aware_ehvi_vs_aflow_mcts:regret: p < 1e-4
- cost_aware_ehvi_vs_aflow_mcts:auc: p < 1e-4
- cost_aware_ehvi_vs_random:regret: p < 1e-4
- cost_aware_ehvi_vs_random:auc: p < 1e-4
- cost_aware_ehvi_vs_greedy_q:regret: p < 1e-4
- cost_aware_ehvi_vs_greedy_q:auc: p < 1e-4

注：nsga2/qnparego/qnehvi/aflow_mcts 为搜索机制的诚实适配（同一冻结空间、执行结果固定），非原系统完整复现；论文表述见 naming 字段。

## 锁定的主张层级（论文表述基准）

**qNEHVI ≈ SA-PGFS > {qNParEGO, AFlow-style MCTS, NSGA-II, Greedy, Random}**
（≈ = 配对置换检验不显著；> = p < 10⁻⁴；写"达到最强 noisy-MOBO 基线同等水平"，
不写"超过 qNEHVI"）。

qNEHVI 的区分措辞（防审稿反驳）：qNEHVI 作为通用 noisy 多目标采集基线使用；
SA-PGFS 的差异在于把 Pareto 搜索嵌入状态条件协同调度框架——可行图集 G(s)、
恢复动作与 Pareto 档案均相对运行状态定义。**不声称**跨状态迁移或
state-aware surrogate 优于 qNEHVI（当前 replay 为逐状态独立运行，无此实验支持）。

术语：本表"Signed normalized HV gap"可为负（噪声采样下发现前沿可略超实测前沿），
不使用"regret"（默认非负，易误读）。

外部方法措辞（正文原句）：We adapt the search mechanism of representative
external methods to the same frozen configuration space and lookup evaluator;
these comparisons evaluate search behavior rather than reproducing the original
end-to-end systems. NSGA-II 在 budget=8 下的结果不泛化为"NSGA-II 本身弱"
（evolutionary methods typically require larger evaluation populations；讨论部分说明）。

## 三句主结论（锁定）

1. 协同并非天然优越：全局前沿在 clean 与 fault 两状态下均由 Single 占据。
2. 一旦进入协同模式，运行状态显著改变拓扑 Y 与恢复策略 Z 的 Pareto 价值
   （DAG 子空间 front 2→3、HV 翻倍、Δ_Z 三族为正；X 排序稳定）。
3. SA-PGFS 达到最强 noisy-MOBO 基线 qNEHVI 的同等水平，并显著优于
   随机、贪心、进化、标量化 MOBO 与 workflow-search 基线。
