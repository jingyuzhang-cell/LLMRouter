# 实验审计阶段 A–F 输出

> 2026-09-27 | 基于全部冻结实验文件与 3 次数据修正后的最终结果

---

## A. 最终实验结果总账

| # | 实验 | 类型 | 面板 | N | Seeds | 方法 | 最终数字 | 统计 | 支持 | 不支持 | §4 | 来源 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 主故障鲁棒性 | 主实验 | 120题 TAT-QA | 120 | 3 | Single/Static/Dynamic × f10/20/30% | f30: Single=0.3639±0.026, Static=0.2861±0.014, Dyn=0.4056±0.010 | dQ(D−S)=+8.1/+10.6/+11.9pp, 每seed正 | Dyn保持质量(退化<3%) | Dyn显著反超Single(frozen未确认) | 4.3.1 | MULTI_SEED_REPORT |
| 2 | 零伤害配对 | 主实验子项 | 同上 | 120 | 1(20260923) | Dyn vs Static Help/Harm | 11/0, 14/0, 17/0 | McNemar p≤0.001 | 主面板完全零伤害 | Frozen面板(18/1,23/1,28/1)有极低harm | 4.3.1 | STAT_CHECK |
| 3 | 恢复归因消融 | 消融 | 120题(修正后) | 120 | — | Static-fb/SM/Ideal/RD/FR | 39.17/41.67/42.50/40.00/37.50% | SM vs Static: +2.5pp p=0.453 | 归因不构成逐组件递增链 | 升级目标或策略的独立显著贡献 | 4.3.2 | CORRECTED_ARMS |
| 4 | 局部恢复 vs 整图重执行 | 消融 | 120题(修正后) | 120 | — | RD vs FR | RD: 40.00%, 2324tok, 309calls / FR: 37.50%, 3347tok, 592calls | dQ=−2.5pp, CI[−5.8,0], p=0.25 | 局部恢复省31%tok/48%call/35%lat | 质量等价/非劣(未达显著) | 4.3.2 | CORRECTED_REPORT |
| 5 | 检测评估F1 | 诊断 | 120题初始输出 | 120 | — | 部署信号 | Evidence P=1.0 R=0.87 F1=0.93 / Exec P=1.0 R=1.0 F1=1.0 / Verify P=0.83 R=0.73 F1=0.78 / Reasoning R=0.0 | — | 执行级失败可靠检测 | 语义/推理级错误检测(召回0) | 4.3.3 | corrected_replay |
| 6 | Verifier消融 | 诊断 | 120题 | 120 | — | Dyn vs Dyn+Verifier | 均为40.00%, H/H=1/1, p=1.0 | — | 额外检测信号不必然带来净收益 | Verifier无用(不这么写) | 4.3.3 | SUBSET_REPORT |
| 7 | 恢复归因(78题) | 诊断 | 120题 | 78 | — | 按首要失败类型 | 证据解析44→恢复16% / 证据值错8→12% / 执行4→0% / 推理20→0% / 验证2→0% | — | clean失败多为任务固有 | 全部类型可恢复 | 4.3.3 | RECOVERY_ATTRIBUTION |
| 8 | **Frozen 200 独立评估** | **独立确认** | **200题(零重叠)** | 200 | 3 | Single/Static/Dynamic × clean+f30% | clean: 0.5500/0.3350/0.4150 / f30: 0.3967±0.018/0.2933±0.028/0.4033±0.003 | Dyn vs Single +0.7pp, p=0.58-0.88(ns) | Dyn质量稳定(退化2.8%); Pareto结构保持 | Dyn显著反超Single | 4.3.3 | FROZEN200_CORRECTED |
| 9 | Frozen 200 分层诊断 | 诊断 | 200题 | 200 | 1(20260923) | 按Single fault存活/受损 | 存活79题: Dyn Q=0.747 / 受损31题: Dyn Q=0.484 / clean错90题: Dyn Q=0.078 | — | 恢复率48.4%; 干预损害25.3% | — | 4.3.3 | FROZEN200_DIAGNOSTIC |
| 10 | Selective Oracle | 事后上界 | 200题 | 200 | 1 | 事后路由 | 101/200=50.5% | +10.8pp vs Single, +10.2pp vs Dyn | 存在显著选择空间(post-hoc上界) | 可部署/已实现 | 4.3.3 | FROZEN200_DIAGNOSTIC |
| 11 | 故障节点类型 | 诊断 | 200题 | 60 | 1 | 按注入节点 | evidence(32): Dyn 31.3% / reasoning(15): 33.3% / verification(13): 15.4% | — | 不同节点可修复性不同 | 泛化(小子集) | 4.3.3 | FROZEN200_DIAGNOSTIC |
| 12 | Selective-DAG OOF | 入口门控 | TAT-QA-200+MH-100 | 300 | 5-fold | Mono vs DAG vs 门控 | Mono=38.67%, DAG=31.67%, Selective=42.0% | +3.3pp, H/H=20/10, p=0.20(ns) | 方向性正向证据 | 显著确认 | 4.2.2 | selective_dag_oof |
| 13 | 条件节点质量 | 基础 | 100题493节点 | 493 | — | 三模型各阶段 | 抽取: large 0.596 / 推理: med/coder 0.310 / 验证: coder 0.590 | Oracle gap 3.0-10.0pp | 池内无全能模型 | 部署特征可预测逐节点最优 | 4.2.1 | EXPERIMENTS_V8表4-1 |
| 14 | 严格配对分解 | 基础 | MH100+TAT200 | 300 | — | Mono-L/DAG-LL/DAG-LM | TAT: −21.0pp拆分/+8.5pp异构 / 总体: −12.0/+5.0pp | p<0.001(拆分); p=0.014(异构) | 分解引入接口损耗;异构缓解但未完全抵消 | 分解普遍提升质量 | 4.2.1 | EXPERIMENTS_V8表4-2 |
| 15 | 查询/节点路由 | 基础 | 100题493节点 | 493 | — | Query vs Node routing | Query 0.4665, Node 0.5355, TypePrior 0.5355 | — | 收益来自阶段粒度 | 实例级学习优势 | 4.2.2 | EXPERIMENTS_V8 |
| 16 | Pareto前沿+HV | 多目标 | 120题×4场景 | 120 | 3 | (Q,C,L) Pareto | clean: Single支配 / f30: {Single,Dyn}双前沿 | — | 无固定策略全状态最优 | Dynamic拥有最高HV | 4.4.1 | MULTIOBJECTIVE_TRADEOFF |
| 17 | 预算完成率Q(B) | 多目标 | 120题 | 120 | 3 | 8预算档 | f30: Single全档领先(主面板);B≥2800 Dyn接近 | — | 预算约束改变策略选择 | — | 4.4.1 | MULTIOBJECTIVE_TRADEOFF |
| 18 | Pareto Scheduler | 方法 | 120题×32状态 | 120 | 3-fold | Pareto-selector vs 固定 | grid avg=0.4234(=cost-only); B3000=0.4625 | — | 逐状态不劣于任何固定策略 | 正的平均质量增益 | 4.4.2 | SCHEDULER_EXPERIMENTS |
| 19 | 状态消融 | 消融 | 120题×32状态 | 120 | 3-fold | full/no-fail/no-budget | full=0.4234 / no-fail=0.4234 / no-budget=0.3718 | — | 预算信息是硬需求 | — | 4.4.2 | SCHEDULER_EXPERIMENTS |
| 20 | DV/FR池扩展 | 消融 | 120题×3seeds | 120 | 3 | +DV/+FR进故障 | DV=0.3917, FR=0.3833, Dyn=0.4056(f30) | — | 均被Dyn支配;前沿保持紧凑 | 候选增多带来平均收益 | 4.4.3 | POOL_ANALYSIS |
| 21 | Exact Pareto 18配置 | 空间分析 | 120题×3seeds | 120 | 3 | 9X×2Z穷举 | 9none全0.3500, 8/9switch全0.3917, ε≥0.1%坍缩为2 | — | 名义大空间≠有效大空间 | — | 4.4.3 | exact_pareto |
| 22 | 跨域(Math/MBPP) | 边界 | Math100+MBPP100 | 200 | — | 6臂 | Math: Single 54%, DAG 13-16% / MBPP: Single 76%, Dyn 80% | MBPP Dyn vs Static +6.0pp p=0.07(支持性) | 可诊断反馈是关键条件 | 广泛跨域泛化 | 4.5 | EXPERIMENTS_V8 4.5 |
| 23 | 外部方法 | 基线 | TAT200+MBPP100 | 300 | — | RouteLLM/Frugal/Self-Refine | Finance: RouteLLM=52.5%, Frugal=32.5%, SF=8.0% / Code: SF=85.0% | SF vs Dyn p=0.267(ns) | 核心贡献不是全域最高准确率 | — | 4.5 | EXPERIMENTS_V8表4-9 |

---

## B. 研究问题—实验—结论映射表

| RQ | 实验 | 结论 |
|---|---|---|
| **RQ1** 为什么需要不同执行策略与workflow-level decision? | #13(能力异质) #14(分解基准) #15(路由粒度) #12(Selective-DAG OOF) | 阶段能力异质存在但分解引入损耗;查询/节点路由收益来自阶段粒度;入口门控方向性正向(+3.3pp ns);因此需在workflow层面做策略选择 |
| **RQ2** feedback-aware Dynamic为什么有价值? | #1(鲁棒性) #2(零伤害) #4(局部vs整图) #7(恢复归因) #8-11(Frozen 200) | Dyn在故障下保持质量(退化<3%),相对Static有强烈Help/Harm不对称(18/1~28/1);局部恢复省31-48%计算;Frozen 200确认质量稳定但vs Single仅+0.7pp(ns);恢复率48.4%被干预损害25.3%部分抵消→需要选择性调度 |
| **RQ3** 为什么需要Pareto-aware scheduling? | #16(Pareto) #17(Q(B)) #18(scheduler) #19(状态消融) | 无固定策略全状态最优;预算约束改变最优选择;Pareto-aware selector逐状态不劣于固定;预算信息是硬需求(no-budget崩溃) |
| **RQ4** 为什么不继续做复杂Search? | #20(DV/FR) #21(Exact Pareto) | 候选增多(DV/FR)不产生新Pareto点;18配置空间坍缩为二元(ε≥0.1%时2点);名义大空间≠有效大空间;Selection已覆盖有效模式 |
| **RQ5** 方法在哪些条件下有效? | #8-11(Frozen诊断) #22(跨域) #5(检测F1) | 5条件:故障风险非平凡/反馈可诊断/故障可修复/候选互补/干预收益>成本(第5条来自Frozen 200) |

---

## C. 第四章最终目录

```
4.1 实验设置
4.2 执行策略空间与决策粒度分析
    4.2.1 单模型与静态DAG执行特征
    4.2.2 不同决策粒度下的执行策略比较
4.3 反馈感知的动态执行与故障恢复
    4.3.1 不同执行策略的故障鲁棒性
    4.3.2 反馈驱动的局部恢复机制
    4.3.3 故障归因与独立冻结验证
4.4 Pareto感知的多目标协同调度
    4.4.1 多目标权衡与Pareto前沿分析
    4.4.2 多目标策略选择方法比较
    4.4.3 候选策略扩展与有效优化空间分析
4.5 跨任务适用边界分析
4.6 本章小结
```

---

## D. 旧结论修订清单

| # | 旧结论/表述 | 状态 | 修改说明 |
|---|---|---|---|
| 1 | "Dynamic提升约20pp" | **删除** | 解析缺陷伪影 |
| 2 | "增益保留率91.7%" | **删除** | 同上 |
| 3 | "Dynamic在30%故障下显著超过Single" | **改写** | Frozen未确认(+0.7pp ns);改为"质量保持稳定" |
| 4 | "zero-harm"(泛化) | **改写** | 主面板0/0/0, Frozen 1/1/1;改为"strongly favorable asymmetry" |
| 5 | "Single exhibits substantial cost advantage" | **改写** | FZ-1修正后C=802(非434);改为"cost advantage with narrowed margin" |
| 6 | "Local与Full Replay等价" | **改写** | 质量差异未达显著,不等于等价;改为"without demonstrating additional recovery benefit" |
| 7 | "Verifier fails / useless" | **改写** | 改为"does not provide additional Pareto gains" |
| 8 | "提出多目标组合搜索算法" | **删除** | 本文是Selection不是Search |
| 9 | "证明了广泛跨域泛化" | **删除** | Math/MBPP样本小,定位为"边界分析" |
| 10 | "Workflow Scheduler 56.0%" | **排除** | 来源不明,未经审计确认 |
| 11 | "Oracle 50.5%是本文方法结果" | **改写** | 必须标注"post-hoc upper bound" |
| 12 | "Dynamic拥有最高HV" | **删除** | Single的exclusive HV通常更大 |
| 13 | 修正前Static/Dynamic/SM/RD/FG数字 | **删除** | 全部以修正后为准 |
| 14 | 修正前多种子Static列(偏高) | **删除** | 故障治愈bug修正后为准 |

---

## E. 图表位置规划表

| 编号 | 类型 | 位置 | 内容 | 来源 |
|---|---|---|---|---|
| 表4-1 | 表 | 4.1 | 面板与实验配置 | 各POLICY.json |
| 表4-2 | 表 | 4.2.1 | 条件节点质量(异质性) | EXPERIMENTS_V8表4-1 |
| 表4-3 | 表 | 4.2.1 | 严格配对分解 | EXPERIMENTS_V8表4-2 |
| 表4-4 | 表 | 4.2.2 | 决策粒度比较(Query/Node/Selective-DAG) | 路由结果+selective_dag_oof |
| 图4-1 | 图 | 4.3.1 | 故障鲁棒性曲线(双面板) | plot_fig4_1.py |
| 表4-5 | 表 | 4.3.1 | 故障主表(3种子mean±std) | MULTI_SEED_REPORT |
| 表4-6 | 表 | 4.3.2 | 恢复归因+局部vs整图 | CORRECTED_REPORT |
| 表4-7 | 表 | 4.3.3 | Frozen 200主表+分层诊断 | FROZEN200_CORRECTED |
| 表4-8 | 表 | 4.3.3 | 检测F1+故障节点类型 | corrected_replay+FROZEN200_DIAG |
| 图4-2 | 图 | 4.4.1 | 预算-质量曲线 | plot_fig4_2.py |
| 表4-9 | 表 | 4.4.1 | Pareto前沿+HV | MULTIOBJECTIVE_TRADEOFF |
| 表4-10 | 表 | 4.4.2 | 调度器vs基线+状态消融 | SCHEDULER_EXPERIMENTS |
| 表4-11 | 表 | 4.4.3 | DV/FR池+Exact Pareto+ε-Pareto | POOL_ANALYSIS+exact_pareto |
| 表4-12 | 表 | 4.5 | 跨任务综合表 | EXPERIMENTS_V8 4.5 |

---

## F. 数字冲突与仍需人工确认的项目

| # | 项目 | 状态 | 说明 |
|---|---|---|---|
| 1 | Workflow Scheduler 56.0% | ❌ 排除 | 来源不明;无对应脚本或结果文件;未经审计确认 |
| 2 | Selective-DAG OOF面板 | ⚠️ 待确认 | TAT-QA-200+MH-100(300题)与主面板120题任务是否有重叠需核查 |
| 3 | 主面板f30预算交叉 | ✅ 已确认 | 主面板B≥2800 Dyn反超(+1.1pp);Frozen面板无交叉(Single全档领先)——两面板结果不同但均如实报告 |
| 4 | Frozen 200 Single fault cost | ✅ 已修正 | FZ-1: 434→802(后处理修正,无新调用) |
| 5 | Scheduler grid avg | ✅ 已确认 | 修正后=cost-only(0.4234),非此前报告的0.4238(FZ-1影响) |
