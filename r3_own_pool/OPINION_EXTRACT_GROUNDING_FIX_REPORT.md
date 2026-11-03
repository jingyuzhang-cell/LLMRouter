# 抽取节点Evidence Grounding修复

**EXTRACT_QUOTE_GROUNDING_OFFLINE_READY。** 独立新版本`opinion-extract-quote.v1`已实现Schema、短Prompt、程序定位、来源/实体/字段守卫及22项零调用验证。没有真实API、GPU或历史记录修改；原DAG字节不变。

## 1. 当前失败的准确根因

真实extract_current/Qwen-Plus返回HTTP200，输入5164、输出4096 Token，finish_reason=length；文本在第7项事实的entity_ref中截断，节点未形成完整JSON。6个完整片段都至少有引用跨度错误，实际四类引用均出现不匹配。

旧输出重复生成4套EvidenceRef、64位SHA、offset、event/fact身份等，增加输出结构开销；同时把Unicode定位交给模型。它不是只缺Token预算，也不是所有金额都被证明错误。

原响应主体为facts；没有完整claims，更未进入风险节点。本次不把用户概括的“总结性内容”当作已证实的唯一失败原因；新Schema无论如何禁止解释/总结/风险字段。

只读尝试定位6个原始quote，3个可以唯一匹配，其余因重复引用拒绝。没有重写原offset、补全JSON、登记历史片段或回填质量。当前修复不能追溯改变原Pilot失败结论。

## 2. 新轻量传输合同

模型只返回：

```json
{"facts":[{"entity":"来源支持的实体","field_role":"合法字段角色","value":"原文值","unit":"原文单位或UNKNOWN","quote":"连续原文引用","source_ref":"给定文档或片段ID"}]}
```

只有这六个字段；additionalProperties=false，无完整答案enum、无结论const。禁止风险、解释、总结、claims、confidence、verified、fact_id、hash及offset。实体/字段词表在输入中用于约束引用，未提供预写事实值。

模型可以产生多个真实合理候选，不要求复现固定对象。候选ID、event_id、源版本及证据定位由程序从冻结上下文生成，属于来源元数据，不是补造事实内容。

[OUTPUT_SCHEMA.json](opinion_extract_grounding_fix_v1/OUTPUT_SCHEMA.json)、[PROMPT.json](opinion_extract_grounding_fix_v1/PROMPT.json)、[grounding.py](opinion_extract_grounding_fix_v1/grounding.py)分别保存机器合同、真实待用提示及可执行守卫。Prompt沿用原Graph的subtask与原任务问题，改变输出职责及格式，不更改任务目标。

## 3. quote_match及来源保护

输入由原5页公告完整分成6个窗口，保留原始页面位置、版本及绝对索引。所有原文都覆盖，不裁剪必要材料或按答案反选段落。

程序执行：

1. 源字节哈希、原PDF重新解析文本、片段ID、信息截止核验。
2. quote只在本次给定文档/片段窗口中作精确匹配；不做模糊纠错、空白替换或跨未提供片段拼接。
3. 重复quote返回QUOTE_AMBIGUOUS；重叠窗口内同一物理跨度去重，不把重叠误判为重复证据。
4. 唯一命中后生成page/start/end、原文quote、源hash与chunk血统。
5. 完整数值token校验，拒绝截取数字子串；可接受数值逗号格式差异，但不换单位、不算新值。
6. 实体必须由quote中的登记别名支持，或明确是冻结文档所属上市主体；后者只证明文档归属，不证明金额的交易对手/行列语义。其他交易对手不得仅凭同文档存在名字就绑定金额；多交易对手引用歧义也拒绝。
7. field_role须属于节点词表；明确实际/预计冲突时拒绝。词面证据不足为UNKNOWN，不升级成语义正确。
8. 单位须在给定引用窗口存在。窗口单位仅为词面代理，不冒充完整表格列映射认证。

不合法候选记为invalid_fact，原始模型输出哈希保持一致。任一候选失败时整批不登记，也不只挑有效子集使节点PASS；空数组是弃权，不是成功。

登记状态为**SOURCE_GROUNDED_CANDIDATE**，不是verified world fact。适用会计期间与value_scope在短格式中未独立核实时保持UNKNOWN；程序不会补缺失的时间或角色。

## 4. 与Contract V2、原图的兼容边界

Contract V2总体原则不变：开放候选、无答案泄漏、来源身份/截止/血统硬保护、语义不确定性分层。旧V2冻结Schema及质量协议不覆写；新版本是extract_current单节点传输覆盖，绑定同一原图哈希。

原图结构和依赖不变。但原完整V2消费者仍要求其他fact字段及claims端口；本轮不静默填time、confidence或claims去骗过旧消费者。因此当前可以在**单节点QuoteValidator**验证真实待用抽取输出，不能直接声称完整六节点已兼容。后续全图应用需显式版本绑定消费者，并保留原必要主张信息；不能跳过原图所需内容。

原始DAG哈希：`e2878846a22e10f1e6a92481f845969ab99e96aed04f3275f29fa786e97f4b53`。所有来源、截止和原真实失败文件重核未改变。

## 5. Token控制与Q/C/L可测性

单事实结构从原4套引用及元数据收缩为6个短字段；模型无需生成任何offset/hash。对原6个完整片段只做字节结构投影：原6124字节，新781字节，减少87.2%。这是格式开销审计，**不是云Tokenizer计数、修复后的真实输出或质量提升证据**。

下一次只针对extract_current建议max_output_tokens=1024（512可作更小方案，但本报告优先1024），不承诺一定完整。Prompt明确不输出长解释，不穷举无关金额，也不能为了预算省略必需事实；截断仍按失败保留。

各模型使用同一原文、chunk版本、Prompt、Schema与Validator，可以测源字面grounding、实体/引用准入及invalid_fact率；模型无需猜测位置造成无意义格式差异。source_grounding_rate按值/quote支持单独计量，单位或实体错误不会被误写成quote错误；事实语义precision/recall仍UNKNOWN，未改成通过率。

C记录真实usage及账单待核验，L记录真实API/节点单调时延；本轮无真实C/L样本。单次通过也仅证明抽取定位接口，不能证明模型能力差异或动态路由收益。

## 6. 零调用验证

22/22通过：正例登记；无答案enum/const且禁止offset/风险字段；错误quote；缺/错source；重复quote歧义；未知/跨交易对手实体；部分数字；错误value/unit/field；给定chunk ID；事务登记拒绝；未来来源；伪造解析文本；空输出；长文本全覆盖；重叠窗口去重；未给定跨块引用拒绝。

正例直接来自原公告，只用于离线接口fixture，不进入Prompt、真实样本或Gold。真实历史quote定位诊断也不进入模型输入。

## 7. 下一次最小真实Pilot

**最多1次Qwen-Plus生成请求**，仅执行原extract_current节点，最大输出1024 Token，单请求120秒，完整客户端180秒草案。不运行其余节点、不重试、不恢复、不追加模型评审。源版本、别名身份、Prompt/Schema/输出原件、程序定位结果、invalid_fact原因、usage与时延均独立记账。

若要后续三模型对比则需另批3请求，不能由这次单节点授权自动延伸。输入Token和实际费用上界仍未认证，必须取得新的独立探索性费用授权；原18请求Pilot已经结束，不沿用余量。

建议授权文本：批准一次quote-grounding抽取Pilot，最多1次qwen-plus请求、最大输出1024 Token、单请求120秒、完整客户端180秒；接受未认证输入Token和实际费用风险；失败不重试，不执行下游、恢复或路由。

本轮仅准备，到此停止，等待独立真实调用授权。
