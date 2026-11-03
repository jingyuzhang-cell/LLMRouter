"""Read-only raw-response analysis; writes separate derived observations, never changes scores or requests."""
import json,hashlib,statistics
from pathlib import Path
P=Path(__file__).resolve().parent
BASE=Path('/root/research_outputs/RONBAY_FINAL_ADMISSION_20261102')
FIELDS=set('claim_id answer_id subject predicate value unit time_scope statement_kind status evidence_ids parent_claim_ids unknown_reason'.split())
KINDS=set('ISSUER_ASSERTION CONTRACT_REPORTED_TERM ESTIMATE FORECAST CONFLICT UNKNOWN'.split())
def check(obj,inp,node):
 errors=[]
 if not isinstance(obj,dict):return ['NOT_JSON_OBJECT']
 if set(obj)!={'claims','complete'}:errors.append('TOP_FIELDS')
 if obj.get('complete') is not True:errors.append('NOT_COMPLETE')
 cs=obj.get('claims')
 if not isinstance(cs,list):return errors+['CLAIMS_NOT_LIST']
 if len(cs)>12:errors.append('CLAIMS_LIMIT')
 if node=='FINAL' and (len(cs)!=6 or sorted(str(c.get('answer_id')) for c in cs if isinstance(c,dict))!=['T1','T2','T3','T4','T5','T6']):errors.append('FINAL_SIX_ANSWERS')
 ids=[];refs=[]
 for i,c in enumerate(cs):
  tag=f'claim[{i}]:'
  if not isinstance(c,dict):errors.append(tag+'NOT_OBJECT');continue
  if set(c)!=FIELDS:errors.append(tag+'FIELDS missing='+','.join(sorted(FIELDS-set(c)))+' extra='+','.join(sorted(set(c)-FIELDS)))
  for k in ['claim_id','answer_id','subject','predicate']:
   if not isinstance(c.get(k),str) or not c.get(k):errors.append(tag+k+'_TYPE')
  ids.append(c.get('claim_id'))
  if c.get('answer_id') not in ['T1','T2','T3','T4','T5','T6','NA']:errors.append(tag+'ANSWER_ID')
  if c.get('statement_kind') not in KINDS:errors.append(tag+'STATEMENT_KIND')
  if c.get('status') not in ['ASSERTED','UNKNOWN','CONFLICT']:errors.append(tag+'STATUS')
  for k in ['evidence_ids','parent_claim_ids']:
   if not isinstance(c.get(k),list) or any(not isinstance(v,str) for v in c.get(k,[])):errors.append(tag+k+'_TYPE')
  es=c.get('evidence_ids',[]);ps=c.get('parent_claim_ids',[])
  if isinstance(es,list) and any(e not in inp['evidence_registry'] for e in es if isinstance(e,str)):errors.append(tag+'UNAVAILABLE_EVIDENCE')
  if isinstance(ps,list):
   refs.extend(ps)
   if any(v not in inp['parent_record_registry'] for v in ps if isinstance(v,str)):errors.append(tag+'UNAVAILABLE_PARENT')
  if c.get('status')=='UNKNOWN':
   if c.get('value') is not None or not isinstance(c.get('unknown_reason'),str) or not c['unknown_reason'].strip():errors.append(tag+'UNKNOWN_RULE')
  elif c.get('value') is None or not es:errors.append(tag+'ASSERTION_VALUE_OR_EVIDENCE')
 if len(set(str(v) for v in ids))!=len(ids):errors.append('DUPLICATE_CLAIM_ID')
 if inp['parent_outputs'] and not any(isinstance(r,str) and r in inp['parent_record_registry'] for r in refs):errors.append('NO_VALID_PARENT_CONSUMED')
 return errors

def main():
 rows=[]
 for d in sorted((P/'run/requests').iterdir()):
  f=d/'MEASUREMENT.json'
  if not f.exists():continue
  m=json.loads(f.read_text());raw=(d/'RESPONSE.bin').read_bytes();r=json.loads(raw)
  try:o=json.loads(r['choices'][0]['message']['content'])
  except (ValueError,TypeError,KeyError):o=None
  inp=json.loads((BASE/'inputs'/f"{m['node']}.json").read_text());errors=check(o,inp,m['node'])
  if m['finish_reason']!='stop':errors.append('INCOMPLETE_GENERATION')
  u=m['usage'];cost=m['public_or_confirmed_price_estimate']
  rows.append({'index':m['index'],'model_key':m['model_key'],'node':m['node'],'repeat':m['repeat'],'K_diagnostic':'PASS' if not errors else 'FAIL','K_errors':errors,'response_sha256':hashlib.sha256(raw).hexdigest(),'input_tokens':u['prompt_tokens'],'output_tokens':u['completion_tokens'],'reasoning_tokens':u.get('completion_tokens_details',{}).get('reasoning_tokens'),'wall_s':m['wall_s'],'public_tariff_CNY_equivalent':(cost['micro_cny']+8*cost['micro_usd'])/1e6,'actual_bill':None,'Q':None,'E_semantic':None})
 matrix=[]
 for n in ['INQUIRY','REPLY','OBLIGATIONS','CROSSCHECK','FINAL']:
  for k in ['glm53','glm53flash','deepseek','qwen']:
   rs=[r for r in rows if r['node']==n and r['model_key']==k]
   matrix.append({'node':n,'model_key':k,'planned_n':3,'response_n':len(rs),'K_pass_n':sum(r['K_diagnostic']=='PASS' for r in rs),'K_fail_n':sum(r['K_diagnostic']=='FAIL' for r in rs),'Q':None,'E_semantic':None,'mean_wall_s':statistics.mean(r['wall_s'] for r in rs) if rs else None,'min_max_wall_s':[min(r['wall_s'] for r in rs),max(r['wall_s'] for r in rs)] if rs else None,'mean_public_tariff_CNY_equivalent':statistics.mean(r['public_tariff_CNY_equivalent'] for r in rs) if rs else None,'total_input_tokens':sum(r['input_tokens'] for r in rs),'total_output_tokens':sum(r['output_tokens'] for r in rs),'actual_bill':None})
 out=P/'analysis';out.mkdir(exist_ok=True)
 (out/'OBSERVATIONS.json').write_text(json.dumps({'note':'Derived schema diagnostics against frozen WIRE_CONTRACT; not a semantic scorer or rewritten historical grade. Q/E require source review. Reasoning token missing means unknown.','rows':rows,'matrix':matrix},ensure_ascii=False,indent=2)+'\n')
 print('Responses analyzed:',len(rows),'K PASS:',sum(r['K_diagnostic']=='PASS' for r in rows))
if __name__=='__main__':main()
