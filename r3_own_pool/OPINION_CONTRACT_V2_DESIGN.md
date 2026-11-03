# OPINION_CONTRACT_V2：证据约束质量合同

**结论：OPINION_CONTRACT_V2_OFFLINE_READY。** 新合同Schema、可执行证据守卫、逐尝试质量记录、Stub迁移和28项针对性测试完成；未调用模型、GPU、动态调度或恢复实验。尚未接入真实云端执行入口，不能声称REAL EXECUTION READY。

## 1. V1为什么无法测量独立LLM能力

V1抽取Schema的enum包含完整预写事实及主张；assess/report的const包含完整输出；runtime.py同时做完整对象匹配。提供Schema会泄漏目标对象，隐藏对象则要求模型猜测人为ID和固定措辞。它能验证目录选择/复现，却不能识别独立抽取或研判能力。

V1原图与合同不改写。新版本独立位于[opinion_contract_v2](opinion_contract_v2/)，命名明确为OPINION_CONTRACT_V2，与历史已叫opinion_extract.v2的旧合同不是同一版本。

V2只使用类型/作用域词表enum；没有完整事实enum、结论const、预写报告匹配。模型自己产生候选ID、事实、主张和措辞。程序验证证据及引用，不替模型生成内容。

## 2. 原图与新版本绑定

原始6节点6边Graph保持字节不变：
`e2878846a22e10f1e6a92481f845969ab99e96aed04f3275f29fa786e97f4b53`是其canonical content hash。

新CONTRACT_BINDING.json以原图哈希绑定节点级V2输入/输出Schema；保留既有端口名和全部依赖。没有把新合同静默写入旧图，也没有把旧TypedExecutor的答案相等检查宣称已更新。

本轮六节点迁移是按原依赖顺序调用**新Guard**验证Stub输出，不是旧执行启动器已能消费新合同。下一阶段应通过显式版本消费者使用该绑定，并禁止落回V1。

## 3. 每个节点的输入输出Schema

完整机器Schema：[SCHEMAS.json](opinion_contract_v2/SCHEMAS.json)。schema.py可重现这些定义，所有对象additionalProperties=false。

|节点|保留输入端口|V2输出|硬检查/状态|
|---|---|---|---|
|extract_current|question、context|facts: FactCandidate[]；claims: Claim[]|来源归属、金额完整token、实体证据、时间/角色引用|
|extract_media|question、context|facts: FactCandidate[]；claims: Claim[]|抽取媒体归属主张，不判真假；允许无数值facts|
|retrieve_history|question、context|facts: FactCandidate[]；claims: Claim[]|历史原文、期间、预计/暂估/实际作用域，不靠对象匹配|
|reconcile|facts、claims|facts、claims原输入转发；relations: Relation[]|合法生产者引用、无上游篡改、不同口径不可强判矛盾|
|assess|facts、claims、relations|assessment: RiskAssessment|开放风险陈述、引用与不确定性；主观严重程度UNKNOWN|
|report|facts、claims、relations、assessment|report: OpinionReport|开放报告、合法引用、覆盖proxy及证据限制|

context仍可保持原Graph中的text端口，但内容为JSON EvidenceDocument集合：source_id、source_sha256、hash_scope、available_by_utc、title、pages。程序须显式解析并验证contentSchema，不能误认为JSON Schema的contentSchema注释已自动校验。

初始输入只允许原始材料、实体/来源注册表、任务要求、截止与类型词表。**旧facts/claims完整目录、预写relations/assessment/report，以及迁移Stub文件禁止进入Prompt。** PUBLIC_PLANNING_INPUT.json不含这些答案对象；原文中包含真实金额是合法任务输入，不属于答案泄漏。

## 4. 核心对象及证据约束

### EvidenceRef

字段：source_id、source_sha256、space、page、start、end、quote。space为PAGE_TEXT或METADATA_TITLE，跨度为保留文本Unicode码点半开区间。源文件SHA、页/片段定位、原文quote必须匹配；原HTML哈希仍UNKNOWN的新闻只能绑定保留片段版本，不能升为原网页版本认证。上下文注册表在构造Guard时重核文件哈希及冻结截止。

### FactCandidate

字段：fact_id、event_id、entity_id、field_role、value、unit、time、value_scope、source_ref、evidence_ref、entity_ref、role_ref、time_ref、confidence。

value_scope允许ACTUAL、ESTIMATED_ACTUAL、PROJECTED_CAP、DOCUMENT_DATE、UNKNOWN。实体/字段词表来自公开来源与任务合同，未使用完整答案作为enum。fact_id只要求合法且唯一，不预设某个候选ID。

- 数值必须对应来源内完整数值token；允许逗号格式变化，拒绝截取数字子串，不自动换单位或补计算。
- 实体ID存在并由同文档实体证据支持；金额、角色、期间引用同源，避免跨文档拼接假绑定。
- field_role必须属于该节点的领域词表。角色引用出现唯一相反的实际/预计/暂估线索时拒绝；多义表头或不充分线索为UNKNOWN。
- 单位必须出现在引用上下文，年份须有时间证据。年份匹配只是词面代理，不能冒充完整会计期间/行列语义核验。
- confidence是模型自报值，不作质量标签、可信概率或质量先验。
- 模型不能输出verified字段。程序产生单独证据凭证：VERIFIED_SOURCE_LITERAL只证明来源字面支持，world_truth仍UNKNOWN。

### Claim

字段：claim_id、event_id、speaker、claim_text、target_entity、published_time、source_ref、evidence_ref、claim_type。claim_type仅为FACT_ASSERTION/OPINION/SPECULATION/UNKNOWN，不是事实真伪标签。

必须存在原文跨度、合法目标实体及出处；speaker不得无来源创造。发表时间使用可核实元数据，否则UNKNOWN，不把署期或抓取时间变成首次发布时间。主张改写或分类的准确性没有独立标签时为UNKNOWN；有效quote不证明claim_text语义等价。

### Relation

字段：relation_id、event_id、fact_ids、claim_ids、relation_type、evidence_refs、rationale。类型为SUPPORTED、CONTRADICTED、DIFFERENT_SCOPE、TIME_MISMATCH、INSUFFICIENT_EVIDENCE、UNKNOWN。

引用只能来自已登记上游。明确实体/期间/实际—预计作用域不同的事实，不能直接输出CONTRADICTED；需要DIFFERENT_SCOPE、TIME_MISMATCH或UNKNOWN等候选。程序不强制唯一关系答案；同作用域的SUPPORTED/CONTRADICTED也不会自动获“正确”标签，必须保留语义核验UNKNOWN。

reconcile继续转发已有候选，内容哈希只用于**上游不可篡改/血统连续性**。这是针对运行中真实生产者输出的完整性检查，不是针对人工答案或最终报告匹配。

### RiskAssessment / OpinionReport

风险输出含risk_points、uncertainties、limitations。每个点含statement、supporting_facts、supporting_relations、evidence_refs、risk_level，允许LOW/MEDIUM/HIGH/UNKNOWN，不要求固定文字或唯一等级。

缺证据风险可以保留原话，但程序凭证必须标UNKNOWN，有效风险等级不升级；未知fact_id或非法EvidenceRef直接拒绝。附有效引用仍不证明因果支持或严重程度正确。原始模型输出绝不被程序改写。

报告含confirmed_source_assertions、source_differences、unresolved_questions、risk_analysis、evidence_limitations。confirmed_source_assertions仅指有来源核验的文档断言，不是现实真值。不同措辞和组织方式可通过，禁止拿全文等同预写报告。

自由文字中的隐藏新实体、文本蕴含和因果支持无法由简单引用检查完整认证，必须保留UNKNOWN；结构化实体引用的硬保护不被扩大为“所有自由文本语义都已证明正确”。

## 5. 质量指标：OPINION_QUALITY_METRICS_V1

机器协议见[OPINION_QUALITY_METRICS_V1.json](opinion_contract_v2/OPINION_QUALITY_METRICS_V1.json)。

|指标|定义和分母|等级/边界|
|---|---|---|
|contract_pass|格式、引用及硬约束准入0/1|verified；不是任务正确性|
|source_validity|注册来源/版本有效的候选数 ÷ 所有候选数|verified source snapshot|
|source_grounding_rate|有效事实数值/字面跨度和主张quote跨度数 ÷ 所有候选数|verified literal；不含主张蕴含|
|entity_consistency|实体证据别名匹配的事实候选数 ÷ 所有事实候选数|verified alias；主张目标归属另列proxy|
|temporal_validity|绑定材料未晚于截止的候选数 ÷ 所有候选数|verified snapshot；不认证首次发布/完整期间语义|
|fact_precision|语义正确事实 ÷ 所有事实|当前UNKNOWN，无独立语义基准|
|fact_recall|正确必要事实 ÷ 完整必要事实集合|当前UNKNOWN，不新增人工Gold|
|claim relation accuracy|正确关系 ÷ 独立核验关系|当前UNKNOWN，不用同模型自评|
|upstream fact coverage|报告引用的已登记fact ID ÷ 上游fact ID|proxy；不是任务事实recall|
|citation_validity|有非空合法引用的报告陈述 ÷ 全部报告陈述|verified span；不是语义支持|
|citation_missing_rate|缺supporting fact或EvidenceRef的风险点 ÷ 风险点数|proxy；不能等同全体unsupported-claim率|
|unsupported_claim_rate|无语义支持的陈述 ÷ 独立语义核验陈述|当前UNKNOWN|
|未来经营/情绪/投资价值/主观严重度|没有可靠自动评价基准|UNKNOWN|

所有失败、JSON异常、拒绝、弃权和UNKNOWN都保留在尝试账本。evaluate_attempt对拒绝输出也统计候选分母，避免只在通过集合报1.0；分母为0输出null/UNKNOWN，不设为100%。接受后条件指标须另列，不能只挑成功轨迹。

空抽取可以作为合法弃权保留，但minimum_input_readiness_proxy为INSUFFICIENT_INPUT，原图必要下游不得派发。完整语义覆盖仍UNKNOWN，不以最小输入具备冒充任务完成。

不人为制造统一scalar Q；保留质量向量及各指标verified/proxy/unknown。需要后续确定权重时另行预登记，不将confidence、parse PASS或UNKNOWN改成手设质量0.8。

## 6. Q/C/L与模型池兼容

Qwen、DeepSeek、GLM均必须使用相同源快照、原图、Schema、准入和质量定义。不同服务参数、模型ID/返回身份、版本、结构化输出支持及思考模式分别冻结，不模拟不可用服务。

NODE_QCL_RECORD_SCHEMA定义node/model身份、真实usage、客户端请求与节点时延、cost、账单状态、质量向量及失败原因。输入上界未知或费用待账单核实继续明示；客户端API耗时不冒充服务端推理时延。Stub中的Token/模型时延/费用为null，不能作为真实样本。

本轮无模型参数扫描、真实调用、Router训练或费用估算，也没有确认性模型排名。

## 7. 动态路由、缓存与恢复

缓存绑定OPINION_CONTRACT_V2、节点Schema、原图、模型身份/版本、完整输入、来源版本、截止及上游版本；重用时再次核验输出。旧V1缓存拒绝，合法V2缓存可以复用。修改上游fact内容仍须拒绝或显式版本失效，不自动替换引用ID。

后续LOCAL/FULL必须保留既有依赖闭包、π及原来源保护，重新登记候选/凭证后失效受影响下游缓存；没有原始事实或来源版本失效不能盲目重试。当前只实现缓存门禁和依赖输入守卫，**没有运行或开发动态调度器**。

历史质量反馈只能使用决策之前已完成的独立任务结果。当前任务的事后语义标签不得进入当前动作，proxy也不能称确认性质量。正式Qmin/epsilon/期限保持不变，缺可信Q或P90时不能靠新合同绕过策略门禁。

## 8. 本轮验证、冻结与准入

28/28针对性测试通过：错误source_span、不存在文档/实体/fact_id、未来材料和时间、模型verified字段、部分数字截取、错误单位、跨口径矛盾、上游篡改/遗漏、空输出阻断下游、旧缓存拒绝、新缓存重核及模型身份变化拒绝；不同风险表述、报告文本、候选ID和数值格式可以通过；无证据风险单独降级UNKNOWN并保持原始输出。

V1泄漏字段审计、新Schema反泄漏扫描、六节点Stub迁移、上下文Schema显式校验均完成。未重复无关回归；生产代码、原图和历史结果不改。Stub迁移仅作为测试fixture，不进入模型输入、质量训练或真实样本分母。

**CONTRACT_V2_OFFLINE_READY，非REAL_EXECUTION_READY。** 下一阶段只需把显式V2绑定、Guard、质量账本接入真实节点传输并核验完整Prompt隔离、资源及模型身份，再获得独立真实调用授权；不能继续调用原V1运行器或泄漏Schema。

本轮到此停止，不执行真实模型或调度实验。
