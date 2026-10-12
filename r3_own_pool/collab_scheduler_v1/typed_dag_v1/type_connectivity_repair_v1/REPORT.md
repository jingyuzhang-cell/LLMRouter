# Stage 3 类型合同与最终输出连通性专项修复

本轮仅零调用代码修复、保存响应重放和 Stub 测试。245/245 测试通过（原226项、新增19项）。未启动模型、未发起真实请求、未提交或推送 Git。真实生成合法率仍沿用历史0/2，不能由本轮测试改写。

## 真实证据与根因

输入原件为 `stage3_heterogeneous_real_01/REPORT.md`、`FINAL_EVIDENCE.json`、`RESPONSE_01..04_RAW.txt` 和对应 PARSED.json。原件未修改；逐文件 SHA256 见 REPLAY_EVIDENCE.json。

太阳能初次候选 RESPONSE_01：

| 消费节点 | 端口 | 生产者 | 实际输出 | 预期输入 |
|---|---|---|---|---|
| nodes.2.ref | facts | nodes.1.ref（reasoning） | expression | facts |
| nodes.3.ref | facts | nodes.2.ref（reasoning） | expression | facts |
| nodes.4.ref | value | nodes.3.ref（reasoning） | expression | number |

`nodes.0.ref` 等是候选中实际定义的字面引用，不是悬空引用。节点名字含 calculate 或 subtask 写 transformation 都不能改变 type=reasoning 所选择的 expression.v1 合同。此候选没有真实计算结果生产者。RESPONSE_02_RAW 与 RESPONSE_01_RAW 字节一致，三处错误均重复。旧 producer_plan.compile_producer_plan 已拒绝这些类型，但反馈缺少直接可读的 producer_ref/consumer_ref/offending_port，且失败发生在修复签名比较之前。

行程 RESPONSE_03：n1..n5 全部 type=extraction，input_producers={}，所以五个节点之间没有任何边。n5 虽名为 calculate_average_speed、subtask=transformation，仍只能绑定 facts.v1。最终输出 n4 时，n1/n2/n3/n5 无法进入最终输出。RESPONSE_04 仅把 final_outputs 改为 n5；此时 n1/n2/n3/n4 仍未进入最终输出。两份候选均有五个独立连通分量，无推理/汇聚路径。旧代码在 protocol._validate 的 Dead branch 检查才拒绝，assembly.assemble 包装为 GRAPH_VALIDATION；修复没有收到具体断开的分支。旧 repair_comparison 仅比较装配前错误列表，两个列表皆空，未覆盖真正的图错误。

这两题均未完成语义审查，也没有节点真实执行。不能据此认定事实内容正确或错误，也不能将源选择覆盖缺口当作本轮模型实际执行错误。

## 实际修改

1. `producer_plan.py:12`：OUTPUT_KINDS、ROLE_KINDS，明确原始事实、计算表达式、计算结果、验证结果的语义类别；数值是 number 值域，并非自动表达式求值规则。保持既有 Graph 和合同 wire types。
2. `producer_plan.py:18`：producer_type_issue；compile_producer_plan 同时检查精确 wire type 和已注册语义类别，返回生产者、消费节点、端口、实际与预期类型。没有新增转换器，未注册类型不隐式转换。
3. `producer_plan.py:77`：producer_schema 增加类型说明及 uniqueItems；保留 input_producers 单一依赖来源、前向引用、可变节点数和拓扑。
4. `semantic_validation.py:54`：connectivity_errors，在合同装配前沿最终节点反向追踪生产者，返回 final_output_ref、unreachable_required_nodes、missing_consumer_or_aggregation、disconnected_components、declared_dependencies。所有声明节点沿用既有协议的“必须贡献于至少一个最终输出”要求。多最终输出采用祖先并集，无须每个节点通向每个输出。
5. `semantic_validation.py:99`：inspect_semantic_plan 在引用、环和最终引用合法后检查连通性。协议级完整 validate 保留作为第二层守卫。未自动删除节点、添加边或更改最终输出。
6. `semantic_validation.py:17/183`：error_signature/compare_errors；连通错误按连通分量及精确依赖签名比较，单纯移动 final_output 不计为连线修复；依赖发生实际变化会产生不同签名。NO_PROGRESS 是结构错误比较，不保证或否定语义进展。
7. `generation.py:135`：统一在拒绝路径比较完整反馈错误集，覆盖 compile 类型错误和装配/审查错误；避免仅比较空的预检列表。一次修复上限不变。规划及修复 Prompt 明确类型不是子任务名称，要求所有节点贡献于最终输出，不代替程序校验。
8. 新增 `test_type_connectivity.py`、本目录 replay.py、报告、重放 JSON 和测试日志。

## 类型规则与血统

| 生产者合同 | wire 输出 | 语义类别 | 允许的消费端口 |
|---|---|---|---|
| facts.v1 | facts | source_fact | facts |
| expression.v1 | expression | calculation_expression | expression |
| calculate.v1 | number | calculated_result | value |
| verify_expression.v1 / verify_value.v1 | number | verification_result | value |

number 是数值数据类型，不能仅凭数值内容推断来源。原始事实的数值仍封装在 facts 内。表达式转为计算结果只通过既有 calculate.v1 或 verify_expression.v1 执行路径：execution.expression_binding、事实 ID/单位/引用检查和 value_lineage 保留。没有字段相似度转换、派生结果到原始事实转换、未知数字到有血统结果转换。类型合法不等于原文支撑；现有执行层事实溯源检查未绕过。

## 历史重放

| 原件 | 新版本结果 | 装配前拦截 | 可确定性修复成合法图 |
|---|---|---|---|
| RESPONSE_01 | 3个 PRODUCER_TYPE_MISMATCH，完整端口反馈 | 是 | 否 |
| RESPONSE_02 | 同上，NO_PROGRESS | 是 | 否 |
| RESPONSE_03 | FINAL_OUTPUT_CONNECTIVITY：5分量、4不可达节点 | 是 | 否 |
| RESPONSE_04 | 同上，仅移动final，NO_PROGRESS | 是 | 否 |

四份仍需模型重新规划；程序没有伪造成功。派生依赖集合是明确声明关系的确定性表示，不是未知依赖补全。

## 零调用测试

```bash
python3 -m unittest discover -s collab_scheduler_v1/typed_dag_v1 -t .
python3 -m unittest collab_scheduler_v1.joint_search_v1.test_evaluator collab_scheduler_v1.joint_search_v1.test_runtime
python3 -m collab_scheduler_v1.typed_dag_v1.type_connectivity_repair_v1.replay
```

typed 测试227/227；原固定 evaluator/runtime 18/18；合计245/245。专项新增19项覆盖表达式/数值/事实混用、派生/验证结果不能作为原始事实、多阶段正确类型、孤立抽取、必要分支、缺失最终节点、三/五节点、多根与前向引用、多最终输出祖先并集、四候选重放、重复修复、新错误、完整修复反馈和合法执行血统。

Stub 合法五节点完整执行得到5，reference_bindings 与 value_lineage 非空、data_errors={}，6次 Stub dispatch 由原 MeteredExecutor 计量；这不是真实模型执行证据。测试过程曾发现测试把排序后最后一个节点当作验证节点，已修正测试按 node_type 查找；没有为测试改图或放松校验。

## 合法图误拒绝与协议判断

现有及新增合法三/五节点、多根、前向引用、不同顺序和多最终输出样例均通过，没有观察到新增误拒绝。这不保证任意合法任务图均无误拒绝。

无需新增不兼容规划结构；现有 input_producers 足以精确表达这些已注册合同。已补 Schema/Prompt 的语义说明，程序仍不能凭名称认定计算/聚合语义。仅做事实输出的任务不强制加推理节点；数值任务的完整语义覆盖仍需现有审查，不能用本次连通性检查替代。所有声明节点必须有用途是原协议限制；将来若允许可选诊断节点，需要独立协议设计，不能偷偷删节点。

修复保留子任务和已声明有效边的现有 guard 仍较保守；本轮不放松，可能拒绝涉及重写必要子任务的修复。类型与连通性检查保证拒绝已知错误，不保证模型下一轮能生成正确计划。

## 下一次真实诊断条件

零调用准备完成，可提交新的独立资源信封与冻结哈希供批准；尚未获得下一轮真实调用授权。既有批准包的源码哈希已因本次授权修复变化，不能直接复用旧包启动真实实验。任务是否继续使用历史题必须在新协议中明确，重测历史题不得称为全新任务泛化验收。

下一次应关注模型是否按类型合同产生有效汇聚，而不是增加结构搜索。真实异构节点执行、答案正确性、合法率稳定性仍未验证。完成后停止，等待下一步授权。
