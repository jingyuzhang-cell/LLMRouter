# 新云池真实恢复观测采集：最小机制试验准备

日期：2026-10-14。**本轮0真实API请求、0GPU加载。当前NO-GO仅针对启动：这个新任务的`task_deadline_seconds`从未冻结，现为null。**采集入口、合法失效、两种固定动作及独立账本已完成；不是要求先证明质量/P90才能采集。另行付费授权仍是本轮规定的阶段边界。

准备版本：[real_recovery_collection_preparation_v1](real_recovery_collection_preparation_v1/PROTOCOL.json)。真实入口在未获得探索性费用风险授权或D为空时均拒绝；本轮未偷偷设D、延长期限、使用旧本地先验，也未调用生产动态策略。

## 1. 第一例任务与场景资格

MultiHiertt开发任务UID `87db6a9c0c874dc4ba00221006d105b1`，原问题为“what was the total amount lost from the bond authorization to the withdrawn?”。原4表、全部段落和8节点12边人工机制Graph原样复制，字节/hash不变。不是LLM自动图成功，亦不是独立泛化样本。

原Table 3确有Franklin、Macon、Brentwood三设施，每设施有Bond Authorized Amount和Amount Drawn两项数值，单位来自表头millions；段落53给出as of December 30, 2017。任务的已冻结图目标就是三设施authorized−drawn的总差额。本轮将该公开原文解释固定为**授权与提取的差额**，不把它称作会计损失或现金损失，不使用Gold选择事实。

三对操作数分别对应三个语义分支，缺任何一组都不能完成原任务；三个差额汇入总值。共享抽取、三表达式、三工具计算、一个工具求和全部贡献目标，没有新加节点。**分支分解合理，但非不可约**：数学上能写成一个表达式，不能由此宣称复杂DAG优化优于Single。这一图可以做固定Graph的范围恢复机制观测，不足以证明DAG分解必然必要或有净收益。

来源/表头/适用时间/准确绝对位置冻结在[FACT_REQUIREMENTS](real_recovery_collection_preparation_v1/FACT_REQUIREMENTS.json)，六个位置均由原表列/行直接确定。运行时缺必要位置会触发FACT_MISSING，保持拒绝；不得补造抽取内容。保留完整来源，不裁剪输入到答案相关小表。

既有Typed事实器识别相邻`$`为USD，表头millions的尺度不是自动维度证明。本采集明确采用原表共同millions尺度做独立评分，保留这个执行合同边界，不修改Graph单位或宣称自动单位认证。

**SCENARIO资格：适合受限固定动作机制采集；不是自然复杂DAG优化资格证明。**

## 2. 失效冻结

选择branch_0_expression，即Franklin表达式节点，精确ID在PROTOCOL.target_node。规则为：

1. 正常调用模型，保存完整原响应、usage和费用信息。
2. 原表达式先通过既有parse及事实绑定检查。
3. 仅给TypedExecutor的消费副本替换为未闭合JSON `{"expression":`。
4. 原响应和源事实保持不变，记录两个answer SHA、注入位置、规则及种子20261014。
5. TypedExecutor产生OUTPUT_SCHEMA_OR_ARITHMETIC，原Graph与数据依赖不改。

这是**受控JSON解析实例失效**，不是自然发生的故障。自然JSON/来源/绑定失败必须单独标注，不能冒充注入。共享阶段若不恰好形成该唯一失败节点，停止本次实例，不重试、不寻找另一个失败位置。

FACT_MISSING、单位冲突和血统错误仍不能触发盲目模型恢复。不得删除必要事实、污染Gold或伪造事实使恢复容易。

## 3. 两种公平固定动作

最小子池只用**qwen-plus**。优先隔离恢复范围与闭包可执行性，避免同时混入新模型能力/参数差异。不称四模型异构优化，不称反馈策略收益。

|动作|Z|R|π|合法复用|恢复LLM请求|
|---|---|---|---|---|---:|
|A固定整图恢复|FULL|原8节点|全部节点绑定qwen-plus；工具只保留占位绑定|不复用节点完成状态|4|
|B固定局部恢复|LOCAL|失败表达式→对应calculate→aggregate，3节点|R及尚未完成节点绑定qwen-plus|原5个DONE节点，身份/来源/计算血统重新核验|1|

共享前置只执行一次：抽取1、表达式3，共4个LLM请求；两条正常分支的工具结果及共同facts冻结为同一post-failure状态。分别复制到独立LOCAL/FULL执行目录；同一状态哈希、同一Graph、同一来源。底层不在两个动作之间复用模型响应缓存；LOCAL仅复用合法Typed完成结果，FULL重新请求。

seed固定的执行顺序为LOCAL→FULL。单次顺序无法消除远程队列/服务漂移混杂，保存顺序并禁止把墙钟差直接解释为策略优势。共享成本只在全局账本算一次，同时报告每动作增量及“共享+该动作”的假想独立总成本；不能将这些假想总成本再加总成实际账单。

正式Qmin=.8、ε=.1及动态门禁不变。这里没有predictor选优，角色为**探索性固定动作观测采集**；生产策略是否拒绝不被改写成PASS。

## 4. 模型与真实参数

有效请求复用已有实际Qwen路径：

- endpoint：`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`。
- model：qwen-plus；允许响应身份qwen-plus或既有兼容快照别名qwen-plus-2025-12-01。其余身份立即停止，不能回退本地medium。
- 完整system、节点user Prompt均保存；`temperature=0,n=1,stream=false,enable_thinking=false,response_format={type:json_object},max_tokens=512`。
- 每响应保存model、system_fingerprint（缺失则UNKNOWN）、headers、原bytes、finish_reason、usage；返回别名不等于固定权重版本。
- 所有云调用只在显式未来授权后，使用环境中DASHSCOPE_API_KEY；密钥不写冻结包、Prompt或账本。不发送额外余额/计数/身份生成请求。

其余模型沿用[上一轮候选核查](p0_prediction_joint_20261014/CLOUD_POOL_CANDIDATES.json)：GLM-5.3/Flash为BigModel anthropic messages路径，low effort/8192为历史参数；DeepSeek为chat/completions、thinking disabled/2048历史候选。它们在当前三分支图没有匹配任务质量与恢复时延，所选FE账本缺实际返回版本，GLM/DeepSeek当前价格未获本轮可核实认证；**均不进入本次最小子池**。不扫描四池，不迁移本地先验。

Qwen公开北京地域、输入≤128K非思考原价参考为输入¥0.8/百万、输出¥2/百万，来源：[阿里云官方模型页](https://help.aliyun.com/zh/model-studio/qwen-plus)。该价不是账户账单，也不覆盖全档位/所有地域。usage缓存命中、优惠及账户实际扣费另核验；本次不能认证完整输入Token或总现金硬上界。

## 5. 采集入口与账本

[recovery_collection.py](collab_scheduler_v1/typed_dag_v1/recovery_collection.py)是独立探索入口，复用request_body、绝对客户端request_deadline、TypedExecutor、事实守卫和JointRecovery，**不修改或绕过正式StrictMeter**。本轮增加JointRecovery可选executor_factory，使FULL仍使用同一个TraceExecutor输入记录/来源守卫；默认旧Typed路径不变。

未来启动文件：[RUN_PREPARED.py](real_recovery_collection_preparation_v1/RUN_PREPARED.py)。必须提供符合9请求/512输出/1200秒且明确接受未认证输入与费用风险的独立授权文件；当前包D为空，即使其他授权标志为true也拒绝。

安全约束：冻结哈希校验、运行目录原子创建、冻结协议级一次性持久认领（不同目录也不能重派）、每phase独立配额、全局已派发计数、派发前fsync、无重试/重定向/备用模型；同实例不自动恢复或重复启动。timeout或身份/usage异常停止全部新请求。已收到可信usage的截断/失败响应仍计消耗；缺失/无可信usage保留整笔未知费用暴露，不记零。客户端timeout的远程取消状态记UNKNOWN。

### 字段如何落盘

|要求|记录位置与定义|
|---|---|
|任务/图/独立身份|TASK_PUBLIC、GRAPH、协议hash；每轨迹task_id/graph_id/hash；只有1个独立开发任务|
|失效及在线反馈|FAILURE_INJECTION、SHARED_VISIBLE_STATE、TYPED_EVENTS；原输出/消费副本hash均保存|
|Z/R/π及合法性|每动作ACTION及JOINT_RECOVERY，图/状态绑定、闭包/模型/尝试检查|
|模型/参数/输入输出|逐请求REQUEST/RESPONSE.bin/RESPONSE.json/HEADERS/METERED_RECORD及节点INPUTS/TYPED_EVENTS|
|缓存与血统|复用DONE集合、source_sha、number_start、reference binding、value_lineage；工具没有LLM请求|
|Token/请求|全局CALL_LEDGER和逐phase计数；已知usage与unknown分列，失败不从分母删除|
|服务时间|client_api_duration_s是可观测API时延，不能冒充隔离的服务推理时间；queue/prefill/decode无证据则UNKNOWN|
|恢复剩余墙钟|在动作apply前取单调tick，至apply返回/抛错后的finally；包含校验、请求、工具和动作记录，不含独立评分|
|端到端/截止|全局同一launch单调起点，shared及动作finish_elapsed；D独立字段，on_time按同一起点+D比较|
|任务质量|EXECUTION_STOPPED后才解析独立Gold；完整执行、数字匹配、六个必要源位置及三分支输入角色/运算检查共同决定task_success_offline|
|费用|已知usage公开价参考估算、未知费用暴露与bill_verified=false分别记录，账单未核实不声称实际现金|

参考文件启动前只做内容哈希核验，不解析答案；执行Prompt和动作决策不包含Gold或事后标签。原始模型错误、超时和未启动动作分别记录FAILED/NOT_STARTED。若共享阶段失败，完整共享状态和原账本仍保留，不能删除这个试验实例。

## 6. 重新核算预算草案

**最多9次真实云请求，而非17次。**每节点仅一次，任何失败不追加：

- shared：最多4。
- LOCAL：最多1。
- FULL：最多4。
- 每请求max output512；请求参数输出总上限4608。
- 单请求客户端绝对截止120秒。
- 全局计划客户端墙钟1200秒：9×120 +120秒保存/评分预留；每次派发要求剩余≥120+120，否则拒绝。没有GPU加载或模型切换预算。
- CPU构造、Hash、状态复制均消耗同一总钟；1200秒不是完成保证，工作变慢时会提前停止，不能超额补请求。
- 不含任何规划、语义评审、修复器、Single对照或四池扫描请求。

[REQUEST_SIZE_ESTIMATES](real_recovery_collection_preparation_v1/REQUEST_SIZE_ESTIMATES.json)用完整Mock输入构造测得消息字节，再以bytes/4至bytes/2给出**经验量级**：9请求合计约13967–27934输入Token；实际模型输出和服务消息包装会改变它。它不是Tokenizer计数、置信区间或认证上界，角色模板开销未认证。按公开参考价和满输出推算约¥0.020–0.032，也**不是现金硬上限**；用户须单独接受实际费用不确定性。

普通节点合同拒绝保留失败轨迹；另一固定动作仅在全局安全条件仍满足时继续。timeout、HTTP/身份错误、未知usage或预算/墙钟拒绝停止剩余派发，标注后续NOT_STARTED。不自动补用剩余额度。

## 7. 离线验收

新6项针对性测试验证两动作从同一post-failure状态运行、原8节点输入跟踪、Gold隔离、真实授权与D拒绝、timeout无重试/未知usage、自然截断不冒充注入、配额和墙钟拒绝。网络及进程启动被阻断。

[MOCK_TRACE](real_recovery_collection_preparation_v1/MOCK_RESULT_FINAL.json)完成9次Mock调用的共享/LOCAL/FULL轨迹；task_success_offline仅为Mock接口评分，不计真实模型质量或恢复成功。D为空，因此Mock on_time为null，没有伪造按时结果。旧相关回归亦验证默认联合接口未破坏，详见最终测试记录。

## 8. 七问直接裁决与下一步

1. **对象**：上述三设施授权/提取差额开发任务；语义三分支合理，非不可约复杂优化证据。
2. **失效**：合法facts存在，原表达式parse/bind成功后，受控注入未闭合JSON；不改来源、不用Gold。
3. **动作**：相同post-failure状态下固定LOCAL与FULL，同Qwen子池，分别复用5节点与不复用完成节点。
4. **调用**：全局最多9，shared4 + LOCAL1 + FULL4；不沿用17，不要求消耗完。
5. **标签**：恢复remaining wall从apply前至finally；停止所有派发后独立评分task_success_offline，失败保留。
6. **能否首次真实采集**：当前**NO-GO**；入口与协议准备可用，但还没有本任务合法冻结的D，也没有本次付费授权。
7. **唯一协议阻塞**：`PROTOCOL.json.task_deadline_seconds=null`。这是先前就未冻结的实际字段，不是新增“必须先校准预测”要求。不能把1200秒总实验预算冒充任务D，也不能悄悄调整旧60题deadline。

最小下一步是**确认该新任务的测量截止D（必须在观察本次结果前确定），形成新版本冻结，然后独立批准9请求/512输出/1200秒及未认证输入与费用风险**。这与修改旧截止时间不同；本轮没有擅自填写。D只用于固定动作测量的按时标签，生产概率门禁仍不运行也不放宽。无需再开发缓存、奖励或生成器。

即使之后一次试验成功，也只证明固定联合恢复路径真实可执行、观测字段可形成、同条件动作可描述比较；不认证质量/P90，不宣称动态策略、异构优化或因果净收益。
