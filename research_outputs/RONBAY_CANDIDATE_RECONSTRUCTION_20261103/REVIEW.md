# 静态异构候选重构：科学证据与边界

本轮仅使用既有46份响应及其冻结审阅记录，零API、零GPU。原三臂暂停，C优先推荐仍撤回。以下资格是开发探索中的相对证据分层，不是新增通过门禁或可靠性认证；没有任何方案获得完整终端资格。

## 五节点×四模型资格矩阵

K为合同；F为事实PASS/FAIL/UNKNOWN；S为事实正确且证据支持数/既有审阅分母。S计入K失败输出的内容诊断，不代表合法可交付质量。INQUIRY完整T1超出单来源输入范围，不能以UNKNOWN判模型事实能力差。

| 节点 | 模型 | K逐次 | F(P/F/U) | S | 均值估费¥ | 均值秒 | 资格解释 |
|---|---|---|---|---|---:|---:|---|
|INQUIRY|glm53|PASS/FAIL/PASS|0/0/3|0/3|0.045743|16.674|条件候选，存在合同失败|
|INQUIRY|glm53flash|FAIL/FAIL/FAIL|0/0/3|0/3|0.005118|19.733|重复合同失败，不优先|
|INQUIRY|deepseek|PASS/FAIL/FAIL|0/0/3|0/3|0.020368|7.787|条件候选，存在合同失败|
|INQUIRY|qwen|PASS/PASS/PASS|0/0/3|0/3|0.003447|16.942|仅观测合同稳定，Q仍受限|
|REPLY|glm53|PASS/FAIL/PASS|12/0/6|12/18|0.092887|16.648|条件候选，存在合同失败|
|REPLY|glm53flash|PASS/FAIL/FAIL|12/0/6|12/18|0.008713|14.661|条件候选，存在合同失败|
|REPLY|deepseek|PASS/PASS/FAIL|13/0/5|13/18|0.032067|7.367|条件候选，存在合同失败|
|REPLY|qwen|FAIL/FAIL/FAIL|3/0/15|3/18|0.008232|21.662|重复合同失败，不优先|
|OBLIGATIONS|glm53|PASS/PASS/PASS|12/0/0|12/12|0.093508|22.426|仅观测合同稳定，Q仍受限|
|OBLIGATIONS|glm53flash|PASS/PASS/PASS|12/0/0|12/12|0.009208|16.034|仅观测合同稳定，Q仍受限|
|OBLIGATIONS|deepseek|PASS/PASS/PASS|11/0/1|11/12|0.030645|5.875|仅观测合同稳定，Q仍受限|
|OBLIGATIONS|qwen|PASS/FAIL/FAIL|3/0/9|3/12|0.008569|19.136|条件候选，存在合同失败|
|CROSSCHECK|glm53|PASS/PASS/PASS|16/0/2|16/18|0.116431|19.206|仅观测合同稳定，Q仍受限|
|CROSSCHECK|glm53flash|PASS/PASS/UNKNOWN|10/0/2|10/12|0.011293|16.385|仅观测合同稳定，Q仍受限|
|CROSSCHECK|deepseek|PASS/FAIL/NOT_DISPATCHED|11/0/1|11/12|0.039020|7.397|条件候选，存在合同失败|
|CROSSCHECK|qwen|FAIL/FAIL/FAIL|5/1/12|4/18|0.011008|20.866|重复合同失败，不优先|
|FINAL|glm53|NOT_DISPATCHED/NOT_DISPATCHED/NOT_DISPATCHED|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|无响应，未知|
|FINAL|glm53flash|NOT_DISPATCHED/NOT_DISPATCHED/NOT_DISPATCHED|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|无响应，未知|
|FINAL|deepseek|NOT_DISPATCHED/NOT_DISPATCHED/NOT_DISPATCHED|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|无响应，未知|
|FINAL|qwen|NOT_DISPATCHED/NOT_DISPATCHED/NOT_DISPATCHED|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|无响应，未知|

原始逐次Token、成本、时延、K错误、条件语义和审阅引用均保存在配套JSON的repeat_records，不只保留均值。CROSSCHECK Flash第三次结果未知、DeepSeek第三次未派发，二者都不算零质量。FINAL四模型全部未派发。三次同事件重复不能保证稳定可靠。

## 有限候选比较

仅比较四同构、原C，以及针对已经观察到的具体瓶颈提出的三个候选；不枚举模型组合后挑最高分。F=Flash，D=DeepSeek，Q=Qwen，G=完整版GLM。

| 候选 | INQUIRY/REPLY/OBLIGATIONS/CROSSCHECK/FINAL | 前四节点估费¥ | 前四节点服务时间和秒 |
|---|---|---:|---:|
|All-glm53|glm53 / glm53 / glm53 / glm53 / glm53|0.348568|74.955|
|All-glm53flash|glm53flash / glm53flash / glm53flash / glm53flash / glm53flash|0.034333|66.813|
|All-deepseek|deepseek / deepseek / deepseek / deepseek / deepseek|0.122100|28.427|
|All-qwen|qwen / qwen / qwen / qwen / qwen|0.031256|78.605|
|C|deepseek / deepseek / glm53flash / glm53flash / glm53flash|0.072936|47.573|
|C1|qwen / deepseek / glm53flash / glm53flash / glm53flash|0.056015|56.728|
|C2|qwen / deepseek / glm53flash / glm53 / glm53flash|0.161153|59.549|
|C3|glm53 / deepseek / glm53flash / glm53flash / glm53flash|0.098311|56.460|

这些组合量包含全部已观测重复，不因K失败删除成本/时延。它们不是完整DAG实际费用或Makespan，缺FINAL、真实父输出及失败阻断影响，不据此排序完整Q或宣布Pareto赢家。所有方案终端Q/C/L均UNKNOWN。

## 节点资格与重复机制

- **INQUIRY：** Qwen K3/3，完整版GLM2/3，DeepSeek1/3，Flash0/3。当前最有根据的是Qwen的合同稳定性与低估费，不是已证明事实更好。DeepSeek cell05、08重复违反UNKNOWN.value=null；08还引用本节点而非实际父claim。根节点没有父模型，这些错误不可能是上游模型传播导致。Flash出现同节点引用、UNKNOWN和额外字段问题。三次都通过也不能推出未来成功率为100%。
- **REPLY：** DeepSeek与完整版GLM均K2/3；Flash1/3；Qwen0/3。DeepSeek支持4/6、4/6、5/6，但第三次有额外字段导致不可合法消费。前两次T3未完整明确最低采购具体量未披露；不能将引用原文中有该内容当输出已经表达。完整版GLM无明确覆盖优势且更贵，故DeepSeek是条件候选，不是已认证稳健提取器。
- **OBLIGATIONS：** Flash和完整版GLM三次均K PASS且支持4/4；Flash成本较低。DeepSeek三次K PASS，支持3/4、4/4、4/4且更快；这是一项质量覆盖—时延权衡，尚不是稳健质量优势。Qwen仅1/3 K，三次都支持1/4，当前不优先。
- **CROSSCHECK：** Flash两次K PASS但T1两次UNKNOWN；DeepSeek一次完整支持、另一次K失败；完整版GLM K3/3，支持6/6、6/6、4/6，不可删除第三次。Qwen三次K FAIL，第二次有明确T3事实错误及T4证据链缺失，不能凭便宜选作汇合节点。完整版GLM是有依据的质量保全候选，但与Flash均值支持覆盖接近且成本高，不构成已证明的支配关系。
- **FINAL：** 所有模型UNKNOWN。任何完整候选都含无测量支持的末节点。沿用Flash是保持机制对照一致及较低价格的设计选择，必须披露，不声称经过质量优化。

日期与条件缺失仍沿用既有UNKNOWN；本轮没有重评分或将UNKNOWN改成WRONG。资料内事件归属错误、输出未覆盖、原文未提供和合同失败是不同原因，不能合并成一个“模型质量差”。

## 传播机制：已观察与尚未知

| 问题 | 已有证据 | 能否回答真实传播 |
|---|---|---|
| 上游错误会否被继承 | 冻结依赖合同要求消费父记录；无真实模型父输出链 | 未知，不能把潜在路径当已发生传播 |
| 下游会否识别/纠正上游错误 | OBLIGATIONS输入为核对过的夹具，含条件与UNKNOWN边界 | 未知；12/12不能解释为修复DeepSeek遗漏 |
| 输入充分是否仍日期遗漏 | Flash cell36引用INQUIRY:DATE却遗漏notice_signature；43把公司公告落款称为问询函落款 | 已观察下游整合失配，不是上游缺材料 |
| 引用正确是否等于证据支持 | Qwen cell41 T3称触发条件未披露，E0080实际列条件；T4缺预测量引用且不消费父记录 | 已观察ID存在仍有语义错误/证据不全 |
| 混合模型会否放大或纠正 | 所有节点独立使用同一固定父夹具 | 未知，无模型组合间的传播因果对照 |
| 独立能力能否预测终端Q | 无FINAL，无完整DAG实测 | 未知，不能连乘K率或拼接答案估终端质量 |

关键来源：上一轮科学复核REVIEW.md，以及原批次analysis/REVIEW_05、08、15、18、21、27、30、33、36、41、43。CROSSCHECK输入夹具明确提供INQUIRY:DATE.notice_signature=2026-01-14、receipt=2026-01-13，因此Flash日期问题有“信息已在输入但输出未充分保留”的具体证据。它不证明模型本质上无法处理日期，也不证明FINAL无法纠正。

## C与C1：为何只提升候选依据，不宣布胜出

C=D/D/F/F/F；C1=Q/D/F/F/F。仅INQUIRY不同，故两者共享REPLY不完整、CROSSCHECK日期问题及FINAL缺测风险。

将根节点换Qwen依据是K3/3对1/3，节点均值估费约¥0.003447对¥0.020368；代价是平均响应约16.94秒对7.79秒。事实质量在完整T1口径下双方UNKNOWN，不能声称Qwen更准确。C1前四节点组合估费约比C低23.2%，服务时间和约高19.2%，这些只是测量组合，尚未包含合法完成概率和FINAL。

因此C1比C更适合检验“合同瓶颈缓解能否传递到终端”，但不适合直接宣布是更优分配。此选择来自已曝光开发数据，属于事后形成的研究假设，需要新响应验证，不能用这46份响应同时选优又证明胜出。

C2=Q/D/F/G/F是第二层候选，针对Flash汇合日期失配，但加入另一干预且显著增费；完整版GLM第三次仍有遗漏。C3=G/D/F/F/F的根节点比Qwen更贵、略快、合同并非更稳定，没有充分理由优先执行。全GLM可作为质量侧比较候选，但同样FINAL未知；全Flash和全DeepSeek是必要资源侧基线，不应冠以已验证强终端基线；全Qwen根节点表现不能抵消其下游重复失败。

## 最有价值的下一实验及可证伪边界

**优先候选是C1，优先科学实验是C对C1的单节点替换、真实父输出完整DAG对照。** 这不是立即启动授权，也不是重开原三臂批次。

只改变INQUIRY分配，保留其余模型、DAG、合同、来源、重试、预算及顺序控制；所有父记录必须来自当次真实执行。主要检验根节点合法输出差异是否带来完整FINAL交付及有证据事实的改善，分别报告事实、证据、覆盖率和完成率，不用完成率替代Q。记录事实从父到子的保留、丢失或新增；其中新增正确内容还可能来自下游直接阅读原文，不自动归功于异构协作。不能人为注入错误或删除失败样本。

C与C1在真实根输出之外仍可能随机不同，因此单对照只能估计换根模型的总体效应，不能完全识别“错误纠正能力”的因果机制。模型提示、父ID绑定等变化须各组一致，不可借实验单独修好一臂。

允许负结果：C1无改进、因更慢而超时、两者均被REPLY阻断、汇合持续丢信息、FINAL全部失败、完成率提高但终端证据变差。无论何种结果均不能临时加入C2或追加样本。真正RQ2的异构对强同构确认仍需另行冻结独立任务和配对方案，本轮不声称机制对照即可证明普遍静态收益。

当前无法回答：长期模型能力稳定性、实际上游输入泛化、组合纠错/放大效应、完整终端Q、实际端到端成本与时延、跨事件Pareto优势。现有证据支持候选优先级和风险定位，不支持“找到了最优方案”。本轮完成后停止，零新批次、零调用；原三臂计划保持暂停。
