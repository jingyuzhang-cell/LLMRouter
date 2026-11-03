# 首个真实事件Typed DAG：欧菲光两源披露状态任务

结论：**OFFLINE_TYPED_DAG_PASS；THREE_SOURCE_NOT_QUALIFIED；真实舆情执行NO-GO**。
本轮0付费模型请求、0GPU加载、未扩展数据集、未提交Git。源数据集及历史账本未修改。

## 1. 选择与资格

选择欧菲光002456的2026-075《澄清公告》和2026-077《独立董事聘请独立第三方中介机构核查相关事项的公告》。原文为已有巨潮公告PDF；逐页重新解析与冻结文本完全相等，文件SHA256重核通过。

|材料|原始URL|SHA256|
|---|---|---|
|2026-075|https://static.cninfo.com.cn/finalpage/2026-08-10/1225465394.PDF|98c437b56d8b87e2ada7d95d467fc4c0f64a218185bff693dcbf18f1792f2f81|
|2026-077|https://static.cninfo.com.cn/finalpage/2026-08-15/1225474285.PDF|183bb1b2a1b7af49ca0c18410d2b74706435bb3d4b8c8094b66b70045209e7d7|

两个三源候选逐项记录在[QUALIFICATION.json](opinion_typed_first_task_v1/QUALIFICATION.json)。欧菲光第一财经片段有实质主张，但主张是转述公司否认，不是独立调查；上实发展新浪/观点片段是同案上诉诉求转述，未证明第三分支新增必要事实职责。故两者均未通过当前任务的三源必要性验收，未人为添加新闻节点。上实历史登记署期3037-05-05未被作为可靠时点使用，也未改写。

这是**两份同一披露主体的材料**，并非两个独立证人。第一份提供公司针对新思考关联交易的立场，第二份提供针对该报道的后续核查安排且显式引用前公告。单份不能覆盖两个时点、两个状态和可追溯披露链；任务要求合并这些输入。单模型读取两份材料也可能完成任务，本轮不证明DAG性能优于摘要，不把五节点称为复杂调度空间。

## 2. 冻结任务与信息截止

任务：基于保留材料，区分公司否认、独董核查安排与未知调查结论，提供来源和时点，避免把否认或聘请核查等同于事实已证实。

信息截止为 **2026-10-14T11:26:10.300643+00:00**，依据第二份文件已经成功获取的UTC记录；这是**回溯的已保存来源快照**。公告署期分别2026-08-10、2026-08-15，会议日期2026-08-14；精确首次公开时间UNKNOWN。没有声称构建了2026-08-15盘中可见信息集，也没有声称截至抓取日不存在其他后续文件。来源fetched_at晚于截止则拒绝；当前事实全部依赖这两份已保存文档。截止不作为业务任务D或SLA。

## 3. 实际图与版本

人工审核的符号计划经确定性编译构建Graph，**不是LLM自动生成成功**。5个必要接口阶段、5条真实输入依赖边，4层；来源抽取两分支合流，离线执行仍串行，无真实并发收益主张。

|节点|合同|上游|本轮执行|
|---|---|---|---|
|extract_stance|opinion_extract.v1|冻结任务来源|Stub，未调用模型|
|extract_followup|opinion_extract.v1|冻结任务来源|Stub，未调用模型|
|relate|opinion_relate.v1|extract_stance, extract_followup|确定性披露编号关系核验|
|assess|opinion_assess.v1|relate|Stub，未调用模型|
|report|opinion_report.v1|relate, assess|Stub，未调用模型|

边：extract_stance→relate；extract_followup→relate；relate→assess；relate→report；assess→report。各依赖有实际端口引用，所有节点贡献最终report。源事实和主张在relate输出继续传给后续，风险/可靠性判断合为一个受限节点，没有为了套模板增设独立新闻、检索或验证空分支。

Graph SHA256（canonical content_hash）：`f5d6919a0e19bb0b8a1510ebccb86a670e29e038df7d248b602b1dcbd2f73b6e`。文件原始字节哈希另见FREEZE_MANIFEST。原计划、图、上下文、语义来源信封、Stub轨迹独立保存在[opinion_typed_first_task_v1](opinion_typed_first_task_v1/)。

## 4. 逐事实与主张证据

8个必要文档字段、2条来源归属主张。跨度采用冻结页面Unicode码点半开区间，源PDF及页面文本哈希均进入EvidenceRef。Claim的value保留完整原文，不把否定句切成孤立金额/肯定结论。角色由人工审核的来源合同冻结，模型不得自报角色后被直接信任。

|ID|字段/主张角色|文档|位置|适用署期|原文|核验等级|
|---|---|---|---|---|---|---|
|fact_e529fa1e3b4d80481680|security_code|doc_a4947abf56ffa947dddf|p1 [0,11)|2026-08-10|证券代码：002456|SOURCE_ASSERTION_VERIFIED / world UNKNOWN|
|fact_e53cd8d8cb201a1546e8|announcement_id|doc_a4947abf56ffa947dddf|p1 [31,44)|2026-08-10|公告编号：2026-075|SOURCE_ASSERTION_VERIFIED / world UNKNOWN|
|fact_bf5508caecbf4086bcf6|document_signed_date|doc_a4947abf56ffa947dddf|p5 [339,352)|2026-08-10|2026 年8 月10 日|SOURCE_ASSERTION_VERIFIED / world UNKNOWN|
|fact_571866638ccd4617f525|security_code|doc_9e1253423f08b498d2c3|p1 [0,11)|2026-08-15|证券代码：002456|SOURCE_ASSERTION_VERIFIED / world UNKNOWN|
|fact_a37ae28e561d03a4b0fa|announcement_id|doc_9e1253423f08b498d2c3|p1 [31,44)|2026-08-15|公告编号：2026-077|SOURCE_ASSERTION_VERIFIED / world UNKNOWN|
|fact_890c9218a4703248d48a|document_signed_date|doc_9e1253423f08b498d2c3|p2 [142,155)|2026-08-15|2026 年8 月15 日|SOURCE_ASSERTION_VERIFIED / world UNKNOWN|
|fact_c87fea2c0173eaf7c222|referenced_announcement_id|doc_9e1253423f08b498d2c3|p1 [373,388)|2026-08-15|（公告编号：2026-075）|SOURCE_ASSERTION_VERIFIED / world UNKNOWN|
|fact_e8a2fcf69cd223dffdc9|independent_directors_meeting_date|doc_9e1253423f08b498d2c3|p1 [587,600)|2026-08-15|2026 年8 月14 日|SOURCE_ASSERTION_VERIFIED / world UNKNOWN|
|claim_d9e2f16d3604aa3877c3|issuer_denial_of_new_sika_transactions|doc_a4947abf56ffa947dddf|p4 [1081,1132)|2026-08-10|新思考发生的关联交易定价公允，不  存在利益输送情形，亦不存在技术无偿输送、成本转嫁及资金占用等情形。|SOURCE_ASSERTION_VERIFIED / world UNKNOWN|
|claim_474255629e7da067df3b|announced_independent_inquiry|doc_9e1253423f08b498d2c3|p1 [694,760)|2026-08-15|行使特别职权，独立聘请第三方中介机构就该报道所涉关联交易等相关事项进行  专项核查，向市场呈现更为客观、公正、中立、可信的核查结果。|SOURCE_ASSERTION_VERIFIED / world UNKNOWN|

“SOURCE_ASSERTION_VERIFIED”仅证明原文存在、对应主体/角色和定位正确。即使为官方公告，也不把其中利益输送否认认定为已独立证实的世界事实。

可确定性核验：证券代码、公告编号、署期原文、会议日期原文、引用2026-075编号、主体身份、 source/span/page版本、来源归属、两份材料链接。

仍UNKNOWN：传闻真实性、公司否认的现实真值、核查完成情况与结果、独立文本蕴含/语义冲突、风险严重程度、投资影响。独董启动调查与公司否认不是已证明的逻辑矛盾；未伪造冲突Gold。

## 5. 最小合同与接口

新增模块：`collab_scheduler_v1/typed_dag_v1/opinion.py`和`opinion_schema.py`。复用Graph/Node/Binding/Output、原结构验证与TypedExecutor初始化、状态及事件日志。

已有生产模块只作两处接线：protocol.validate支持**显式独立contracts注册表和类型化多输入**，默认数值CONTRACTS不变；TypedExecutor的结构验证入口变为可覆盖validate_graph。OpinionTypedExecutor是显式专用子类，旧数值入口仍拒绝舆情合同，不进行静默类型扩展。

EvidenceRef为嵌套证据对象；EventFact/Claim保留event/entity/role/value/time/span/version与UNKNOWN世界真值；ClaimRelation仅核验显式文档引用，不推断矛盾；RiskAssessment/OpinionReport仅保留有证据的状态及未知判断。各输出严格JSON Schema与来源语义校验独立进行。完整数值Computation IR和旧LLM规划协议不变；新opinion-plan.v1只用于本轮符号计划，当前数字规划器不能冒充已经支持自动舆情生成。

程序不补造事实、节点或公式。extract必须覆盖冻结事实和主张，不能用省略信息让准入通过；relate按两组合法多输入合流，保留原对象，重复或改动证据拒绝。报告缺引用、丢UNKNOWN或添加不受支持结论拒绝。

缓存key绑定Graph、节点、模型及版本、输入、输出合同、完整来源信封（含语义版本、截止及源哈希）；缓存命中仍做全输出Schema/来源/覆盖校验。旧无版本缓存不能命中。自有Stub缓存与历史缓存独立。

## 6. 零调用验收

31/31新任务与接线测试通过；27/27既有test_typed_dag数值协议、执行、工具计算、缓存与恢复回归通过。未把旧566项全部重复运行写作本轮结果。

覆盖：合法两源合流与报告；缺失事实/主张；错实体、错角色、错跨度、错来源版本；原PDF与文本不一致；未来输入；真值及风险越权；虚构关系；UNKNOWN丢失；报告引用遗漏；符号/目标缺失；环与死分支；缺端口；合法缓存复用、篡改缓存拒绝、模型版本差异与旧缓存拒绝；真实构建的Stub请求含对应输出Schema与单源候选。

结果为**STUB_INTERFACE_PASS**。两抽取、assessment与report均为Stub响应，relate为确定性来源关系工具；4次Stub接口调用，0次真实模型请求，没有伪报真实Token/费用。主观质量UNKNOWN，未声称真实TASK_SUCCESS或调度收益。

## 7. 首次真实执行准入与唯一阻塞

离线图可以正确编译和执行；**当前还不能宣称首次真实LLM舆情DAG执行READY**。唯一工程阻塞是：本版舆情输出Schema/语义信封尚未绑定到独立冻结的云端节点传输，当前可用适配器只有StubMeter。原数值云入口不能隐式接收这些新合同。

下一步仅需为该图接入一个真实云端节点传输并冻结模型身份、每节点输出限额、请求/费用/墙钟及无重试账本，先Mock核验同一完整请求，然后取得独立付费授权。无需扩大数据集或重复本地GPU预检。当前不提供会发送真实请求的命令。

可复核零调用命令：`cd /root/r3_own_pool && python opinion_typed_first_task_v1/CHECK_OFFLINE.py`；该命令核验全部新冻结文件、原数据集141份文件及临时Stub执行，绝不连接云API。来源/主观判断UNKNOWN属于应报告的研究边界，不通过放宽合同消除。

本轮到此停止。未修改旧KDX/ST、原始数据集、历史账本、奖励/预测/Qmin/epsilon或固定配置。
