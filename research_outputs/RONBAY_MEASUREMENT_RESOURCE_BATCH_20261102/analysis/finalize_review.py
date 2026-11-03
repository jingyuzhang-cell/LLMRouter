"""Archive explicit source-constrained offline adjudications, not additional model calls."""
import json,sys,hashlib,sqlite3,statistics,datetime
from pathlib import Path
P=Path(__file__).resolve().parents[1]; A=P/'analysis'; BASE=Path('/root/research_outputs/RONBAY_FINAL_ADMISSION_20261102')
sys.path.insert(0,str(BASE))
from score_review import aggregate
correct={12:'',13:'2456',14:'2456',15:'2456',16:'2456',17:'2456',18:'2456',19:'4',20:'2456',21:'23456',22:'46',23:'2456',24:'235',25:'3',26:'2356',27:'2356',28:'3',29:'2356',30:'2356',31:'2356',32:'2356',33:'2356',34:'2356',35:'3',36:'23456',37:'123456',38:'4',39:'123456',40:'23456',41:'24',42:'123456',43:'23456',44:'34',45:'2456'}
rationale={
 'T1':'收到问询日、问询公告董事会落款日、回复公告董事会落款日三者分别核对；落款不直接证明公开时刻。',
 'T2':'公司估算1200亿元、协议未约定固定采购金额、实际销售金额随订单价格和数量而不确定；不构成收入保证。',
 'T3':'305万吨/6年是预测量；附条件最低采购存在而非无条件保证，具体最低量未披露；检查结论、主体和期间字段。',
 'T4':'6万吨/年是现有产线口径，305万吨为6年预测总量；两者不可直接证明实际履约能力。',
 'T5':'必须同时保留2026年碳酸锂成本加加工费公式、2027年起待议、5代以上产品待议。',
 'T6':'四类风险以及3/4代未规模化稳定量产、5代开发阶段、收入不能保证均需保留。'}
unknowns={
 'T1':'未完整保留三种日期及其事件属性，或将公告落款直接当作公开时间。INQUIRY没有回复文本、REPLY没有问询公告落款，不能因这些输入缺口认定模型能力差。',
 'T2':'已提及公司估算/非约定金额，但未完整表达冻结参考要求的销售金额不确定性与收入非保证边界；不补用引用中未输出的结论。',
 'T3':'未完整保留附条件最低采购或具体最低量未披露边界；不将遗漏自动判为错误，也不以引用存在代替覆盖。',
 'T4':'仅给出部分产能信息，未完整展开现有年产能与六年预测总量的口径及实际能力未知边界。',
 'T5':'只列未来待议条件，缺少2026年具体计价公式。',
 'T6':'风险列举未完整保留3/4代与5代不同量产状态；引用原文含该事实不等于模型已表达该事实。'}
rubric=json.loads((BASE/'SILVER_RUBRIC.json').read_text()); obs=json.loads((A/'OBSERVATIONS.json').read_text()); reviews=[]
for row in obs['rows']:
 i=row['index'];d=next((P/'run/requests').glob(f'cell{i:02d}__*'));raw=(d/'RESPONSE.bin').read_bytes();o=json.loads(json.loads(raw)['choices'][0]['message']['content']);inp=json.loads((BASE/'inputs'/f"{row['node']}.json").read_text()); items=[]
 for tid in rubric['per_node_scope'][row['node']]:
  # For diagnosis only: long answer IDs are recognized by explicit suffix; K remains FAIL.
  claims=[c for c in o['claims'] if str(c.get('answer_id','')).split('_')[-1]==tid]
  ids=sorted({e for c in claims for e in c.get('evidence_ids',[]) if e in inp['evidence_registry']})
  ok=tid[1:] in correct.get(i,'')
  fact='CORRECT' if ok else 'UNKNOWN';evidence='SUPPORTED' if ok else 'UNKNOWN'
  why=rationale[tid]+' 已阅读本输出结论与所引原文，覆盖成立。' if ok else unknowns[tid]
  if i<12:why='输出的接收日期/落款日期仅作局部诊断；冻结T1还要求回复公告日期，而当前INQUIRY材料未提供，完整T1保留UNKNOWN。'
  if i==41 and tid=='T3':fact='WRONG';evidence='UNSUPPORTED';why='输出称最低采购“触发条件未披露”，但E0080明确列出综合竞争力条件；未披露的是具体最低数量及条件实际满足情况，不能将二者混同。'
  if i==41 and tid=='T4':evidence='UNSUPPORTED';why+=' 但本claim仅引E0039/E0059/E0060，未引305万吨六年预测的E0057，且未消费父记录，证据链不完整。'
  if i==43 and tid=='T1':why='输出将2026-01-14称为“问询函落款”，E0027实际为公司收到问询函公告的董事会落款，事件归属含混；不自动改写后判通过。'
  if i==36 and tid=='T1':why='输出有1月13日接收和1月19日回复落款，但遗漏1月14日问询公告落款，故不计完整T1。'
  items.append({'id':tid,'factual':fact,'evidence':evidence,'rationale':why,'evidence_ids':ids,'omission_or_uncertainty':not ok,'quoted_model_claims':claims})
 review={'response_sha256':hashlib.sha256(raw).hexdigest(),'reviewer':'assistant source-constrained offline review; non-independent; operator has seen model identities','independent':False,'identity_blinding_achieved':False,'items':items}
 result=aggregate(row['node'],review,raw)
 record={'index':i,'node':row['node'],'review':review,'aggregate':result,'K_diagnostic':row['K_diagnostic'],'K_errors':row['K_errors'],'no_response_repair':True}
 (A/f'REVIEW_{i:02d}.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');reviews.append(record)
for cell in obs['matrix']:
 rs=[r for r in reviews if r['node']==cell['node'] and next(x for x in obs['rows'] if x['index']==r['index'])['model_key']==cell['model_key']]
 n=sum(r['aggregate']['denominator'] for r in rs);c=sum(r['aggregate']['fact_correct'] for r in rs);w=sum(r['aggregate']['fact_wrong'] for r in rs);u=sum(r['aggregate']['fact_unknown'] for r in rs);s=sum(r['aggregate']['supported_correct'] for r in rs);e=sum(r['aggregate']['supported_incorrect_or_unsupported'] for r in rs)
 cell.update(reference_grade='NON_INDEPENDENT_SILVER',reviewed_fact_denominator=n,fact_correct=c,fact_wrong=w,fact_unknown=u,supported_correct=s,fact_coverage=(c+w)/n if n else None,fact_bounds=[c/n,(c+u)/n] if n else None,supported_bounds=[s/n,(n-e)/n] if n else None,full_terminal_Q=None,not_confidence_interval=True)
con=sqlite3.connect('file:'+str(P/'run/ledger.sqlite')+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
calls=[dict(r) for r in con.execute('select * from calls')];pending=[r for r in calls if r['status']!='SETTLED'];attempted=len(calls)
for cell in obs['matrix']:
 model={'glm53':'glm-5.3','glm53flash':'glm-5.3-flash','deepseek':'deepseek-flash','qwen':'qwen-plus-2025-12-01'}[cell['model_key']]
 cell['attempted_n']=sum(c['model']==model and c['request_id'].endswith('__'+cell['node']) for c in calls)
 cell['outcome_unknown_n']=cell['attempted_n']-cell['response_n'];cell['not_dispatched_n']=3-cell['attempted_n']
known={k:0 for k in ['input_tokens','output_tokens','micro_cny','micro_usd']}
for c in calls:
 if c['actual']:
  v=json.loads(c['actual'])
  for k in known:known[k]+=v[k]
closure={'status':'CLOSED_INCOMPLETE_PROCESS_LOSS','observed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'runner_process_present':False,'normal_finalization_present':False,'cause':'UNKNOWN; runner and worker no longer present, no terminal exception persisted','planned_requests':60,'attempted_ledger_requests':attempted,'responses_with_usage':len(obs['rows']),'unresolved_dispatched_requests':[c['request_id'] for c in pending],'not_dispatched':60-attempted,'known_usage_and_estimate':known,'known_CNY_equivalent_estimate':(known['micro_cny']+8*known['micro_usd'])/1e6,'actual_bill':None,'unresolved_request_bill':None,'pending_reservations':[json.loads(c['reserved']) for c in pending],'stage2_started':False,'remaining_authorization_reusable':False,'no_retry_or_resume':True,'raw_ledger_preserved':True,'source_ledger_sha256':hashlib.sha256((P/'run/ledger.sqlite').read_bytes()).hexdigest()}
(P/'RECOVERY_CLOSURE.json').write_text(json.dumps(closure,ensure_ascii=False,indent=2)+'\n')
(A/'MODEL_NODE_MATRIX.json').write_text(json.dumps({'reference_level':'exploratory non-independent Silver','review_is_not_blinded':True,'semantic_mapping_of_long_answer_ids_is_diagnostic_only':True,'historical_K_not_regraded':True,'matrix':obs['matrix']},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(closure,ensure_ascii=False,indent=2))
for c in obs['matrix']:print(c['node'],c['model_key'],'n',c['response_n'],'K',c['K_pass_n'],'Silver supported',c['supported_correct'],'/',c['reviewed_fact_denominator'],'unknown',c['fact_unknown'])
