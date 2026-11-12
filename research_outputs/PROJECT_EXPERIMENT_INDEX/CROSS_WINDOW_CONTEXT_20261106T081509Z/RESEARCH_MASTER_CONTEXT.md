# 研究主线上下文（跨窗口统一入口 v1）
> 生成：2026-11-06（本会话）。权威来源：q_foundation/QF_GOVERNANCE_PLAN.md（296KB 多窗口日志）、MAINLINE_DYNAMIC_JOINT_RULING_20261106.md、SNAPSHOT_20261106T073050Z/SCIENTIFIC_SUMMARY.md。本文件是导航层，冲突时以上述原始文件为准。

## 研究目标（操作者 2026-11-06 固定表述）
面向复杂任务的异构大模型协同调度与 Q/C/L 联合优化：模型能力画像 → DAG 自动生成与结构优化 → 静态异构分配 → 执行反馈驱动的动态联合决策（Z 结构修复 / R 节点恢复 / π 模型重分配）→ 动态 DAG 图森林搜索 + 反馈学习 + 约束式多目标优化，在保证终端质量与可靠性前提下降本降时延。

## 核心假设 H（正式固定）
在具有可利用结构修复空间、执行异常和模型能力互补性的复杂 DAG 任务中，反馈驱动的动态联合调度优于静态调度和最强固定恢复策略，并在预算/截止约束下改善终端质量或资源效率（质量收益或效率收益二选一成立 + 安全指标不恶化）。
对照最低要求：Static / Z-only / R-only / π-only / 最优固定组合 / Dynamic Joint——**Joint 必须对最强固定组合比较**。

## 当前位置（2026-11-06，诚实版）
- 已有正向机制证据：Z 结构修复（R6 3/4 vs 0/4；M6: Z 使 R-only INCOMPLETE→COMPLETE −12.3% tok）；M8-4 三档截止 E[TP] 均 Proposed>Static（翻转假设否定）；静态节点路由 +0.069[0.034,0.105]；信息架构修复 +400%；森林复用调用−50%。
- 核心增量未坐实：全项目无 Joint vs 最强固定组合的配对比较；M6-4"Joint 正向完全来自 Z"；DD_V51 π-only(0.1458)>Joint(0.0903)；H1V7 门控正但 H1V8 独立任务未复现；PHASE_PI_V2 Q_final 36/36=None。
- 关键耦合：正式 Q 依赖 QF 人工 Gold（P1 双人评审 BLOCKED）——人工评审在主线假设检验关键路径上。
- Stage D V1.3（192 执行六臂、精确置换、功效 0.736）已设计待操作者终审授权；确认性需 ≥7 独立任务（independent_case_search 正在跑）。

## 四优先级（操作者 2026-11-06 裁定，顺序固定）
P1 做实正向收益（口径核验+证据复用）→ P2 联合增量（Joint vs 最强固定）→ P3 条件化收益 → P4 反馈学习与 Pareto。
纪律：先历史后前瞻、最小必要、无授权不付费调用、负结果如实呈现。

## 主要目录导航
- 治理/决策：/root/q_foundation/（QF_GOVERNANCE_PLAN.md, MAINLINE_DYNAMIC_JOINT_RULING_20261106.md）
- 资源索引：/root/research_outputs/PROJECT_EXPERIMENT_INDEX/（本目录；资源盘点见 RESOURCE_SYNC_20261106T080009Z/）
- 动态调度主线（近两周）：/root/research_outputs/static_pi/stage_d/；/root/r3_own_pool/deadline_reward_v1/
- 能力画像/早期线：/root/r3_own_pool/（data/frozen/full_v2 两万格）、/root/phase_c*/、/root/e2_*/phase_e*/
- 评分器：/root/r3_own_pool/deadline_reward_v1/quality_v4/（v1.2.3 已入 main，PR#5）
- 人工 Gold 材料：/root/phase_c9_0/human_judge_calibration/（C9 123 候选）、/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/（E08）
- GitHub：jingyuzhang-cell/LLMRouter（main=c91afd43；归档分支工作流 research-archive-YYYYMMDD-live*，PR#7-#11 惯例）
