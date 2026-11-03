# OPINION_MULTINODE_EVIDENCE_VNEXT_V1

结论：**统一接口及引用型合流已达到 TECHNICAL_READY；真实执行 HOLD，等待独立新版本付费授权。** 本轮0真实API、0凭据读取、0GPU。只建立新版本，没有修改旧合同、原GRAPH、历史响应或ZCODE/DD-V4。

新目录：`/root/r3_own_pool/opinion_multinode_evidence_vnext_v1/`。

## 1. 三个抽取节点统一证据接口

extract_current、extract_media、retrieve_history现在使用同一原始输出Schema：`facts[] + claims[]`。Fact包含局部ID、实体、角色、数值、单位、期间、口径、声明来源、原文quote，以及分别支持实体/角色/期间/单位的quote声明；Claim包含局部ID、提出者、目标、主张、时间、类型、来源和quote。模型不输出字符offset、文档哈希或verified标签。

每个quote声明只能含source_ref、space、quote。程序查验**模型声明且节点允许的来源**，唯一定位后生成原始页码、Unicode起止位置、来源SHA256。source_ref是chunk时，只在那个chunk内搜索；不会退回整篇文档或另选chunk。source_ref是允许的文档时，在已提供的该文档页内搜索，多个位置一律拒绝。完整原文、无关来源的元数据不混入其他节点。

Prompt明确提供allowed_source_ids、allowed_chunk_ids、该节点来源材料及必要标题/时间/发布者/哈希元数据。新闻节点不再看到forecast/current/prior_revision的文档元数据。公开实体词汇仍可供身份引用，但不携带其他来源事实或评分答案。原始来源全文保持，无裁剪必要内容来控制输出。

当前公告保留旧的六个chunk身份，便于复现错误引用；新闻和历史文档建立版本化页级chunk。新contract.py统一解析，原错误chunk不获替换。

原生Schema、原生完整合同、适配后Schema、证据守卫和transport_format_violation分别记录。仅extract_current保留明确的裸Fact数组顶层封装，绝不补事实字段或改quote；其余节点裸数组不推测用途。重复JSON键、非JSON数值及额外字段拒绝。

## 2. 角色、期间、单位与真实性边界

- 实体必须存在且其独立身份quote包含注册别名；数值仍按完整数字token验证，不能用数字子串充当支持。
- 每个事实的实体、角色、期间、单位引用必须来自同一文档；跨文档借单位拒绝。
- 角色按节点词汇与来源线索检查；已知应收/应付/负债等余额不得登记成交易发生金额。预计、暂估、实际口径不自动替换。
- 已声明期间必须有quote；无期间证据只能time=UNKNOWN。来源只给年度时不能凭空加某月某日。21个金额单元和1个签署日期的确定性来源参考用于限定范围核验，不能进入模型Prompt，也不作为完整任务Gold。
- 在该来源表格可识别的范围内，错误列期间、实体、金额角色或单位拒绝；范围外语义、实体与金额的复杂归属仍为UNKNOWN或proxy，不宣称自动蕴含证明。
- ISO/中文日期可以通过确定性日历组件比较，但原value和quote保持；无效日历日期拒绝。日期unit明确为null，不把签署日期当事件发生或公告发布时间。
- 跨页单位必须同时满足：声明的unit_evidence精确存在、同文档/版本、明确单位文字、经过原PDF列几何复核的续表证书及限定行范围。已验证page3余额表头→page4两行；范围外继续拒绝。不会自动填unit或从任意前页借用“万元”。此为新版本证据路径扩展，不回写旧UNIT拒绝。

因此本次增强的是可验证引用与已知不一致拦截，不是让所有语义判断都变成verified。

## 3. reconcile不再要求模型完整复制对象

新原始输出仅：

```json
{"relations": [{"relation_id":"...","event_id":"...","fact_ids":[],"claim_ids":[],"relation_type":"UNKNOWN","evidence_refs":[],"rationale":"..."}], "unresolved": [{"unresolved_id":"...","statement":"...","fact_ids":[],"claim_ids":[],"reason":"UNKNOWN"}]}
```

这是结构示意，不是固定答案。关系引用必须指向登记表中现有且未变更的对象，事件身份匹配；其证据quote只能来自所引用对象贡献的文档。已知实体/期间/口径不同，不能直接标成CONTRADICTED或SUPPORTED。语义关系准确性继续UNKNOWN。

**每个上游fact/claim必须被关系或显式未决项覆盖**，禁止通过省略输入减少核验工作；UNKNOWN/INSUFFICIENT_EVIDENCE及未决项必须保留。程序按不可变登记表恢复原facts/claims端口，不调用模型补全，不改变对象内容；缺ID、上游被修改、漏覆盖均拒绝。关系登记后也有内容哈希保护。

assess/report新版本额外携带unresolved_ids，要求完整传递未决项ID；不要求唯一风险结论或报告全文。该机制证明未决状态未静默丢失，不证明自然语言报告已充分解释所有不确定性。

同一手工Stub来源输入下，旧合流原始输出38,617字节，新输出1,802字节，**减少95.33%**（规范UTF8 JSON口径）。程序恢复的对象哈希保持一致。这不是实测Token节省率、时延加速或对历史105秒ReadTimeout的因果解释。

## 4. 图和执行器兼容

原GRAPH仍为6节点6边，节点、依赖、来源和目标不变。EXECUTION_OVERLAY.json显式声明新原始Schema与程序端口适配，原output_contract字符串不被偷偷改写。

executor.py为独立TypedExecutor子类：复用原Graph解析、类型/拓扑检查和基础状态，按原始Binding合流数据；替换的只是新版本输出接收与证据登记。SCHEMAS.json同时声明模型原始输出、程序规范化输出和节点输入类型，null日期单位/UNKNOWN期间引用亦显式版本化。程序恢复合流facts/claims后，原下游依赖可以正常消费。

同一原图六节点Stub端到端通过。Stub及其上游都是**人工来源夹具迁移，不是历史模型成功、不是Gold、不是新真实执行**。新缓存键绑定合同/Schema、模型身份、节点输入、源版本、chunk、单位证书和上下游对象哈希；命中后重新校验，新旧版本不可混用。

## 5. 自动质量记录

|类别|记录|边界|
|---|---|---|
|格式/合同|raw_schema_pass、raw_contract_pass、adapted_schema_pass、evidence_guard_pass、adaptation_type、transport_format_violation|适配成功不等于模型原生成功|
|确定性引用|合法来源率、quote唯一定位率、来源截止有效性、实体别名证据率、数值支持率|quote存在不等于事实语义正确|
|限定L1|匹配表格/签署日期的字段准确性，角色/期间准确性及明确分母|只针对可匹配参考，未匹配事实不偷算正确；不称完整precision/recall|
|proxy|事实语义绑定守卫通过率、参考范围覆盖、声明支持|不能作为任务级质量保证|
|UNKNOWN|完整事实精确率/召回、未评分角色与期间、关系蕴含、主观风险与未来影响|不构造伪Gold或模型自评标签|

所有候选和失败都保存。节点输出原子登记，部分候选通过不意味着整个输出成功。实际Token/费用/时延只有真实调用后才填写，本轮保持未测。

## 6. 已有真实输出的影子回放

旧响应不具备新完整字段，因此严格按新Schema回放时三个输出均REJECTED，登记0；不把任何映射后的对象称为原生新合同成功。

额外仅提取**原来声明的来源和原quote**做诊断，不改引用、不登记：

|历史节点|可唯一定位/总引用|仍拒绝|
|---|---:|---|
|extract_current|10/15|原facts[9—13]仍绑定错误chunk，不回退到第4页|
|extract_media|3/6|三条新闻claim的quote可定位；三条fact仍引用越权文档|
|retrieve_history|1/10|首条quote可定位，其余含不存在的quote或越权来源|
|reconcile|不可回放|历史无响应；服务端完成状态仍UNKNOWN|

去掉offset不代表旧历史输出全变正确；历史正式REJECTED及ReadTimeout原样保留。

## 7. 针对性验证与冻结

17项必要测试覆盖：三节点共用定位、错误chunk、不合法来源、歧义quote、跨页单位证书、金额/实体/角色/期间错误、合流合法ID与全输入覆盖、上游突变、UNKNOWN传播、缓存版本/模型隔离、原图六节点Stub执行、未来材料、日期、原始字节不变、四模型等价Prompt/无答案enum及付费启动器Mock正常/超时停止。未重跑数百项无关回归。

OFFLINE_TEST_RESULT.json、OFFLINE_TYPED_TRACE.json、SHADOW_REPLAY.json及冻结清单为证据。仅复核相关旧冻结包50份文件与本次失败运行45份证据，确认未改；没有重做全项目审计。数值Typed DAG和调度算法未修改。

## 8. 四模型公平性与下一次最小请求

使用既定qwen-plus、deepseek-flash、glm-5.3、qwen-flash；同节点四模型的消息、来源、Schema、守卫、质量规则和输出上限完全相同。节点间依据业务职责具有不同输入。GLM沿用思考low，Qwen/DeepSeek为非思考：比较的是公开参数下的服务配置，不声称仅权重差异的因果实验。当前账户余额和权限没有重新API核验，运行时拒绝身份/账户错误，不模拟缺失模型。

建议下一轮先验证本次改变的四个节点，不重复额外权限探针：

|模式|请求|输出上限|总输出上限|完整客户端墙钟|
|---|---:|---|---:|---:|
|qwen-four|4（Qwen-Flash各1）|3抽取各16,384；reconcile 4,096|53,248|900秒|
|four-model-sixteen|16（同4节点×4模型）|同节点同上限|212,992|2400秒|

三个抽取保留既有16,384输出 allowance，不以缩短输出裁剪必要事实；只降低引用型合流输出预算。每请求客户端120秒，connect/read=15/105秒，独立父watchdog提前60秒收尾；不重试、不修复、不换模型。Schema/证据失败记录该格后按独立固定输入继续；账号/身份/接口/未知usage错误停止整批；未知远端完成及费用保留，不自动续采。

这两种模式都是**固定合法前置状态下的节点能力测量**，合流使用统一来源验证的Stub前置，不能冒充新真实抽取结果驱动的完整DAG。完整六节点24格模板已生成，但最小启动器不开放该规模，不擅自扩大。完整DAG真实业务执行仍需独立授权与方案。

每格实际输入Token上界和现金上界仍未认证；REQUEST_BUDGET.json只记录实际序列化字节数，不用其他Tokenizer冒充认证。GLM绝对价格仍未认证，16格模式必须另行明确接受该费用风险。费用只在usage/账单可得后记录，不能沿用旧¥2阈值假称新四模型现金上限。旧授权均不适用于本版本。

## 9. 准确命令与最终准入

新启动器默认零调用：

```bash
PYTHONDONTWRITEBYTECODE=1 python /root/r3_own_pool/opinion_multinode_evidence_vnext_v1/START.py
```

独立批准4请求探索风险、凭据用途和新冻结版本后：

```bash
python /root/r3_own_pool/opinion_multinode_evidence_vnext_v1/START.py --execute --mode qwen-four --authorization /absolute/path/approved_vnext_qwen_four.json
```

若直接批准四模型16格：

```bash
python /root/r3_own_pool/opinion_multinode_evidence_vnext_v1/START.py --execute --mode four-model-sixteen --authorization /absolute/path/approved_vnext_four_models.json
```

从相应AUTHORIZATION模板生成独立文件；approved默认false，freeze_sha256必须填新FREEZE_MANIFEST的SHA256。永久排他派发标记不自动清除；两个规模是互斥选项，不自动串联。没有本轮付费授权便不会读取凭据或派发。

**七项直接回答：**三个抽取已统一quote定位；不能自动改选来源；合流复制负担已显著减少；保留来源/实体/数值/期间/口径约束及UNKNOWN边界；四模型可按相同新协议比较但需披露思考配置差异；最小为4请求、四模型同节点比较为16请求；**技术READY，真实执行HOLD仅待新版本独立付费授权**。本轮完成后停止，不追加预检或真实实验。
