# extract_current 历史输出最终四状态审查

本次交付严格使用已冻结V4评价范围：6项年度合计、16组核心立场，共22项必要要求。此前用户所称Gold V3的金额/立场选择已在V4冻结，本轮不回退或另建Gold解释。没有修改Prompt、Contract、评分规则或旧输出。

## 1. 四模型Q及计数

|模型|TP必要项匹配|FP完整输出错误原子|FN必要项未完成|必要项UNKNOWN|Q_objective|
|---|---:|---|---:|---:|---|
|Qwen-Flash|2|UNKNOWN|20|0|null|
|Qwen-Plus|0–3|UNKNOWN|19–22|3|null|
|DeepSeek-Flash|3–9|UNKNOWN|13–19|6|null|
|GLM-5.3|2–7|UNKNOWN|15–20|5|null|

区间是未决必要项全部判为满足/未满足时的可识别计数范围，不是统计置信区间。已确认匹配分别为2、0、3、2。

**必要参考数为22；F1真正分母是`2TP+FP+FN`，不是22。**当前它不能数值确定，因为完整输出FP尚未穷尽裁决，且三模型的必要项仍有UNKNOWN。15项交易分项不作为必要FN；但错误的额外断言不能因此免评，不能把FP填0。WRONG表示必要项不满足，不等于相同数量的输出错误原子。

Qwen-Flash的必要项均可判定，不代表完整预测精度FP已经识别。其TP=2/FN=20也不能直接推导Q，且用户要求四模型均满足准入后才计算。因此本轮没有执行冻结score.py，也没有产生四个分数。

## 2. 完整逐必要项审查表

|必要项ID|必要内容|Qwen-Flash|Qwen-Plus|DeepSeek-Flash|GLM-5.3|
|---|---|---|---|---|---|
|l1_579439736091369a97d118ee|新菲光 2023合计 123.48万元|WRONG|UNKNOWN|UNKNOWN|UNKNOWN|
|l1_5069f8bbc5fc15889b889c8e|新菲光 2024合计 0万元|MISSING|UNKNOWN|UNKNOWN|MISSING|
|l1_9dbe03dfc6946fe4de2df6ac|新菲光 2025合计 0万元|MISSING|UNKNOWN|UNKNOWN|MISSING|
|l1_de12ccb7dfe44c432688b522|新思考 2023合计 32,645.74万元|WRONG|MISSING|UNKNOWN|UNKNOWN|
|l1_2c7ccbe65b1305b600cff1db|新思考 2024合计 43,195.48万元|WRONG|MISSING|UNKNOWN|UNKNOWN|
|l1_c4b4a9d454bb5f7c6a2b3a6a|新思考 2025合计 59,538.86万元|WRONG|MISSING|UNKNOWN|UNKNOWN|
|C01|研发体系及研发实施|MISSING|MISSING|MISSING|MISSING|
|C02|共享研发技术及专利|MATCH|MISSING|MISSING|MISSING|
|C03|承担研发亏损但工艺无合理对价复用|MISSING|MISSING|MISSING|MISSING|
|C04|人员混同|MISSING|MISSING|MISSING|MISSING|
|C05|报道所述人工/基础设施费用安排|MISSING|MISSING|MISSING|MISSING|
|C06|业务模式与产品线|MATCH|MISSING|MISSING|MISSING|
|C07|报道所述光模块相关产品的生产或代工|MISSING|MISSING|MISSING|MISSING|
|C08|人为压价向新菲光转移利润|MISSING|MISSING|MISSING|MISSING|
|C09|交易定价原则|MISSING|MISSING|MISSING|MISSING|
|C10|新思考取得控制权的来源|MISSING|MISSING|MISSING|MATCH|
|C11|报道所述VCM业务拆分及成本利润安排|MISSING|MISSING|MISSING|MISSING|
|C12|近三年主要关联交易方向与产品|MISSING|MISSING|MATCH|MISSING|
|C13|马达选定、规格、需求及价格|MISSING|MISSING|MISSING|MISSING|
|C14|关联交易的经营用途|MISSING|MISSING|MISSING|MISSING|
|C15|公允定价及否认利益输送|MISSING|MISSING|MATCH|MATCH|
|C16|技术无偿输送、成本转嫁及资金占用|MISSING|MISSING|MATCH|UNKNOWN|

四状态仅用于必要要求满足性。此前PARTIAL在此归为MISSING，表示**缺少完成冻结组合的必要内容**，不表示整条输出缺席或事实为假；此前细分类别、部分表达原文和理由完整保存在JSON/CSV。没有改变既有“组合不计部分TP”的评分规则。此前NOT_SATISFIED显示为WRONG，仍保留时间精度反证。

## 3. 原始证据和每个UNKNOWN的原因

[ATOM_REVIEW.json](extract_current_final_review_v1/ATOM_REVIEW.json)逐项保存完整模型原始对象、独立原文跨度、响应文件路径/哈希及裁决理由；[ATOM_REVIEW.csv](extract_current_final_review_v1/ATOM_REVIEW.csv)便于逐模型筛选。88项无遗漏或重复，所有引用的对象均与原始响应字节解析出的对象完全一致，未改字段。

金额检查另外列出实际声明的entity_id、time、field_role、unit、value及未声明的角色。未从local_id中的total字样、Gold值、证据片段或分项相加补写交易对手/合计身份。

- DeepSeek：6个合计必要项UNKNOWN；金额和年度候选存在，但缺少明确的交易对手与合计语义绑定。
- Qwen-Plus：新菲光三年合计UNKNOWN；新思考三年合计未输出，未根据分项相加生成答案。
- GLM：新菲光2023及新思考三年合计UNKNOWN；C16并列对象使否认范围待复核。不会因其entity_id使用交易对手而自动判实体错误。
- Qwen-Flash：两个零合计MISSING，4个有数值候选的合计因年度流量写成具体日而WRONG；公司立场的匹配、遗漏和不完整表达分开记录。此处错误不是由Contract=REJECTED推导。

例如DeepSeek的c2完整表达C12，c3表达C15/C16；Qwen-Flash的claim_2以“业务模式与产品线完全独立”满足C06，未因正常等价转述判错。GLM的C15使用原响应中两条明确陈述共同覆盖，未从参考补出未表达的信息。审查者是单一Codex开发审查者，属于事后来源裁决，未经过独立盲审复核，不能称自动语义真值认证。

## 4. 哪些可以进入能力矩阵

可以保存：22×4必要项覆盖、原子级UNKNOWN及mask、原始Schema/Contract/Evidence结果、真实Token、API往返与观测时间。它们是一个事件的条件化探索观测，保留历史采样时间差异。

不能保存为已识别量：完整Q点值、FP、成功概率、P90或模型优劣排名。实际费用待账单核验，未知不记0。不得用Contract失败替代Q，也不得用已确认匹配数/22替代F1，不接入Qmin保证。

## 5. 最终结论

本轮完成所请求的最后一次可判定性审查，没有发现新的Gold来源错误。阻塞已准确落到旧输出的角色/范围语义及完整输出FP裁决，不再笼统重复“Gold不足”。现有冻结信息未满足四模型Q的准入，不能合法运行评分器得到四个点值。

到此停止：不继续其他节点、不新增API、不修改规则或ZCODE、不启动GPU、不提交Git。保持具体UNKNOWN是本次审查的真实结果，不能为了得到第一个分数将其抹掉。
