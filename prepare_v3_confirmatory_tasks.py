#!/usr/bin/env python3
"""Freeze outcome-blind 120-task v3 confirmatory manifest."""
import hashlib,json,random,re
from collections import Counter,defaultdict
from pathlib import Path
SEED=20260829;ROOT=Path('/root');DATA=ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/data/finance_router';EXP=ROOT/'target_support_expansion_v1';OUT=ROOT/'v3_confirmatory';OUT.mkdir(exist_ok=True)
SOURCES=('finrome_legacy_v2_confirmatory','finrome_300_confirmatory_v3','finrome_300','safety_expansion_v1');MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo');EXISTING_QUOTA={('TAT-QA','medium'):24,('TAT-QA','low'):2,('ObliQA','high'):40};RAW_MEDIUM={('table','arithmetic'):10,('table-text','arithmetic'):8,('text','arithmetic'):4,('table','span'):4,('table-text','span'):4,('table','multi-span'):2,('table-text','multi-span'):2,('table-text','count'):2};RAW_LOW={('table','span'):6,('table-text','span'):6,('text','span'):6}
def read(p):return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def digest(x):return hashlib.sha256(' '.join((str(x.get('question',''))+' '+str(x.get('context',''))).lower().split()).encode()).hexdigest()
used=read(EXP/'combined_509_tasks_frozen.jsonl');v2=read(DATA/'safety_expansion_v2_counterexample_enrichment/tasks.jsonl');used_ids={x['id'] for x in used};v2_ids={x['id'] for x in v2};used_text={digest(x) for x in used};seen_ids=set();seen_text=set();pools=defaultdict(list)
scored={}
for source in SOURCES:
 latest={(x['task_id'],x['model'],int(x.get('repeat',0))) for x in read(DATA/source/'scored_responses.jsonl')};scored[source]=latest
 for x in read(DATA/source/'tasks.jsonl'):
  key=(str(x.get('dataset')),str(x.get('risk_level')).lower());d=digest(x)
  if key not in EXISTING_QUOTA or x['id'] in used_ids or x['id'] in v2_ids or x['id'] in seen_ids or d in used_text or d in seen_text:continue
  if not all((x['id'],m,r) in latest for m in MODELS for r in range(3)):continue
  seen_ids.add(x['id']);seen_text.add(d);row=dict(x);row['_source_dataset_dir']=source;row['_v3_response_plan']='gemini_only_existing_four_models';pools[key].append(row)
rng=random.Random(SEED);selected=[]
for key,n in EXISTING_QUOTA.items():
 vals=sorted(pools[key],key=lambda x:x['id']);rng.shuffle(vals);assert len(vals)>=n;selected+=vals[:n]
selected_ids={x['id'] for x in selected};selected_text={digest(x) for x in selected};raw=json.load(open(DATA/'raw/tatqa/train.json'));rawp=defaultdict(list)
for doc in raw:
 table=doc['table']['table'];paragraphs=doc.get('paragraphs') or [];context='\n'.join(str(x.get('text') or '') for x in sorted(paragraphs,key=lambda x:x.get('order',0)));rows=len(table);cols=max((len(r) for r in table),default=0)
 for q in doc.get('questions') or []:
  uid=q['uid'];key=(q.get('answer_from'),q.get('answer_type'));question=str(q.get('question') or '');probe={'question':question,'context':context};d=digest(probe)
  if uid in used_ids or uid in v2_ids or uid in selected_ids or d in used_text or d in selected_text:continue
  answer=q.get('answer');answer_text=', '.join(map(str,answer)) if isinstance(answer,list) else str(answer);scale=str(q.get('scale') or '').strip();gold=(answer_text+' '+scale).strip();deriv=str(q.get('derivation') or '').strip();evidence=([deriv] if deriv else [])+list(q.get('rel_paragraphs') or [])
  row={'id':uid,'domain':'finance','dataset':'TAT-QA','task_type':'financial_table_text_reasoning','question':question,'context':context,'table':table,'gold_answer':gold,'evidence':evidence,'requires_calculation':q.get('answer_type')=='arithmetic','requires_table_reasoning':q.get('answer_from') in ('table','table-text'),'requires_kg_reasoning':False,'requires_verification':True,'stratum':f"{q.get('answer_from')}:{q.get('answer_type')}",'source_split':'train','source_url':'https://github.com/NExTplusplus/TAT-QA','source_id':uid,'raw_table_rows':rows,'raw_table_columns':cols,'raw_answer_type':q.get('answer_type'),'raw_answer_from':q.get('answer_from'),'raw_derivation_depth':sum(deriv.count(op) for op in "+-*\/"),'_source_dataset_dir':'raw/tatqa/train.json','_v3_response_plan':'collect_all_five_models'}
  rawp[key].append(row)
def choose(quotas,risk):
 out=[]
 for key,n in quotas.items():
  vals=sorted(rawp[key],key=lambda x:(x['raw_table_rows']*x['raw_table_columns'],x['raw_derivation_depth'],x['id']));rng.shuffle(vals);assert len(vals)>=n
  # Deterministic spread across the shuffled structural pool, with no outcome access.
  pick=vals[:n]
  for x in pick:x['risk_level']=risk
  out.extend(pick)
 return out
selected+=choose(RAW_MEDIUM,'medium')+choose(RAW_LOW,'low');rng.shuffle(selected)
assert len(selected)==120 and len({x['id'] for x in selected})==120 and not ({x['id'] for x in selected}&used_ids) and not ({x['id'] for x in selected}&v2_ids)
assert Counter((x['dataset'],x['risk_level']) for x in selected)==Counter({('TAT-QA','medium'):60,('TAT-QA','low'):20,('ObliQA','high'):40})
path=OUT/'V3_CONFIRMATORY_TASKS.jsonl';path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in selected));distribution=Counter(f"{x['dataset']}:{x['risk_level']}" for x in selected);plans=Counter(x['_v3_response_plan'] for x in selected)
protocol={'version':'v3-confirmatory-v1','status':'FROZEN_BEFORE_ANY_V3_MODEL_OUTCOME','seed':SEED,'selection_outcome_blind':True,'tasks':120,'distribution':dict(distribution),'response_plans':dict(plans),'overlap_existing_509':0,'overlap_c2_diagnostic_90':0,'overlap_v2':0,'normalized_text_overlap':0,'selection_features':['dataset','risk','answer_from','answer_type','table dimensions','derivation operator depth','task id and normalized text uniqueness'],'forbidden_selection_features':['any model response','quality','utility','failure','winner','C2 diagnostic outcomes','v2 outcomes'],'primary_method':'frozen C3 selective advantage; safety-veto failed and is not used','baselines':['best single','frozen C3 selective advantage','oracle'],'success_gates':{'gap_recovery_min':.20,'bootstrap_probability_router_above_best_min':.95,'failure_router_le_best':True,'high_risk_failure_router_le_best':True},'new_response_calls':1008,'gemini_calls':360,'old_four_model_calls_for_new_raw_tat':648,'new_dual_judge_calls':240,'total_external_calls_required':1248,'frar_locked':True}
pp=OUT/'V3_CONFIRMATORY_PROTOCOL.json';pp.write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n')
for p in (path,pp):(OUT/(p.name+'.sha256')).write_text(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n')
print(json.dumps(protocol,ensure_ascii=False,indent=2))
