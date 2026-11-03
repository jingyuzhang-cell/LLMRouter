# 首次舆情DAG云端执行：启动前合同阻塞

**NO-GO：0真实API请求，实验未启动。** 本轮没有新增测试、GPU、恢复、动态路由或Git提交，也没有改动任何冻结DAG、来源、截止、合同、评分或历史记录。

## 1. 启动前发现的具体问题

27份冻结文件SHA256均一致。结构仍为6节点6边；来源保留此前的完整PDF与新闻短片段边界。阻塞不是冻结损坏，而是现有输出合同只支持预写对象复现。

[SCOPED_OUTPUT_SCHEMAS.json](opinion_multisource_dag_v1/SCOPED_OUTPUT_SCHEMAS.json)实际规定：

- extract_current、extract_media、retrieve_history：事实/主张为包含完整fact_id、金额、角色、跨度、归属和核验状态的预写对象enum。给模型这个Schema，就同时提供了目标对象。
- reconcile：facts、claims、relations都是完整const；其中金额换算另有确定性程序核验，本节点本来不需LLM。
- assess：整个assessment为const，包含预先写好的可靠性与限制判断。
- report：整个最终报告为const，含预写关系、评估和结论。

执行器并非仅检查JSON结构与证据合法性：[runtime.py:65](opinion_multisource_dag_v1/runtime.py:65)要求完整事实对象与冻结目录相等；[runtime.py:71](opinion_multisource_dag_v1/runtime.py:71)至73要求关系、评估、报告与预写答案整体相等。

因此，隐去目标对象时，模型不能从来源自行恢复人为分配的ID、字段说明及完全相同的限制措辞；提供目标对象时，通过只能证明目录选择/对象复现和来源传输，不能识别独立抽取或研判能力。问题不仅在服务接线，**前轮把仅适合Stub验证的定值约束当成可直接测量真实节点能力的合同，这个判断不充分。**

enum引用ID或固定UNKNOWN状态本身合理；这里的问题是enum/const覆盖完整事实内容和完整评估/报告。没有把所有证据约束都判成错误，也没有提议放松来源、身份、时间或缺失事实保护。

## 2. 六节点计划与本轮实际结果

固定策略A（全模型节点Qwen-Plus）是可进一步冻结的候选；确定性节点不强制调用模型。实际没有模型请求，故不能填写服务端身份或实测Q/C/L。

|节点|输入|输出|原运行方式|本轮状态|Q / C / L|
|---|---|---|---|---|---|
|extract_current|question、当前公告context|EventFact、Claim|LLM候选qwen-plus|未派发|UNKNOWN / 未发生调用费用 / 未执行|
|extract_media|question、媒体片段context|EventFact空数组、Claim|LLM候选qwen-plus|未派发|UNKNOWN / 未发生调用费用 / 未执行|
|retrieve_history|question、历史公告context|EventFact、Claim空数组|LLM候选qwen-plus|未派发|UNKNOWN / 未发生调用费用 / 未执行|
|reconcile|三分支facts、claims|facts、claims、ClaimRelation|确定性|本轮未执行|UNKNOWN / 不适用 / 未执行|
|assess|facts、claims、relations|RiskAssessment|LLM候选qwen-plus|定值合同阻塞|UNKNOWN / 未发生调用费用 / 未执行|
|report|facts、claims、relations、assessment|OpinionReport|LLM候选qwen-plus|定值合同阻塞|UNKNOWN / 未发生调用费用 / 未执行|

本轮不是节点调用后失败，准确状态为启动前NO-GO。既有Stub和LOCAL证明不被改写为真实失败或成功。独立结果见[REAL_OPINION_DAG_EXECUTION_RESULT.json](opinion_multisource_cloud_execution_v1/REAL_OPINION_DAG_EXECUTION_RESULT.json)，账本只有一条派发前停止事件，没有伪造请求记录。

## 3. 能自动评价什么

现有程序可以核验源字节/片段版本、页与跨度、已登记身份/金额/角色、必要覆盖、数值换算、UNKNOWN保留。这些核验能力不等于真实LLM独立质量观测。

若真实模型收到完整目标对象后复现成功，可以记“对象复现合同通过”，不能记“模型事实抽取正确率”或“风险分析质量”。未知事项仍包括主观风险严重程度、独立语义推断质量、实际模型差异、真实节点成本及服务时延。

本轮未修改评分规则，没有用新的分数弥补实验不可识别性。未发生任何API派发，输入/输出Token为0；没有未结算请求，账单状态为不适用。实验未启动，完整实验墙钟不伪造；结果只记录此次可重现准入检查的墙钟，不冒充整个交互耗时。

## 4. 下一步与权限边界

在当前冻结合同不变的前提下，不能把一次付费对象复现运行当作用户要求的舆情节点能力实验，故未接入API强行启动，也没有修改Prompt后尝试。

最小后续工作需**另行允许新版本输出合同**：保留同一DAG、来源、截止及证据保护，把完整答案enum/const改成类型结构、合法引用及事实/时间/覆盖校验；允许模型生成可核验内容与带来源的评估，并将预写参考对象只置于离线评价。旧冻结版本及当前NO-GO证据必须保留。该改动超出本轮“语义合同不修改”的边界，本轮未实施。

合同修正后再冻结真实请求、模型参数、逐节点输出容量、最多5个模型节点各一次的请求计划及客户端墙钟，记录云端输入/费用未知边界。不得未经准入消耗真实请求；GLM/DeepSeek在本任务的参数和能力未核验，不模拟其可用性。

**尚不具备下一步异构模型路由实验条件。** 先解决可识别的节点输出合同，才值得测真实Q/C/L；不需要增加数据集规模、模型池扫描或继续堆积Stub测试。
