# 第三阶段节点身份稳定性修复：零调用验收

本轮完成代码修复与132项零调用回归（原110项+新增22项），停止在用户明确要求的零调用报告阶段。没有启动模型服务、没有真实LLM请求，没有修改历史轨迹、冻结实验、固定48配置或评分协议，没有提交/推送GitHub。**新任务真实端到端验收仍未完成。**

## 历史证据区分

| 结果类别 | 审计结论与证据 |
|---|---|
| 旧图延续执行成功 | `stage3_source_selection_real_05/RESULTS.json` 标记 `REUSED_GENERATED`、`new_generation=false`；旧图来源 `stage3_fact_reference_real_03/RESULTS.json`。执行COMPLETE。 |
| 新图首次生成合法 | 本轮未真实调用，不能认定；历史real_01/04两开发题分别首次合法0/2。 |
| 新图首次生成并完整执行 | 当前无新任务真实证据。本轮仅Stub从输入生成3/5节点图并完成执行。 |
| 最终答案评分正确 | 旧图延续案例最终11、既有score_v21正确；不代表当前生成器在新任务上的完整验收。 |

历史real_05执行是3请求/1348Token；不得当成本轮新生成成本或把跨版本生成与执行时延相加。历史HTTP400独立记录、其8192未知用量预留保持原状。本轮真实合法率、修复后合法率、回退率均为NOT_RUN（分母0），不写为0%或100%。

## 根因和真实失败重放

`stage3_source_selection_real_04/GENERATION_EVENTS.jsonl` 两题均因 `NODE_ID actual_contract="1"` 失败。对应TRAJECTORY保存纯数字ID与引用，修复轮返回相同候选；此前 `assembly.assemble` 要求字母开头，直接使用LLM给出的ID为Graph身份。

重放该TRAJECTORY原始候选后：新适配器能将全部数字引用映射为程序ID，但候选仍被 `CONTRACT_UNBINDABLE` 拒绝。现金候选中节点3 transformation仅依赖抽取节点1，缺expression；节点4 verification仅依赖reasoning，缺facts。**身份问题解除不等于必要数据依赖已正确。** 未补猜测依赖、未删边、未把它登记为合法生成。

## 实际代码改动

- 新增 `semantic_ids.py`：`normalize_plan`、`assemble_semantic`、`guard_semantic_repair`、`semantic_schema`、`resolve_review_references`。
- 修改 `generation.py`：默认语义模式使用新Schema/装配适配器；覆盖审查精确解析已注册语义引用；保留原/标准化计划、映射、标签、合同绑定、graph_version和parent_graph溯源。覆盖审查仍是模型启发式，非语义正确性证明。
- 新增 `test_semantic_ids.py`：22项独立新增测试。
- 修改 `test_source_selection.py` 一处：原 `:read:` 轨迹断言通过生成图的明确映射读取新ID，仍断言账本原始选择响应、5次Stub请求及完整执行；未放松原断言。
- 修改 `real_fact_reference_smoke.py` 一处：代码哈希绑定增加semantic_ids.py；没有执行该诊断入口。
- 新增本报告及 `stage3_identity_zero_call/` 独立Mock图、账本、事件、输出证据。

没有另建Graph或成本账本：语义计划是现有Graph前的适配输入，最终仍调用assembly.assemble→validate→TypedExecutor→MeteredExecutor。

## 身份与依赖规则

LLM提供唯一 `ref`、可重复的显示 `name`、type/subtask/dependencies/context_field；final_outputs使用node_ref。依赖必须精确引用ref，不按自然语言相似度或节点顺序猜测。程序以task_id+ref哈希分配合法node_id，先收集全部引用，再绑定合同，支持前向引用、多根、多节点及不同输入顺序。

相同ref在同任务、修复轮和列表重排时ID稳定；不同任务身份隔离。**不保证模型重命名ref后的ID相同，也不声称图同构规范化。** 原始计划顺序等仍记入provenance，因此重排不保证整个Graph content_hash相同。

- 重复显示ID/name且明确ref不同：保留全部节点并分配唯一ID。
- 重复ref或仅有重复旧id：明确AMBIGUOUS_SEMANTIC_REFERENCE，不自动加序号猜测依赖。旧图无法唯一对应时修复保护返回REPAIR_AMBIGUOUS_IDENTITY，采取保守失败/有限回退。
- 非存在引用：DEPENDENCY_REFERENCE；不删边。
- 单独更改显示标签不能成为隐式依赖匹配依据。
- 输出端口/合同由现有注册表绑定，LLM指定非法port不接受。
- 修复保留已有可识别节点和有效依赖；原guard_repair仅允许明确悬空引用替换或已证明的环边调整，之后完整重新验证。
- 旧id-only计划可作为明确语义引用输入，用于兼容既有Mock与真实失败重放；生成Schema不再请求执行ID。旧Graph兼容诊断模式保留。

## 测试结果

完整回归：132/132 PASS，unittest观测耗时4.141秒。原110项全部通过。

新增覆盖：重复显示ID、重复ref、重复旧ID、不存在引用、前向引用、重排稳定性、多根、三/五节点、重名、错误输出端口、自然语言依赖不可解析、数字旧引用、环、缺必需边、子任务修复ID稳定、禁止删节点/有效边、歧义修复失败、真实失败原文重放、Schema、3/5节点完整Stub闭环、悬空依赖修复闭环、有限失败后合法回退。

实际服务环境 `/root/autodl-tmp/r3_venv/bin/python` 离线xgrammar编译新Schema通过；另一个现有llmrouterbench环境也通过。系统python没有xgrammar，不能据此判Schema错误。没有加载模型；编译不等于真实HTTP生成通过。

```bash
cd /root/r3_own_pool
python3 -m unittest collab_scheduler_v1.typed_dag_v1.test_typed_dag collab_scheduler_v1.typed_dag_v1.test_generation collab_scheduler_v1.typed_dag_v1.test_assembly collab_scheduler_v1.typed_dag_v1.test_fact_semantics collab_scheduler_v1.typed_dag_v1.test_source_selection collab_scheduler_v1.typed_dag_v1.test_semantic_ids collab_scheduler_v1.joint_search_v1.test_evaluator collab_scheduler_v1.joint_search_v1.test_runtime
```

### 独立Stub闭环原件

`stage3_identity_zero_call/mock_3/RESULT.json` 与 `mock_5/RESULT.json` 含实际生成Graph、模型分配/执行结果；相同目录保留GENERATION_EVENTS、TRAJECTORY、DISPATCH、TYPED_EVENTS等。分别生成3/5节点非回退图，执行COMPLETE，Mock值2/5正确；Stub物理派发分别4/6次，每次夹具记30模拟Token。这些费用和答案仅属于Stub，**本轮真实物理调用0、真实Token0；没有真实端到端时延可报告。**

## 未解决与下一步准入

当前修复已满足零调用阶段，尚未验证真实模型能遵守新ref协议、给出充分依赖并正确完成新任务。事实词法支撑、单位和覆盖审查仍有既有语义局限。结构合法、执行完成、任务正确继续分列。

按本轮用户明确要求，**先报告，再获得新明确预算**。不能借用之前剩余请求或运行旧任务/旧保存图补证。下一阶段应先绑定全新任务UID及公开内容哈希、扫描既有生成调试任务排除重复内容，把评价答案存放在仅执行后评分可访问的独立区；冻结请求/Token/墙钟、每次预留、最大修复次数、失败与未知费用停止规则及当前代码哈希。

预算未批准前，新任务真实Graph、执行轨迹、最终评分、生成合法率和真实总开销均暂缺。已有real_fact_reference_smoke固定开发题且支持旧图resume，**不应直接作为新任务验收入口**；下一步应在同一生成器/执行器上做manifest驱动的受限入口，禁止resume，不建立平行系统。不进入结构优化。
