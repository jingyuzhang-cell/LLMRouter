# 证据三分类（2026-09-27 治理通过后锁定）

机器可读版：`EVIDENCE_CLASSIFICATION.json`。引用规则：论文主结果只允许 TIER-1；
TIER-2 在重算完成前禁止引用；TIER-3 永久退出。

## TIER-1 可保留，进入论文主结果

不依赖多点 HV 计算（clean 前沿为单点）：

- P\*_clean = {SINGLE}（15 配置 + SINGLE 锚，统一 (Q,C,L)）
- 15/15 clean config 的 Q/C/L（runner 与独立 analyzer 15/15 一致）
- SER__HETEROGENEOUS 的 clean 子前沿位置（DAG 侧最优：Q 0.370 @ C 963.5）
- Y/X 排序（Y: SER≈SERV > PARALLELER≈DYNAMICDAG；X: HET > QUALITY > BALANCED）
- clean 锚点一致性（DYN__HET vs frozen200 clean_static：Q 0.330/0.335, C 1484/1485.7）
- 双会话敏感性零散度（SESSION_SENSITIVITY_AUDIT.json，降级为 reproducibility note）
- 台账完整性取证本身（FROZEN200_FAULT_PROVENANCE.json / CACHE_AUDIT.json）

## TIER-2 必须重算（零新调用），完成前禁止引用

依赖多点 HV / 坏 ehvi 的一切 simulation/replay/策略效率曲线：

- `sa_pgfs_v1/results_sim_v1/`（整体）——**INVALIDATED BY HV IMPLEMENTATION BUG**
  （标记文件已放入该目录）。替代品：`results_sim_v1_regenerated/`（后台重生中）。
  即使重算数字与旧值接近，也只引用新版本。
- 旧 REPLAY_CLEAN 的策略比值在本轮已用修复后实现重出（数字不变），
  但按 2026-09-27 治理判定降级为 smoke test（clean 前沿单点，区分度弱是构造性的）。

## TIER-3 永久 retired

- f30_static = 0.2933 及全部派生 static-fault budget/HV/Pareto 结论。
- **f30_dynamic = 0.4033 及"fault 使 Dynamic 进入全局前沿"主张（2026-09-28 撤回）**：
  修正协议下重测 DYN__HET__LOCAL_REROUTE = 0.3433±0.0047（差 0.060 >> 容差 0.02）；
  修正后全局前沿 P*_clean = P*_fault = {Single}。
  两者均见 fault30_prep/RETIRED_EVIDENCE.json，由 fault30 cube 完全替代。

## 表述规则（2026-09-28 冻结）

- **全局与协同结果永远分表**：Single 是外部 global baseline，不是搜索候选；
  SA-PGFS 的搜索问题显式限定为 G_collab（15 协同配置）。
- 全局结论：两种状态下 Single 均支配（front 不扩张）。
- 协同子空间结论：front 2→3 点（HV 翻倍）、Δ_Z 三族正、Y 翻转 SERV↔DYN、X 稳定。

## 统计口径（即刻锁死）

- fault30 主前沿用 (Q̄, C̄, L̄)（3 种子均值），每个 ND 点必须附
  **front membership frequency**: freq(G) = (1/S)·Σ_s 1[G ∈ P_s]（逐种子前沿），
  区分"三种子恒在前沿 / 仅均值后进前沿 / 单种子推入"。
- SA-PGFS replay 报告四指标：Normalized HV Regret(t)、Pareto Recall(t)、
  N_95%HV、AUC-HV（reveal 预算全程 HV 曲线下面积，体现"早找到"）。

## 措辞红线

fault30 = 冻结故障模型下的**状态干预**；结论限定为"该干预下恢复策略的价值"，
不泛化为模型能力变化或任意现实故障。
