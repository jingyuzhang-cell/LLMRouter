from pathlib import Path
import json,csv
P=Path(__file__).resolve().parent
M=json.loads((P/'MATRIX_20.json').read_text());R=json.loads((P/'REPEAT_OBSERVATIONS_60.json').read_text())['rows'];S=json.loads((P/'STATIC_COMPOSITION_ESTIMATES.json').read_text());T=json.loads((P/'COMMON_REPEAT_SENSITIVITY.json').read_text());rank=json.loads((P/'RANKINGS.json').read_text())
lab={'glm53':'GLM','glm53flash':'Flash','deepseek':'DeepSeek','qwen':'Qwen'}
f=lambda x,d=3:'UNKNOWN' if x is None else f'{x:.{d}f}'
def counts(v):return 'UNKNOWN' if v is None else '/'.join(str(v[k]) for k in ['PASS','FAIL','UNKNOWN'])
lines=[]
for r in M:
 lines.append(f"|{r['node']}|{lab[r['model_key']]}|{r['attempted_n']}/{r['response_PASS_n']}/{r['response_UNKNOWN_n']}/{r['NOT_DISPATCHED_n']}|{r['K_PASS_n']}/{r['K_FAIL_n']}|{counts(r['fact_counts'])}|{counts(r['semantic_evidence_counts'])}|{f(None if r['CNY_equivalent_estimate'] is None else r['CNY_equivalent_estimate']['mean'],6)}|{f(None if r['L_seconds'] is None else r['L_seconds']['mean'])}|")
ranklines=[]
for r in rank:
 n=r['node'];a=[v for v in M if v['node']==n];k='；'.join(f"{lab[v['model_key']]} {v['K_PASS_n']}/{v['response_PASS_n']}" for v in a);q='；'.join(f"{lab[v['model_key']]} {v['supported_correct']}/{v['fact_counts']['denominator']}" for v in a)
 ranklines.append(f"|{n}|{' < '.join(lab[m] for m in r['cost_order'])}|{' < '.join(lab[m] for m in r['latency_order'])}|{k}|{q}|")
flash=[]
for n in ['INQUIRY','REPLY','OBLIGATIONS','CROSSCHECK']:
 g=next(r for r in M if r['node']==n and r['model_key']=='glm53');h=next(r for r in M if r['node']==n and r['model_key']=='glm53flash')
 flash.append(f"|{n}|{1-h['CNY_equivalent_estimate']['mean']/g['CNY_equivalent_estimate']['mean']:.1%}|{h['L_seconds']['mean']/g['L_seconds']['mean']-1:+.1%}|{g['K_PASS_n']}/{g['response_PASS_n']} → {h['K_PASS_n']}/{h['response_PASS_n']}|{g['supported_correct']}/{g['fact_counts']['denominator']} → {h['supported_correct']}/{h['fact_counts']['denominator']}|")
comps=[]
for r in S['A_to_E']:
 comps.append(f"|{r['label']}|{' / '.join(lab[r['assignment'][n]] for n in ['INQUIRY','REPLY','OBLIGATIONS','CROSSCHECK'])}|{r['partial_mean_cost_CNY']:.6f}|{r['partial_service_time_sum_seconds']:.3f}|UNKNOWN|UNKNOWN|")
repeats=[]
for r in R:
 countsval='UNKNOWN' if r['fact_counts'] is None else counts(r['fact_counts'])
 repeats.append(f"|{r['index']+1}|{r['node']}|{lab[r['model_key']]}|{r['repeat']}|{r['response_status']}|{r['contract_status']}|{countsval}|{'UNKNOWN' if r['input_tokens'] is None else r['input_tokens']} / {'UNKNOWN' if r['output_tokens'] is None else r['output_tokens']}|{f(r['CNY_equivalent_estimate'],6)}|{f(r['wall_s'])}|")
text='''# 四模型跨节点能力异质性与静态分配潜在收益

**结论：已有可利用的节点差异信号，但尚无完整静态异构分配收益证据，Dynamic-π仍不具备充分实测依据。** 本轮零模型调用，仅分析已关闭批次；未修改原始响应、历史评分、冻结评分器、运行器或ZCode。未重启、未补跑。

## 证据身份与计量范围

- 对照冻结60条顺序，逐一读取47条派发账本、46份REQUEST/RESPONSE/ACCOUNTING/MEASUREMENT、46份既有Silver评分和20单元矩阵，身份、用量账本、响应哈希及汇总一致，差异清单为空。
- 46份有效响应是JSON/usage层面的有效，**不是46份合法或正确节点输出**；既有合同诊断27 PASS、19 FAIL。第47次Flash/CROSSCHECK为派发后结果UNKNOWN，不认定服务商失败；最后13次NOT_DISPATCHED。
- 14单元有3份响应，2单元有2份响应，FINAL四单元无响应。所有单元原计划3次。无响应的Token、费用、时延、质量均为null/UNKNOWN，不以0冒充观测；次数0仅表示未观测。
- 实测输入326,395 Token、输出49,975 Token；公开牌价估费¥1.231177+$0.040910，按冻结8折算¥1.558457。失败/未知请求预留单列，资源包摊销和真实账单仍UNKNOWN。不得用该数声称现金节省。
- 银标事实是同一事件、非独立且非盲来源复核。三次重复不是三个独立任务。以下评分沿用已有记录，不重评、不改口径；UNKNOWN包括遗漏、输入范围不足及语义尚不可确认。

## 完整20单元矩阵

GLM=GLM-5.3；Flash=GLM-5.3-Flash。D/R/U/N分别为派发/响应/派发结果未知/未派发。K列为PASS/FAIL，事实及语义证据列为PASS/FAIL/UNKNOWN项数，分母为该节点参考范围×响应数；这些项并非相互独立样本。费用是每份响应均值，L是单次API调用墙钟。

|节点|模型|D/R/U/N|K P/F|事实 P/F/U|语义证据 P/F/U|平均公开估费¥|平均L秒|
|---|---|---|---|---|---|---:|---:|
'''+ '\n'.join(lines)+'''

完整Token、每次调用、费用币种、预留、引用与条件语义诊断见机读矩阵及末尾逐次表。所有`formal_Q`、实际账单均UNKNOWN；FINAL无数据时不作任何排名。

## 八个维度的节点比较

### 事实、证据与条件

- 1,303次引用ID使用均能在该节点输入注册表定位，并与冻结页文本跨度吻合；它们包含重复引用，不能当作1,303条独立事实，也不证明语义支持。引用存在≠结论成立。
- INQUIRY的冻结T1要求三类日期，其中回复公告日期不在INQUIRY输入中；四模型均为3项UNKNOWN，不能写成事实正确率0或质量持平。其全部监管问题提取质量未被T1覆盖。REPLY缺问询公告落款，亦限制T1。不能拿这种基准/输入覆盖差异解释能力下降。
- T3条件语义：REPLY下GLM/Flash均0/3“完整支持”，DeepSeek 1/3、Qwen 0/3，主要是附条件最低采购或具体最低量未知边界遗漏；不是所有内容错误。OBLIGATIONS给定来源核查父输入后，四模型T3均3/3完整支持。跨节点变化同时受任务和父夹具影响，不能归因于动态反馈或恢复。
- T5：GLM、Flash、DeepSeek在REPLY/OBLIGATIONS/CROSSCHECK均覆盖完整；Qwen各节点均未完整给出2026年的具体计价公式，虽常保留2027年及以后和5代以上待议条件。遗漏保留UNKNOWN。
- Qwen CROSSCHECK一次将“具体最低数量未披露”扩大为“触发条件未披露”，与E0080列出的条件矛盾，记事实FAIL；另一次涉及数量口径的引用链未覆盖其结论，语义证据FAIL。不能仅凭引用位置有效放行。
- 模型主动UNKNOWN与审阅UNKNOWN分开：主动UNKNOWN是否`value=null`、是否有原因只检查合同；其弃答是否正确未自动评分。具体次数及不合法UNKNOWN保存在矩阵，不能把“不主动弃答”视为更可靠。

### 合同、成本与时延排名

下表为描述性观测次序，不是显著性结论。Silver列是事实完整且证据支持的计数，K失败的这些事实不能作为合法节点结果传给下游。

|节点|均价从低到高|平均时延从低到高|K通过|Silver完整支持|
|---|---|---|---|---|
'''+ '\n'.join(ranklines)+'''

- **价格和速度本身没有模型排名交叉**：Qwen在四个已测节点均为最低均价，DeepSeek均为最快；DeepSeek每节点的观测时延最大值也低于其他模型该节点的最小值。该现象仍局限于本批时段、模型模式和输入规模。
- **合同稳定性存在交叉**：Qwen INQUIRY为3/3，但REPLY为0/3、OBLIGATIONS为1/3、CROSSCHECK为0/3；Flash INQUIRY为0/3，OBLIGATIONS为3/3、CROSSCHECK已响应2/2。这是合同可靠性差异，不能冒充事实能力交叉。
- **Silver覆盖有描述性交叉**：REPLY DeepSeek 13/18略高于两个GLM 12/18；OBLIGATIONS两个GLM12/12，DeepSeek11/12；CROSSCHECK的样本量不等且多项未知。相差一项不足以证实稳定的质量排序翻转。
- 每单元n≤3；未进行显著性检验或宣称可靠性达到阈值。逐次值、min/max均保留；未知评分区间为识别界限而非置信区间。评分上界大多可达1，正式质量排名仍UNKNOWN。

### Flash相对完整版的优势是否跨节点成立？

时延变化为Flash/完整版−1，正数表示更慢。

|节点|公开估费降低|平均时延变化|K完整版→Flash|Silver完整支持完整版→Flash|
|---|---:|---:|---|---|
'''+ '\n'.join(flash)+'''

**成本优势在四个已测节点都出现；“质量和合法性不降且更快”不能通用化。** OBLIGATIONS最接近局部观测支配：同为3/3 K与12/12 Silver，Flash更便宜且平均更快。但时延范围重叠、仅三次、父输入为优质固定夹具，不是终端因果收益。INQUIRY Flash更慢且K更差；REPLY K更差；CROSSCHECK样本不齐且Silver覆盖较低。

## 静态分配：仅计算四节点条件组合估计

A—D按题意指定全五节点同一模型，但FINAL测量缺失，完整成本/时延/终端Q不可计算。表中只加总INQUIRY、REPLY、OBLIGATIONS、CROSSCHECK独立测量均值。CAPACITY时间、规划、排队、FINAL、重执行成本未计，故不是完整任务预算或Makespan；每个节点按一次执行估计，失败分布保留，**不假设已成功接通下游**。

E为本轮事后分析候选：每节点先最大观测K率，再最大Silver支持下界，再最低估费。它不是原冻结优化器的输出，更不是通过测试验证的选择算法；用同批数据选模并估计会乐观偏倚，须新响应验证。不把节点成功率相乘为任务成功率。

|方案|四已测节点分配（问询/回复/义务/核查）|局部估费¥|调用时间加总秒|完整终端Q|实际Makespan|
|---|---|---:|---:|---|---|
'''+ '\n'.join(comps)+'''

- E相对A：局部估费低53.8%，调用时间加总低20.6%，观测K向量与Silver支持下界没有下降。这是**事后组合潜力**，不是已执行收益。
- E相对全Flash：更贵（约4.69倍），时间加总较短；相对全DeepSeek：更贵且更慢。它没有形成优于所有强同构基线的结论。
- 选择规则敏感：若先最大K再最低成本，CROSSCHECK会改用Flash，得到局部¥0.056015、56.728秒，Silver覆盖下界不同。不存在由现有数据唯一决定的“最佳异构分配”。INQUIRY事实未充分评估，选择Qwen只基于合同与费用，不能宣称质量满足。
- 仅取四模型共同有响应的重复（前三节点各1/2/3、CROSSCHECK仅1/2）作敏感性对照：A为¥0.349319/77.274秒，E为¥0.161904/61.868秒。结论方向不变，但这不是同时运行配对；全矩阵保留所有缺测，不删除未知结果。
- 枚举4^4=256种四节点组合，在“局部费用、时间加总、逐节点K率、Silver支持下界”这些代理维度上存在多种非支配组合；不能把这种预测/组合前沿称为真实Q/C/L Pareto改善。真实终端Q未知。

## 六个研究判断与下一实验

|研究问题|结论|
|---|---|
|是否存在节点级能力差异？|是：响应速度、估费、合同通过和Silver覆盖存在真实观测差异，适用范围为本事件和固定夹具。|
|是否存在模型优势交叉？|合同稳定性有交叉；Silver覆盖有弱交叉信号；稳定的事实质量互补尚未证明。|
|Flash是否形成成本优势？|是，相对完整版在四已测节点均有公开估费优势；不是已结算现金节省。|
|是否有Pareto权衡？|节点层存在Flash低价与DeepSeek低时延、覆盖和合同率之间的权衡；完整任务前沿未知。|
|是否值得开展静态对照？|值得，已有可证伪的静态分工假设；但不能将本批组合估计作为成功结果。|
|是否具备Dynamic-π条件？|尚不充分：FINAL缺测、真实父输出误差传播未测、共同初始分配及反馈后的终端收益未比较。|

**下一项最值得开展的是固定DAG的静态异构对照，而非先启动动态恢复。** 将独立校准选出的异构分配与强同构Flash、快速同构DeepSeek进行完整端到端比较，保留自然失败，最终汇总节点必须具有可评价输出。核心假设：在回复/义务/核查节点采用不同模型，能否把局部条件语义覆盖与成本—时延差异转化成完整回答的证据质量或资源收益。

若质量仍UNKNOWN、一个同构模型已足够好、串行依赖/终端汇总吞掉节省，或真实上游错误导致异构组合失败，应接受无收益结果。不将本批部分评分当Gold，不以组合估计选择成功样本，不追加调用追求正结果。本轮没有启动此实验，也不提出补跑旧批次。

## 逐次观测（保留全部60个计划位置）

事实P/F/U沿用原复核；缺测列UNKNOWN与NOT_DISPATCHED区分。Token栏为实测输入/输出，非预留。

|序号|节点|模型|重复|响应状态|K|事实P/F/U|Token入/出|公开估费¥|响应秒|
|---:|---|---|---:|---|---|---|---|---:|---:|
'''+ '\n'.join(repeats)+'''

## 文件

- MATRIX_20.json / MATRIX_20.csv：完整20单元，引用定位、条件语义、主动UNKNOWN、用量、币种、重复范围与缺测。
- REPEAT_OBSERVATIONS_60.json / .csv：所有计划位置及真实逐次数据。
- STATIC_COMPOSITION_ESTIMATES.json：A—E、选择敏感性及局部代理前沿，完整Q/C/L均保留UNKNOWN。
- COMMON_REPEAT_SENSITIVITY.json：仅共同已观测重复的敏感性比较，不改原统计分母。
- RANKINGS.json：描述性排名，无正式质量排名。
- SOURCE_RECONCILIATION.json：原文件哈希与账本/评分对齐结果；模型调用0。
'''
(P/'RESULTS.md').write_text(text)
fields=['node','model_key','planned_n','attempted_n','response_PASS_n','response_FAIL_n','response_UNKNOWN_n','NOT_DISPATCHED_n','K_PASS_n','K_FAIL_n','known_input_tokens','known_output_tokens','known_CNY_estimate','known_USD_estimate','actual_bill','formal_Q']
with (P/'MATRIX_20.csv').open('w') as f:
 extra=['fact_PASS','fact_FAIL','fact_UNKNOWN','evidence_PASS','evidence_FAIL','evidence_UNKNOWN','L_mean','L_min','L_max','cost_mean','location_PASS','location_FAIL'];w=csv.DictWriter(f,fieldnames=fields+extra);w.writeheader()
 for r in M:
  d={k:r[k] for k in fields}
  for k in ['PASS','FAIL','UNKNOWN']:
   d['fact_'+k]=None if r['fact_counts'] is None else r['fact_counts'][k];d['evidence_'+k]=None if r['semantic_evidence_counts'] is None else r['semantic_evidence_counts'][k]
  for k in ['mean','min','max']:d['L_'+k]=None if r['L_seconds'] is None else r['L_seconds'][k]
  d['cost_mean']=None if r['CNY_equivalent_estimate'] is None else r['CNY_equivalent_estimate']['mean'];d['location_PASS']=r['location_PASS_occurrences'];d['location_FAIL']=r['location_FAIL_occurrences'];w.writerow(d)
print('Scientific report, 20-cell matrix and all 60 planned-position observations saved; zero calls.')
