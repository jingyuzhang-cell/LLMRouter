"""Offline integrity and diagnostic verification. No dispatch or historical write."""
import collections,hashlib,importlib.util,json,pathlib
P=pathlib.Path(__file__).resolve().parent
ROOT=P.parent
B=ROOT/'RONBAY_MEASUREMENT_RESOURCE_BATCH_20261102'
BASE=ROOT/'RONBAY_FINAL_ADMISSION_20261102'
load=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 inputs={}
 for root in [B,BASE,ROOT/'RONBAY_CROSS_NODE_ANALYSIS_20261103',ROOT/'RONBAY_STATIC_RQ2_PLAN_20261103']:
  for f in root.rglob('*'):
   if f.is_file() and '__pycache__' not in f.parts:inputs[str(f)]=sha(f)
 for f in [P/'EVIDENCE_AND_CANDIDATES.json',P/'REVIEW.md']:inputs[str(f)]=sha(f)
 d=load(P/'EVIDENCE_AND_CANDIDATES.json');rows=d['all_60_observation_states_preserved']
 assert len(rows)==60 and len({r['index'] for r in rows})==60
 spec=importlib.util.spec_from_file_location('offline_contract_check',B/'summarize_observations.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 checked=[]
 for item in d['raw_response_hashes']:
  i=item['index'];row=next(r for r in rows if r['index']==i);f=pathlib.Path(item['path'])
  assert sha(f)==item['sha256']==row['response_sha256']
  req=f.parent/'REQUEST.json';assert sha(req)==row['request_sha256']
  raw=load(f);obj=json.loads(raw['choices'][0]['message']['content'])
  inp=load(BASE/'inputs'/f"{row['node']}.json")
  errors=mod.check(obj,inp,row['node'])
  if raw['choices'][0].get('finish_reason')!='stop':errors.append('INCOMPLETE_GENERATION')
  assert errors==row['contract_errors'],i
  review=load(pathlib.Path(row['review']))
  assert review['review']['response_sha256']==sha(f)
  assert review['K_errors']==errors
  checked.append({'index':i,'node':row['node'],'response_sha256':sha(f),'request_sha256':sha(req),'historical_contract_diagnostic_reproduced':True,'review_response_identity_matches':True})
 assert len(checked)==46
 cross=load(BASE/'inputs/CROSSCHECK.json');date=cross['parent_record_registry']['INQUIRY:DATE']
 assert date['value']=={'notice_signature':'2026-01-14','receipt':'2026-01-13'}
 assert '董事会' in cross['evidence_registry']['E0027']['text']
 details=[]
 for i,n in [(5,'INQUIRY'),(8,'INQUIRY'),(15,'REPLY'),(18,'REPLY'),(21,'REPLY'),(36,'CROSSCHECK'),(43,'CROSSCHECK')]:
  folder=B/'run/requests'/f'cell{i:02d}__{n}';obj=json.loads(load(folder/'RESPONSE.bin')['choices'][0]['message']['content'])
  review=load(B/'analysis'/f'REVIEW_{i:02d}.json')
  target='T1' if n=='CROSSCHECK' else 'T3' if n=='REPLY' else None
  selected=[{'claim_index':j,'raw_claim':c} for j,c in enumerate(obj['claims']) if (target and c.get('answer_id')==target) or (target is None and (c.get('status')=='UNKNOWN' or c.get('parent_claim_ids')))]
  details.append({'index':i,'node':n,'response_sha256':sha(folder/'RESPONSE.bin'),'claims':selected,'original_K_errors':review['K_errors'],'original_review_items':[v for v in review['review']['items'] if v['id']==target]})
  if i==36:assert '2026-01-14' not in json.dumps(selected,ensure_ascii=False) and any('INQUIRY:DATE' in c['raw_claim']['parent_claim_ids'] for c in selected)
  if i==43:assert '问询函落款2026-01-14' in selected[0]['raw_claim']['value']
 assert all(r['dispatch_status']=='NOT_DISPATCHED' for r in rows if r['node']=='FINAL')
 for f,h in inputs.items():assert sha(pathlib.Path(f))==h,f
 out={'status':'OFFLINE_REVIEW_CLOSED_EXECUTION_REMAINS_PAUSED','model_calls_this_review':0,'historical_scores_changed':False,'new_experiment_authorized':False,'inputs_unchanged':True,'input_file_count':len(inputs),'observation_slots':60,'dispatch_states':dict(collections.Counter(r['dispatch_status'] for r in rows)),'response_states':dict(collections.Counter(r['response_status'] for r in rows)),'complete_raw_responses_verified':len(checked),'verified_responses':checked,'focus_cases':details,'crosscheck_input_date_fixture':date,'crosscheck_input_E0027':cross['evidence_registry']['E0027'],'C_decision':'WITHDRAW_PRIORITY_RECOMMENDATION_NOT_TERMINALLY_FALSIFIED','C1_status':'POSTHOC_DEVELOPMENT_HYPOTHESIS_NOT_APPROVED_REPLACEMENT','terminal_propagation_observed':False,'full_Q':None,'input_hashes':inputs}
 with (P/'CLOSEOUT_AUDIT.json').open('x') as f:json.dump(out,f,ensure_ascii=False,indent=2)
 print(json.dumps({k:v for k,v in out.items() if k in ['status','model_calls_this_review','inputs_unchanged','input_file_count','dispatch_states','response_states','complete_raw_responses_verified','C_decision']},ensure_ascii=False))
if __name__=='__main__':main()
