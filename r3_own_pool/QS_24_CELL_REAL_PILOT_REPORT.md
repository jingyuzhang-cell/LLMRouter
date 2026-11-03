# QS24真实区分度Pilot：执行完成，完整质量矩阵未成立

**实际24/24请求全部完成，HTTP200为24/24；未重试、未追加、未触发全局停止。完整Q仅2/24可计算，22/24为UNKNOWN。**因此本轮没有形成可用于模型质量排名或Router训练的完整Q/C/L矩阵，不能把22个未知格当0分，也不能据此证明模型之间没有能力差异。

真实运行目录：[REAL_RUN_20261016_102901](qs_24_cell_execution_binding_v1/REAL_RUN_20261016_102901/)。运行从2026-10-16 18:29:01北京时间对应的UTC命名开始；精确UTC与单调起点见START_TIME.json。执行绑定SHA256为`f3d291ae18191cb55b79837cf809695c372afef29406909c8a9f3c3cce6d67d3`，原评分冻结SHA256为`fae5c7bccb052ef0f9ae5a2101caec0fac54b5e59652b6bb00e1b06e06985fa0`。本轮没有修改它们，没有GPU、Git或ZCODE变更。

## 1. 执行与费用

|项目|实际观测|批准上限|
|---|---:|---:|
|生成请求|24|24|
|输入Token|120,656|每请求60,000估费预留，非认证输入上界|
|输出Token|16,912|98,304总输出；每次4096|
|完整客户端墙钟|207.655秒|5400秒|
|人民币估费|¥0.39995490|¥5.00估费停止阈值|
|美元估费|$0.0130065|$0.25估费停止阈值|
|未知usage|0|遇到即全局停止|
|未执行单元|0|—|

实际账单仍待核验，cost_actual=null。上述费用按已记录真实usage与冻结公开价目估算，不是账户实际扣费；不跨币种换算。没有未知费用预留残留。D继续UNKNOWN，不计算按时收益或P90。

## 2. 全部六题的内容Q

|任务|Qwen-Flash|Qwen-Plus|DeepSeek-Flash|GLM-5.3|
|---|---:|---:|---:|---:|
|宏景更正增减额|UNKNOWN|1.0000|1.0000|UNKNOWN|
|宏景毛利与推断|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|
|上实诉请精度|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|
|上实诉讼阶段|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|
|欧菲光流量/余额|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|
|欧菲光声明归属|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|

只有同一“宏景更正增减额”任务上的Qwen-Plus与DeepSeek完整Q可比，均TP=6、FP=0、FN=0、UNKNOWN=0、F1分母12。该任务未观察到这两模型的质量差异，不支持跨任务或四模型排名。

## 3. Q、格式、证据和时延分开看

|模型（各6请求）|完整Q可计算|原生Schema通过|测量Contract通过|证据守卫通过|平均API客户端等待|Token输入/输出|估费|
|---|---:|---:|---:|---:|---:|---:|---:|
|qwen-flash|0/6|4/6|3/6|0/6|5.059秒|32,542 / 3,408|¥0.0099933|
|qwen-plus|1/6|3/6|3/6|1/6|18.608秒|32,542 / 4,920|¥0.0358736|
|deepseek-flash|1/6|6/6|6/6|0/6|2.823秒|27,355 / 4,000|$0.0130065|
|glm-5.3|0/6|6/6|6/6|0/6|7.699秒|28,217 / 4,584|¥0.354088|

合计Schema19/24、测量Contract18/24、Evidence守卫1/24。此处Contract是冻结的条件化测量结构/引用身份检查，Evidence守卫是冻结参考跨度覆盖检查；均不是完整TypedExecutor下传成功，也不等于真实事实正确率。

两条已知Q都没有通过全部证据守卫。Qwen-Plus该格原生Schema失败而Q=1，说明合同失败确实没有抹掉可计算内容Q。唯一Evidence守卫通过格是Qwen-Plus欧菲光声明归属，但完整Q仍UNKNOWN。完整Q、Contract、Evidence同时通过的格为0。

均值仅是本批六题一次观测的描述值；不同供应商Token定义、思考模式和时间窗口不同。API等待不是纯服务端推理时间；不能据此认证哪个模型通常更快、P90可靠或成本质量Pareto最优。

## 4. 为什么22格Q仍不可计算

逐原子共160个观测：冻结评分MATCH=18、UNKNOWN=140、WRONG=2。非MATCH原因记录：交易对手未解析61、角色未解析38、实体不在已接受表达中39、语义等价未证明2、期间不匹配2。原因有先后短路，后续内容未必均被独立裁决，不能把计数当成140个真实事实错误。

代表性原始证据：

- GLM宏景增减额`delta_1`输出role为“营业收入：更正后减更正前”，冻结角色是“营业收入更正后减更正前”，触发ROLE_UNRESOLVED，value原样为−136449740.67。至少存在表示边界导致未裁决的情况；未修改原结果。
- DeepSeek欧菲光采购项counterparty输出“新思考电机股份有限公司”，参考只接受“新思考”，触发COUNTERPARTY_UNRESOLVED；同时role输出“flow”。本轮不扩别名、不由Gold补写新判定。
- Qwen-Flash宏景`delta_1`把entity填写为“营业收入”、role为“delta”，触发实体未解析，同时value为正136449740.67。说明未知格也可能包含真实身份/方向问题，不能反过来把所有UNKNOWN都当表示正确。
- DeepSeek宏景毛利解释以“不支持；本次更正仅涉及……”长句回答，冻结的有限语义规则未证明整段等价，保持UNKNOWN。
- 两项冻结WRONG均由GLM的PERIOD_MISMATCH触发：输出“表列三个会计期间（2025年一季度、半年度、三季度）”及“2026-08-10与2026-08-15两份公告范围”，相对参考的短期间标签不完全匹配。不能单凭该代码就声称模型实际弄错了年份；历史冻结判定不改，也不在本轮另算侧评Q。

这些记录表明：离线夹具验收并没有保证真实模型表达落入有限匹配范围。**本轮暴露的是完整Q的可识别性仍不足，而不是已经测得22格内容质量差。**证据覆盖低同样不能解释成“只有1格的事实受到来源支持”；该指标要求覆盖冻结的行、单位、表头和身份跨度，是更窄的引用检查。

## 5. 研究裁决与停止

预登记Q≥0.95实际为2/24，但22格Q未知，不能用这一数字证明“天花板消失”。没有足够完整Q检验模型×任务优势反转，不能产生完整质量—成本—时延选择空间，更不能训练Router或自动推进QS-1000。

本轮已经完整执行获批矩阵，不再新增模型/任务/请求，不改Prompt、Gold、Contract或评分器，不把影子判断回填原分数。不提出自动开启下一轮付费实验。若后续讨论路线，必须基于本次失败边界，不能继续声称测量体系已在真实模型上稳定产出完整Q。

## 6. 交付证据

- [完整24格Q/C/L表及逐格状态](qs_24_cell_execution_binding_v1/REAL_RUN_20261016_102901/REAL_CAPABILITY_MATRIX.csv)
- [真实结果报告（含全部节点/模型行）](qs_24_cell_execution_binding_v1/REAL_RUN_20261016_102901/RESULT_REPORT.md)
- [结构化汇总及UNKNOWN原因](qs_24_cell_execution_binding_v1/REAL_RUN_20261016_102901/ANALYSIS_SUMMARY.json)
- [24格原始最终状态](qs_24_cell_execution_binding_v1/REAL_RUN_20261016_102901/ALL_CELL_STATUS.json)
- 各格REQUEST_BODY.bin、RESPONSE.bin、RAW_MODEL_OUTPUT.txt、EVALUATION.json、RECORD.json及全局LEDGER.jsonl完整保留。
- RAW_EVIDENCE_INTEGRITY_CHECK.json确认分析新增文件没有改动原请求/响应/账本；EVIDENCE_MANIFEST.json与SHA256覆盖本轮证据。账单仍待控制台核验，未打印Key。

**本批已结束并停止。结论是执行与C/L观测完成，完整质量矩阵准入未通过。**
