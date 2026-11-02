# AAAI-27 MORobust Workshop 论文骨架（工作文档）

- **投稿对象**: AAAI-27 Workshop "Multi-objective and Multi-task Optimization for Robust AI" (MORobust), Montreal, 2027-02-22/23
- **截稿**: 2026-11-20 AoE（camera-ready 2027-01-02 AoE）；混合形式，至少一名作者注册并展示
- **格式**: AAAI 模板，目标 **4 页 short paper**（不含参考文献/附录）
- **定位**: 对应 CFP 主题 "Pareto-aware training and evaluation" + "Benchmarks for multi-objective AI evaluation" + "Constraint handling"。摘要第一句钉在**多目标权衡**上，不是"调度系统"上。

---

## 0. 标题候选（三选一）

1. **The Objective Changes the Answer: Multi-Objective Geometry of Quality–Cost–Latency Scheduling for LLM Ensembles**（首选：直接呼应 CFP"单一标量掩盖权衡"）
2. Separable Levers, Not Closed Loops: A Preregistered Multi-Objective Evaluation of Multi-Model LLM Scheduling
3. What Pays Off in Multi-Objective LLM Pipeline Scheduling? Confirmed Levers, Null Results, and Boundary Conditions

---

## 1. 摘要草稿（英文，可直接改用）

> Scheduling a pool of heterogeneous LLMs over decomposed task DAGs is inherently multi-objective: answer quality (Q), cost (C), and latency (L) trade off, and single scalar scores can mask which mechanism actually creates value. We report a preregistered, multi-family evaluation of Q/C/L scheduling spanning roughly 1,100 tasks, six model pools, and more than twenty frozen protocols with paired statistics (McNemar, bootstrap CIs, frozen admission gates). Three findings emerge. **(1) The objective, not the mechanism, decides the ranking**: under quality-plus-cost alone, no confirmed win–win operating point exists; adding latency or reliability to the objective makes adaptive scheduling significantly better (+0.008 to +0.011, CIs excluding zero); and under fault injection the system-level Pareto front flips from single-model-dominated to recovery-dominated. **(2) Separable levers carry all confirmed value**: static node-type-prior routing (+6.5pp quality with fewer tokens and lower latency, preregistered gates passed), heterogeneous static assignment (+8.5pp at zero marginal cost), and fault-targeted local recovery (+20pp quality, −33% tokens versus full replay). **(3) The combination layer does not pay**: learned query/embedding routers add nothing over type priors, joint scope×model×structure optimization loses to the best single lever in a real paired run, and feedback-driven profile updates do not improve quality because runtime errors are unobservable. We release frozen protocols, corrected analyses, and negative-result attributions as a benchmark for Pareto-aware evaluation of LLM systems.

（~215 词。如果版面紧，删 "We release..." 句——开源承诺要做得到才写。）

---

## 2. 逐节骨架（4 页预算，两栏 ≈ 每页 700–800 词）

### §1 Introduction（~0.6 页 / ~450 词）

- 开头两句话（钉主题）：可信 AI 的"reliable and efficient"维度天然冲突；LLM 集群调度 = 在 DAG 上做 Q/C/L 三目标决策，实践文献大量用单标量（win-rate、平均分）报告，掩盖了机制在哪个目标下创造价值。
- 提问（三个，与结果一一对应）：
  RQ1 目标组合如何改变"动态 vs 静态"的结论？
  RQ2 哪些调度杠杆有**确认的**多目标收益？
  RQ3 组合层（学习型路由 / 联合优化 / 反馈闭环）是否在其之上有增量？
- 一段方法学差异声明：全部结果来自冻结协议 + 预注册准入门 + 配对统计；三套实验族口径不同，**从不跨族池化**；已撤销数字用修正值。
- 贡献列表（3 条 = 三个 finding + benchmark 交付）。

### §2 Experimental Discipline and Setup（~0.6 页 / ~450 词）

- **Table 1（三实验族，并排标注口径，绝不合并数值）**：

| Family | 任务/规模 | 模型池 | 关键口径 | 代表来源 |
|---|---|---|---|---|
| A: 419-task replay | 419 任务（5 模型×3 重复采集的重放面板） | qwen-plus, deepseek, gemini, GLM 等 | 效用 = 加权 Q/C/T/R 组合；重放口径 | `phase_e3_0/E3_0_RESULTS.json`, `phase_e3_1/E3_1_RESULTS.json`, `routing_regime_objective_results/PAPER_EVIDENCE_REPORT.md` |
| B: DAG execution panels | fresh 100 题（493 节点、3×404 真实请求）；multidag 120；frozen200；adaptive 120×3seed×3故障率 | medium/large/coder（+reasoner 池） | 节点契约计分 + 终端计分；故障注入 f10/20/30 | `static_dag_v0/fresh_static_confirmation/RESULTS.json`, `static_dag_v0/multidag_dynamic_120/CONFIRM_ANALYSIS.json`, `static_dag_v0/adaptive_benchmark/` |
| C: paired mechanism probes | DD-V5.1（4臂×5block 真实执行）；DYNPI 10 run；MVR 343 调用；89-run 反馈批 | glm53/glm53flash（+DeepSeek） | 事实级 F1；双异常注入 | `cap_eval_bench_v1/dd_v51_results/RESULTS.json`, `cap_eval_bench_v1/STAGE_C_DYNPI_RESULTS.md`, `research_outputs/mvr_batch1/BATCH1_FINAL_REPORT.md`, `cap_eval_bench_v1/EVAL_CALIBRATION_RESULTS.md` |

- 一段纪律描述：预注册 → 冻结 → 配对分析（McNemar / 分组 bootstrap CI）→ 准入门（F1–F3 等）；错误更正台账（例：f30_dynamic 0.4033 因实现泄漏撤销，修正 0.3433，见 `r3_own_pool/collab_scheduler_v1/REFERENCE_CUBE.json`）——这段是"benchmark 贡献"的证据。
- Q/C/L 定义一句带过（Q=契约/事实级计分；C=tokens（逻辑 vs 物理分开计）；L=服务时延，不与墙钟混报）。

### §3 RQ1: Objective Geometry（~0.8 页 / ~600 词）——全文最有 Workshop 相的一节

- **核心表/Figure 1（条形图 + CI）**：dynamic−static 效用差，按目标组合分面（Family A，E3_0_RESULTS.json）：
  - 单目标 Q: +0.0042，CI 含 0（不显著）
  - 双目标 Q+C: **−0.0012（负，不显著）**
  - Q+T: +0.0114 [0.0018, 0.0212]
  - Q+C+T: +0.0091 [0.0018, 0.0167]
  - Q+T+R: +0.0095 [0.0022, 0.0171]
  - Q+C+T+R: **+0.0079 [0.0031, 0.0134]**（回收 oracle 空间 13.5%）
- **双目标没有免费午餐**（E3_1_RESULTS.json）：τ=0.05 省 4.7% 成本但质量项 CI 含 0；τ=0.10 省 39.4% 但质量 **−0.0239 显著受损**；τ=0.02 质量微升但成本反升 8%；Tchebycheff 策略质量 +0.0040 但成本 −12%。措辞红线：写 "no confirmed win–win operating point"，不写 "impossible"。
- **故障翻转前沿（Figure 2：clean vs fault 两个 Pareto 面板）**：
  - clean：单模型 Pareto 支配（frozen200 修正后全局前沿仅 SINGLE+RETRY，`FROZEN200_CORRECTED_SUMMARY.json`；adaptive_benchmark clean 前沿只含 single/router，`MULTIOBJECTIVE_TRADEOFF.json`）
  - f10–f30：dynamic−static +9~14pp、零记录伤害、逐 seed p≤0.001（adaptive_benchmark）
- 一句机制解释：时延/可靠性目标奖励"在执行中放弃无效路径"的能力，而这恰是静态分配做不到的——所以**机制的价值由目标定义**。

### §4 RQ2: Separable Levers（~0.8 页 / ~600 词）

- **Table 2（主结果表，全部带 CI 和门禁状态）**：

| 杠杆 | 效果 | 成本/时延 | 证据 | 门禁 |
|---|---|---|---|---|
| 静态类型先验节点路由 (FrozenNodeRouter) | Q 0.5132 vs 0.4483，**+6.49pp CI [3.86, 9.13]** | tokens −134.6/任务，服务时延 −3.92s/任务（均显著为负） | `fresh_static_confirmation/RESULTS.json` | F1/F3/统计门通过，Static stage confirmed |
| 静态异构分配（reasoning→换模型） | +8.5pp（31.5→40.0），p=0.0015，n=200 严格配对 | 零边际成本/时延 | `decomposition_benchmark/horizontal_comparison.json` | 冻结面板配对 |
| 故障定向局部恢复 | +20pp CI [11.7, 28.3]，McNemar p=1.9e-5 | tokens −90.4/任务，时延 −0.34s | `multidag_dynamic_120/CONFIRM_ANALYSIS.json` | 预注册 case 1 confirmed |
| 局部恢复 vs 整图重放 | 质量未检出差异（p=0.69/0.125，**不写等价**） | **tokens −33~39%，调用 −50%，时延 −38~44%**（fg 需 ~2.1× 预算） | `multidag_fullgraph_120/FULLGRAPH_ANALYSIS.json` | 修正后重放分析 |
| 依赖感知图森林复用 | 复用 12/20 vs 重生成 3/20 | 调用 −50%，tokens −91.4%；整链重跑 −16.7pp 且 +4423 tokens | `graph_forest_v1/`, `graph_forest_v2*/` | 机制验证 |
| 同模型分解的代价（边界） | −21.0pp（52.5→31.5），p=4.3e-07（MultiHiertt +6pp 不显著） | +31% tokens | `decomposition_benchmark/` + `DAG_MAINLINE_EVIDENCE_FINAL.md` g2 | 冻结配对 |

- 关键归因一句（诚实加分项）：+20pp 恢复中 **18.3pp 来自"对准故障节点"这个动作本身**，策略超出对准的净增量 +1.67pp CI 含 0（`multidag_ablation_120/ABLATION_ANALYSIS.json`）——杠杆是"定向"，不是"智能策略"。
- oracle 差距给上限锚点：NodeOracle 0.5781 vs 已实现 0.5132（恢复 50%，CI [32.8, 65.3]%）；exact 枚举族 `exact_oracle/EXACT_ORACLE.json`（写时用本族口径，注明不可跨族比较）。

### §5 RQ3: The Combination Layer Does Not Pay（~0.8 页 / ~600 词）

- **Table 3（零/负结果一览，每行注明这是"未检出"还是"负"）**：
  1. **学习型路由器 ≈ 类型先验**：嵌入 NodeRouter fresh CI [−0.8, +1.2]pp（"类型粒度承载全部收益，嵌入贡献≈0"，`node_router_ablation/RESULTS.json`）；CapabilityRouter CI [−1.11, +0.89]；TAT-QA 上 NodeRouter 显著**低于** TypePrior（CI [−6.5, −0.5]，`tatqa_benchmark/ANALYSIS.json`）；419 线确认实验 gap recovery −19.85%（`ROUTABILITY_LEARNABILITY_GAP_REPORT.md`）→ "routable-but-not-learnable"。
  2. **联合优化不超过最优单杠杆**：DD-V5.1 真实配对（2026-11-01）：Q_F1 均值 pi_only 0.1458 > Joint 0.0903 > Static 0.0807；Joint−pi_only 1 胜/4 负，中位 −0.074；C_info 变体全 0.000（`cap_eval_bench_v1/dd_v51_results/RESULTS.json`，**投稿前需先落结题报告**）。辅证：DYNPI ΔQ=0.000（p=1.0）、成本 +13.2%；MVR 换模质量持平、成本 +82%、时延 −44.7%（C/L 权衡而非双赢）。
  3. **反馈画像在线更新 dQ≈0**：dQ 中位 +0.000、均值 −0.046（`EVAL_CALIBRATION_RESULTS.md`）；跨模型生产门禁 NO_GO_UNCALIBRATED。
  4. **根因：运行时错误不可观测**——实际检测器工作点 recall 0.273 → 系统级恢复 0.0、+439 次验证调用零质量收益；完美检测参照 0.5497 vs 实际 0.5132（`verifier_sensitivity/RESULTS.json`, `system_verifier_impact/RESULTS.json`）。feedback_state_aware_v1 replay +4.67pp CI [2.6, 6.8] 作为初步正向对照（标注 replay 口径 + PRELIMINARY）。
  5. **预算条件几乎不改变决策**（约束处理的实证负结果，呼应 CFP "constraint handling"）：各预算档选择分布几乎不变（`budget_conditioned_routing/BUDGET_ROUTING.json`）；deadline 约束净收益**无任何实测证据**（`DEADLINE_PAIR_ADMISSION_AUDIT.md` NO-GO）。
- 结尾一句提炼：不是"组合层永远无用"，而是**在错误不可观测、目标不含时延、任务为浅层 DAG 的当前条件下**，组合层无法在单杠杆之上积累增量——这正是 Pareto 感知评估应当暴露的事实。

### §6 Limitations and Implications（~0.3 页）

- 强制边界声明（照 `DAG_MAINLINE_EVIDENCE_FINAL.md` 第 5 条）：任务计算结构多为**浅层 DAG**（e1→e2→r→v），构造任务 ≠ 自然复杂 DAG；故障为注入式（且 DYNPI 的理论优势域在冻结词表中不可表达）；模型池非 frontier；deadline 维度未测。
- 含一句自我修正声明：本文所有数字采用修正后台账值；一处实现泄漏导致的数字已撤销并重测——作为 benchmark 贡献的一部分。

### §7 Conclusion（~0.15 页）

- 三句话：目标几何决定结论；可分离杠杆承载全部已确认价值；组合层收益在当前可观测性下未被证明——为 Pareto 感知评估提供一个带冻结协议与负结果归因的 benchmark。

---

## 3. 图表清单（2 图 + 3 表，short paper 上限）

| 编号 | 内容 | 数据来源 | 形式 |
|---|---|---|---|
| Fig 1 | dynamic−static 效用差 × 6 种目标组合（含 CI 误差棒） | `phase_e3_0/E3_0_RESULTS.json` | 条形图 |
| Fig 2 | clean vs fault 两面板 Pareto 前沿（Q vs tokens） | `FROZEN200_CORRECTED_SUMMARY.json` + `adaptive_benchmark/MULTIOBJECTIVE_TRADEOFF.json` | 散点前沿 |
| Tab 1 | 三实验族口径表 | §2 | 表 |
| Tab 2 | 可分离杠杆主表（效应+CI+成本+门禁） | §4 | 表 |
| Tab 3 | 组合层零/负结果表（含"未检出/负"分类） | §5 | 表 |

## 4. 参考文献桶（作者补全，10–15 条即可）

1. LLM 路由/级联：FrugalGPT、RouteLLM、cascades（C6 线的对照文献）
2. 多目标 LLM 系统：EcoOptiGen 及 cost-quality tradeoff 类
3. MOO 方法：Pareto 前沿/HV、约束 MOO（支撑 §3 术语）
4. 多智能体/协作 LLM 调度（相关工作定位用）
5. 评测方法学：preregistration / paired testing 在 ML 中的用法

## 5. 写作红线（投稿前逐条自查）

- [ ] 不写：联合闭环收益、56% scheduler、Exact-Pareto 54 组合、任何"dynamic beats single in general"
- [ ] 不写：deadline 约束收益（无实测证据）；p=0.125/0.69 只写"未检出差异"，绝不写"等价/无损"
- [ ] 不用撤销值 f30_dynamic=0.4033（用 0.3433）；不用跨族池化数字（Tab 1 并排标注即可）
- [ ] 不写 oracle union 可部署；不写任何"认证时延分位数"
- [ ] L 一律服务时延，不与墙钟混报；C 注明 tokens 口径（逻辑/物理分开）
- [ ] DD-V5.1 数字引用前先落结题报告（目前只有预注册+原始数据）
- [ ] feedback_state_aware_v1 的 +4.67pp 必须带 "replay 口径、PRELIMINARY" 标签

## 6. 18 天时间表（今天 11-02，截稿 11-20 AoE）

| 日期 | 任务 |
|---|---|
| 11-02 → 11-05 | ① 为 DD-V5.1 写结题报告（落台账+md，放 `cap_eval_bench_v1/`）；② 建"主数字总表"（每格：数值+CI+来源文件+口径标签），全部用修正值 |
| 11-06 → 11-10 | LaTeX 模板起稿：§1–§2 + Fig 1/Fig 2 出图（matplotlib，两栏宽度） |
| 11-11 → 11-15 | §3–§5 + Tab 2/3；内部红线自查（第 5 节清单逐条过） |
| 11-16 → 11-18 | 全文合稿、共同作者过一遍、摘要定稿 |
| 11-19 | OpenReview 提交（留一天缓冲；确认至少一名作者能注册） |

## 7. 待定决策（需要你拍板）

1. 标题选 1/2/3（我推荐 1）；
2. 4 页 short（推荐，现有材料刚好）还是 8 页 full（需要把 DYNPI/MVR 细节展开，风险是把未确证内容写进去）；
3. 是否承诺 "release protocols"——仓库能否开源或至少提供冻结协议附录，决定摘要最后一句去留；
4. 作者列表与致谢（模型 API 费用主要由本仓库实验承担，是否致谢）。
