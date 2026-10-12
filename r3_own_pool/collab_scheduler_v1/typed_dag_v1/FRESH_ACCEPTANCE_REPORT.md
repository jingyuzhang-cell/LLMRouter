# 第三阶段：两题新任务真实端到端验收结果

**本次未通过端到端验收。** 两题均真实首次生成并修复一次，但未获得合法非回退图。按照批准的停止条件，两题生成流程完成后停止；没有执行固定回退图，没有借用旧图或旧预算，没有继续消耗剩余额度。

|任务|首次合法|一次修复后合法|程序回退|真实执行|答案/评分|任务流程墙钟|
|---|---|---|---|---|---|---|
|发票净额|否|否|是（未执行）|未开始|无答案、未评分|10.060s|
|双批次加权均价|否|否|是（未执行）|未开始|无答案、未评分|8.123s|

首次合法率0/2；一次修复后合法率0/2；回退率2/2。分母为两道不同的新合成任务，不把修复请求作为独立任务；不推断总体合法率。没有结构合法→真实执行→最终评分的成功轨迹。事实来源与推理引用检查未进入执行阶段，标记NOT_RUN，而非PASS。

## 原始失败与根因

- 发票首次候选5节点，重复ref `fixed_discount_node`；引用不存在的 `discount_node` 和 `answer_node`，多个节点自依赖；候选中缺少能获取quantity/unit price的合法表抽取节点。首次错误AMBIGUOUS_SEMANTIC_REFERENCE。修复仍重复ref，仍有悬空final及自依赖；保守修复保护返回REPAIR_AMBIGUOUS_IDENTITY。它不能确定旧歧义节点的一一对应，不会猜测重命名关系。该限制也意味着当前实现无法自动修复某些歧义身份问题。
- 加权均价首次候选5节点，n3依赖n1/n2，而n1/n2又依赖n3，形成环；修复候选与首次候选相同，仍CYCLE。抽取节点带上游依赖，多个transformation没有facts+expression的合法输入；即使只解除环，仍需合同验证，不能直接执行。
- 四个响应finish_reason均为stop，没有输出截断；HTTP请求全部成功、usage有效。本次失败是候选计划约束及修复问题，不是HTTP500、Token耗尽或程序ID字符格式问题。Schema约束保证字段形状，尚不保证ref唯一、无环、有效依赖或语义覆盖。
- subtask仍多为“extraction/transformation”类型名而非任务具体描述；覆盖审查未到达，不将此视为覆盖通过。

## 请求与Token逐阶段

|任务|首次生成|修复|语义审查|执行|恢复|评分|
|---|---|---|---|---|---|---|
|发票|1请求 / 1208 Token|1请求 / 1527 Token|未到达，0请求|未到达，0请求|未到达，0请求|未评分，0请求|
|加权均价|1请求 / 1206 Token|1请求 / 1514 Token|未到达，0请求|未到达，0请求|未到达，0请求|未评分，0请求|

合计4次新请求尝试、4次有效响应、5455实际Token；charged同为5455，pending为空。发票生成+修复2735、加权均价2720，分别小于6000；两题的执行6000额度均未动用。没有缓存命中/旧图加载。没有用剩余额度重试第二轮。

全运行墙钟（含检查点核验、模型加载、任务、服务清理）86.819s；其中模型加载37.098s。逐任务表是从该题输入开始的生成流程耗时；因执行未开始，不称为成功端到端性能。模型加载只在全局计一次，不重复加到两题。

## 真实原件和可追踪性

- PROTOCOL.json：两题公开输入、输出要求、批准预算、代码/模型来源哈希；没有旧预算或resume参数。
- *_INITIAL_CANDIDATE.json / *_REPAIR_CANDIDATE.json：四张真实候选计划原件；没有合法非回退Graph可以导出。
- HTTP_INPUTS.jsonl / HTTP_OUTPUTS.jsonl：完整真实输入、输出、usage与finish_reason；规划输入无评分答案。
- GENERATION_EVENTS.jsonl / GENERATED_GRAPHS.jsonl：验证错误、修复、固定回退图及其状态；固定图只构建验证，未执行。
- TRAJECTORY.jsonl / WORKFLOW.jsonl / DISPATCH.jsonl：全部调用身份、响应与reserve/response证据。
- REQUEST_PRECHECK.jsonl / PHASE_BUDGET.jsonl：每次Tokenizer预检、阶段预留及实际结算；不能挪用执行额度。
- EVALUATION_ONLY.json：隔离的最终评分标签，仅评分函数可读取；本次未到达评分，因此无任务质量判断。
- RESULTS.json / ACCEPTANCE_EVIDENCE.json：终局快照、各项硬顶核销与失败统计。

## 实现与测试

新增fresh_acceptance.py和test_fresh_acceptance.py，复用InitialDAGGenerator→assemble_semantic→validate→TypedExecutor→MeteredExecutor→Budget。ScopedBudget在原Budget计量上增加每题12请求、generation/execution各6000Token；按真实chat模板输入Token+最大输出Token逐次预留，失败usage未知仍保留。两题最多5节点、1轮修复、1次执行恢复，禁止HTTP重试与历史续图。

新增4项预算测试先4/4通过；实验后原132项+4项全部136/136通过（4.311秒）。源码哈希验收与实验协议一致。GPU当前0MiB、vLLM服务已停止。冻结实验、48配置、原评分未改；没有git提交/推送。

## 下一阶段判断

程序拥有最终执行ID和精确引用绑定已在位，但LLM仍能生成重复语义ref、悬空最终输出及环；错误反馈修复未改善结果。下一轮应先零调用改进规划协议的引用约束、结构错误集合反馈及保守修复身份规则，并重放本轮四个真实候选。不得靠删必要依赖、猜测引用或固定模板获得表面成功。该工作仍属于第三阶段稳定性修复，不进入结构搜索。

本信封执行已结束，剩余额度不自动用于更换Prompt/修改代码后的新诊断。后续真实调用应明确新协议和批准范围。
