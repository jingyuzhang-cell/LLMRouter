# P7：统一舆情DAG证据片段ID协议

结论：**TECHNICAL_READY / PAID_EXECUTION_HOLD**。新协议 `OPINION_EVIDENCE_ID_V1` 已完成离线接线；本轮真实API请求0、GPU加载0。真实运行须另行授权。D仍为UNKNOWN，不报告按时概率、P90或调度收益。

版本目录：[opinion_evidence_id_contract_v1](opinion_evidence_id_contract_v1/)。冻结清单为该目录 `FREEZE_MANIFEST.json`，其最终SHA256保存在 `FREEZE_MANIFEST.sha256`。原六节点六边图、旧冻结包、历史正式拒绝均未改写。

## 1. 新协议及证据目录

[EvidenceCatalog](opinion_evidence_id_contract_v1/EVIDENCE_CATALOG.json)包含4份冻结来源的72个片段，覆盖所有留存正文页及标题元数据。不能据此声称已获取完整媒体报道：新闻仍只是原有留存片段。

[catalog.py](opinion_evidence_id_contract_v1/catalog.py)对每个原始文本空间连续、无重叠、无遗漏地分段：最大384个Unicode字符，优先在后半区最后一个换行结束，否则固定长度截断；不跨页。无句子/主题/任务重要性筛选。标题与正文显式区分为 `METADATA_TITLE` / `PAGE_TEXT`，标题证据不能冒充正文数值证据。

每项含 `evidence_id,event_id,source_id,chunk_id,start_offset,end_offset,exact_text,source_sha256,parsed_page_sha256,space,page,segmentation_version`。ID由事件、原文件hash、完整页文本hash、空间、页、边界及文本生成。跨事件、换文档或改变分段版本不能沿用ID。程序重新生成并逐项比较目录；验证原文件hash、解析文本、跨度和信息截止。

生成顺序固定：先从来源生成并保存整个目录，之后才读取人工Stub夹具和历史模型响应。目录生成器没有评分参考、题目目标、字段角色、事实答案或模型输出参数；`CATALOG_AUDIT.json`及测试记录这一边界。原文包含正确事实是任务输入，不等于提供评分答案集合。

目录内容hash：`3df906e25ad44a3773dfdf0367ba8905b8b207711c5adb40cf27467da39cf3c8`。

## 2. 三个抽取节点统一接口

`extract_current`、`extract_media`、`retrieve_history`共用严格Schema：

```json
{
  "facts": [{
    "local_id": "model_local_id",
    "entity_id": "registered_entity_id",
    "field_role": "chosen_role",
    "value": "numeric_or_date_text",
    "unit": "source_supported_unit_or_null_for_date",
    "time": "supported_period_or_UNKNOWN",
    "value_scope": "chosen_scope",
    "source_id": "declared_document_id",
    "value_evidence_ids": ["ev_..."],
    "entity_evidence_ids": ["ev_..."],
    "role_evidence_ids": ["ev_..."],
    "time_evidence_ids": [],
    "unit_evidence_ids": ["ev_..."],
    "confidence": 0.5
  }],
  "claims": [{
    "local_id": "model_local_id",
    "speaker": "attributed_speaker_or_UNKNOWN",
    "target_entity": "registered_entity_id",
    "published_time": "supported_time_or_UNKNOWN",
    "claim_text": "attributed_claim",
    "claim_type": "UNKNOWN",
    "source_id": "declared_document_id",
    "evidence_ids": ["ev_..."]
  }]
}
```

这是结构示意，合法模式及字段必需性以 [SCHEMAS.json](opinion_evidence_id_contract_v1/SCHEMAS.json)为准，示意ID不是可执行证据ID。全部对象禁止额外字段；无完整答案enum/const。金额必须将数值与单位分离，日期允许有依据的ISO/中文日历表达；不能由年度推造具体日期。日期单位为null，UNKNOWN时间可无时间证据，金额单位不能凭空补填。

模型仍承担真实语义选择：从全文目录挑哪些片段、抽哪些值、绑定哪个实体、角色、期间、口径，以及提出何种主张。程序没有为它选好正确证据，也没有登记它未输出的事实。entity_id是允许实体词表，不是每个金额的答案绑定。

每个Prompt只提供该节点允许的来源目录和必要元数据：当前公告仅current；新闻仅media_excerpt；历史仅forecast/prior_revision。模型输入的目录条目不要求输出offset，程序保存完整跨度。source_id、chunk_id和evidence_id的映射固定；模型选择错误来源直接拒绝，不自动换ID、不模糊查找、不替换来源。**三个抽取节点的主quote、辅助quote、精确offset生成要求均已移除。** assess/report的输出引用也统一为ID，避免下游重新要求offset；节点业务目标和依赖不变。

## 3. 程序守卫与语义边界

[core.py](opinion_evidence_id_contract_v1/core.py)执行：严格JSON与Schema → ID存在/事件/允许来源/声明来源/文档版本检查 → 解引用冻结文本 → 完整数值token或日期支持 → 实体别名证据 → 字段及口径约束 → 单位/期间 → 原有独立来源表格的限定L1身份校验 → 原子登记。

多个显式ID允许组合。只有同来源、同空间、同页且相邻的已选片段会拼接；没有选择的中间片段不会被补上。数值以原始完整页上的完整token为基础，截断在片段边界的部分数字不能冒充另一个数值。canonical EvidenceRef由程序生成；完整多片段证据链另保存在登记对象的ID组和证书中，不丢失只存第一个片段之外的支持。

跨页单位继续使用既有PDF表头/列对齐证据，仅覆盖已审定的相邻页及两行余额范围；不因模型声明而扩张。原金额/单位/期间/列角色的限定来源表检查保留，错实体、错角色或错期间会拒绝。原始来源、问题、截止、评分参考不变。

**ID存在不等于事实正确。** 目录只解决定位接口。独立来源表之外，角色线索属于proxy，期间语义、实体与某一具体数值的深层关系未必可识别；证书保留UNKNOWN，不提升为完整事实正确率。claim归属/字面支持与实际主张真实性分开；没有独立语义依据不能把自由改写、风险结论、主张类型或主张支持关系升为verified。

## 4. reconcile引用及下游

原始输出只含 `relations` 和 `unresolved`。relation使用已有稳定fact_id、claim_id、evidence_id及既有关系类型、rationale；不复制facts/claims完整对象。unresolved仅允许既有字段 `unresolved_id,statement,fact_ids,claim_ids,reason`，不接纳历史错误中的额外rationale。

检查所有ID生产者、事件、来源、完整对象引用；每条relation必须覆盖所引用fact的全部value证据ID及claim的全部证据ID，UNKNOWN关系也不能省略证据链。每个上游对象必须出现在relation或unresolved中。已知实体/期间/实际、预计、暂估口径不同，不能直接认作CONTRADICTED，也不能直接认作SUPPORTED。自由文本claim的完整语义关系仍UNKNOWN。

程序从已接受、不可变的登记表恢复原图需要的canonical端口，禁止创建事实、替换值或补算操作。原图三抽取分支→reconcile→assess→report及reconcile→report六条边不变。assess/report保留全部unresolved_ids。缓存键新增协议、Schema、目录身份，并绑定图、来源、模型配置、输入与上游版本；命中仍重跑守卫，旧quote缓存不能直通新合同。

## 5. 离线验证及历史影子检查

[OFFLINE_TEST_RESULT.json](opinion_evidence_id_contract_v1/OFFLINE_TEST_RESULT.json)：21/21针对性测试通过。包括正确ID、越权来源、不存在ID、正确金额但错误角色、跨期间、实体证据不足、多片段值支持/不补缺段/不接受半个数字、关系ID与证据完整性、UNKNOWN及额外字段拒绝、缓存/事件/原文件版本保护、未来材料拒绝、同节点四模型消息及上限一致、原始字节不变，以及假传输下启动器遇首次合同失败立即停止。

[OFFLINE_TYPED_TRACE.json](opinion_evidence_id_contract_v1/OFFLINE_TYPED_TRACE.json)：原6节点6边图使用新版独立执行覆盖层全部Stub执行完成；仅证明接口和守卫机制，不证明真实模型质量或端到端真实成功。人工夹具迁移明确标记MANUAL/STUB，不计入真实生成/执行成功。

[SHADOW_REPLAY.json](opinion_evidence_id_contract_v1/SHADOW_REPLAY.json)只读检查4份已有真实响应，历史47个记录文件hash不变，目录检查前后hash一致：

|旧节点|新协议直接回放|只读归因及界限|
|---|---|---|
|extract_current|Schema拒绝，登记0|旧响应主金额quote可定位；辅助entity/role存在旧quote不匹配或歧义。只列出原有跨度覆盖的预生成目录ID，不替模型生成新选择。|
|extract_media|Schema拒绝，登记0|旧主quote可定位；数字片段不能自行证明issuer实体或预计口径，标题与正文ID现在可显式分别选择。仍需模型实际选择正确证据。|
|retrieve_history|Schema拒绝，登记0|旧辅助quote存在歧义/改写。新目录提供确定位置，不认定旧角色/期间选择因而正确。|
|reconcile|Schema拒绝，登记0|旧unresolved额外rationale仍不合法；旧fact/claim ID不自动重映射，旧关系证据不补齐。|

四次旧实验仍保持其原始正式失败；新合同影子拒绝也不是新的真实调用结果。

## 6. 质量记录及UNKNOWN

分开保存 `raw_schema_pass,raw_contract_pass,adapted_schema_pass,transport_format_violation,evidence_guard_pass,adaptation_type,first_failure,raw_output_sha256`。新wire协议不执行输出适配，adaptation_type为NONE；程序证据解引用不构成原生模型格式成功之外的修复。

verified范围：声明ID来源合法性、原文数值token支持、实体别名字面支持、文档截止有效性、限定独立L1表格的entity/role/unit字段准确率与期间准确率，均保存各自分母。局部来源字段评分不等于完整事实准确率。无法匹配独立表格的候选不能排除后声称全样本高正确率。

proxy范围：事实绑定合同通过率、来源线索支持、字面主张支持、引用及输入对象覆盖。UNKNOWN范围：完整fact precision/recall、未被独立表识别的角色/期间语义、新闻主张真实性、关系准确率、风险严重程度、未来影响及投资价值。模型confidence不当作质量；Gold/评分reference没有进入模型Prompt或目录。

## 7. 四模型公平性和历史边界

冻结候选仍为 `qwen-plus,deepseek-flash,glm-5.3,qwen-flash`。同一节点四模型的messages、来源、Schema、证据守卫、质量指标和输出上限相同，24份模板已生成供接口校验；启动器不开放24格全跑。

保留各真实供应商端点及冻结参数映射；Qwen/DeepSeek非思考，GLM沿用thinking-low。这是配置服务对照，不能说成仅改变模型权重的因果实验。记录响应模型、系统指纹、usage；动态别名不是固定权重证明。没有本轮账户权限检查，没有模拟GLM可用性。

旧quote/offset结果与新ID协议不是严格同协议配对；输入目录、Prompt、Schema及缓存版本均变化。旧记录保留作历史探索；只能新协议内同条件采集后比较。下游模板使用共同的人工来源核验Stub上游状态，明确是conditional-node测量，不冒称上游真实LLM输出或整图执行。

## 8. 下一次最小真实Pilot及启动

建议只验证统一后的四节点：extract_current、extract_media、retrieve_history、reconcile；每节点qwen-flash最多一次，共最多4请求。三个抽取各最大16,384输出Token，reconcile最大4,096，累计最大53,248输出Token；单请求120秒（连接15秒、读取105秒及独立信号总截止），完整客户端900秒，末尾60秒预留保存证据。不重试、不换模型、不加规划/修复/评审/权限探针。

任一JSON/Schema/证据/语义合同失败或非正常finish立即停止剩余单元；HTTP/身份/usage/输出上限/时间门禁失败也停止。未派发明确NOT_EXECUTED；超时远端完成状态UNKNOWN，不能声称已取消或费用为零。所有派发先持久化请求占额及原始请求，保留原始响应、失败、实际usage、时延、完整墙钟及待核验费用；不读旧结果伪造成功。

完整输入Token及现金上界仍未认证；REQUEST_BUDGET.json只给实际序列化字节数，不冒充Tokenizer认证。输出/请求/时间上限不是现金硬上限。真实账单待按request ID、usage及运营商账单核验；无自动充值/资源包购买。新版本必须独立接受输入和费用风险。之前P6四请求授权已使用，不沿用到P7。

无网络技术检查命令：

```bash
python -B /root/r3_own_pool/opinion_evidence_id_contract_v1/START.py --mode qwen-four
```

获得新独立授权后，另存批准文件，填入最终freeze hash及请求/输出/墙钟/凭据用途/费用风险批准字段；模板默认approved=false，不能直接作为授权凭证。未来受限命令（本轮未执行）：

```bash
python -B /root/r3_own_pool/opinion_evidence_id_contract_v1/START.py --execute --mode qwen-four --authorization /root/r3_own_pool/opinion_evidence_id_contract_v1/P7_APPROVED_AUTHORIZATION.json
```

四模型同四节点最多16请求、输出212,992 Token、客户端2400秒仅是另行授权选项；GLM价格/账户未知须独立处理，不是本次建议直接运行的批次。

## 9. 最终准入

统一引用接口及原图离线执行达到**TECHNICAL_READY**。真实模型可能仍选错值、实体、角色、期间或关系，这些应按原严格守卫记录失败，不继续为追求通过率放宽合同。没有本轮模型质量结论。

真实付费执行保持**HOLD：尚无P7新冻结版本的独立调用授权**。本轮完成后停止，不运行API，不启动GPU，不修改ZCODE或调度算法，不自动提交Git。
