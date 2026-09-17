# V1 Baseline（冻结于 2026-09-15）

> **终局定位与贡献收敛（2026-09-15，P0 全部结束）**：论文 = **B+少C**："Feedback-aware multi-model execution framework over adaptive DAGs"（面向复杂任务的反馈感知多模型协同执行框架）。**三贡献收敛**：①节点级多模型协同选择（Node Router +6.9pp，EXEC 评分下精确保持）；②反馈驱动执行适应（Feedback +4pp，双口径复现）；③失败感知结构恢复与系统诊断（Decompose +6pp + Oracle/Verifier 两层诊断）。Graph Forest → supporting capability；Multi-objective → deployment analysis。**核心叙事双数字：实际 34% vs 潜力 50%，16pp 差距归因 extraction(+12pp)/reasoning**；检测在节点级有价值（18.7%）任务级归零（剩余失败为多模型共同失败）。不再加大实验；剩余可选 P1 仅第二域核心复现（Query/TypePrior/NodeRouter 三臂）。写作期任务：EXPERIMENTS.md 全表换 EXEC 口径（SCORED_MATRIX_EXEC）、5.8 换 live 表+单模型基线+实测成本、5.5 增设 Failure/Component-Ablation/Oracle 三小节、删除过强表述（dynamic planning / learned representation / optimization algorithm）。

> **主线收官（同日）**：Multi-objective 正式实验（bi/tri Pareto={Static, Feedback v1}，选定 Feedback v1；Type-aware Dynamic 计入验证开销后被支配，定位为鲁棒性而非成本效率）与 **E2E formal**（StaticOnly .13 / Static+Feedback .27 / **FullAdaptiveDAG .56 task success**，Q .5801，追问复用 50%/−91.4% tokens）。E2E 为 measured-component 回放（采样点全部披露），live 集成运行留作 future work。Type-aware Verifier Gate（Q .5254/18.75% recovery，漏检 61→6）与 System-level Verifier Impact（完美检测 +3.65pp vs 真实检测归零——检测是瓶颈）构成 Dynamic 章闭环。全部模块 ✅。

> **Adaptive DAG v1 冻结（同日）** = Static DAG + Node Router + **State-aware Feedback v1** + Failure-aware Dynamic（Reroute/Decompose 双分支）。Feedback v1（`feedback_state_aware_v1/`，零生成）：(type,length-bucket,m) 初始记忆 + **失败态记忆驱动回退**（λ'=0.5，替代冻结次优规则）→ Q .5558 @1.49× 调用，recovery **3.1%→65.6%**，v1−v0 +4.1pp CI[+2.2,+6.0] helped 20/harmed 0，**同预算下胜过 Dynamic 固定规则（.5497）**——Feedback 从最弱模块变为性价比最高模块。框架图升级为：Decomposition→Node-level Q/C/L 估计→Static 多目标→执行→Feedback→Failure Diagnosis→{Model Failure→Reroute；Evidence/Structure Failure→Decompose}→Adaptive DAG→Graph Forest→Pareto→Best Plan。

> **v1.1 增补（Decompose v1 PASS）**：Dynamic DAG 失败处理升级为双分支诊断——
> **Evidence Failure（证据缺失/语义未对齐）→ Failure-aware Decompose（6/20；对照 Fixed 0/10、Plain 重问 0/20。根因：裸事实丢失报告上下文的实体/期间分组语义；另发现 v1 表达式语言常数白名单 {0,1,100} 使平均类题目结构性不可表达，v1.1 起执行器扩展为任意有理常数）**；
> **Reasoning Failure（关系推理错误）→ Upgrade/Search（未实现，后续）**。
> Verifier 债确认：D4 与真实结果一致仅 7/20，step-level 验证列入优化清单。

**框架**：面向复杂任务的反馈驱动自适应 DAG 多模型协同优化（Feedback-aware Adaptive DAG Routing for Multi-Model LLM Agents）。
**规则**：本文件冻结 v1 架构。此后不再新增模块、不改架构；后续实验只允许优化既有模块的效果。

## 模块与冻结产物

| 模块 | 状态 | 关键结果 | 产物目录 |
|---|---|---|---|
| Node Capability Benchmark + Node Router | ✅ 效果确认 | dev: +6.4pp vs Query Router, recovery 46.2%；fresh 100 题 holdout: **+6.9pp, recovery 50.0%**；类型翻转（extraction→large / reasoning→medium / verification→coder） | `tool_aware_v1/node_benchmark/`, `fresh_static_confirmation/` |
| Static DAG（Tool-aware） | ✅ Gate A/B | 工具执行 30/30=100%；旧路由审计 ρ_Q=−0.013 → 被 Node Router 替代 | `tool_aware_v1/` |
| Feedback Memory v0 | ✅ 机制 / 效果弱 | 36 决策变化，helped 2/harmed 0，Q +0.4pp（CI 含 0） | `feedback_memory_v0/` |
| Dynamic DAG v0（Reroute+Dependency Replan） | ✅ 机制 / 可部署口径有效 | 次优单次 reroute: **+3.65pp @1.49× 调用**；升级到第三=池穷举=oracle 上界（不作部署证据） | `dynamic_dag_v0/` |
| Dynamic Decompose | ✅ 机制 / 效果债 | 10/10 子链跑通，**0/10 救回**（问题在分解模板/语义，非管道） | `dynamic_dag_v0/decompose_pilot/` |
| Graph Forest v0 | ✅ 机制 | 存/检索/复用（零调用）/版本化/失效重算全过；债：LLM 算术与 verifier 质量 | `graph_forest_v0/` |
| Multi-objective Optimization v0 | ✅ | 单目标双方向=Feedback Router；Pareto(2/3 目标)={Feedback, Dynamic-Reroute}；Oracle 只作上界 | `optimization_v0/` |
| End-to-End Demo | ✅ | 失败→反馈→reroute 恢复→森林复用(0 调用)+工具比较→版本化局部重算→Pareto 选 Graph-Reuse；全程 2 次真实调用 | `end_to_end_demo/` |

## 前置诊断链（论文 Motivation 章）

E1–E9 + label repair（router_v2/）：query-level 路由在 representation/objective/probe/标签修复各维度全线无法恢复 GAP（recovery ≈ 0 或负）→ 证明需要 node-level 条件能力估计。fresh-100 确认集同时证明 query-level 机会不迁移（switch median p=0.5）。

## 效果债（二阶段只许还债，不许加模块；按优先级）

1. **Decompose**（最高优先）：0/10 → 需要更强分解模板/语义策略；
2. **Feedback Memory 增强**：λ 调参、顺序 seeds、更强记忆结构（仍是 Q(node,m,state)，非 RL）；
3. **Graph Forest 质量**：聚合/比较一律工具节点、verifier 强化；
4. **多目标正式实验**：扩大数据规模、正式 Pareto 统计；
5. **大规模 benchmark 验证**。

## 解释边界（论文必须保留）

- 条件节点表评估（reasoning/verification 用 gold 输入），非端到端 DAG 质量；
- fresh holdout 来自经审计未使用的 train split（预训练不可证）；
- 3 模型池下 best+2nd+3rd = 穷举 = oracle 上界，任何升级策略结果只能报上界；
- 本地 GPU 延迟为请求服务时长，货币成本未建立；
- R1（DeepSeek-distill）仅 shadow 诊断，不入冻结候选池。
