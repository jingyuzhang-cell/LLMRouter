"""Offline source-bound fixture and request construction. No network, keys or dispatcher."""
import json, hashlib, sys, ast
from pathlib import Path
P=Path(__file__).resolve().parent
B=Path('/root/research_outputs/THREE_TASK_FEASIBILITY_20261101')
SRC=Path('/root/research_outputs/CAPITAL_PUBLIC_DATA_20261031/RONBAY_202601')
PREV=Path('/root/research_outputs/RONBAY_FOUR_MODEL_PLAN_20261102/EXPERIMENT_CONFIG.json')
sys.path.insert(0,'/root/research_outputs/TERMINAL_ADAPTER_FIX_20261101')
from evidence_registry import build_registry,resolve
enc=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
hashb=lambda x:hashlib.sha256(x).hexdigest()
def write(n,x):
 p=P/n;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f:f.write(enc(x))
refs=[r for r in json.loads((B/'REFERENCE_ANSWERS.json').read_text())['items'] if r['id'].startswith('RONBAY')]
dag=json.loads((B/'DAG_RONBAY_202601.json').read_text());prior=json.loads(PREV.read_text());sources={};hashes={str(PREV):hashb(PREV.read_bytes())}
for f in [B/'REFERENCE_ANSWERS.json',B/'DAG_RONBAY_202601.json',B/'NODE_CONTRACT.json']:
 hashes[str(f)]=hashb(f.read_bytes())
for did in ['INQUIRY','REPLY']:
 raw=SRC/did/'source.pdf';hashes[str(raw)]=hashb(raw.read_bytes());pages={}
 for f in sorted((SRC/did).glob('p*.txt')):
  t=f.read_text();hashes[str(f)]=hashb(f.read_bytes());pages[str(int(f.stem[1:]))]={'text':t,'page_sha256':hashb(t.encode())}
 sources[did]={'raw_sha256':hashes[str(raw)],'pages':pages}
registry=build_registry(sources);aliases={f'E{i:04d}':eid for i,eid in enumerate(registry,1)}
# One body per mechanically segmented source span; parent records only use IDs.
evidence={a:{'source_id':registry[e]['doc_id'],'page':registry[e]['page'],'start':registry[e]['start'],'end':registry[e]['end'],'text':registry[e]['quote']} for a,e in aliases.items()}
spans=[]
for r in refs:
 for e in r['evidence']:
  t=Path(e['file']).read_text()
  assert t[e['start']:e['end']]==e['quote'] and hashb(t.encode())==e['text_sha256']
  assert sources[e['source_id']]['raw_sha256']==e['source_sha256']
  spans.append({'item':r['id'],'page':e['page'],'source_id':e['source_id'],'exact':True})
def ids_for(r):
 return [a for a,x in evidence.items() if any(x['source_id']==e['source_id'] and x['page']==e['page'] and x['end']>e['start'] and x['start']<e['end'] for e in r['evidence'])]
records={}
def add(cid,value,eids,parents=()):
 records[cid]={'claim_id':cid,'value':value,'evidence_ids':eids,'parent_claim_ids':list(parents),'provenance':'SOURCE_REVIEWED_SILVER_FIXTURE_NOT_MODEL_OUTPUT','semantic_certification':'NON_INDEPENDENT'}
# Facts are attributed source-review fixtures, NOT secret scoring labels or generated responses.
for i,r in enumerate(refs,1):
 add('REPLY:T'+str(i),({'reply_signature':'2026-01-19'} if i==1 else r['required_answer_components']),[a for a in ids_for(r) if evidence[a]['source_id']=='REPLY'])
add('INQUIRY:DATE',{'receipt':'2026-01-13','notice_signature':'2026-01-14'},[a for a in ids_for(refs[0]) if evidence[a]['source_id']=='INQUIRY'])
add('INQUIRY:QUESTION',{'regulator_question_is_not_final_finding':True,'subjects':['金额依据','履约能力和风险','协议条件和义务']},[a for a,x in evidence.items() if x['source_id']=='INQUIRY'])
for i in [2,3,5,6]:
 r=refs[i-1];add('OBLIGATIONS:T'+str(i),{'source_statement_scope':'公司回复及转述合同，不作外部履约保证','unknown_boundaries':r['UNKNOWN_boundaries']},[a for a in ids_for(r) if evidence[a]['source_id']=='REPLY'],['REPLY:T'+str(i)])
add('CAPACITY:PERIOD',{'capacity_unit':'万吨/年','demand_unit':'万吨/6年','comparison':'不同期间；不自动推出实际履约能力'},ids_for(refs[3]),['REPLY:T4'])
for i,r in enumerate(refs,1):
 parents=['REPLY:T'+str(i)]
 if i in [2,3,5,6]:parents+=['OBLIGATIONS:T'+str(i)]
 if i==1:parents+=['INQUIRY:DATE']
 if i==4:parents+=['CAPACITY:PERIOD']
 add('CROSSCHECK:T'+str(i),{'attributed_source_facts':r['required_answer_components'],'unknown_boundaries':r['UNKNOWN_boundaries']},ids_for(r),parents)
outputs={n:[k for k in records if k.startswith(n+':')] for n in ['INQUIRY','REPLY','OBLIGATIONS','CAPACITY','CROSSCHECK']}
# All transitive references resolve without repeating any parent record.
def closure(keys):
 out=set(keys);todo=list(keys)
 while todo:
  for p in records[todo.pop()]['parent_claim_ids']:
   if p not in out:out.add(p);todo.append(p)
 return sorted(out)
for cid,r in records.items():
 assert all(p in records for p in r['parent_claim_ids'])
 assert all(e in evidence for e in r['evidence_ids'])
 for a in r['evidence_ids']:resolve(aliases[a],registry,sources)
write('EVIDENCE_REGISTRY.json',{'sources':sources,'registry':registry,'aliases':aliases})
write('FIXTURES.json',{'status':'FROZEN_SOURCE_REVIEWED_SILVER_NOT_GOLD','records':records,'outputs':outputs,'scope':'Correct-upstream conditional node measurement; final fixture exposes source-reviewed answers through legitimate parents. Does NOT measure error propagation or independent end-to-end reasoning.','compiler':'assistant','independent_reviewers':0})
# Retain the prior strict wire schema, not its runner or transport.
oldrun=Path('/root/research_outputs/RONBAY_DYNAMIC_PI_20261102/run.py');hashes[str(oldrun)]=hashb(oldrun.read_bytes())
for stmt in ast.parse(oldrun.read_text()).body:
 if isinstance(stmt,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SYSTEM' for t in stmt.targets):system=ast.literal_eval(stmt.value)
system+='\n父记录通过parent_outputs和parent_record_registry解析，每条父记录仅保存一次。源证据通过evidence_registry解析。固定父输入是来源核查的测量夹具，不是真实模型输出，需保留未知与条件，不得将其理解为正式Gold。'
write('WIRE_CONTRACT.json',{'system_prompt':system,'original_wire_contract_source_sha256':hashes[str(oldrun)],'source_dag_contract_sha256':hashes[str(B/'NODE_CONTRACT.json')],'schema_changed':False,'input_projection':'Reference-only parents, sources represented once; original wire JSON schema retained','validation':'Exact schema and source IDs plus separate semantic review; K never substitutes Q'})
rows=[];payloads={}
models=prior['models']
for m in models:
 if m['key'] in ['glm53','glm53flash']:
  m['model_id']='glm-5.3' if m['key']=='glm53' else 'glm-5.3-flash'
  m['endpoint']='https://open.bigmodel.cn/api/paas/v4/chat/completions'
  m['endpoint_status']='OFFICIAL_DOCUMENTED_STANDARD_API_ACCOUNT_UNVERIFIED'
  m['price']={'currency':'CNY','input_per_M':8 if m['key']=='glm53' else .8,'output_per_M':28 if m['key']=='glm53' else 2.8,'cache_per_M':2 if m['key']=='glm53' else .23,'status':'OFFICIAL_PUBLIC_TARIFF_NOT_ACCOUNT_CERTIFIED'}
  m['thinking']='enabled; reasoning_effort=low'
for n in dag['nodes']:
 if n['executor_kind']!='LLM':continue
 needed=closure([c for par in n['parents'] for c in outputs[par]])
 srcs=set(n['allowed_sources']);ev={k:v for k,v in evidence.items() if v['source_id'] in srcs}
 assert all(a in ev for cid in needed for a in records[cid]['evidence_ids'])
 inp={'task':'RONBAY_202601','node':n['id'],'cutoff':dag['cutoff'],'role':n['role'],'deliverables':n['output_contract']['mandatory_deliverables'],'questions':dag['public_questions'],'evidence_registry':ev,'parent_outputs':{par:outputs[par] for par in n['parents']},'parent_record_registry':{c:records[c] for c in needed},'fixture_origin':'SOURCE_REVIEWED_SILVER_CONDITIONAL_INPUT'}
 write('inputs/'+n['id']+'.json',inp)
 for m in models:
  body={'model':m['model_id'],'max_tokens':3072,'temperature':1.0,'stream':False,'response_format':{'type':'json_object'},'messages':[{'role':'system','content':system},{'role':'user','content':enc(inp).decode()}]}
  if m['key'].startswith('glm'):body.update(thinking={'type':'enabled'},reasoning_effort='low')
  elif m['key']=='deepseek':body['thinking']={'type':'disabled'}
  else:body['enable_thinking']=False
  b=enc(body);write('requests/'+n['id']+'__'+m['key']+'.json',body)
  rows.append({'node':n['id'],'model_key':m['key'],'endpoint':m['endpoint'],'request_sha256':hashb(b),'input_sha256':hashb(enc(inp)),'request_bytes':len(b),'source_spans':len(ev),'parent_records_unique':len(needed),'source_text_once':True,'parent_text_copies':0,'byte_cap':131072,'byte_pass':len(b)<=131072,'exact_provider_tokens':None,'input_token_reserve':65536,'input_bound_certified':False,'output_parameter':3072,'total_billed_output_bound_certified':False,'dispatch_allowed':False})
  payloads[n['id'],m['key']]=hashb(enc(inp))
assert len(rows)==20 and all(r['byte_pass'] for r in rows)
assert all(len({payloads[n,m['key']] for m in models})==1 for n in prior['nodes'])
# Private rubric is never embedded into requests except legitimate, clearly labeled parent fixtures.
classes={1:('收到日/落款日；公开日另据清单，不把落款当公开时刻','监管提问不是最终认定'),2:('1200亿归属公司估算；协议无固定金额','估算不能证明未来收入'),3:('305万吨/6年、附综合竞争力前提的最低采购约定','不能推定无条件305万吨，不能否定附条件约定'),4:('6万吨/年与305万吨/6年；单位期间','不得直接推断履约能力；可选均摊非公司承诺'),5:('2026公式与2027以后、5代以上另议','不得外推六年固定价格；5代以上不擅自改写'),6:('四风险、3/4代未稳定量产及5代开发中','公司判断不是外部保证；最终收入未知')}
rubric=[]
for i,r in enumerate(refs,1):
 rubric.append({'id':'T'+str(i),'source_reference_id':r['id'],'objective_or_direct_statement':classes[i][0],'semantic_guard':classes[i][1],'required_components':r['required_answer_components'],'source_spans':r['evidence'],'unknown':r['UNKNOWN_boundaries'],'optional_calculations':r['calculations'],'reference_grade':'NON_INDEPENDENT_SOURCE_REVIEWED_SILVER','formal_gold':False,'review_rule':'Source-supported substantive components all required for CORRECT; direct contradiction WRONG; unresolved semantic entailment UNKNOWN; omissions reported separately, not silently dropped; citation existence alone is not SUPPORT.'})
write('SILVER_RUBRIC.json',{'items':rubric,'formal_Q':None,'denominator':6,'reviewer':'assistant source-constrained review, non-independent; must preserve itemwise rationale and response hash','mask_model_identity_for_review':True,'review_is_not_independent_blind_human':True,'per_node_scope':{'INQUIRY':['T1'],'REPLY':['T1','T2','T3','T4','T5','T6'],'OBLIGATIONS':['T2','T3','T5','T6'],'CROSSCHECK':['T1','T2','T3','T4','T5','T6'],'FINAL':['T1','T2','T3','T4','T5','T6']},'scope_caveat':'INQUIRY partial factual score does not cover full question extraction; separately audit its deliverable completeness. Different node denominators not interchangeable.','model_unknown_vs_reviewer_unknown':'Model UNKNOWN is recorded verbatim; known reference facts explicitly withheld are omissions, unreviewable semantics remain UNKNOWN. Correct required abstention is scored only against its relevant boundary.','formal_frozen_scorer':'unchanged; no Gold/relevance admissibility override'})
write('REQUEST_AUDIT.json',{'rows':rows,'max_bytes':max(r['request_bytes'] for r in rows),'max_join_bytes':max(r['request_bytes'] for r in rows if r['node']=='CROSSCHECK'),'reference_span_checks':spans,'all_reference_spans_exact':True,'all_inputs_identical_across_models':True,'provider_finality':'Bodies fully serialized, but dispatch BLOCKED for account/fee/token semantics; not a claim of tested provider acceptance','scope':'60 fixed-fixture measurements only; future variable paired-parent maximum not certified'})
prices=[(8,28,1),(.8,2.8,1),(.3,1.2,8),(.8,2,1)]
per=[(65536*a+3072*b)/1e6*fx for a,b,fx in prices]
write('BUDGET.json',{'price_basis':'OFFICIAL_PUBLIC_SCENARIO_NOT_ACTUAL_ACCOUNT_FEES','input_reserved_per_request':65536,'output_planning_cap':3072,'input_worst_case':None,'bill_worst_case':None,'thinking_inclusion_verified':False,'per_model_order':[m['key'] for m in models],'per_model_one_call_CNY':per,'per_model_15_calls_CNY':[15*p for p in per],'measurement_60_CNY':15*sum(per),'paired_24_max_CNY':24*max(per),'total_84_CNY':15*sum(per)+24*max(per),'measurement_60_input_reserve':60*65536,'measurement_60_output_planning_cap':60*3072,'total_84_input_reserve':84*65536,'total_84_output_planning_cap':84*3072,'per_model_measurement_requests':15,'per_model_combined_max_requests':39,'proposed_measurement_estimate_stop_CNY':15,'proposed_full_batch_estimate_stop_CNY':30,'approved_stop_CNY':None,'old_10_transferred':False,'currency_factor':8,'account_rate_certified':False,'automatic_stage2':False,'calibration_planning_scoring_costs':'Paid requests only in measurement/paired sections; local build/selection/manual-review time measured separately, not silently free economic cost; no paid judge requests included'})
write('MODEL_BINDINGS.json',{'models':models,'credential_name_present':{'ZHIPUAI_API_KEY':True,'DEEPSEEK_API_KEY':True,'DASHSCOPE_API_KEY':True},'credential_values_read_or_stored_here':False,'account_product_type':None,'current_permissions':None,'bill_export':None,'no_provider_requests_sent':True,'provider_public_docs':['https://docs.bigmodel.cn/cn/guide/start/pricing','https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash','https://docs.bigmodel.cn/cn/guide/start/concept-param','https://docs.bigmodel.cn/cn/api/introduction'],'mapping_revision':'Both GLMs now use official lowercase model IDs on documented standard endpoint; historical Anthropic request preserved, no automatic identity substitution.'})
write('SCHEDULE_60.json',{'schedule':prior['schedule'],'dispatch_enabled':False,'stage2_enabled':False})
for f,h in hashes.items():assert hashb(Path(f).read_bytes())==h
write('SOURCE_HASHES.json',hashes)
print(json.dumps({'requests_constructed':len(rows),'max_request_bytes':max(r['request_bytes'] for r in rows),'max_crosscheck_bytes':max(r['request_bytes'] for r in rows if r['node']=='CROSSCHECK'),'source_span_checks':len(spans),'measurement_estimate':15*sum(per),'full_estimate':15*sum(per)+24*max(per),'model_calls':0}))
