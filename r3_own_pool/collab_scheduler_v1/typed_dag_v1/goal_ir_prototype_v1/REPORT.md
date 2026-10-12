# 可选目标驱动语义 IR 原型

本轮真实请求为0。270/270零调用测试通过：原245项保留，新增25项。4个人工计划 Stub 对照完整执行成功，不是 LLM 生成成功率，不证明B优于A。默认生成仍为 planning_mode='semantic'；B须显式选择 planning_mode='goal_ir'。未改变冻结任务、gold、固定48配置或评分协议；未提交/推送 Git。

## 1. 架构审计与技术差异

现有 generation.InitialDAGGenerator.generate 的 semantic 分支以 producer_schema 提示 LLM 选择 input_producers；producer_plan.compile_producer_plan 将每个 role 的明确节点引用推导为 dependencies；semantic_ids.assemble_semantic 通过程序分配最终 ID，再经 assembly.assemble 绑定注册合同。该设计避免多套依赖字段互相矛盾，但 LLM 仍需同时完成任务分解、操作类型、接口类别及生产者节点引用。

太阳能历史 RESPONSE_01/02 中三个 reasoning 节点被描述为抽取或计算，属于语义操作与执行类型选择错位；nodes.2/3 的 facts 引用 expression 生产者、nodes.4 的 value 引用 expression，属于数据生产者和类型合同错误。表达式不是已计算数值，必须由正确的计算/验证操作产生数值。引用字符串本身都有定义，不能误报悬空。题中费用来自另一输入域，计划只选表输入的覆盖风险需要语义重新规划，不能仅由类型检查确定修复。一次修复响应字节相同。

行程历史 RESPONSE_03/04 五节点全部 extraction、空 input_producers：将计算意图写进名称没有选择计算操作；最终目标缺少完整依赖、没有实际汇聚。改 final_output 从 n4 到 n5 不会生成计算过程。程序只能指出缺陷，不能知道这些错误节点应如何重写或补边。

| 维度 | A input_producers | B goal-symbol-ir.v1 |
|---|---|---|
| LLM声明 | 节点类型、子任务、消费role到节点ref | 最终目标、语义操作、所需/产出的typed symbols和单位 |
| 生产者解析 | LLM直接给精确节点ref | 程序按精确symbol建立唯一生产者表 |
| 边/端口 | role选择直接派生 | 符号关系先映射为现有producer plan再装配 |
| 最终ID | 程序负责 | 同一程序负责 |
| 可自动解决 | 精确引用绑定、合同装配、验证 | 同左，加唯一符号表与声明单位匹配 |
| 不能解决 | 缺数据、错误算式、错误来源、遗漏目标 | 同左，不能凭symbol名称猜来源或意义 |

B减少“数据由哪一个节点产出”的重复表达，但没有免除语义生产者规划：模型仍必须声明正确输出符号及匹配输入。它可能把节点ref错误换成symbol错误，需真实对照验证。

## 2. Schema 与中间表示

完整Schema见 SCHEMA.json；运行时编译器也独立检查，JSON符合Schema不等于可执行。

```json
{
  "final_goal": {
    "description": "求公开输入的指定结果",
    "outputs": [{"name":"answer","symbol":"checked_result","type":"verified_value","unit":"unitless"}]
  },
  "steps": [
    {"ref":"read","operation":"extract","description":"抽取原文操作数",
     "context_field":"ctx_table","inputs":[],
     "outputs":[{"symbol":"source_data","type":"source_facts","unit":"unitless"}]}
  ]
}
```

以上是字段说明片段，不是完整合法图：checked_result 尚无生产者，会被拒绝。完整合法三/五节点计划在 semantic_3/5、goal_ir_3/5 下 INPUT_PLAN.json，全部使用独立通用Stub上下文2和3，未引用冻结太阳能/行程任务或答案。

操作映射固定为已有合同能力，不固定拓扑：

| operation | 输入符号类型 | 输出类型 | 现有执行能力 |
|---|---|---|---|
| extract | 无；显式选择公开context_field | source_facts | facts.v1 |
| form_expression | source_facts（一或多根） | expression | expression.v1 |
| calculate | source_facts + 一个expression | calculated_value | calculate.v1 |
| verify_value | 一个calculated_value或verified_value | verified_value | verify_value.v1 |
| verify_expression | source_facts + 一个expression | verified_value | verify_expression.v1 |

每步输出一个完整合同对象；source_facts 是事实包，不是单独操作数、不承诺一个符号对应一个数值。事实ID、原文证据和具体算式引用仍由既有执行协议处理。units通过每个symbol的unit表达，避免重复根级units声明。混合单位事实包可显式标为mixed/unspecified；这些标签不是量纲正确性证明。链路单位必须精确匹配，无别名或自动换算；calculate/verification 的结果单位须与其expression/value单位匹配。模型声明算式的结果单位是否正确仍须语义审查及执行层单位/来源检查。未实现通用量纲推导或转换节点。

## 3. 调用链及修改文件

```text
InitialDAGGenerator(planning_mode='goal_ir')
  -> 原MeteredExecutor.call：plan_goal_ir / 至多一次repair_goal_ir
  -> goal_ir.compile_goal_ir：symbols、唯一生产者、类型、单位、最终符号
  -> producer_plan.compile_producer_plan：现有role及dependencies
  -> semantic_validation.validate_semantic_plan：环、引用、最终连通性
  -> semantic_ids.assemble_semantic：稳定程序ID
  -> assembly.assemble -> protocol.validate：现有合同及Graph
  -> 原semantic_review（启发式，不保证正确）
  -> 原allocate -> TypedExecutor -> 原账本、事实溯源、value_lineage
```

新增 goal_ir.py：OPERATIONS/ROLES、symbol、compile_goal_ir、guard_goal_repair、goal_ir_schema；新增 test_goal_ir.py、此目录offline_compare.py及报告/证据/Schema/Stub轨迹。

修改 generation.py：可选模式、Prompt/Schema、编译分支、统一错误签名、graph.provenance保存原IR及symbol_table/relations；仍使用原预算、ask、review、修复上限及领域回退，不创建第二个执行器。默认模式和旧Graph兼容模式保留。graph_version、parent_graph、raw_response_sha及原输入hash保留。IR原件在goal_ir provenance，转换计划在raw_planner_plan，分别保存。

符号关系和单位来源保存在goal_ir_compilation；并非执行层已经核验该语义声明。真实事实血统由原TypedExecutor生成，不从IR注释伪造。

## 4. 离线对照和历史重放

OFFLINE_EVIDENCE.json记录两方案各三/五节点的完整Graph、Stub计量、执行血统；子目录保存全部MeteredExecutor账本及GENERATION_PIPELINE、TYPED_EVENTS/RESULTS。

| 方案 | 人工节点数 | Stub执行 | 人工预期结果 | Stub请求数 |
|---|---|---|---|---|
| A | 3 | COMPLETE | 2 | 4 |
| A | 5 | COMPLETE | 5 | 6 |
| B | 3 | COMPLETE | 2 | 4 |
| B | 5 | COMPLETE | 5 | 6 |

这些数值只针对通用Stub“2/3求和”夹具；Token为Stub返回的计量模拟值，不是真实费用或效率证据。5节点支持两根汇聚、计算和验证；3节点支持单根推理计算，另有1节点合法抽取任务及前向引用/重排序测试。四个Stub图均复用异构类型基线（抽取medium、推理large、验证coder；计算工具无LLM调用），不宣称模型真实身份加载或学习最优分配。

历史四份原候选按A真实规则重放仍被拒绝，hash和具体错误写入OFFLINE_EVIDENCE。没有自动将历史JSON转为合法IR。B能够让程序由“某数据symbol由唯一声明步骤产出”代替LLM手写producer ref，但不能凭历史extract_rate/calculation名称改类型、补费用事实或添加算式；这些需要重新规划。

## 5. 测试结果与复现

```bash
python3 -m unittest discover -s collab_scheduler_v1/typed_dag_v1 -t .
python3 -m unittest collab_scheduler_v1.joint_search_v1.test_evaluator collab_scheduler_v1.joint_search_v1.test_runtime
python3 -m collab_scheduler_v1.typed_dag_v1.goal_ir_prototype_v1.offline_compare
```

252项typed + 18项固定基础设施 = 270/270；原245项保留。新增25项包括可变拓扑、多根/前向引用/同序Graph、唯一symbol/ref、缺失/歧义生产者、表达式/原事实/派生数值类型、未知操作输出、单位冲突/禁止隐式转换、最终目标缺失/类型、环、无用分支、缺计算输入、禁止重复依赖字段、保护修复节点和最终目标、Schema、原异构分配、真实计量类的Stub闭环及受限修复。源hash记录在OFFLINE_EVIDENCE。

测试开发期间3项失败来自人工夹具共用输入输出dict，修改输入同时修改了生产者；夹具改为deepcopy后通过，没有放松生产约束。

## 6. 风险与限制

- 原型仅支持注册的五种operation，每步一个合同级输出。不支持任意新工具或多输出合同，不能将未知operation偷偷映射到近似合同。
- 符号唯一、类型匹配和图连通不保证操作数完备、算式正确、单位正确或最终任务质量；原语义审查仍须执行，模型自审也不是证明。
- exact unit很保守；美元/USD不自动等价，复杂量纲/单位转换需要明确新合同和验证。IR注释并未自动成为事实注册表中的单位证据。
- 修复guard保留步骤、输出和已声明已知symbol输入。涉及纠正循环已知symbol依赖的修复可能被保守拒绝；本轮不放松以免删必要边。最多一次修复仍可能回退。
- 新Prompt长度/输入Token及IR审查开销尚无真实测量。现有fresh_acceptance真实入口仍沿原方案；本轮未修改冻结入口预算、任务或哈希。下一轮B真实入口需单独冻结和资源预检，不能复用旧冻结包。
- 模型可能在新符号协议中继续遗漏生产者、选错operation或生成冗余步骤。本轮没有真实合法率、质量或成本优势证据。

## 7. 下一次独立真实对照设计（未授权执行）

先准备独立的新公开任务面板、单独评分文件及源码/Schema/Prompt hash；核查未用于调试。每题A/B配对，同一规划模型、同一公开输入、同一最大5节点、生成/审查/一次修复上限、同一异构类型基线和事实执行协议。A/B分离缓存scope及账本，避免答案复用改变生成物理成本。预先固定运行顺序/交替，模型加载切换单列，服务错误与有效响应合法率分开。

正式预算须按A+B四条任务路径的最坏输入（分别测量两Prompt/Schema）、输出、审查、5节点和一次恢复计算；不能把此前两题24请求/56k信封当作四条路径批准。先在Stub上保证真实入口预算可行，再申请具体请求/Token/墙钟信封。任何一侧停止或回退保留记录，不筛掉失败任务。

主指标：首次结构合法、一次修复后合法、语义审查通过、非回退接受、完整执行及独立最终评分；调用/Token/墙钟按规划、审查、修复、执行、恢复分列。少量任务只报告案例和描述性结果，不能用两道题宣称稳定提高合法率或算法优势。不进行结构搜索或Pareto联合优化。

本轮完成后停止，等待进一步确认。
