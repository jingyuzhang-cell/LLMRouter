# CROSS_WINDOW_Z_DEFECTS_HANDOFF — 执行侧发现的两项 z_ops_v2 缺陷（交窗口1权威修复）

> 来源：执行侧 harness（feature/planner-execution / feature/joint-algorithm
> worktree）在把 z_ops_v2 接入统一 Z 候选源时的实测发现。操作者已裁决：
> 两项均由窗口1在其权威实现中统一修复，执行侧只消费同一实现，不复制
> 结构算法。本文件为交接说明，不改任何上游代码。

## F1（代码缺陷）：SPLIT_VERIFY 生成的角色不在合法白名单

`z_ops_v2.split_verify` 为 locate 节点使用 `role='retrieval'`
（z_ops_v2.py L48），而 `dag_runtime_v1.check_legality` 的 ROLE_CLASS
白名单没有该角色 → **任何图上 SPLIT_VERIFY 候选都过不了合法性**。
这与已记录的"V1 规划器单字段 produces 无过载节点"是两个独立原因。

操作者要求：不要只往白名单加 'retrieval' 了事——需统一节点角色、
输入输出类型、上下游连接与实际执行 handler，修复后 SPLIT_VERIFY 应能
在满足条件的 DAG 上形成合法候选。

## F2（语义正确性缺陷，优先级更高）：ADJUST_DEP 可跨文档重接证据

实测（福耀双文档图）：ADJUST_DEP 生成
`extract_plan: retrieve_plan -> retrieve_implementation`（及其镜像）——
结构合法、`z_semantic_guard` 放行（它只查 sink 合同与证据文档表），
但语义上把"读预案公告的抽取分支"改成了"读实施公告"：即使输出字段
同名，时间、事件阶段与法律含义都可能改变。若此类变更后评分提高，
不能计为结构优化收益——任务语义可能已被改变。

操作者要求（正式语义审查，至少核对）：证据对象、事件阶段、事实范围、
来源关系、替代依据；且**不得僵化为"必须同一份文件"**——满足等价或
替代条件（事实/时间范围/来源权威性/任务合同）的不同来源替换应当合法。
这正是 SUBSTITUTE_EV 的设计场景：证据不可用时的合法替代路径。

## 执行侧现状（供上游修复后对接）

- 执行侧临时守卫：EVIDENCE_IDENTITY 审阅规则（抽取类节点的证据生产者
  不可跨文档变更）——**保守版**，在窗口1正式等价性检查落地后应被替换/
  放宽。`z_ops_v2_port.port_menu(base, ctx, evidence_guard=...)` 已改为
  可插拔：上游提供正式检查（签名 `(base_graph, candidate) -> (ok, detail)`
  的 typed 层检查，或 DAGSpec 层等价物经端口适配）后，执行侧直接消费。
- 端口适配器位置：worktree `r3_own_pool/joint_algorithm_workpackage_
  20261028_v1/z_ops_v2_port.py`（typed-Graph↔DAGSpec 双向转换 + 规则
  引擎把关；z_ops_v2.py 已按 sha 快照，上游修复后重快照即可）。
- 修复验收建议（与操作者验收重点一致）：Joint(Z,R,π) 既能**拒绝有害**
  结构变更（如 F2 场景），也能在结构修改确有价值时**合法选择修改**
  （如证据不可用→SUBSTITUTE_EV）；不要求其一定选择结构变更。


## 操作者第七轮裁决补充（2026-10-28，窗口1实现时必须吸收）

1. **anchor_coverage >= 0.5 不构成充分的语义等价证明**：关键日期、主体、
   处罚事实等必要锚点不得因总体覆盖率过半而允许缺失——需要"必要锚点
   全覆盖"条件，而非仅聚合覆盖率阈值。
2. **AND/OR 语义按关系类型区分**：SUBSTITUTE_EV 的合法替代来源构成
   OR 式恢复选择；SPLIT_VERIFY 的分域子核验各负责不同必需事实，仍为
   AND。不把整个 DAG 改为 OR 图；为特定替代/冗余关系定义显式 OR-join
   合同（证据等价条件、结果选择规则、核验规则）。
3. **质量口径**：PRIORS_REAL_V1 节点级 q_success 为格式可解析率
   （生产侧审计 S4 已标注 MAJOR），不可用于质量约束或 Q_min；语义级
   节点质量（metric 2）尚无标定。窗口3 Silver/Gold 锚点严禁进入决策层。


## 状态更新（2026-10-28 晚，执行侧核验）

- **F2 已在权威实现修复并经执行侧快照核验**（z_ops_v2.py fe975a68f5）：
  substitute_evidence 三重门（同案身份 + 锚点覆盖 τ=0.5 + 终端合同不变）
  生效；实测 kangda→main=0.596 通过、kangda→tj=0.191 拒绝；操作者的
  "必要锚点逐项满足"原则已在 FINAL_ALIGNMENT 附录固化。执行侧端口守卫
  已按第七轮裁决路由：上游过权威门的 SUBSTITUTE_EV 候选放行（带来源
  标注），未过门的跨文档重接线（如 ADJUST_DEP）继续拒绝。
- **F1 仍开放**（split_verify 仍用 role='retrieval'，不在 ROLE_CLASS）：
  对当前核心实验为哑缺陷（真实规划图无过载核验节点），保留在窗口1
  待修清单。
- FINAL_ALIGNMENT_ADMISSION：窗口1准备阶段结束；剩余两道门=窗口3参考
  对齐 → 操作者 140 次数字授权。执行侧六条件准入表同步更新。
