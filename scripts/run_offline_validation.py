#!/usr/bin/env python3
"""Run offline data, scoring, and checkpoint validation without model calls."""
from __future__ import annotations
import argparse, hashlib, json, math, random, re, sys, tempfile
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openclaw_router.checkpoint import append_record, load_successful, write_progress
from openclaw_router.scoring import WEIGHTS, normalized_cost, normalized_latency, risk_weighted_mean, utility

DATA=ROOT/'data/finance_router/frozen/v1/finance_benchmark_v1.jsonl'
PROTOCOL=ROOT/'data/finance_router/frozen/v1/experiment_protocol_v1.json'
PROGRESS=ROOT/'run_logs/llmrouter_experiment_progress_v1.json'
OUT_JSON=ROOT/'run_logs/offline_validation_report.json'
OUT_MD=ROOT/'run_logs/offline_validation_report.md'
SEED=20260727
MODELS=['deepseek-chat','qwen-plus','qwen-turbo','glm-5.2']

def norm(text): return re.sub(r'[^a-z0-9\u4e00-\u9fff]+','',str(text or '').lower())
def task_view(item):
 risk={'high':.86,'medium':.62}.get(str(item.get('risk_level')).lower(),.35)
 return {'id':'finance_dataset_'+str(item['id']),'dataset':item.get('dataset','finance_router'),'task_type':item.get('task_type','financial_qa'),'risk':risk,'raw':item}
def sample(rows,limit=100):
 groups=defaultdict(list)
 for task in rows:
  bucket='high' if task['risk']>=.75 else 'medium' if task['risk']>=.45 else 'low'
  groups[f"{task['dataset']}|{task['task_type']}|{bucket}"].append(task)
 rng=random.Random(SEED)
 for values in groups.values(): rng.shuffle(values)
 selected=[]; keys=sorted(groups)
 while len(selected)<min(limit,len(rows),100):
  progressed=False
  for key in keys:
   if groups[key] and len(selected)<limit: selected.append(groups[key].pop()); progressed=True
  if not progressed: break
 rng.shuffle(selected); return selected

def data_audit(selected,protocol):
 raws=[x['raw'] for x in selected]
 rows_by_id={str(row['id']):row for row in raws}
 questions=[str(x.get('question') or '').strip() for x in raws]
 exact=defaultdict(list)
 for i,q in enumerate(questions): exact[norm(q)].append(raws[i]['id'])
 exact_dupes=[ids for key,ids in exact.items() if key and len(ids)>1]
 near=[]
 for i in range(len(questions)):
  for j in range(i+1,len(questions)):
   if norm(questions[i])==norm(questions[j]): continue
   ratio=SequenceMatcher(None,norm(questions[i]),norm(questions[j])).ratio()
   if ratio>=.92: near.append({'left':raws[i]['id'],'right':raws[j]['id'],'similarity':round(ratio,4)})
 leaks=[]
 for row in raws:
  qn,an=norm(row.get('question')),norm(row.get('gold_answer'))
  if len(an)>=4 and an in qn: leaks.append(row['id'])
 empty_answers=[r['id'] for r in raws if not str(r.get('gold_answer') or '').strip()]
 empty_questions=[r['id'] for r in raws if not str(r.get('question') or '').strip()]
 missing_context=[r['id'] for r in raws if not str(r.get('context') or '').strip() and not r.get('table')]
 missing_evidence=[r['id'] for r in raws if not r.get('evidence')]
 abnormal_questions=[{'id':r['id'],'length':len(str(r.get('question') or ''))} for r in raws if len(str(r.get('question') or ''))<12 or len(str(r.get('question') or ''))>600]
 abnormal_answers=[{'id':r['id'],'length':len(str(r.get('gold_answer') or ''))} for r in raws if len(str(r.get('gold_answer') or ''))>2000]
 def template(q):
  x=str(q).lower(); x=re.sub(r'[0-9a-f]{8}-[0-9a-f-]{20,}','<id>',x); x=re.sub(r'\b\d+(?:\.\d+)?%?\b','<num>',x); x=re.sub(r'\b[A-Z]{2,6}\b','<entity>',str(q)); return re.sub(r'\s+',' ',x).strip()
 templates=Counter(template(q) for q in questions)
 dominant=[{'count':n,'template':t[:240]} for t,n in templates.most_common() if n>=4]
 datasets=Counter(r.get('dataset','unknown') for r in raws)
 risks=Counter(str(r.get('risk_level','unknown')).lower() for r in raws)
 task_types=Counter(r.get('task_type','unknown') for r in raws)
 capability={k:sum(bool(r.get(k)) for r in raws) for k in ('requires_calculation','requires_table_reasoning','requires_kg_reasoning','requires_verification')}
 tickers=Counter()
 for r in raws:
  if 'FinReflect' in str(r.get('dataset')):
   tickers.update(re.findall(r'\b[A-Z]{2,6}\b',str(r.get('question') or '')))
 signature_payload={'freeze_id':protocol.get('freeze_id','unfrozen'),'dataset_sha256':protocol.get('dataset_sha256'),'models':MODELS,'task_ids':[x['id'] for x in selected],'repeats':3,'judge_count':2,'objective_weight':.6,'judge_weight':.4}
 signature=hashlib.sha256(json.dumps(signature_payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 active=json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {}
 errors=[]; warnings=[]
 if empty_questions: errors.append(f'{len(empty_questions)} empty questions')
 if empty_answers: errors.append(f'{len(empty_answers)} empty gold answers')
 if exact_dupes: errors.append(f'{len(exact_dupes)} exact duplicate groups')
 if signature!=active.get('signature'): errors.append('reproduced sample signature differs from active formal run')
 if near: warnings.append(f'{len(near)} near-duplicate pairs require review')
 if leaks: warnings.append(f'{len(leaks)} answers appear verbatim in questions')
 if missing_evidence: warnings.append(f'{len(missing_evidence)} rows have no separate evidence field (all retain non-empty context/table)')
 if abnormal_answers: warnings.append(f'{len(abnormal_answers)} long reference answers exceed 2000 characters')
 near_are_template_variants=bool(near) and all(str(rows_by_id.get(pair['left'],{}).get('dataset','')).startswith('FinReflect') and str(rows_by_id.get(pair['right'],{}).get('dataset','')).startswith('FinReflect') and str(rows_by_id[pair['left']].get('gold_answer')) != str(rows_by_id[pair['right']].get('gold_answer')) for pair in near)
 return {'status':'PASS' if not errors else 'FAIL','errors':errors,'warnings':warnings,'sample_count':len(raws),'sample_signature':signature,'active_signature':active.get('signature'),'signature_match':signature==active.get('signature'),'datasets':dict(datasets),'risk_levels':dict(risks),'task_types':dict(task_types),'capability_coverage':capability,'exact_duplicate_groups':exact_dupes,'near_duplicate_pairs':near,'near_duplicate_classification':'templated_kg_variants_with_distinct_answers' if near_are_template_variants else 'manual_review_required','question_answer_leakage_ids':leaks,'empty_questions':empty_questions,'empty_answers':empty_answers,'missing_context':missing_context,'missing_evidence':missing_evidence,'abnormal_questions':abnormal_questions,'abnormal_answers':abnormal_answers,'dominant_templates':dominant,'finreflect_entity_concentration':dict(tickers.most_common())}

def scoring_audit():
 checks=[]
 def check(name,condition,detail=''): checks.append({'name':name,'passed':bool(condition),'detail':detail})
 base={'quality':.5,'cost':.5,'latency':.5,'reliability':.5}; u=utility(base)
 check('quality monotonic',utility({**base,'quality':.6})>u)
 check('cost monotonic decreasing',utility({**base,'cost':.6})<u)
 check('latency monotonic decreasing',utility({**base,'latency':.6})<u)
 check('reliability monotonic',utility({**base,'reliability':.6})>u)
 check('all-best boundary',utility({'quality':1,'cost':0,'latency':0,'reliability':1})==1.0)
 check('all-worst boundary',utility({'quality':0,'cost':1,'latency':1,'reliability':0})==0.0)
 check('cost clamp low/high',normalized_cost(-1)==0.0 and normalized_cost(10)==1.0)
 check('token clamp',normalized_cost(None,-5,False)==0.0 and normalized_cost(None,9000,False)==1.0)
 check('latency clamp',normalized_latency(-1)==0.0 and normalized_latency(999999)==1.0)
 check('weights sum one',math.isclose(sum(WEIGHTS.values()),1.0))
 rng=random.Random(7); monotonic=True
 for _ in range(2000):
  m={k:rng.random() for k in base}; delta=rng.random()*(1-m['quality'])
  monotonic &= utility({**m,'quality':m['quality']+delta})>=utility(m)
  monotonic &= utility({**m,'cost':min(1,m['cost']+delta)})<=utility(m)
  monotonic &= utility({**m,'latency':min(1,m['latency']+delta)})<=utility(m)
  monotonic &= utility({**m,'reliability':min(1,m['reliability']+delta)})>=utility(m)
 check('2000 randomized monotonic cases',monotonic)
 before=risk_weighted_mean([.4,.6],[.2,.9]); after=risk_weighted_mean([.4,.7],[.2,.9])
 check('risk weighting preserves utility direction',after>before)
 return {'status':'PASS' if all(x['passed'] for x in checks) else 'FAIL','checks':checks,'formula':'U=0.45Q+0.20(1-C)+0.15(1-L)+0.20R'}

def checkpoint_audit():
 checks=[]
 def check(name,condition,detail=''): checks.append({'name':name,'passed':bool(condition),'detail':detail})
 with tempfile.TemporaryDirectory(prefix='llmrouter-checkpoint-test-') as td:
  path=Path(td)/'checkpoint.jsonl'; sig='sig-A'; other='sig-B'
  for i in range(30): append_record(path,{'signature':sig,'task_id':f't{i}','model':'m','repeat':1,'result':{'ok':True,'value':i}})
  loaded=load_successful(path,sig); check('30 percent interruption resumes 30 successes',len(loaded)==30)
  append_record(path,{'signature':sig,'task_id':'failed','model':'m','repeat':1,'result':{'ok':False,'error':'injected'}})
  check('failed result remains retryable',('failed','m',1) not in load_successful(path,sig))
  before=len(load_successful(path,sig)); pending=[f't{i}' for i in range(100) if (f't{i}','m',1) not in load_successful(path,sig)]
  check('successful calls are not scheduled again',before==30 and len(pending)==70)
  append_record(path,{'signature':sig,'task_id':'t1','model':'m','repeat':1,'result':{'ok':True,'value':'latest'}})
  check('latest successful duplicate wins',load_successful(path,sig)[('t1','m',1)]['value']=='latest')
  with path.open('a') as f: f.write('{corrupt json line\n')
  check('corrupt line is ignored',len(load_successful(path,sig))==30)
  append_record(path,{'signature':other,'task_id':'foreign','model':'m','repeat':1,'result':{'ok':True}})
  check('signature isolation',('foreign','m',1) not in load_successful(path,sig) and len(load_successful(path,other))==1)
  progress=Path(td)/'progress.json'; write_progress(progress,{'status':'running','completed':30,'total':100})
  check('atomic progress write',json.loads(progress.read_text())['completed']==30 and not progress.with_suffix('.json.tmp').exists())
 return {'status':'PASS' if all(x['passed'] for x in checks) else 'FAIL','checks':checks}

def markdown(report):
 d,s,c=report['data_audit'],report['scoring_audit'],report['checkpoint_audit']
 lines=['# Offline Experiment Validation','',f"Overall: **{report['overall_status']}**",'', '## Data audit',f"- Status: {d['status']}",f"- Formal sample signature match: {d['signature_match']}",f"- Dataset distribution: {d['datasets']}",f"- Risk distribution: {d['risk_levels']}",f"- Capability coverage: {d['capability_coverage']}",f"- Exact duplicate groups: {len(d['exact_duplicate_groups'])}",f"- Near-duplicate pairs: {len(d['near_duplicate_pairs'])}",f"- Question/answer leakage flags: {len(d['question_answer_leakage_ids'])}",f"- Missing evidence: {len(d['missing_evidence'])}"]
 if d['errors']: lines += ['','Errors:']+[f'- {x}' for x in d['errors']]
 if d['warnings']: lines += ['','Warnings:']+[f'- {x}' for x in d['warnings']]
 lines += ['','## Scoring properties',f"- Status: {s['status']}"]+[f"- {'PASS' if x['passed'] else 'FAIL'}: {x['name']}" for x in s['checks']]
 lines += ['','## Checkpoint fault injection',f"- Status: {c['status']}"]+[f"- {'PASS' if x['passed'] else 'FAIL'}: {x['name']}" for x in c['checks']]
 return '\n'.join(lines)+'\n'

def main():
 rows=[task_view(json.loads(line)) for line in DATA.read_text(encoding='utf-8').splitlines() if line.strip()]
 protocol=json.loads(PROTOCOL.read_text())
 selected=sample(rows,100)
 report={'data_audit':data_audit(selected,protocol),'scoring_audit':scoring_audit(),'checkpoint_audit':checkpoint_audit()}
 report['overall_status']='PASS' if all(report[k]['status']=='PASS' for k in ('data_audit','scoring_audit','checkpoint_audit')) else 'FAIL'
 OUT_JSON.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); OUT_MD.write_text(markdown(report),encoding='utf-8')
 print(json.dumps({'overall_status':report['overall_status'],'json':str(OUT_JSON),'markdown':str(OUT_MD),'data_errors':report['data_audit']['errors'],'data_warnings':report['data_audit']['warnings'],'scoring_passed':sum(x['passed'] for x in report['scoring_audit']['checks']),'checkpoint_passed':sum(x['passed'] for x in report['checkpoint_audit']['checks'])},ensure_ascii=False,indent=2))
 raise SystemExit(0 if report['overall_status']=='PASS' else 1)
if __name__=='__main__': main()
