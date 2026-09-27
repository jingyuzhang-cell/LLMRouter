# 第二篇方法框架 V1.1（2026-09-26，含 P0-1 结果）

状态：设计稿。证据均已提交（25b6113 / ba04aef / 本 selective-gate commit）。

## 1. 中心问题与主线

**When should a multi-agent system trust, reuse, verify, or recompute a
historical workflow state under quality–cost–latency trade-offs?**

主线正式收敛为：

    Runtime Diagnosability → Trust Estimation → Selective Intervention
    → State-conditioned Pareto Scheduling

Graph Forest 是其中的历史状态与复用层（h），不与 selective gate 分开讲述。
两轴互补：运行时干预轴（何时动）+ 复用轴（有可信历史时是否重执行）。

统一机制证据（已提交）：
- 任务级（frozen200）：Always-Dynamic 在健康任务上 harm:help = 67:14；
  clean 面板 0.55 → 0.415（净伤害）。
- 节点级（GFv2 REUSE_ARM）：重生成 12/20 → 3/20 且多 2 次调用/任务；
  存储表达式重执行零调用 12/20，正确性 20/20 严格继承。
- 写入级（GFv2 3×2）：假阳性检查驱动的修复 12/20 → 11/20；
  oracle 选择 + 泛化反馈 8/8 原样复现（Detection ≠ Correction）。

一句话结论：**错误不会因为重新调用 LLM 而自动消失，干预本身也是风险；
且 P0-1 证明事前特征原则上无法定位干预机会——真正可优化的是运行时
diagnosability，而不是更复杂的先验分类器。**

## 2. 形式化

调度对象：

    F(G, a | x, h) = (Q, C, L)

- G = (Y, X, Z, M)：拓扑 / 节点模型分配 / 恢复策略 / 复用策略
- a ∈ {reuse, validate, regenerate, reroute, recompute, stop}
- x：当前任务（含是否 follow-up、修改类型）
- h：Graph Forest 历史状态（节点信任度 r_i、版本、来源、依赖）

**方法流（P0-1 后修订）**：

    x → initial plan → s_t → Trust Estimation → Intervention Gate

真正决定是否干预的是运行时状态，而非任务静态词法特征：

    s_t = [ parser/schema status, execution failure, consistency,
            node history, remaining budget, forest trust ]

干预净值原则（仅当 V>0 才动）：

    V(a|s) = P_help(a|s)·ΔQ_help − P_harm(a|s)·ΔQ_harm − λ_C·ΔC − λ_L·ΔL

阈值由干预收益/伤害比决定，且必须偏保守（M2，见 67:14）：

    P(fault|s) > τ = (ΔQ_harm + λ_C·ΔC + λ_L·ΔL) / (ΔQ_help + ΔQ_harm)

**理论上界分层（P0-1，frozen200 f30 面板）**：

    Q(Always-Dynamic)            = 0.4033
    Q(Perfect fault-aware gate)  = 0.4917
    Q(Selective Oracle)          = 0.5150

可优化空间拆解：
- **0.4033 → 0.4917（+8.8pp）**：运行时故障诊断（检测器在 s_t 信号上的
  precision/recall）——第二篇的主攻段；
- **0.4917 → 0.5150（+2.3pp）**：非故障内生 help/harm 预测（14 样本 vs
  67 内生 harm，基数上应保守）——困难段，不作为主线。

关键概念切分：
- **Detection ≠ Correction**（3×2：oracle 知道哪 8 个错，泛化反馈 0/8 修正）。
- **Agreement ≠ Correctness**（4/8 错误三模型一致；3/12 正确是少数派）。
- **A-priori ≠ Diagnosable**（P0-1：80% help 在随机注入任务上，事前特征
  AUROC≈0.5；机会在运行时状态里）。
- 同一 G 的 Pareto 坐标随 (a,h) 变化 → **State-conditioned Pareto Frontier**。

## 3. 算法模块

M1 **Trust model**：节点级 r_i = P(stored state trustworthy)。输入：写入时
验证（exec/schema 已有；语义层待做）、运行时一致性、执行历史。已定结论：
朴素多数投票无天花板；报告口径含 Precision/Recall/FPR/TPR 与
**P(wrong intervention | trigger)**。

M2 **Selective intervention policy（运行时）**：在 s_t 上估计 P_help/P_harm，
按 V(a|s)>0 门控。**必须显式计入 false positive 代价**：健康状态上
harm:help = 67:14 → 阈值偏保守，τ 由上式给出；健康状态上的错误干预比
"没修到"更危险（与 Graph Forest 结果统一）。待学：s_t 特征上的
P(fault|s_t)（候选：parser/schema 状态、执行失败、跨节点一致性、
节点历史、剩余预算、forest trust）。

M3 **State-conditioned Pareto scheduler**：检索 F 中候选 (G,a)，按
F(G,a|x,h) 算当前前沿，budget / preference / knee 三种选择
（组件已在 sa_pgfs_v1/pareto.py）。

M4 **Forest construction（离线）**：代理辅助搜索（GP 只对 Q；MC-EHVI /
cost-aware；对偶档案）。当前为 calibrated simulation（ba04aef）；真实阶段
候选图换真实执行填充，写入带 M1 信任分层。

## 4. 研究问题（RQ）

RQ1 Trust & Reuse：历史状态何时可信可复用？写入验证的精确度-伤害权衡
能否刻画（P(wrong intervention|trigger) 一等指标）？
→ 证据：3×2 + REUSE_ARM + 跨模型负结果；待跑：P0-2（200 任务 3×2 + C′）。

RQ2 State-conditioned Pareto：h 条件化是否实质改变前沿（配置被提升为
非支配、HV 移动、knee 迁移）？
→ 待跑：真实面板 reuse 前后对比。

**RQ3：运行时状态是否提供足够的可诊断信号，使选择性干预能够在
质量—成本—时延约束下优于 Always-Single 与 Always-Dynamic，并逼近
fault-aware selective upper bound（0.4917）？**

RQ3 (EN): Can runtime execution state provide sufficient diagnostic signals
for selective intervention to outperform always-on collaboration under
quality–cost–latency constraints and approach the fault-aware selective
upper bound?

（不再写"能否根据 task features 选择协同"——P0-1 已在当前协议下否定。）

## 5. 措辞红线

1. "复用严格占优"仅限当前协议（20 个单事实扰动 follow-up 任务）。
2. C 臂 0/20 谨慎解释；0/20 进主表前补 C′（normalized full rerun）。
3. 跨模型一致性负结果限定：当前模型池与面板中朴素多数一致性不足
   （错误相关），不写"多模型验证没用"。
4. verifier 报告 accuracy 与 discriminative utility 分开。
5. P0-1 负结果限定：当前随机故障注入协议下，事前 task-conditioned
   特征缺少可辨识信号；不外推为"任务特征永远无用"。

## 6. 只跑支撑故事的实验（按优先级）

| 优先级 | 实验 | 支撑 | 状态/规模 |
|---|---|---|---|
| P0-1 | Selective gate 可学习性 | RQ3 否定事前路径 + 上界分层 | **完成（阴性+机制）** |
| P0-2 | 200 任务 3×2 + C′ | RQ1 主表 | ~600 调用，继续做 |
| P1 | P(fault|s_t) 运行时检测器（现有 deployable 信号上） | RQ3 主攻段 0.4033→0.4917 | 复用 frozen 信号 + 少量调用 |
| P1 | 状态条件前沿（真实面板 reuse 前后） | RQ2 | 复用现有+少量 |
| P1 | 语义写入验证 probe | RQ1、M1 | ~200 调用 |
| P2 | SA-PGFS 真实评价阶段（HV-vs-evals 主图） | RQ2/M4 | 分批 |
| P2 | V(a|s) 门控 vs 三种 Always 统一负载 | RQ3 主表 | ~1000 调用 |
