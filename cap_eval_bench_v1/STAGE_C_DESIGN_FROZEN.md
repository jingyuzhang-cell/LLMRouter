# STAGE_C_DESIGN_FROZEN — 动态联合 (Z,R,π) 层设计冻结（窗口1；不运行）

## 1. 同异常状态比较（严格配对）
- 异常注入协议：类型 ∈ {contract_parse_failure, timeout, budget_stop}；绑定 (task, node, attempt)；
  种子固定（20261028 系）；注入率与绑定集合在本文件冻结后不得按结果调整；
- 每个动态臂在同一初始 DAG 状态快照（同一节点输出、同一检索日志位置）上启动；
- 窗口1必须在**同一状态快照**上输出全部候选（Static/R-only/π-only/Joint(R,π)/Joint(Z,R,π)）
  的决策记录（decision_record.schema.json），供窗口3逐臂配对评分；禁止逐臂重放不同状态。

## 2. 合法动作空间
- R（恢复）：failed 节点重路由（≤2 attempts）／合法替代节点／按 F7 记录性放弃；完成输出受保护；
  失效闭包按依赖图精确计算；
- Z（结构）：identity / add / remove / rewire / split——每个变更必须通过语义守卫（复用类型化
  验证器）并记录结构版本；禁止无数据流的新边；
- π（分配）：对剩余待执行节点的模型映射 ∈ {GLM-5.3, GLM-5.3-Flash}；
- NONE/DECLINE：仅当终端合同允许或如实记录失败时合法；决策记录须含触发信号与理由。

## 3. 度量与归因
- 收益定义：相对 dyn_Static 的 Q 恢复增益 − 恢复调用成本（token 记账）；K.deadline/verdict 单列；
- 失败诚实：信封耗尽、规划合法失败原样保留（承 Phase-1 T-P1 处置）；
- 运行规模（gated on Stage-A 锚点 + 窗口1算法交付）：2 锚点 × 5 臂 × k=2，预算另册申请。
