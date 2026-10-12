# 第三阶段：事实来源与引用合同补充验收

本轮仅代码修复和零真实模型调用。93/93 测试通过（原73项+新增20项）；真实端到端验收仍未完成。没有启动服务/GPU、提交或推送。既有冻结数据、固定48入口、合同注册表及评分函数未修改。

## 失败审计与调用链

依据原件 STAGE3_REPAIR_REPORT.md、STAGE3_REPAIR_EVIDENCE.json、stage3_repair_real_02_VALID_GENERATED_GRAPH.json 和对应 TRAJECTORY。原件保留，新增重放结果 FACT_REFERENCE_REPLAY.json 记录原始文件SHA及行号。

- 公共任务通过 generation.py:generate_and_execute → TypedExecutor.__init__ → inputs；仅 question/ctx_table/ctx_text 入执行上下文。抽取 context 由 Graph 的 Binding 决定，而不是程序根据 gold 选来源。生成图02明确绑定 ctx_table。
- execution.py:run 以合同、子任务和实际输入构造 prompt；旧 parse 只验证 facts 数值有限及非空证据字符串。原来没有证据匹配、事实注册身份；输入事实按绑定顺序拼接，表达式用 v0/v1 位置引用。
- 图02实际答案 facts=[11]、evidence='Last year cash: 6. This year cash: 17.'；原始操作数为6和17，11不在引用文本中。表达式 v1-v0 对单事实列表越界。现有重放在抽取节点即返回 SOURCE_VALUE_UNSUPPORTED，阻断后继。程序只确认无数值支撑，不能单凭该错误确定模型是计算、编造还是单位转换。
- 延续执行原始事实仍为11，表达式 v0+0-11 算出0。合法位置不等于符合问题语义。旧索引检查只能检查范围；protocol.py:validate 检查节点、端口、类型、依赖及无环性，不检查执行数据。
- 延续执行 ABORT.json 明确 StopRun('request budget')；STAGE3_REPAIR_EVIDENCE 的请求硬顶18，已耗11+5+2=18、Token11170，pending为空。验证派发前请求预算检查停止，不能称验证完成，也不能重新使用该预算。本轮新增真实调用为0。

## 最小协议与正式路径

沿用 Graph、facts数组、MeteredExecutor 和现有 TYPED_EVENTS/TYPED_RESULTS，未建立第二套请求账本。

fact_semantics.py:ground 将通过来源检查的事实扩展为 source_fact，保留 fact_id、value、unit、data_type、证据位置、源字段/全文SHA、producing_nodes。ID按任务/来源/数值位置/值/单位生成，与抽取输出顺序及产生节点名称无关。同源事实重复出现合并产生节点；同ID内容冲突拒绝。派生值另在 value_lineage 中登记 kind=derived_value、表达式、来源事实ID和绑定快照，不登记为原始事实。

fact_semantics.py:bind 将显式位置映射或稳定ID表达式解析为稳定ID AST；不存在的索引/ID拒绝，不猜其他事实。引用快照校验值及来源；排序变化仍引用原事实。lower_expression 只按已验证ID映射到现有 exec_calc 的位置变量，保留原算术工具。

执行前检查必要事实、表达式绑定、事实快照和单位维度；验证值须与已登记计算结果一致。verify_value 输入与血统不一致时在请求前阻断。核对计算一致性不是最终任务评分：表达式选择错误但数值自洽仍可能 COMPLETE，必须另行使用既有评分函数判任务质量。

默认 TypedExecutor 与 semantic 生成路径使用 strict。graph_compat 和历史 test_typed_dag 的假来源夹具显式 legacy，状态和账本均标政策；旧73项是回归/兼容证据，不能替代新增严格测试。严格作用域改为 typed-facts-v1；新prompt/作用域不承诺命中旧执行缓存，不复用旧预算。

## 反馈与恢复

错误区分 FACT_MISSING、SOURCE_MISMATCH、SOURCE_VALUE_UNSUPPORTED、DERIVED_AS_SOURCE、REFERENCE_NOT_FOUND、REFERENCE_CHANGED、UNIT_MISMATCH、EXPRESSION_ILLEGAL、VERIFICATION_INCONSISTENT 等；结构化记录 node_id/detail/cause_certainty。

显式 recover_failed 仅允许失败节点有限重路由（最多配置3次尝试），向新请求传入可观察错误反馈，清理该节点及未完成后继的事实输出、引用绑定和派生血统；既有成功且已消费输出受保护，不回滚费用。缺事实、单位/血统问题阻止盲目局部重试，需上游检查。本轮未实现自动语义故障分类或自动修改图。

## 测试与结果

命令（从 /root/r3_own_pool 执行）：

```bash
python3 -m unittest collab_scheduler_v1.typed_dag_v1.test_typed_dag collab_scheduler_v1.typed_dag_v1.test_generation collab_scheduler_v1.typed_dag_v1.test_assembly collab_scheduler_v1.typed_dag_v1.test_fact_semantics collab_scheduler_v1.joint_search_v1.test_evaluator collab_scheduler_v1.joint_search_v1.test_runtime
```

FACT_REFERENCE_TEST_RESULT.json：93测试、0失败、0错误，包含源码SHA。新增20项包括原始/派生混淆、已保存失败内容、数字子串伪支撑、引用不存在/越界、重排、合并、快照变更、单位冲突/无依据单位声明、重复证据定位、纯常数拒绝、合法算术及血统、完整严格Stub执行、失败恢复映射刷新、验证错误阻断、空事实提前阻断。

严格Stub四节点闭环 COMPLETE、答案11，三次Stub dispatch、90模拟Token；计算节点走原工具，未调用真实模型。失败抽取恢复后 COMPLETE，累计四次Stub dispatch，原失败费用保留。数字均为测试夹具，不能报告为真实模型性能或合法率。原语义生成端到端回归同样通过严格事实路径；本轮未取得新的真实生成图或真实成功率。

实际代码新增 fact_semantics.py/test_fact_semantics.py；修改 execution.py/generation.py/generation_schema.py/test_typed_dag.py。新增本报告、重放JSON与测试JSON。TYPED_EVENTS 保留注册事实/引用/血统/错误；TYPED_RESULTS 保留 semantic_check_s、物理费用、部署Token、服务和墙钟；语义检查及工具适配耗时有部分重叠，不应简单相加为端到端时间，端到端以 observed_execution_wall_s 为准。所有真实调用阶段开销仍以既有生成和派发账本为准，本轮无真实开销估计。

## 仍未解决的边界

1. 精确数值和引用定位仅证明词法支撑，不能证明事实相关性、证据语义或必要事实完整性；源中的错误数字也能通过。合法ID引用错误事实的意图无法由索引检查识别。
2. 单位仅识别相邻 USD/EUR/kg/万元/元/%/$；未知单位标 UNDETERMINED，即使除法抵消也不称单位已验证。同为未知单位的加减允许但未经语义单位认证。未自动做单位转换、跨量纲猜测或百分比缩放。
3. 对同单位数值加无单位常量保守拒绝；需要常量带单位或单位转换的任务须后续明确扩展合同，不能为通过而猜测。当前没有时间/实体标签语义检查。
4. 来源支持数值在全文另一无关位置出现仍可能假通过。证据归属、事实角色、问题所需依赖需独立语义审查；禁止声称事实正确性保证。
5. Stub完整执行不等于真实验收，COMPLETE不等于答案正确。严格约束可能降低真实模型首次通过率，需新预算下实测。

按要求在零调用测试后停止。下一步仅在取得独立的新请求/Token/时间信封后，用已有非回退生成图进行少量真实执行；分别报告图合法、执行完成、评分正确及生成/修复/执行/恢复开销。当前不进入结构优化。
