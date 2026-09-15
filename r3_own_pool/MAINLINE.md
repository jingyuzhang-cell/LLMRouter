# 当前研究主线

Model Utility Profiling → Initial Routing → Static DAG → Execution Feedback → Dynamic Replanning → Pareto Multi-objective Optimization。

GAP、重复稳定性和 Label Repair 保留为前置实验，用于支持模型异质性、静态选择机会与初始路由估计的不确定性。Label Repair 的已冻结确认标准未达成；不再沿 GAP Recovery 继续自动搜索 Router。

已执行静态基线入口：[Static DAG v0](static_dag_v0/README.md)。它使用 20 个构造的多步采购任务验证分解、依赖、初始分配、真实本地执行和 Q/C/L 计量。领域模板分解和迁移的全局模型画像是显式限制。此 pilot 不替代自然复杂任务 benchmark，也不能证明路由、修复或动态方法优于基线。

后续逐层推进；局部修复已完成下述首轮对照，其余尚未启动：

1. Static + Local Repair：只修复失败节点，明确重试/换模型预算，累计全部代价。
2. Dynamic Replanning：根据已执行状态重新评估剩余计划；已花费成本不消失，失效后继输出必须撤销。
3. Graph Forest + Pareto Search：候选后续 DAG 的 Q/C/L/R 估计、非支配过滤、固定 beam 选择与反馈更新。
4. 固定比较 BestSingle、Router Only、Static DAG、Local Repair、Dynamic DAG；同任务、同模型池、同预算与评分条件。报告 Quality、Cost、Latency、Task Success、Recovery、Replanning Cost、Hypervolume，后者需统一归一化和冻结参考点。

1000 题 × 模型数据未来定位为 Utility Profiling Dataset，记录 `(q,m,Q,C,L)` 和可追溯模型/输入/计价/失败信息；本轮没有启动该数据扩展。当前 C 使用 tokens 资源指标；若论文比较货币成本，需要另外确认统一真实计价依据。真实端到端延迟与服务时长关键路径不可混报。

## Local Repair v1：已经执行的决策证据

[报告](static_dag_v0/local_repair/run_v1/REPORT.md)与[协议](static_dag_v0/local_repair/run_v1/PROTOCOL.json)：20个新同模板任务，冻结模型和图，每节点最多修复一次。Static成功3/20，Local Repair成功4/20，差值+5pp、95%任务配对区间[0,15]pp。41次节点修复中2次通过局部契约，逻辑tokens由22883增至38944。该结果未确认修复收益。

确定性工具基线20/20成功、零模型调用，表明此采购算术任务族首先应采用执行器类型选择：可计算节点交给工具，而非让LLM反复算数。其100%不代表自然复杂任务也能由这些规则解决。

下一里程碑应是Tool-aware Static DAG与需要语义提取/推理的自然任务静态对照；在该基线和可检测失败机制站稳之前，不推进Graph Forest。现有采购pilot只保留为执行器回归测试，不当作动态规划创新主结果。新增里程碑尚未自动执行。

## Fresh Static DAG Confirmation（当前执行）

用户已明确授权：官方MultiHiertt test缺少标签，改用经工作区使用记录审计未参与开发的train任务，固定100题作为独立fresh holdout。参数和全部部署选择在fresh回答生成前封存，三个Router候选medium/large/coder各节点真实执行一次；R1不加入、不采集。本轮只比较Always Large、Query Router、Static Capability、Frozen Node Router和Node Oracle。

[当前协议与结果目录](static_dag_v0/fresh_static_confirmation/README.md)。F1–F3均在固定统计规则下检验；不能按fresh结果改模型、阈值或特征。通过后才可把Static阶段证据冻结，不自动启动Feedback。

后续路线明确为Static DAG → Feedback Memory → Dynamic DAG → Graph Forest → 单/双/多目标优化。Graph Forest定义为历史任务图/子图的可检索、可复用、可修改、可版本化集合，支持追问复用已有节点；动态DAG的新候选分支只是其中一部分，不能把Graph Forest缩减为本次候选beam。这里只记录路线，尚未实现或启动这些阶段。
