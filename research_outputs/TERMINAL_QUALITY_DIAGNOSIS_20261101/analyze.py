"""Read-only analysis of saved outputs. No runner import, dispatch or rescoring in place."""
import ast, json, hashlib, sys, re
from pathlib import Path
from collections import Counter
from statistics import mean
ROOT=Path(__file__).resolve().parent
OLD=Path('/root/research_outputs/mvr_batch1')
AD=Path('/root/research_outputs/TERMINAL_ADAPTER_FIX_20261101')
SC=Path('/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4')
BASE=Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence')
paths={'MVR1':BASE/'MVR1_shuntian/TASK_CONTRACT_MVR1_v1.json','MVR2':BASE/'MVR2_yuandao/TASK_CONTRACT_MVR2_v1.json'}
protected=list(paths.values())+[OLD/x for x in ['runner.py','pairs.jsonl','ledger.jsonl','plan.json','calibration.json','propagation_audit.json']]+[AD/'adapter.py',AD/'SHADOW_RESULTS.json',SC/'terminal_quality.py']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before={str(p):sha(p) for p in protected}
sys.dont_write_bytecode=True
sys.path[:0]=[str(AD),str(SC)]
from adapter import adapt,project_slots,compact
from terminal_quality import evaluate_terminal_quality,_citations_support_fact
contracts={k:json.loads(p.read_text()) for k,p in paths.items()}
pairs=[json.loads(s) for s in (OLD/'pairs.jsonl').read_text().splitlines() if s.strip()]
plan=json.loads((OLD/'plan.json').read_text())
# Extract pure graph construction functions ONLY. Never import archived runner.
tree=ast.parse((OLD/'runner.py').read_text())
ns={}; pure=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['doc_pages','build_dag']],type_ignores=[])
exec(compile(pure,'archived_pure_graph_functions','exec'),ns)
graphs={}; mappings={}
for tid,c in contracts.items():
 view={**c,'_source_pages':c['source_pages']}
 nodes,_=ns['build_dag']({tid:view},tid,plan['tstar'],plan['allocation'])
 flat=ns['doc_pages'](c['source_pages']); m={(d,p):'E'+str(i+1) for i,(d,p,_) in enumerate(flat)}; mappings[tid]=m
 dispatched=[d['node'] for d in next(p for p in pairs if p['task']==tid)['arms']['A']['dispatch']]
 assert dispatched==[n['id'] for n in nodes]
 graphs[tid]={'nodes':[{k:v for k,v in n.items() if k!='doc_text'} for n in nodes], 'page_mapping':[{'node':m[d,p],'doc':d,'page':p,'source_chars':len(t),'passed_chars':min(len(t),12000)} for d,p,t in flat], 'node_count':len(nodes),'extractor_count':len(flat),'dispatch_matches_reconstruction':True,'limitations':['E roles rotate by page, not semantic dependency','F1/F2/F3 use identical type and same dependencies','SINK consumes both E and F, so F is not the sole propagation path','Actual upstream payloads not archived; code path is not proof of semantic consumption']}
rows=[]; counts=Counter(); paired=[]
for p in pairs:
 tid=p['task']; c=contracts[tid]; facts={f['fact_id']:f for f in c['required_facts']}; src=c['source_pages']; armrows={}
 switched={a['node'] for a,b in zip(p['arms']['A']['dispatch'],p['arms']['B']['dispatch']) if a['model']!=b['model']}
 for arm,a in p['arms'].items():
  terminal,issues=adapt(a['terminal'],project_slots(c['required_facts']),src)
  score=evaluate_terminal_quality({k:v for k,v in c.items() if k!='source_pages'},terminal,src)
  assert [x['value'] for x in terminal['claims']]==[x['value'] for x in a['terminal']['claims']]
  details=[]; issuecounts=Counter(x.get('citation_result',x.get('reason')) for x in issues)
  for idx,(claim,result) in enumerate(zip(terminal['claims'],score['claim_results'])):
   f=facts.get(claim.get('fact_id')); old=a['terminal']['claims'][idx]; matched=result['status'].startswith(('CORRECT','SEMANTICALLY_CORRECT'))
   if matched: category='FROZEN_VALUE_MATCH'
   elif tid=='MVR1' and f['fact_id']=='F7': category='ARITHMETIC_VALUE_ERROR'
   elif f['value_kind'] in ['amount','number','percent','ratio'] and re.search(r'元|年|万|（|\(',str(claim.get('value'))): category='NUMERIC_FORMAT_OR_EXPLANATION_MISMATCH_NOT_AUTOMATIC_CONTENT_ERROR'
   elif (tid=='MVR1' and f['fact_id'] in ['F12','F16']) or (tid=='MVR2' and f['fact_id']=='FB6'): category='TEXT_VARIANT_OR_ADDITIONAL_ASSERTION_REQUIRES_SEMANTIC_REVIEW'
   else: category='UNRESOLVED_VALUE_OR_RELATION_MISMATCH'
   counts[category]+=1
   candidates=[]
   for cit in old.get('citations',[]):
    q=compact(cit.get('quote',''))[0]
    if q:
     for doc,dr in src.items():
      for page,pr in dr['pages'].items():
       text,positions=compact(pr['text']); start=0
       while True:
        pos=text.find(q,start)
        if pos<0:break
        candidates.append({'doc_id':doc,'page':page,'start':positions[pos],'end':positions[pos+len(q)-1]+1});start=pos+1
   refs=f.get('source_evidence',[]) if f else []
   path=[{'node':mappings[tid].get((e['doc_id'],int(e['page']))),'doc':e['doc_id'],'page':e['page'],'switched':mappings[tid].get((e['doc_id'],int(e['page']))) in switched,'reference_end':e.get('end'),'beyond_12000_char_input':(e.get('end') or 0)>12000} for e in refs]
   hints=[x.get('doc_id') for x in old.get('citations',[])]
   support=_citations_support_fact(claim.get('citations'),f,src) if f else None
   details.append({'fact_id':claim.get('fact_id'),'value':claim.get('value'),'reference_value':f.get('value') if f else None,'reference_provenance_declared':f.get('gold_provenance') if f else None,'frozen_claim_status':result['status'],'diagnostic_category':category,'original_citations':old.get('citations',[]),'original_doc_ids_valid':all(h in src for h in hints) if hints else False,'quote_matches_in_saved_text':candidates,'adapted_citations':claim.get('citations',[]),'frozen_reference_support':support,'semantic_entailment':'FROZEN_REFERENCE_MATCH_ONLY_NOT_INDEPENDENT_REVIEW' if support else 'NOT_ESTABLISHED; absence/ambiguity/span mismatch does not by itself prove false content','reference_paths':path,'actual_upstream_value':'UNKNOWN_NOT_PERSISTED','actual_downstream_consumption':'UNKNOWN_NOT_PERSISTED','adapter_issues':[x for x in issues if x.get('index')==idx]})
  continuation=[d for d in a['dispatch'] if not d['tag'].startswith('prefix')]
  missing=sorted(set(facts)-{x.get('fact_id') for x in terminal['claims']})
  row={'task':tid,'pair':p['pair'],'arm':arm,'historical_online_f1':a['eval']['fact_metrics']['f1'],'offline_diagnostic_score':score,'claim_count':len(details),'missing_fact_slots':missing,'citation_counts':dict(issuecounts),'claims':details,'upstream_transfer':'CODE_HAS_DEPENDENCY_SERIALIZATION; actual payload UNKNOWN','downstream_consumption':'SINK receives E and F by code; actual semantic use UNKNOWN','execution':'dispatch success records exist; original raw responses/status not fully archived','decomposition':'page-rotating E types; identical F prompts; semantic optimality unproven','allocation':'date/id E nodes and all three F nodes switch in B; no isolated F-only control','switched_nodes':sorted(switched),'postfork_recorded_estimated_cny':sum(d['cost'] for d in continuation),'postfork_sum_request_latency_s':sum(d['lat'] for d in continuation),'postfork_tokens':sum(d['in']+d['out'] for d in continuation),'actual_settled_cost':None,'actual_makespan':None,'deadline_success':None,'replanning_wall':'UNKNOWN (historical 0.0 is a placeholder)','model_capacity_causal_attribution':'UNKNOWN; no upstream values or matched alternate F outputs','new_calls':0}
  rows.append(row);armrows[arm]=row
 A,B=armrows['A'],armrows['B']
 paired.append({'task':tid,'pair':p['pair'],'delta_f1_shadow':B['offline_diagnostic_score']['fact_metrics']['f1']-A['offline_diagnostic_score']['fact_metrics']['f1'],'delta_estimated_cny_postfork':B['postfork_recorded_estimated_cny']-A['postfork_recorded_estimated_cny'],'delta_sum_request_latency_s_postfork':B['postfork_sum_request_latency_s']-A['postfork_sum_request_latency_s'],'delta_terminal_Q':None,'delta_actual_makespan':None})
assert before=={str(p):sha(p) for p in protected}
summary={'outputs':len(rows),'claims':sum(r['claim_count'] for r in rows),'claim_categories':dict(counts),'citation_counts':dict(sum((Counter(r['citation_counts']) for r in rows),Counter())),'frozen_statuses':dict(Counter(d['frozen_claim_status'] for r in rows for d in r['claims'])),'gate_statuses':dict(Counter(r['offline_diagnostic_score']['critical_gate']['status'] for r in rows)),'Q_final_unknown':sum(r['offline_diagnostic_score']['Q_final'] is None for r in rows),'missing_fact_slots':sum(len(r['missing_fact_slots']) for r in rows),'mean_pair_deltas':{k:mean(p[k] for p in paired) for k in ['delta_f1_shadow','delta_estimated_cny_postfork','delta_sum_request_latency_s_postfork']},'semantic_support_review':'NOT_INDEPENDENTLY_ADJUDICATED','historical_values_unchanged':True}
result={'evidence_level':'POSTHOC_DIAGNOSTIC_ONLY_NOT_NEW_MODEL_EXPERIMENT','summary':summary,'source_hashes':before,'protected_files_unchanged':True,'graphs':graphs,'outputs':rows,'paired':paired,'limitations':['No raw E/F payload or prompt archive; cannot certify value transfer or assign errors to a model','Reference GOLD labels are inherited, not newly independently adjudicated','Current source snapshot checked against dispatch length, not proof of historical source versions','No independent test pool accessed; only already-exposed archived batch and contracts']}
(ROOT/'DIAGNOSIS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=False,indent=2))
# One research design, not an executable paid authorization.
design={
 'status':'DESIGN_ONLY_PAID_HOLD',
 'name':'Evidence-preserving targeted recovery and heterogeneous reassignment',
 'hypothesis':'With the same natural feedback and feasible resources, targeted R plus calibrated pi improves frozen delivered terminal Q over Static, beyond R-only or pi-only; costs and wall-clock overhead must be measured.',
 'Z':'FIXED_NOT_TESTED',
 'independent_events_planned':12,'repeats_per_event':2,'arms':['Single','Static','R-only','pi-only','Joint'],
 'full_arm_deliveries_planned':120,'independent_unit':'event, not repetitions or branches',
 'primary_contrast':'Joint minus Static','primary_endpoint':'frozen scorer Q_delivered, NOT fact F1',
 'secondary_contrasts':['Joint minus R-only','Joint minus pi-only','Static minus Single'],
 'missing_quality':'No imputation of PENDING as 0 or 1; retain all units, report per-event [0,1] bounds for unknown Q and paired [-1,1] bounds. No positive full-Q claim if missingness permits reversal.',
 'failure_quality':'Absent/invalid delivery is Q_delivered=0 per existing scorer; evaluator/reference failure is UNKNOWN, not task failure.',
 'primary_analysis':'Average two repeat differences within each event; 12 equally weighted event differences; two-sided event-level sign-flip randomization test with all 4096 signs if arm scheduling randomized and exchangeability holds; 95% event bootstrap CI (10000 resamples, fixed seed 20261101), small-n limitation explicit.',
 'secondary_analysis':'Holm correction for 3 prespecified quality contrasts; effect sizes and event-level C/L differences; do not treat node calls as independent samples.',
 'net_benefit_rule_proposed':'Primary path: lower 95% CI of delta Q > 0 and upper 95% CI of mean C and L ratios <=1.10. Secondary Pareto pathway: lower delta Q CI >= -0.02, one resource upper ratio CI <=0.90 and other <=1.0, jointly reported with multiplicity-adjusted bounds; fixed before calls, not historical reinterpretation.',
 'sample_size_scope':'Fixed mechanistic pilot, not powered confirmatory population-effect study. No reliable between-event variance from 2 exposed events; power not asserted and no post-result sample extension.',
 'actual_models':'NOT_FROZEN; historical GLM-5.3-Flash/deepseek-flash are candidates only, not demonstrated superior at all contracts',
 'request_count':'UNKNOWN until task DAG and bounded recovery matrix selected; 120 deliveries are not 120 API calls',
 'budget':'NOT_AUTHORIZED; no new live prices checked. Separate native-currency reservation and billing/estimate ledgers required.',
 'stop':'Fixed sample; no retry/supplement for negative results. System/transport errors, budget exhaustion or batch wall-clock limit stop dispatch. Normal model errors retained, illegal outputs blocked from downstream.',
 'natural_feedback':'Run scheduled units regardless of whether naturally occurring feedback fires; no artificial corruption, no screening confirmation cases by observed failure or model benefit.',
 'fairness':'DAG arms share initial pi, DAG, evidence, common prefix and feedback snapshot, resource slots/deadline; same legal candidates and evidence validation. Single uses same full question and evidence with no DAG, so its contrast is system-level, not isolated pi attribution.',
 'current_external_gaps':['Independent event set and pre-output reference review','Credentialed relevance/semantic assessment required by frozen scorer','Independent contract-matched calibration','Explicit paid batch matrix, model versions and budgets']}
result['next_experiment']=design
(ROOT/'DIAGNOSIS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
lines=['# 终端质量诊断与下一轮协作实验','',
'日期：2026-11-01（Asia/Shanghai）。本轮零模型调用、零付费；仅在新目录生成分析，未修改 ZCode、冻结评分器或历史结果。',
'','## 结论先行','',
'当前最值得开展的是 **同一自然反馈状态下，证据保持的定向恢复与异构重分配五臂配对实验**。主比较 Joint 对 Static，R-only 与 π-only 用于分辨“重做”与“换模型”的增量；Single 是系统级强基线。Z 固定。本轮只交付设计，真实执行 HOLD。',
'现有证据指向引用链和派生事实的薄弱环节，并未证明更强模型可普遍修复它们。应检验局部恢复是否修复终端证据/算术、换模型是否带来额外质量或速度收益，以及这种收益能否覆盖调用与规划成本；不预设 Joint 获胜。',
'', '## 1. 分析口径与实质发现','',
'读取已曝光 mvr_batch1 的 pairs、ledger、runner 和两份原冻结合同；仅提取 runner 的两个纯图构建函数，不导入或运行历史执行器。对存档终端对象使用现有隔离适配器，调用原冻结评分器；未重新执行历史 DAG，也未恢复缺失的原始模型回答。全量哈希及逐主张证据见 DIAGNOSIS.json。',
'合同内 GOLD_CONFIRMED/official_structured_record 是继承标签，本轮未进行独立裁决，不能据标签宣称独立 Gold 已复核。原 PDF 文件未重新核验；本轮核对的是冻结合同内文本与引用哈希。',
'', '|观测|数量|解释|','|---|---:|---|',
'|终端输出|16|2个已曝光事件×4对×2臂；不是16个独立事件|',
'|主张|344|按主张出现次数计，不是344个独立事实|',
'|冻结事实值匹配|282|不等于证据支持或完整任务成功|',
'|值匹配且冻结引用要求通过|80|冻结规则内通过，不代替独立语义裁决|',
'|值匹配但引用未通过|202|不得归为内容错误|',
'|明确合计算术错误|2|MVR1 A-p1=1440、A-p4=1380；参考1430|',
'|数值夹单位/解释导致匹配失败|37|包含额外因果说明，不能仅剥单位就宣称全句正确|',
'|文本变体/附加断言需语义复核|23|文号前缀、禁入期限、免罚表述等；未改判|',
'|完整引用唯一定位/歧义/未找到|134 / 171 / 39|歧义可来自真实重复公告，未找到可来自省略号/算式/改写，不全是编造|',
'|缺失必需 fact_id 槽位|0|槽位齐不等于交付语义完整|',
'|关键证据门禁 FAIL / 完整Q未知|16 / 16|所有输出还缺有效问题相关性评价|',
'',
'**冻结证据支持的实际含义**：评分器要求引用在指定文档/页且覆盖参考跨度至少80%（有offset时），派生事实默认 ALL 参考。定位到另一份内容一致公告或只引用正确处罚短句，仍可能失败；这不能直接推出语义不支持。例：MVR1 F1短句支持1000万元，但参考是D2含全部当事人的110字符处罚段。不得为了通过而把引用扩展成整页，或利用答案替模型补引文。本轮保留失败，单列“参考来源/跨度要求未满足”与“语义支持未独立判定”。',
'', '## 2. 16份输出逐项诊断','',
'表中F1均为新适配器的事后离线值匹配诊断；原在线F1仍全0，历史成绩不变。U/A/N分别是唯一定位/歧义/未找到。E列是冻结规则下值正确且证据通过的主张数。',
'', '|任务-对-臂|F1（离线）|E/主张|U/A/N|值匹配失败ID|关键事实值失败|关键证据未满足|', '|---|---:|---:|---|---|---|---|']
for r in rows:
 s=r['offline_diagnostic_score'];bad=[c['fact_id'] for c in r['claims'] if c['diagnostic_category']!='FROZEN_VALUE_MATCH']; n=sum(c['frozen_claim_status']=='CORRECT_GOLD' for c in r['claims']); cc=r['citation_counts'];g=s['critical_gate']
 lines.append(f"|{r['task']}-{r['pair']}-{r['arm']}|{s['fact_metrics']['f1']:.4f}|{n}/{r['claim_count']}|{cc.get('UNIQUE_FULL_QUOTE',0)}/{cc.get('AMBIGUOUS_QUOTE',0)}/{cc.get('QUOTE_NOT_FOUND',0)}|{','.join(bad) or '无'}|{','.join(g['failed_fact_ids']) or '无'}|{','.join(g['evidence_unsatisfied_fact_ids']) or '无'}|")
lines += ['', '逐份完整值、引用原文、候选位置、精确跨度、参考路径、失败类别及评分器结果均在 JSON 的 outputs[].claims[]（344项），不是只列汇总。每份的上游正确传递、下游正确消费均为 UNKNOWN：历史只存派发计量和终端对象，没有 E/F 完整载荷、实际请求体或可验证缓存快照。代码中有传递路径，并不证明内容实际传对/用对。','',
'### 可确定的内容与证据案例','',
'- MVR1 p1/p4：A的F7分别1440/1380，B两次1430。算式1000+150+100+60×3=1430可直接复核；但B的算式被当作原文引用，仍不满足派生事实的输入证据要求。不能将“算对了”当作终端成功。',
'- MVR1 F12：“处罚字〔2023〕37号”与参考“〔2023〕37号”是前缀差异；F16增加期限、市场禁入决定文号等，应核验新增断言，不能一概判语义等价。',
'- MVR2 p4：两臂大量数值带“元”“年”或解释，冻结数值解析失败。Q下降中含格式失配，不能作为模型数值能力下降的独立证据。',
'- MVR2 FF2/FF3：引文使用省略号连接片段，不能唯一匹配完整原句。FG5和MVR1 F7引用算式而非来源原文；需要分别保留操作数的来源及计算关系，而非把计算结果伪装成引文。',
'- FC2附加“因申辩被采纳而下调”的因果解释，即使差额150万元正确，因果关系仍需单独证据；本轮未裁决该推断。',
'', '## 3. 失败归因：观测与因果分开','',
'|类别|可确认事实|不可作出的归因|可干预性|','|---|---|---|---|',
'|评分接口|原adapt_sink漏subject/predicate/unit/date_type，导致原在线事实F1全0；隔离补全公共槽位后恢复值匹配|不能把修复后的分数差称为新模型收益|公共适配器对所有臂一致；补丁未应用|',
'|证据不足/出处丢失|171引用多处匹配、39无法完整匹配；派生算式和省略引用存在|无法据此断定所有引用虚构，或断定首次丢失发生在哪个节点|保持source ID、精确来源位置及派生输入链；自然失败时局部修复|',
'|模型能力|2次明确合计算错；其它60次为格式/附加断言待审|无E/F载荷，不能指定哪个模型/哪个节点负责；不能断言换强模型必好|先隔离测试派生/核验节点能力，而非盲换全部抽取器|',
'|任务分解|E按页轮转类型，F1/F2/F3同类型、同输入、同Prompt；缺语义互补依据|不能把F节点数多当成协作收益|本轮不改图；后续结构消融另测，不夹入π收益|',
'|DAG依赖/传递|SINK同时读取E和F；解析失败时把上游截成600字符；E输入最多12000字符|无实际载荷，600截断是否发生未知；参考跨度未发现超过12000，不能归因该上限|保存实际输入/输出和来源链；不把坏输出合法提交|',
'|模型分配|B同时切换日期类E及全部F；E的实际Prompt抽取全部三类事实|无法区分F/E贡献，节点标签与实际合同不完全匹配|使用真实合同校准；R-only/π-only提供消融|',
'|执行异常|E2由corrupt受控破坏，非自然异常；A先B后顺序执行|没有证据把该批视为自然线上恢复；未记录异常不等于证明无失败/截断|后续自然反馈全量纳入；顺序随机平衡|',
'|评价缺测|16份问题相关性均未有效评估，完整Q=null|不能以Q_raw或F1补完整Q；不能把UNKNOWN算错误|依原冻结规则补齐独立评估流程，不能自行签认|',
'',
'**不采用旧传播摘要的无证据归因。** 当前合同和实际dispatch相符：MVR1为21个E+3个F+SINK=25节点，MVR2为13+3+1=17；旧文字报告“10个E”与账本不符。MVR1实际切换E5/E8/E11/E14/E17/E20及F1–F3，冻结参考来源页未命中这些E；MVR2有11项参考的来源E被切换。但参考页映射不是实际消费证明。SINK还直接读取E，不能说终端改变必然经F唯一通路产生。无载荷时“无传播错误”与“更强模型完全不可修复”均证据不足。',
'', '## 4. 已有Q/C/L信号与可干预机会','',
'8对的事后F1平均B−A = −0.0028935；续执行公开价估费平均增加¥0.0587（旧runner按固定汇率7.5折算）；请求时延累计平均减少90.38875秒。共享前缀从臂增量中排除，项目现金总账不能重复加两遍前缀。**这里没有真实Makespan、账户结算或实际重规划耗时，不能宣称净收益或实测Pareto改善。** 旧replan_wall_s=0是占位，不是测量。',
'', '|动作/对象|现有证据|可能收益|代价及边界|','|---|---|---|---|',
'|换日期抽取模型|旧校准GLM F1 .7778、DS .8235，仅9字段；实测切换请求较快|条件性时延改善|校准来自已曝光任务；E实际抽三类、F为整合合同，不能迁移该分数作可靠下界|',
'|换跨文档核验模型|旧节点测试GLM .3333、DS .5，仅6字段|待检验的核验能力差异|不是正式终端支持证据，未证明同预算优势|',
'|重执行派生/汇总节点|F7两次算错，原文和操作数可能已在上游|小范围恢复可能比整图重跑低成本|缺载荷不能指定必重执行节点；需先判断源事实与版本是否有效|',
'|重执行来源抽取节点|引文ID退化成E编号，来源缺失|若源抽取已缺证据，修复源头后重算受影响后继|若源头本来正确则应只修复下游；健康独立分支必须保留|',
'|异构联合R+π|恢复范围与合同匹配模型共同选择|选择修复节点并由更适配模型执行，可能同时增证据质量、节省无效重试|目前仅假设；所有臂相同证据标准和动作权限，不故意弱化基线|',
'|结构变化Z|F三次同质聚合、按页标签有疑点|或减少冗余与错误传播|历史不能证明删F语义等价；Z不进入下一主实验，也不承诺调用减少|',
'', '## 5. 一个最值得开展的实验（设计，不执行）','',
'**科学假设 H1**：在真实跨文档任务自然出现的证据/派生反馈下，依据节点合同校准的局部恢复与模型重分配，较强Static提高完整终端交付质量，并能在计入重规划、校准、失败调用后保留可接受的成本与时间。H2为Joint相对R-only/π-only的增量。当前仅假设，允许零切换、拒绝、负收益和无差异。',
'',
'|方法|事前规则|识别目标|','|---|---|---|',
'|Single|按隔离校准事前选最佳单模型；同一问题、全部同源证据和输出合同，一次完整任务执行；不事后挑模型|单模型是否已足够；与DAG臂为系统比较，不归因π|',
'|Static|相同DAG、事前异构π；遵守统一最小合法恢复及依赖阻断，不做可选扩展恢复/重分配|强静态基线，健康缓存可复用|',
'|R-only|固定初始π；仅据相同反馈选择合法恢复集合与失效后继闭包|额外局部恢复贡献|',
'|π-only|统一最小R固定；据反馈调整剩余待执行及强制恢复节点模型|动态分配贡献|',
'|Joint|在同候选集合联合选R和π；Z固定|联合效果；分别对两个消融，不以名称差异当贡献|',
'',
'所有DAG臂从同一个真实共同前缀快照分叉；相同合法缓存、模型池、并发槽、资源余量、截止时间、候选权限、输出评分。无效输出不得传下游；健康节点不得无故重跑。允许所有臂“无需恢复”，没有自然反馈也保留在分母。Single从完整任务起点执行，不能给它DAG臂没有的参考答案；其墙钟与成本按完整任务计，与DAG臂“前缀+分支+规划”比较。',
'异常限定可由证据合同、超时或预算反馈真实检出的情况，不注入corrupt、不把事后Gold错误暴露给策略、不只选择观察到失败或有收益的测试任务。基于开发数据提出任务族；新事件按材料完整性/业务类别连续纳入，不能按模型优劣挑选。',
'',
'### 样本与矩阵','',
'建议一个固定的机制探索批次：12个未参与本次诊断/调参的独立事件簇，三类跨文档业务各4个；每事件2次重复、5种方法，共120条完整臂交付记录。DAG四臂每次共享前缀再分叉，Single单独全程执行。独立样本数为12，不是120；2次重复用于测随机性。事件若存在关联并为同簇，不凑数。',
'该规模不是由现有两事件数据推得的充分统计功效：不承诺确认性检验功效，不估造方差。定位机制探索，固定样本完成后停止；不因不显著扩大本批。后续确认实验若需要另行立项，不自动启动。',
'请求数不能由120直接得出：N = 隔离校准请求 + Σ(共享前缀 + 4臂实际续执行及预注册最多一次恢复 + Single完整任务请求 + 如需付费独立评估的请求)。按每个DAG最坏合法闭包计算分模型上限、输入上下文/输出上限和双币种预算；任务、真实版本与费率尚未冻结，所以本轮不给虚假现金上界，也不复用任何旧授权。',
'',
'### 预注册终点与统计','',
'- 主终点：冻结评分器的 Q_delivered，主对比 Joint−Static。完整无效/缺失交付按评分器为0；参考或评价缺测为UNKNOWN，不能补0或删除。任务相关性等独立评价必须符合原评分器的审阅者/校准登记要求。若只能Silver则仅探索性部分指标，不能宣称完整Q收益。',
'- 次终点：Q_final、事实F1、证据支持率、完成率、按期有效完成率、API/Schema/证据合同可靠性分别报告；原生CNY/USD实用量估费与已结算成本分列；真实起止墙钟Makespan含队列/规划/检测/模型/提交；重规划单独实测。不能用请求时延相加替代Makespan。',
'- 决策和资源协议事前固定：对所有方法给同一每任务预算和deadline，阈值由隔离开发数据确定，不能看测试结果再调。模型版本、温度和调度次序随机种子记录；同模型并发槽一致，避免不同臂互相抢资源引入干扰。随机/平衡臂执行顺序，不总是Static先跑。',
'- 每事件先平均两次配对差，再对12事件等权汇总；主差报告95%事件聚类bootstrap区间（10000次，种子20261101）。随机化和交换性成立时做事件级精确符号翻转双侧检验（4096种），否则只报告描述性不确定性，不声称随机化因果检验。',
'- Joint−R-only、Joint−π-only、Static−Single三项质量比较用Holm控制多重检验；事件内调用不能增加自由度。Joint相对Static改善不等于交互收益，另报告(Joint−R-only)−(π-only−Static)及区间；无差异不得宣称等价。',
'- 拟定收益标准（待新批次正式冻结，不改变旧成功标准）：主路径要求ΔQ的95%下界>0，C与L比值95%上界均≤1.10；次路径质量非劣界−0.02，一项资源至少节省10%、另一项不增加，并采用多重性调整的联合区间。分别报告Q/C/L，不临时拟合权重；未知账单或Q使净收益仍不可判定。',
'- UNKNOWN保留所有任务分母；Q在[0,1]给出最坏/最好界，配对缺测差在[-1,1]内报告。任何未知取值可反转结论，就不主张完整质量收益。按期成功率以全部计划任务为分母，并报告失败、拒绝和不可识别项。',
'- 同时报告本批增量成本和包含校准、共同前缀、规划、独立评分的全成本；共享前缀只在项目账本记一次，部署型单臂成本各计其需要的前缀。画像摊销展示N=1及明确部署次数的敏感性，不能只报有利摊销。',
'- Pareto仅用实际可评价Q、实际时延与同币种可比较成本；区间重叠称权衡不确定，不把点估计优越称稳定支配。双币种未冻结换算规则则分别呈现，不擅自换汇。',
'',
'### 停止与结论边界','',
'一次整批、固定事件及重复；无自动重试/补跑/事后换任务。模型正常错误、无反馈和策略拒绝作为结果，不导致样本选择；只对系统/传输异常、预算预留不足、墙钟触顶停止新派发并保留已花成本。合法R恢复是预注册研究动作，有单独上限，不等于传输错误后的自动重试。',
'当前没有新增真实结果，且没有足以支持完整终端Q的独立评价记录、独立节点合同校准和新批次预算。因此 **分析与实验设计完成；付费执行 HOLD**。下一步应是获批后的一个完整科学批次，不是继续改旧成绩。',
'', '## 6. 可复核交付','',
'- DIAGNOSIS.json：16份、344条主张的逐项诊断、来源位置、冻结评分详情、实际dispatch一致性、配对差、源哈希和机读实验建议。',
'- analyze.py：离线只读分析入口；未引入网络/模型调用，所有输出只写本新目录。',
'- 本报告：失败归因、干预机会与唯一下一实验设计。没有新增工程模块、未应用运行器补丁。',
'']
(ROOT/'TERMINAL_QUALITY_DIAGNOSIS.md').write_text('\n'.join(lines))
