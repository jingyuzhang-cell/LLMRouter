# V2真实探针：分支事实重复与LOCAL恢复边界审计

结论：**唯一下一步选择B——修复初始DAG的语义合同。** 首次语义信息丢失发生于extract输出：金额与准确位置保留，但设施/列角色没有随事实传入下游。首次可确认的错误重复引用发生于`shared-3`的Brentwood原始表达式响应。不是三个节点目标重复，不是检索来源串线，也不是缓存把一个响应冒充另一节点。合流合同没有分支语义约束，但外层公共验收已经正确拒绝错误结果，因此仅加强合流验收不能修复上游信息不足。

本轮只读取和复算既有证据，0真实API请求、0GPU启动、无DAG运行、无生产代码改动、无重试。新增审计文件与原实验目录分离。129个已有文件审计前后哈希一致，运行manifest绑定的源码/输入亦全部一致。

## 1. 证据范围与逐节点定位

原运行：[RESULT_REPORT.md](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/RESULT_REPORT.md)。原图：[GRAPH.json](real_recovery_latency_probe_v2/GRAPH.json)，SHA256 `d5785e788741b98b216a681fdcf86ba474ae97f1c69a61753329cb0f1961379c`。完整8节点、绑定、依赖、输出及文件定位见[逐节点证据](v2_real_failure_semantic_audit_20261014/NODE_EVIDENCE.json)。以下用原图semantic_ref_map中的名字表示节点，不改节点ID。

|节点|实际输入/输出与证据|定位结论|
|---|---|---|
|extract|[shared-1请求](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/shared-1_REQUEST.json)含完整表格、设施行名与授权/已提款列；[响应](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/shared-1_RESPONSE.json)抽到54、51.8、58、49.9、78、75.3，各evidence仅为金额字符串|数值抽取正确，六个来源位置完整且互不重复；但要求“保留设施身份”的subtask未在输出中实现。首次信息丢失在此，而非首次错误引用。|
|branch_0_expression：Franklin|[shared-2请求](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/shared-2_REQUEST.json)明确Franklin；[原始响应](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/shared-2_RESPONSE.json)引用54与51.8|原始表达式正确。之后仅消费者副本被受控JSON截断，未删除事实。|
|branch_2_expression：Brentwood|[shared-3请求](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/shared-3_REQUEST.json)明确Brentwood；[原始响应](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/shared-3_RESPONSE.json)却引用54与51.8|**第一个错误重复引用**。应使用78与75.3。发生于真实模型原始响应，早于LOCAL与缓存复用。|
|branch_1_expression：Macon|[shared-4请求](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/shared-4_REQUEST.json)明确Macon；[原始响应](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/shared-4_RESPONSE.json)仍引用54与51.8|第二个错误分支，应使用58与49.9。|
|branch_2_calculate|[输入](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/shared/node_5b916fdffae5570d543a0ca9_INPUTS.json)消费Brentwood表达式节点，却得到Franklin事实表达式；确定性计算输出2.2|计算器正确求值了错误语义表达式，没有另选事实。|
|branch_1_calculate|[输入](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/shared/node_ab2f4f72ee7d18caf6623040_INPUTS.json)消费Macon表达式节点，确定性输出2.2|同上，应为8.1，但数据类型、引用存在性与维度均合法。|
|branch_0_calculate|共享阶段因受控故障blocked；LOCAL后[输入](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/local/node_4bebf1a4cf72fbc999fef975_INPUTS.json)消费修复后的Franklin表达式，输出2.2|格式恢复后完成正确的Franklin计算。|
|aggregate|[输入](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/local/node_1ce94ddac653f9505b9ef2f9_INPUTS.json)来自三个不同计算节点；各value=2.2且血统均指向Franklin两事实，工具输出6.6|三条节点边真实存在，但两条分支的业务事实身份错误。合流算术本身正确，不能证明任务语义正确。|

首次错误响应的API结束时间为UTC 2026-10-14 06:59:36.549944（北京时间14:59:36.549944），客户端monotonic=32635982.90959266，距共享t0约7.604342秒。该时间来自API_END，不冒充模型产生错误Token的具体时间。

三个分支收到完全相同的六事实列表是原图共享facts依赖的设计，不是错误路由：各自subtask正确、请求独立、模型返回均qwen-plus。但事实内容只携带金额短引文、偏移、哈希、ID和unit；**没有facility/semantic_role，也没有原表格、行名或列头**。总问题仅为“what was the total amount lost from the bond authorization to the withdrawn?”，无法给不透明fact_id补充设施映射。输出提示还允许v0/v1位置别名，不能把列表顺序当作业务身份。

## 2. 来源身份、血统与语义身份并不等价

六项公共来源均来自ctx_table，哈希 `f6cc2c84b70fc3fc2030ee66c37f02eddb9adf200968911b615a770881bd5c2e`，适用时间为2017-12-30，金额规模来自表头in millions。

|设施|授权/已提款原始位置|应使用的fact_id|公共差额（百万）|实际|
|---|---|---|---:|---:|
|Franklin|2987 / 3001|f_804382d9287735fb4821a650 / f_c997d5c6cbb65d17939189fd|2.2|2.2|
|Macon|3084 / 3098|f_005d0c9a2e140fb9499d82dc / f_b5a0bbfed02e643f8000736b|8.1|2.2|
|Brentwood|3188 / 3202|f_81f848c90f378aeb392a2b81 / f_76fae1d2acfdcad250a88d1b|2.7|2.2|

必要事实“已抽取并传输”是6/6；最终结果实际使用的来源事实仅2/6。三分支均引用同一对ID，但六事实本身没有重复或伪造。原始位置允许审计程序回到表格查业务含义，却没有为下游LLM提供该对应关系。

来源血统没有断裂：它准确记录错误分支用了Franklin数据。`USD`词面维度检查也没有认证表头的million尺度。**可追溯的错误选择仍是错误**，不能把PROVENANCE完整解释成语义正确。

## 3. 精确代码调用链与合同缺口

1. [protocol.py:12](collab_scheduler_v1/typed_dag_v1/protocol.py:12)的facts.v1只有question/context→facts通用类型，没有必需业务实体/列角色约束。
2. [generation_schema.py:11](collab_scheduler_v1/typed_dag_v1/generation_schema.py:11)允许金额短引文，不要求行名/列头。实际extract响应符合这个弱合同，虽然没有满足subtask的设施身份保留意图。
3. [execution.py:73](collab_scheduler_v1/typed_dag_v1/execution.py:73)仅要求事实value/evidence等基本字段。并非JSON绝对不能放额外字段，而是没有强制业务标签且后续不保留/核验它们。
4. [fact_semantics.py:14](collab_scheduler_v1/typed_dag_v1/fact_semantics.py:14)的ground，尤其第40–42行，重建数值位置、哈希、unit和稳定ID；不带行实体/列角色，未从原表恢复它们。
5. [execution.py:41](collab_scheduler_v1/typed_dag_v1/execution.py:41)的inputs按照合法边传输整个facts集合，原图未为expression节点声明独立表格context端口。第136行构造prompt时也没有附上FACT_REQUIREMENTS中的facility/semantic_role映射。
6. [fact_semantics.py:61](collab_scheduler_v1/typed_dag_v1/fact_semantics.py:61)的bind验证事实存在、快照、算术和维度，不验证“这些事实是否属于该节点指定设施”。故错误兄弟分支成为DONE。
7. [joint_recovery.py:49](collab_scheduler_v1/typed_dag_v1/joint_recovery.py:49)缓存守卫验证来源未变、引用未变及计算一致，不验证业务实体匹配。因此它复用了**原先已算错语义、但格式/血统合法的输出**，没有把缓存错误串到别的节点。
8. [value_join.py:27](collab_scheduler_v1/typed_dag_v1/value_join.py:27)检查不同上游节点及完整来源血统，允许不同派生值共享原始facts；最后source_fact_ids取集合。这是通用合流的合理行为，不能全局禁止共享事实来修复本题。
9. [recovery_collection.py:95](collab_scheduler_v1/typed_dag_v1/recovery_collection.py:95)只检查六必要位置出现在expression输入集合，未检查表达式实际消费哪个设施的事实；[local_latency_probe_v2.py:92](collab_scheduler_v1/typed_dag_v1/local_latency_probe_v2.py:92)的外层public_validation最终逐分支检查引用，正确报PUBLIC_RESULT_OR_BRANCH_VALIDATION_FAILED。

链条因此是：**抽取阶段设施/列身份未保留→下游模型无法从输入核验事实归属并选错→通用合同把错选登记为合法DONE→LOCAL保留这两个错误兄弟缓存→合流得到6.6→外层验收拒绝**。模型内部为什么选择首对事实UNKNOWN，不能仅凭响应归因为attention或provider缓存。

## 4. LOCAL究竟恢复了什么

[LOCAL动作](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/local/ACTION.json)仅包含Franklin表达式、对应calculate、aggregate三节点。π均qwen-plus，恢复仅一个LLM请求。另五DONE节点复用。

|层面|结论|证据与限制|
|---|---|---|
|JSON/端口合同恢复|成功|受控截断令Franklin节点失败；local-5返回合法表达式，该节点及下游转为完成。|
|失效目标节点来源选择|正确，但未证明语义修复能力|local-5使用Franklin正确两ID；shared-2原始响应已经使用同一正确两ID，注入只破坏格式。所以它恢复了格式，没有纠正一次自然来源选择错误。|
|全图来源语义恢复|失败|Macon、Brentwood的旧错误表达式及绑定在VISIBLE_DECISION_STATE与NODE_STATE中逐项相同，未重执行，也未被识别为需要恢复。|
|最终任务恢复|失败|6.6≠公共来源13.0，公共验收拒绝，task_success_offline=false。|

[JOINT_RECOVERY日志](real_recovery_latency_probe_v2/REAL_RUN_20261014_145901/local/JOINT_RECOVERY.jsonl)COMPLETE表示所选动作的节点执行完成，不代表业务完成。LOCAL 9.688738秒、恢复决策至失败验收约9.705128秒、完整客户端18.930303秒是**失败轨迹的观测时延**；保留其负质量标签，不作为成功恢复耗时或可靠P90样本。

五次原始真实HTTP均保留，并不是执行器响应缓存命中。shared-4的usage中cached_tokens=1792属于服务端输入前缀计费缓存，不能据此推断服务端复用了完整答案。两错误兄弟分支在首次真实响应时已错误，LOCAL之后只按状态复用。服务端具体机制仍UNKNOWN。

时间线还显示FINAL_PUBLIC_VALIDATION先于EXECUTION_STOPPED，Gold评分后于STOPPED；原RESULT_REPORT末尾“公共来源差额核对发生在停止调用之后”的文字不够精确。准确说法是恢复调用结束后、禁止后续派发事件前，已完成运行内公开验证；另有停止后的POST_RUN_AUDIT。此处仅说明，不改写旧报告。

## 5. 场景资格与唯一下一步

三个设施确有不同原始金额与不同应有差额，原图目标未重复，不能仅因为模型重复引用就断言分支没有业务意义。因此**不选择E放弃场景**，也不把它标记为“分支本身不独立”的SCENARIO_NOT_QUALIFIED。

但当前可执行合同不足，不能进入动态策略收益配对：**SCENARIO_CONTRACT_NO-GO / PAIR_EXPERIMENT_NO-GO**。该题仍只适合修复后的有限机制观测；数学可化为单式，真实并发、不同模型优势和组合优化价值未证明。

**只选择B：新版本补齐事实的实体—角色—来源语义合同。** 不是另改奖励或D，不再重跑V2。

最小方案：保留原图节点、边及运算语义，另建可选、图/来源哈希绑定的semantic envelope。复用既已独立冻结的FACT_REQUIREMENTS作为公开证据要求，把每个fact_id与经原表行名/列头位置核验的entity、column_role、适用时间及尺度绑定；不得信任模型自报标签，不能依据金额大小或列表顺序推断。无法确定时拒绝。

表达式节点的原始设施目标对应一个声明的事实角色范围；把完整的事实—实体—角色证据映射传给模型。模型仍生成表达式，程序只核验其实际引用和运算角色是否符合该节点的声明，不自动生成公式或替换引用。相同来源被不同节点引用一般合法，只有在已声明不同设施范围时才拒绝越界引用。

该同一语义约束须在expression输出登记为DONE之前及恢复缓存复用时都核验，并纳入新协议/缓存身份。所有元数据均保留原来源位置/哈希；不得修改旧fact_id或回写V2输出。兼容性无法证明时使用独立版本，原强保护不变。这是一项合同修复的传输与验收闭环，不并行开发A/C/D/E四条路线。

本轮仅提出方案，**没有实施新生产合同、没有新冻结就绪结论**。最先需要离线证明：历史shared-3/shared-4在新合同中拒绝，正确公共来源fixture可通过；实体/列标签缺失、错配、篡改拒绝；同值不同实体不会混用；合法共享facts不被误拒；语义不合格缓存不得复用。不将人工fixture计为真实成功。

下一次真实实验必要条件：新版本合同与完整输入证据映射冻结、上述负例验收通过、恢复适用失效类型与停止行为明确、无编译器自动补算或事实替换、原V2记录完整保留，并取得新的独立调用/费用授权。D继续UNKNOWN，正式质量/时延预测与配对门禁不得因为格式恢复成功而解除。

## 6. 审计交付与边界

- [NODE_EVIDENCE.json](v2_real_failure_semantic_audit_20261014/NODE_EVIDENCE.json)：8节点绑定与来源、5个原始请求及响应摘要、正确/实际分支引用对照。
- [audit.py](v2_real_failure_semantic_audit_20261014/audit.py)：只读复算与断言，无HTTP、模型或DAG执行入口。
- [HISTORICAL_EVIDENCE_HASHES.json](v2_real_failure_semantic_audit_20261014/HISTORICAL_EVIDENCE_HASHES.json)：129文件身份锚点，旧冻结manifest逐项核验。

本次不读取Gold内容来决定修复，13.0由冻结公共表格六金额及原任务操作规则复算。0新增真实请求；不修改历史账本、原图、生产代码或评分协议；不提交Git。
