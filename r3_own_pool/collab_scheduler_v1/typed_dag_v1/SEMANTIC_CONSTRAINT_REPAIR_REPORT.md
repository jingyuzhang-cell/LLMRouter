# 第三阶段专项修复：引用、环与修复反馈（零调用）

完成合同装配前语义依赖预检与结构化修复反馈。原136项回归全部保留，新增24项，**160/160 PASS**（4.163秒）。真实模型请求0、真实Token0；GPU未启动，核查显存0MiB。四个历史候选原件未改；冻结实验、固定48配置、评分协议未改；没有Git提交/推送。

## 1. 真实失败根因及证据

原始输入为 `stage3_fresh_acceptance_real_01/*_CANDIDATE.json`。每份JSON与同目录HTTP_OUTPUTS原始模型响应逐对象核对一致，SHA、旧错误、新错误和拦截位置均记录在 `semantic_constraint_replay/REPLAY_EVIDENCE.json`。

### 发票首次候选

节点数组第1与第5项重复定义 `fixed_discount_node`，一个extraction、一个transformation。旧normalize_plan收集ref时立即抛AMBIGUOUS_SEMANTIC_REFERENCE，未继续检查其他节点。它不是程序ID冲突，而是LLM生成了重复的局部语义handle；不能靠最终ID哈希修正。

第1项依赖不存在的discount_node；最终输出answer_node未定义；invoice_total_node依赖自身；第5项fixed_discount_node也引用自身（同时具有歧义）。旧Schema仅要求字符串字段与类型枚举，并不表达跨节点ref唯一/存在性、排除自身引用或无环，因此解码输出符合字段形状仍可能非法。这些约束原来推迟到装配检查，并因首错退出而没有全面反馈。

### 发票修复候选

第1项把discount_node换成fixed_discount_node，但没有解决重复定义，且引用自身/歧义节点；answer_node仍缺失、invoice_total_node仍自依赖。旧guard_semantic_repair不能建立歧义旧节点的一一对应，返回REPAIR_AMBIGUOUS_IDENTITY。保守拒绝有其安全理由，但旧反馈并未列出全部需要修改的结构问题。

### 加权均价首次及修复候选

完整环路径（按“消费者→所需生产者”方向）：

- n1→n3→n1；
- n2→n3→n2。

n3为extraction却依赖n1/n2；n1、n2均为transformation且依赖n3。其余计算节点没有合法expression生产者，多个transformation缺facts或expression输入。只有修掉环也不能合法执行。

修复候选与首次候选内容完全相同，错误集合签名相同。不是Token不足或截断：四个历史响应均finish_reason=stop、HTTP成功；历史4请求/5455Token保持冻结，本轮不把它们登记为新增消耗。

### 旧修复Prompt实际收到什么

直接读取历史HTTP_INPUTS，发票只有 `error_code=AMBIGUOUS_SEMANTIC_REFERENCE, field=ref, actual_contract=fixed_discount_node`；加权均价只有 `error_code=CYCLE, field=dependencies, actual_contract=cycle`。二者node_id与expected_contract均null，没有cycle_path、related_refs、missing_dependency或完整错误集合。不能据当前已改源码推断旧运行获得了这些新反馈。

## 2. 修改文件与函数

- **新增semantic_validation.py**：issue、SemanticErrors、inspect_semantic_plan、cycle_witnesses、validate_semantic_plan、error_signature、compare_errors。
- **修改semantic_ids.py**：normalize_plan增加引用/环预检；assemble_semantic强制完整依赖及必要生产者预检后才调用旧assemble；semantic_schema收紧依赖数量；guard_semantic_repair增加有明确描述的子任务保护。
- **修改generation.py**：InitialDAGGenerator默认语义模式最多一次修复，拒绝传入2；generate收集全部结构错误、生成修复比较事件，并把具体错误及环路径加入修复Prompt；对其他错误也补齐反馈字段。旧graph_compat诊断仍保持最多两次的历史兼容能力，不用于本次新任务真实入口。
- **修改fresh_acceptance.py**：代码哈希绑定新增semantic_validation.py；未执行入口。
- **新增test_semantic_validation.py**及本报告、独立重放JSON。原136项测试文件和历史原件均未修改。

## 3. 新验证与修复行为

生产入口：generate→inspect_semantic_plan→validate_semantic_plan→guard_semantic_repair→assemble_semantic（再次强制预检）→旧assembly.assemble→Graph验证→TypedExecutor→原MeteredExecutor。

检查包括重复定义、悬空/歧义引用、自环、多节点环、重复依赖、非法最终引用、注册类型及必需生产者。必要生产者检查根据注册表输入输出类型确认至少有一个可能合同，**不在预检中选择合同或自动绑定端口**。具体绑定、歧义合同、上下文可用性、全部边消费和最终可达性继续由现有装配器/验证器严格检查。

DFS遍历和邻居顺序固定，环路径按最小字典序旋转，因此可复现。返回确定性环见证，不枚举所有简单环。诊断DFS忽略不唯一的边仅为避免猜测路径；这些候选仍因引用错误整体拒绝，没有将删边后的图送执行。

反馈为完整errors数组，每项包含：

```json
{
  "error_code": "CYCLE",
  "node_ref": "n1",
  "related_refs": ["n1", "n3"],
  "cycle_path": ["n1", "n3", "n1"],
  "missing_dependency": null,
  "expected_constraint": "acyclic dependency graph",
  "actual_value": ["n1", "n3", "n1"]
}
```

保留旧error_code/node_id/expected_contract/actual_contract接口，不破坏原测试。新增error_signature不依赖JSON排版、节点数组顺序或显示名称；修复事件分列removed_errors和introduced_errors。完全相同集合记NO_PROGRESS；错误集合改变只记ERROR_SET_CHANGED，**不等于合法或修复成功**。修复后仍要完整验证。语义覆盖和事实正确性不能从错误签名推断。

已有唯一节点和有效边的保留检查继续生效；有实际描述的子任务不能静默替换（保守精确文本检查，也会拒绝某些合法改写）。原subtask仅为类型名或合同ID时，不把这种占位标签视为已明确的任务语义。旧ref本身重复时仍保守拒绝修复对应关系，不能凭名称相似度猜测。

Schema新增：extraction.dependencies最多0；其他类型至少1，transformation至少2；依赖数量受节点上限约束。ref唯一、依赖存在性、无环和接口兼容仍由程序检查，**不声称JSON Schema已表达全部图约束**。服务环境r3_venv离线xgrammar编译通过，无模型加载。

纯身份normalize_plan诊断接口不认定合同合法；完整必要生产者检查不可绕过assemble_semantic。内部_identity_only仅供修复保护取得旧身份，不是执行入口。

## 4. 四份候选重放

| 候选 | 原首错 | 新识别 | 合同前拦截 | 合法确定性归一化 | 需重新规划 |
|---|---|---|---|---|---|
| 发票首次 | AMBIGUOUS_SEMANTIC_REFERENCE | 重复ref、悬空依赖、歧义依赖、两个自环、缺失最终引用及生产者 | 是 | 否 | 是 |
| 发票修复 | REPAIR_AMBIGUOUS_IDENTITY | 重复ref、歧义依赖、两个自环、缺失最终引用及生产者 | 是 | 否 | 是 |
| 均价首次 | CYCLE（无路径） | 两条完整环见证＋五个节点的生产者/非法依赖问题 | 是 | 否 | 是 |
| 均价修复 | CYCLE（无路径） | 同上，签名完全相同→NO_PROGRESS | 是 | 否 | 是 |

发票修复去掉了一处悬空discount_node，因此错误集合9→8，**不是完全无进展，但核心错误仍在**；不把集合缩小当作修复成功。均价修复7→7且内容完全相同。没有对任一历史候选补边、断环、重命名猜测或执行。批次的单独ID映射可计算，不表示可以合法归一化成执行图。

## 5. 测试与边界

原136项＋新增24项=160/160 PASS。新增覆盖全部指定场景：重复ref、悬空依赖与最终输出、自依赖、二/三节点环、重复依赖、必要生产者缺失、前向引用、多根、重名不同ref、3/5节点合法图、合同装配前拦截、排版/名称变化不算进展、新错误继续拒绝、七项反馈字段、四真实候选重放、同错误修复事件、合法图原计量链完整执行、最多一次修复、子任务保护和Schema约束。

合法五节点Stub闭环仍调用原执行/计量路径，6次模拟派发，最终5。这只是Mock工程证据，不能替代真实调用。测试共4.163秒；GPU0MiB；本轮真实请求0、真实Token0。

```bash
cd /root/r3_own_pool
python3 -m unittest collab_scheduler_v1.typed_dag_v1.test_typed_dag collab_scheduler_v1.typed_dag_v1.test_generation collab_scheduler_v1.typed_dag_v1.test_assembly collab_scheduler_v1.typed_dag_v1.test_fact_semantics collab_scheduler_v1.typed_dag_v1.test_source_selection collab_scheduler_v1.typed_dag_v1.test_semantic_ids collab_scheduler_v1.typed_dag_v1.test_fresh_acceptance collab_scheduler_v1.typed_dag_v1.test_semantic_validation collab_scheduler_v1.joint_search_v1.test_evaluator collab_scheduler_v1.joint_search_v1.test_runtime
```

## 6. 未解决及是否可再真实验收

具备新版本的**有限真实诊断工程准备条件**：前置检查、可复现错误、有限修复、无进展登记、Mock闭环和回归均通过。**仍未达到第三阶段真实稳定性验收**，也没有证据表明LLM会修正新反馈中的全部错误。

剩余风险：重复旧ref的安全一一对应仍无法确立；类型级生产者存在不保证事实相关或任务语义覆盖；子任务精确保留较保守；长errors数组会增加修复输入Token，下一协议须重新测算6k生成上限和8192上下文限制，不可沿用旧Prompt成本假设。

下一次真实调用需要重新批准和冻结当前代码/任务/预算。历史两题已成为调试任务，重跑只能登记为开发诊断，不能重新称为全新独立任务验收。新的首次验收应使用另行冻结且未调试的新题。本轮已停止，不调用模型，不进入结构优化。
