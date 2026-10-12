# 第三阶段修复：合法生成已取得，完整真实执行仍未通过

## 1. 失败归因（原件只读）

逐响应证据：`STAGE3_REPAIR_FAILURE_AUDIT.json`。共10条正常生成/修复响应和1个HTTP中止；每条含原答案、SHA、TRAJECTORY行号、finish_reason、节点与错误分类。

| 原轮次/任务 | 首次候选及修复后仍存在的问题 | 分类 |
|---|---|---|
| 01 / sum | 根被包在graph_format；类型填成facts.v1等合同ID；缺question等必需输入；value/answer/success_contract.v1等未注册合同。修复响应还带JSON外说明文本。 | 根格式、合同、类型、输入 |
| 01 / change | graph_format包装；类型与合同不匹配；context/output、facts/output、expression/output不是注册端口；必需输入缺失。修复响应与首次逐字相同。 | 格式、类型、端口 |
| 02 / sum | extraction缺question；节点输入没node_id；不存在value.v1；绑定来源不在依赖中。修复响应与首次逐字相同。 | 输入、合同、依赖引用 |
| 02 / change | extraction缺question；field写成节点ID.端口而非端口；node_id缺失；计算节点缺facts；验证合同所需输入与实际输入不符。 | 输入、端口、来源、依赖 |
| 04 / sum | REAL_CANDIDATE_INVALID.json的n2–n5有节点绑定但dependencies为空；field写成n1.output.facts等路径；n4使用verify_expression.v1却给value而缺expression。修复响应与首次逐字相同。 | 依赖、端口、合同接口 |

10条响应finish_reason全部为stop，没有生成截断证据。结构验证先失败，均未到语义覆盖审查；不能归因为语义审查拒绝。

HTTP500是API/传输层中止：03的GENERATION_EVENTS只记录ABORTED，没有候选图。旧runner没有保留HTTP错误正文，不能断言确切服务端原因（例如某个Schema关键字不支持）。它不进入DAG合法率分母；原8192 Token未确认预留仍保留，与本轮费用分开。

具体实现位置：
- `protocol.py:9` 合同注册表；`protocol.py:95`起严格检查合同/类型；`protocol.py:105`起检查端口及来源/依赖。
- `generation_schema.py:2`的旧graph_schema只有通用枚举和字符串，没有依合同条件约束type、输入端口集合、来源端口与依赖一致性。它也把Node默认字段要求为必填；此处与构造器默认值的严格度不同，不是上述失败的唯一原因。
- 旧图生成同时让LLM决定任务规划与低层接口。注册表本身与验证器一致；Schema约束弱于验证器，提示不能代替检查。
- 旧修复只剥围栏/去重依赖，错误通常是第一个通用失败。5个修复中3个与首次响应逐字相同；多处接口问题没有变成完整可定位的装配反馈，不能靠重复调用解决。

## 2. 实际修复

新增`assembly.py`：LLM只产出不可执行的语义计划（任意ID、类型建议、实际子任务、依赖、抽取来源、最终输出节点）。程序按现有CONTRACTS精确匹配：question来自公共任务，抽取context来自模型明确选择的公开来源，事实/表达式/数值按声明依赖的输出类型绑定；零匹配或多匹配返回ConstraintError，绝不猜合同，不自动增加/删除语义边。

执行对象仍为现有Graph。每条依赖必须被合同输入消费；完整现有validate再次检查所有结构约束。`generation.py`默认semantic模式；graph_compat仅留作原57项路径回归，不是新的默认。计划不是第二套执行图。

结构化反馈包含error_code/node_id/field/expected_contract/actual_contract/repairable。错误例：CONTRACT_UNBINDABLE，transformation_1，dependencies，期望calculate.v1的facts+expression，但实际只有expression。模型必须修复计划并重新全量装配/验证。最多两轮配置修复，本次真实配置只允许一轮。

`guard_repair`保留已有节点和合法边；只允许更换悬空引用，或经程序证明处于环中的边作为破环修复。守卫本身不编辑图。现有真实修复原件在最终守卫上零调用重放全通过，见STAGE3_REPAIR_PRESERVATION_REPLAY.json。

保留模型覆盖审查，加入选择源是否有数字的词法提示（非语义证明）。移除固定数值输出示例；`execution.py`只向推理节点提供可用事实变量，输出引用不存在的索引时提前失败并阻断后继。未改评分函数、合同注册表、原固定48入口或冻结实验。

## 3. 零调用验证

73/73 PASS：原57项 + 新16项。新增涵盖保存真实非法候选不猜修复、3/4节点及多抽取根可变图、合同唯一匹配、歧义/不兼容拒绝、非法引用/环、类型错误与依赖错误的闭环修复、合法回退、保留节点/边以及表达式越界阻断。

旧共享Stub在单事实三节点图也固定返回v0+v1，加入索引检查后暴露夹具缺陷。仅把Stub改为按事实数引用存在的变量，原测试断言未降低；越界专门负对照保留。旧生成测试显式走graph_compat，新的测试走默认semantic。

证据：STAGE3_REPAIR_TEST_RESULT.json，含完整日志、73项结果及最终源码SHA。

```bash
cd /root/r3_own_pool
python3 -m unittest collab_scheduler_v1.typed_dag_v1.test_typed_dag collab_scheduler_v1.typed_dag_v1.test_generation collab_scheduler_v1.typed_dag_v1.test_assembly collab_scheduler_v1.joint_search_v1.test_evaluator collab_scheduler_v1.joint_search_v1.test_runtime -v
```

## 4. 真实结果与硬停止

两个合成任务，总收入13+9和现金增加17−6；任务标注只在执行后用原score_v21评价，不给生成器或执行器。重复开发运行不是新的独立任务。模型为Qwen2.5-7B-Instruct，temperature=0，全程单GPU锁。

| 诊断版本 | 生成任务次数 | 首次完整验证合法 | 修复后累计合法 | 固定回退 | 非回退执行完成 |
|---|---:|---:|---:|---:|---:|
| repair_real_01 | 2 | 0/2 (0%) | 1/2 (50%) | 1/2 (50%) | 0/1 |
| repair_real_02 | 1（差值题重复） | 0/1 (0%) | 1/1 (100%) | 0/1 (0%) | 0/1 |

这是逐版本开发诊断合法率，不是总体估计或独立确认性样本。延续执行没有新生成候选，不能计为第三个生成成功或增加合法率分母。

合法非回退图的实际合同装配：
```
extraction_1 [facts.v1] ──→ reasoning_1 [expression.v1]
       │                            │
       └──────────→ transformation_1 [calculate.v1]
                                  │
                                  └→ verification_1 [verify_value.v1]
```
4节点、深度4；计算节点依赖extraction_1+reasoning_1。全部节点映射medium；计算节点实际走算术工具、零LLM请求。图版本2、parent_graph、原始计划、合同绑定和模型审查均在导出图/生成账本；两张图经最终代码重新装配，节点、端口和边与记录一致。

- repair_real_01的差值图合法，但选择了无数值ctx_text。抽取返回12，推理引用v0+v1；只有一个事实，工具越界。同期固定回退收入图COMPLETE却给20而非22，执行完成与质量失败分列。
- repair_real_02选择ctx_table并合法装配，但抽取把差值11合成为一个事实，推理仍写v1−v0。接口结构合法不能保证节点事实正确或变量一致；执行未完成。
- execution_continuation保持同一生成图，不重生成、不改拓扑，显式导入完整身份真实缓存来源。变量提示在当时版本加入全部节点，改变抽取prompt SHA，使旧抽取也不能复用；2次新请求返回一个合成事实11及表达式v0+0−11。推理/计算走完，验证节点派发时StopRun(request budget)。当前代码已把变量提示限定推理节点，最终零调用回归通过；没有再次真实运行，不能称该改动已真实验收。

当前所有非回退真实执行仍INCOMPLETE/ABORTED；没有完成的非回退图，不能满足本轮第二项验收。模型覆盖审查在无操作数源时曾给PASS，证明它只能是启发式。合成事实11也没有原数字支撑，不能用schema合法宣称事实正确。

## 5. 实际费用（所有失败保留）

| 单元 | 请求尝试 | 实际Token | 生成/修复/审查Token | 执行Token | 记录总墙钟（含加载） |
|---|---:|---:|---:|---:|---:|
| repair_real_01 | 11 | 6774 | 5653 | 1121 | 87.05秒，加载37.10秒 |
| repair_real_02 | 5 | 3970 | 3560 | 410 | 69.99秒，加载34.09秒 |
| continuation | 2 | 426 | 0 | 426 | 中止没有精确总墙钟字段，不编造 |
| 合计 | 18 | 11170 | 9213 | 1957 | 分单元报告 |

保留阶段GENERATION_EVENTS的物理请求、Token、服务和墙钟；执行账本DISPATCH/TRAJECTORY与节点TYPED_EVENTS保留最终输出前的失败/阻断。首两单元生成阶段服务13.22/10.41/11.74秒（分别为首单元两个任务及第二单元）；节点执行/工具耗时在结果中。

总请求硬顶18已耗尽，实际Token低于57344预算，账本无pending预留。continuation只使用已结算后剩余两次总请求额度，不重置历史消耗。GPU已释放；不再真实调用。旧第三阶段27次尝试和8192未确认预留另存原件，不并入本轮费用。

真实命令留在对应PROTOCOL与脚本；不提供下一轮自动启动。STAGE3_REPAIR_EVIDENCE.json整合费用、两版本结果及最终代码的合法图重放。单个TRACE中的cache alias是复用，不计新请求。

## 6. 验收及剩余风险

通过：合同装配与结构化反馈、原测试回归、可变拓扑测试、至少一个真实非回退合法图、完整生成/修复/失败计量、预算停止。
未通过：非回退图完成真实执行；首次无需修复的合法生成；语义覆盖/节点事实正确性。不能宣称第三阶段完整闭环已验收或进入结构优化。

实际修改：assembly.py、generation.py、execution.py、generation_schema.py、test_generation.py、test_typed_dag.py、test_assembly.py；新增失败审计及三份隔离真实诊断入口，README更新。旧报告和原结果未覆盖；无Git提交/推送。

下一项仅应审查抽取是否保留原始操作数、推理是否遵守已给事实，以及覆盖审查为何误判。尤其LLM把subtask写为合同标签而非任务描述，这说明语义规划仍有质量缺口。需要明确改进方案与下一验证信封后再确认；本轮不继续加调用、不做结构搜索或Pareto优化。
