"""Zero-call analysis of closed batch; no original artifact or scorer is modified."""
from pathlib import Path
import json,sqlite3,hashlib,csv,itertools,statistics,math
P=Path(__file__).resolve().parent
B=Path('/root/research_outputs/RONBAY_MEASUREMENT_RESOURCE_BATCH_20261102')
F=Path('/root/research_outputs/RONBAY_FINAL_ADMISSION_20261102')
NODES=['INQUIRY','REPLY','OBLIGATIONS','CROSSCHECK','FINAL'];MODELS=['glm53','glm53flash','deepseek','qwen']
IDS={'glm53':'glm-5.3','glm53flash':'glm-5.3-flash','deepseek':'deepseek-flash','qwen':'qwen-plus-2025-12-01'}
sha=lambda b:hashlib.sha256(b).hexdigest()
readset={}
def read(p):
 b=p.read_bytes();readset[str(p)]=sha(b);return json.loads(b)
def write(n,x):(P/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
schedule=read(F/'SCHEDULE_60.json')['schedule'];ev=read(F/'EVIDENCE_REGISTRY.json');obs=read(B/'analysis/OBSERVATIONS.json');old={r['index']:r for r in obs['rows']};matrixold=read(B/'analysis/MODEL_NODE_MATRIX.json')['matrix']
con=sqlite3.connect('file:'+str(B/'run/ledger.sqlite')+'?mode=ro',uri=True);con.row_factory=sqlite3.Row;calls={r['cell']:dict(r) for r in con.execute('select * from calls')};readset[str(B/'run/ledger.sqlite')]=sha((B/'run/ledger.sqlite').read_bytes())
rows=[];issues=[]
for i,s in enumerate(schedule):
 cell=f'cell{i:02d}';d=B/'run/requests'/(cell+'__'+s['node']);call=calls.get(cell)
 r={'index':i,'node':s['node'],'model_key':s['model_key'],'model_id':IDS[s['model_key']],'repeat':s['repeat'],'position':s['position'],'dispatch_status':'NOT_DISPATCHED' if not call else 'DISPATCHED','response_status':'NOT_DISPATCHED' if not call else 'UNKNOWN','contract_status':'NOT_DISPATCHED' if not call else 'UNKNOWN','input_tokens':None,'output_tokens':None,'reasoning_tokens':None,'cached_input_tokens':None,'wall_s':None,'CNY_estimate':None,'USD_estimate':None,'CNY_equivalent_estimate':None,'actual_bill':None,'formal_Q':None,'fact_counts':None,'semantic_evidence_counts':None,'review':None,'evidence_location':None,'unknown_output_handling':None,'conditional_semantics':None,'reservation':json.loads(call['reserved']) if call else None}
 if (d/'RESPONSE.bin').exists() and (d/'ACCOUNTING.json').exists():
  response=read(d/'RESPONSE.bin');acct=read(d/'ACCOUNTING.json');req=read(d/'REQUEST.json');m=read(d/'MEASUREMENT.json');review=read(B/'analysis'/f'REVIEW_{i:02d}.json');inp=read(F/'inputs'/f"{s['node']}.json")
  if sha((d/'RESPONSE.bin').read_bytes())!=review['review']['response_sha256']:issues.append({'index':i,'issue':'review response hash mismatch'})
  if req['model']!=IDS[s['model_key']] or acct['reported_model']!=req['model']:issues.append({'index':i,'issue':'model identity mismatch'})
  actual=json.loads(call['actual']) if call and call['actual'] else None
  if not actual or actual!=acct['public_price_estimate']:issues.append({'index':i,'issue':'ledger/accounting mismatch'})
  o=json.loads(response['choices'][0]['message']['content']);cs=o['claims'];location=[]
  for c in cs:
   for eid in c.get('evidence_ids',[]):
    found=eid in inp['evidence_registry'] and eid in ev['aliases'];ok=False
    if found:
     a=inp['evidence_registry'][eid];e=ev['registry'][ev['aliases'][eid]];page=ev['sources'][e['doc_id']]['pages'][str(e['page'])]
     ok=page['text'][e['start']:e['end']]==e['quote']==a['text'] and sha(page['text'].encode())==e['page_sha256'] and a['start']==e['start'] and a['end']==e['end']
    location.append({'claim_id':c.get('claim_id'),'evidence_id':eid,'status':'PASS' if ok else 'FAIL'})
  a=review['aggregate'];u=acct['usage'];cost=acct['public_price_estimate'];valid_unknown=[]
  for c in cs:
   if c.get('status')=='UNKNOWN':valid_unknown.append({'claim_id':c.get('claim_id'),'schema_valid':c.get('value') is None and isinstance(c.get('unknown_reason'),str) and bool(c['unknown_reason'].strip()),'semantic_abstention_correctness':'UNKNOWN'})
  cond={}
  for t in ['T3','T5']:
   item=next((v for v in review['review']['items'] if v['id']==t),None)
   cond[t]={'status':'NOT_IN_NODE_REVIEW_SCOPE'} if item is None else {'factual':item['factual'],'evidence':item['evidence'],'rationale':item['rationale']}
  r.update(response_status='PASS',response_meaning='HTTP/model response and usage present; not task success',contract_status=old[i]['K_diagnostic'],contract_errors=old[i]['K_errors'],input_tokens=u['prompt_tokens'],output_tokens=u['completion_tokens'],reasoning_tokens=u.get('completion_tokens_details',{}).get('reasoning_tokens'),cached_input_tokens=u.get('prompt_tokens_details',{}).get('cached_tokens'),wall_s=acct['wall_s'],CNY_estimate=cost['micro_cny']/1e6,USD_estimate=cost['micro_usd']/1e6,CNY_equivalent_estimate=(cost['micro_cny']+8*cost['micro_usd'])/1e6,fact_counts={'PASS':a['fact_correct'],'FAIL':a['fact_wrong'],'UNKNOWN':a['fact_unknown'],'denominator':a['denominator']},semantic_evidence_counts={k:sum(it['evidence']==v for it in review['review']['items']) for k,v in [('PASS','SUPPORTED'),('FAIL','UNSUPPORTED'),('UNKNOWN','UNKNOWN')]},supported_correct=a['supported_correct'],supported_bounds=a['supported_bounds'],fact_bounds=a['fact_bounds'],review=str(B/'analysis'/f'REVIEW_{i:02d}.json'),evidence_location={'PASS':sum(e['status']=='PASS' for e in location),'FAIL':sum(e['status']=='FAIL' for e in location),'occurrences':location,'not_semantic_support':True},unknown_output_handling={'model_UNKNOWN_claim_count':len(valid_unknown),'schema_valid_count':sum(e['schema_valid'] for e in valid_unknown),'claims':valid_unknown,'reviewer_UNKNOWN_is_separate':True},conditional_semantics=cond,request_sha256=readset[str(d/'REQUEST.json')],response_sha256=readset[str(d/'RESPONSE.bin')])
 rows.append(r)
write('REPEAT_OBSERVATIONS_60.json',{'note':'NOT_DISPATCHED and unresolved DISPATCHED measurements have null metrics. Counts zero mean zero observations, never zero quality/cost/latency. K and Silver reused, no regrading.','rows':rows})
matrix=[]
for n in NODES:
 for model in MODELS:
  rs=[r for r in rows if r['node']==n and r['model_key']==model];valid=[r for r in rs if r['response_status']=='PASS'];nv=len(valid)
  def stat(k):
   a=[r[k] for r in valid if r[k] is not None];return {'mean':statistics.mean(a),'min':min(a),'max':max(a),'values':a} if a else None
  den=sum(r['fact_counts']['denominator'] for r in valid);c=sum(r['fact_counts']['PASS'] for r in valid);w=sum(r['fact_counts']['FAIL'] for r in valid);u=sum(r['fact_counts']['UNKNOWN'] for r in valid);supported=sum(r['supported_correct'] for r in valid)
  oldcell=next(x for x in matrixold if x['node']==n and x['model_key']==model)
  if [nv,c,w,u,supported]!=[oldcell['response_n'],oldcell['fact_correct'],oldcell['fact_wrong'],oldcell['fact_unknown'],oldcell['supported_correct']]:issues.append({'node':n,'model':model,'issue':'matrix mismatch'})
  row={'node':n,'model_key':model,'model_id':IDS[model],'planned_n':3,'attempted_n':sum(r['dispatch_status']=='DISPATCHED' for r in rs),'response_PASS_n':nv,'response_FAIL_n':0,'response_UNKNOWN_n':sum(r['response_status']=='UNKNOWN' for r in rs),'NOT_DISPATCHED_n':sum(r['dispatch_status']=='NOT_DISPATCHED' for r in rs),'K_PASS_n':sum(r['contract_status']=='PASS' for r in valid),'K_FAIL_n':sum(r['contract_status']=='FAIL' for r in valid),'formal_Q':None,'fact_counts':{'PASS':c,'FAIL':w,'UNKNOWN':u,'denominator':den} if nv else None,'semantic_evidence_counts':{k:sum(r['semantic_evidence_counts'][k] for r in valid) for k in ['PASS','FAIL','UNKNOWN']} if nv else None,'fact_coverage':(c+w)/den if den else None,'supported_correct':supported if nv else None,'supported_score_lower':supported/den if den else None,'supported_score_upper':statistics.mean(r['supported_bounds'][1] for r in valid) if nv else None,'location_PASS_occurrences':sum(r['evidence_location']['PASS'] for r in valid) if nv else None,'location_FAIL_occurrences':sum(r['evidence_location']['FAIL'] for r in valid) if nv else None,'UNKNOWN_output_claims':sum(r['unknown_output_handling']['model_UNKNOWN_claim_count'] for r in valid) if nv else None,'UNKNOWN_schema_valid':sum(r['unknown_output_handling']['schema_valid_count'] for r in valid) if nv else None,'L_seconds':stat('wall_s'),'CNY_equivalent_estimate':stat('CNY_equivalent_estimate'),'known_input_tokens':sum(r['input_tokens'] for r in valid) if nv else None,'known_output_tokens':sum(r['output_tokens'] for r in valid) if nv else None,'known_CNY_estimate':sum(r['CNY_estimate'] for r in valid) if nv else None,'known_USD_estimate':sum(r['USD_estimate'] for r in valid) if nv else None,'actual_bill':None,'per_repeat_indices':[r['index'] for r in rs]}
  for t in ['T3','T5']:
   a=[r['conditional_semantics'][t] for r in valid];row[t+'_conditional_diagnostic']=None if not a or 'status' in a[0] else {'PASS':sum(e['factual']=='CORRECT' and e['evidence']=='SUPPORTED' for e in a),'FAIL':sum(e['factual']=='WRONG' or e['evidence']=='UNSUPPORTED' for e in a),'UNKNOWN':sum(e['factual']=='UNKNOWN' and e['evidence']!='UNSUPPORTED' for e in a)}
  matrix.append(row)
write('MATRIX_20.json',matrix)
lookup={(r['node'],r['model_key']):r for r in matrix};nodes=NODES[:4]
def combination(assignment):
 cells=[lookup[(n,k)] for n,k in zip(nodes,assignment)]
 return {'assignment':dict(zip(nodes,assignment))|{'FINAL':'UNKNOWN'},'coverage':'4/5 nodes only; FINAL excluded, no cost/latency imputation','full_terminal_Q':None,'full_cost':None,'full_Makespan':None,'partial_mean_cost_CNY':sum(c['CNY_equivalent_estimate']['mean'] for c in cells),'partial_service_time_sum_seconds':sum(c['L_seconds']['mean'] for c in cells),'partial_observed_cost_envelope':[sum(c['CNY_equivalent_estimate'][k] for c in cells) for k in ['min','max']],'partial_observed_service_time_envelope':[sum(c['L_seconds'][k] for c in cells) for k in ['min','max']],'node_K_rates':[c['K_PASS_n']/c['response_PASS_n'] for c in cells],'node_Silver_supported_lower':[c['supported_score_lower'] for c in cells],'node_Silver_supported_upper':[c['supported_score_upper'] for c in cells],'node_response_ns':[c['response_PASS_n'] for c in cells],'is_end_to_end_execution':False,'posthoc':True}
hom=[dict(label=lab,**combination([k]*4)) for lab,k in zip('ABCD',MODELS)]
for h in hom:h['assignment']['FINAL']=h['assignment']['INQUIRY']
selected=[];costfirst=[]
for n in nodes:
 rs=[lookup[(n,k)] for k in MODELS]
 # A posteriori sensitivity rules, never represented as frozen allocator or validated predictor.
 s=sorted(rs,key=lambda c:(-c['K_PASS_n']/c['response_PASS_n'],-c['supported_score_lower'],c['CNY_equivalent_estimate']['mean'],c['L_seconds']['mean']))[0];selected.append(s['model_key'])
 costfirst.append(sorted(rs,key=lambda c:(-c['K_PASS_n']/c['response_PASS_n'],c['CNY_equivalent_estimate']['mean'],c['L_seconds']['mean']))[0]['model_key'])
E=dict(label='E_posthoc_K_then_Silver_then_cost',**combination(selected));sens=dict(label='E_sensitivity_K_then_cost',**combination(costfirst))
allc=[combination(a) for a in itertools.product(MODELS,repeat=4)]
def dominates(a,b):
 va=[-a['partial_mean_cost_CNY'],-a['partial_service_time_sum_seconds']]+a['node_K_rates']+a['node_Silver_supported_lower'];vb=[-b['partial_mean_cost_CNY'],-b['partial_service_time_sum_seconds']]+b['node_K_rates']+b['node_Silver_supported_lower']
 return all(x>=y-1e-12 for x,y in zip(va,vb)) and any(x>y+1e-12 for x,y in zip(va,vb))
front=[a for a in allc if not any(dominates(b,a) for b in allc)]
write('STATIC_COMPOSITION_ESTIMATES.json',{'qualification':'Posthoc independent-node plug-in estimates, not actual complete DAG execution, optimizer result, validated quality probability or future performance. No costs for FINAL, deterministic CAPACITY or scheduling overhead are known here; sum is incomplete. No independence/product-of-success assumption. min/max envelopes are not confidence intervals or guaranteed bounds.','nodes':nodes,'A_to_E':hom+[E],'sensitivity':sens,'observed_proxy_pareto_front':front,'enumerated_count':256,'front_count':len(front),'ranking_dimensions':['min partial cost','min partial service-time sum','max each node K rate','max each node Silver supported lower'],'unknown_upper_not_assumed_correct':True})
rank=[]
for n in nodes:
 rs=[lookup[(n,k)] for k in MODELS]
 rank.append({'node':n,'cost_order':[r['model_key'] for r in sorted(rs,key=lambda c:c['CNY_equivalent_estimate']['mean'])],'latency_order':[r['model_key'] for r in sorted(rs,key=lambda c:c['L_seconds']['mean'])],'K_order_with_ties':[(r['model_key'],r['K_PASS_n'],r['response_PASS_n']) for r in sorted(rs,key=lambda c:-c['K_PASS_n']/c['response_PASS_n'])],'Silver_supported_lower_order':[(r['model_key'],r['supported_score_lower'],r['supported_score_upper']) for r in sorted(rs,key=lambda c:-c['supported_score_lower'])],'formal_quality_rank':'UNKNOWN'})
write('RANKINGS.json',rank)
write('SOURCE_RECONCILIATION.json',{'read_hashes':readset,'mismatches':issues,'inputs_mutated':False,'model_calls':0,'response_status_counts':{s:sum(r['response_status']==s for r in rows) for s in ['PASS','FAIL','UNKNOWN','NOT_DISPATCHED']},'inherited_PLANNED_NOT_RUN_ignored_for_observed_status':True})
with (P/'REPEAT_OBSERVATIONS_60.csv').open('w') as f:
 fields=['index','node','model_key','repeat','position','dispatch_status','response_status','contract_status','input_tokens','output_tokens','wall_s','CNY_estimate','USD_estimate','CNY_equivalent_estimate','actual_bill'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:r[k] for k in fields} for r in rows)
print('mismatches',issues,'proxy frontier',len(front))
for r in hom+[E,sens]:print(r['label'],r['assignment'],round(r['partial_mean_cost_CNY'],6),round(r['partial_service_time_sum_seconds'],3),r['node_K_rates'],r['node_Silver_supported_lower'])
for n in nodes:
 f=lookup[n,'glm53flash'];g=lookup[n,'glm53'];print(n,'Flash cost saving',1-f['CNY_equivalent_estimate']['mean']/g['CNY_equivalent_estimate']['mean'],'latency change',f['L_seconds']['mean']/g['L_seconds']['mean']-1)
