# 论文摘要草稿 V2（2026-10-14，对齐协议 v2 受控证据；旧稿存档不引用）

面向截止时间约束的反馈驱动异构多智能体 DAG 动态调度，其核心问题是：当静态最优分派
遭遇执行期约束变化（模型服务不可用、契约失败、时延波动）时，复杂的联合动态调度相对
简单反馈恢复是否具有可测量的独立增量。本文在两个真实 A 股资本市场事件（康得新跨年度
财务造假、江苏舜天虚假业务）上，以四模型三家族异构池、七节点并行 DAG、程序锚定的
官方可核验参考事实与字段级确定性评分，对该问题给出受控测量。

主要结果：（1）异构时延差真实且大（同类节点跨模型 2.4–2.8×，实体关系节点
GLM-5.3 18.05s vs DeepSeek 6.38s），分派优化存在物理基础；（2）反馈恢复的必要性成立
——关键节点失效使固定分派的事实覆盖从 4/8 崩溃至 1/8，任何反馈恢复（含查表级简单
恢复）均可追回至场景上限；（3）联合动作 a=(Z,R,π) 的增量是条件性的：π 维度带来方向性
时延收益（单事件 −9.8%、三重复均值 −5.5%，均不显著）但现金成本更高（+29% 至 +76%）；
Z 维度的可观测价值是截止期不可行时的拒绝机制（NONE）；R 维度在全部真实运行中未偏离
局部闭包；（4）任务质量上限主要由证据供给决定（检索可达性与报告长度取舍），而非调度
策略。本文同时给出检索打包（预算均分空检索缺陷的修复与回归锁定）、输出契约（分层
解析与实测标定上限）与截止期控制（P90 校准的事前预检）的协议演化记录，并如实披露
两次执行事故及其工程整改。

结论定位：在本文实验条件下，简单反馈恢复已足够；联合调度的价值应表述为紧截止期与
强异构时延场景下的条件性收益，其适用边界由本文首次给出受控测量。

**关键词**：多智能体调度；有向无环图；截止时间约束；大语言模型异构池；质量—成本—时延权衡

---

Abstract (EN): This thesis studies whether feedback-driven joint dynamic scheduling
of heterogeneous LLM pools on DAGs yields measurable independent gains over simple
feedback recovery when statically optimal assignments meet runtime constraint
changes. Controlled experiments on two real A-share capital-market events with a
four-model, three-family pool, a seven-node parallel DAG, and programmatically
anchored official facts show: (1) large node-level latency heterogeneity
(2.4-2.8x across models); (2) recovery necessity -- node unavailability collapses
fixed-assignment coverage from 4/8 to 1/8, and any feedback recovery restores the
scenario ceiling; (3) the joint action's gains are conditional -- the assignment
dimension (pi) yields directional but non-significant latency benefits at 29-76%
higher cash cost, the mode dimension (Z) acts as a deadline-feasibility gate
(refusing infeasible actions), and the re-execution set (R) never deviates from
the local closure; (4) the quality ceiling is governed by evidence supply rather
than scheduling strategy. We conclude that, under our conditions, simple feedback
recovery suffices, and position joint scheduling as a conditional benefit for
deadline-tight, strongly heterogeneous settings -- a boundary measured under
control for the first time.

# 绪论贡献段 V2（替换旧稿第 58-60 行的贡献 1-2 条）

1. **模型异构性确认（RQ1）**：四模型三家族在节点级存在 2.4–2.8× 的实测时延差与
   抽取层内容保真差异（协议 v2 时代实测，n=5–16/格）。
2. **恢复必要性确认、复杂度门槛澄清（RQ2）**：反馈恢复对故障崩溃的追回真实可靠
  （固定分派 4/8→1/8 崩溃；恢复追回至上限），但查表级简单恢复即可达到上限
  （三重复逐条一致）。
3. **联合增量的条件性刻画（RQ3，本文的核心诚实结论）**：π 有方向性但不显著的时延
   收益、恒更高现金；Z 为可行性守门；R 无偏离。首次以受控、预登记判定的方式给出
   联合调度的适用边界。
