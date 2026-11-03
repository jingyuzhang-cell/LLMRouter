# 论文摘要草稿

## 中文摘要

**面向截止时间约束的反馈驱动异构多智能体 DAG 动态调度与质量—成本—时延联合优化**

随着资本市场信息披露监管的加强，对上市公司违法违规事件的调查涉及大量跨年度、跨文档的证据核验工作。大语言模型（LLM）为智能化辅助调查提供了新路径，但单一模型面临输入长度限制、提取不完整和异构性未利用等挑战。将调查任务分解为有向无环图（DAG），在不同节点上分配异构模型并动态处理执行异常，是应对这些挑战的关键方向。

本文构建了 CapitalEvent-DAGBench——基于真实 A 股资本市场事件的调查 DAG 基准，包含官方文档冻结库、程序锚定的参考事实和统一评价协议。在此基础上，提出了联合动态调度器 S6，其核心是在节点执行异常发生时联合选择恢复模式（Z）、重执行节点集合（R）和异构模型分配（π），通过两阶段决策（可行性过滤 + 多目标优化）在质量、成本和时延三个维度上进行权衡。

在康得新（跨年度财务造假）和江苏舜天（专网通信虚假业务）两个事件上，使用四个模型（三个家族：GLM-5.3/GLM-5.3-Flash/DeepSeek-Flash/Qwen-Plus）进行了五策略配对实验。主要发现包括：

（1）异构模型在四个节点类型上存在显著时延差异（DeepSeek 全类型最快，比 GLM 快 2-3 倍），构成可利用的调度空间；

（2）S6 联合调度器通过选择时延更优的模型进行故障恢复，在两个事件上将端到端时延分别缩短 36% 和 29%（vs 固定恢复策略），且事实覆盖不降低；

（3）S6 的时延优势来源于多目标联合决策中的模型选择（π 维度），而非恢复范围（R）或恢复模式（Z）的独有增量；质量维度上 S6 与最优固定策略持平；

（4）单强模型虽然成本和时延最优，但关键事实覆盖率仅为 33-38%，显著低于 DAG 分解方法的 67-83%。

本文的研究表明，联合动态调度在截止时间敏感的多文档调查任务中具有实际价值，为异构模型资源分配优化提供了新的实证基础。

**关键词**：DAG 调度；异构模型；动态恢复；质量—成本—时延优化；资本市场调查；大语言模型

---

## English Abstract

**Feedback-Driven Heterogeneous Multi-Agent DAG Dynamic Scheduling with Quality-Cost-Latency Joint Optimization under Deadline Constraints**

This thesis addresses the challenge of automating capital market event investigations using large language models (LLMs) within DAG-structured workflows. We build CapitalEvent-DAGBench, a benchmark based on real A-share regulatory events, and propose S6, a joint dynamic scheduler that selects recovery mode (Z), re-execution node set (R), and heterogeneous model assignment (π) upon node execution failures.

Experiments on two events (Kangde Xin cross-year financial fraud; Jiangsu Shuntian fake business) with four models from three families show that: (1) models exhibit significant latency differences (DeepSeek 2-3× faster than GLM across all node types); (2) S6 reduces end-to-end latency by 29-36% vs. fixed recovery strategies while maintaining factual coverage; (3) S6's latency advantage stems from multi-objective model selection (π dimension); (4) single-model approaches achieve lowest cost but lowest fact coverage (33-38% vs. 67-83% for DAG decomposition).

**Keywords**: DAG scheduling; heterogeneous models; dynamic recovery; quality-cost-latency optimization; capital market investigation; large language models
