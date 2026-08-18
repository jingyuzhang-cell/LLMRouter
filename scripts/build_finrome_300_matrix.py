#!/usr/bin/env python3
"""Deduplicate, score, aggregate and freeze the 300x4 outcome matrix."""
import argparse,hashlib,json,statistics
from collections import defaultdict
from pathlib import Path
from openclaw_router.experiment_protocol import objective_score
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data/finance_router/finrome_300'
def read(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
def main(data=DATA):
 global DATA
 DATA=data.resolve()
 tasks={x['id']:x for x in read(DATA/'tasks.jsonl')};responses={}
 for x in read(DATA/'responses.jsonl'):responses[(x['task_id'],x['model'],x['repeat'])]=x
 judge_rows=read(DATA/'judges.jsonl');judges={};failed={}
 for x in judge_rows:
  key=(x['task_id'],x['candidate_model'],x['repeat'],x['judge_model'])
  if x.get('parsed'):judges[key]=x;failed.pop(key,None)
  elif key not in judges:failed[key]=x
 scored=[];manual=[];disagreements=[];uncertain=[]
 for key,r in sorted(responses.items()):
  if not r.get('success'):continue
  tid,model,repeat=key;task=tasks[tid];obj=objective_score(task,str(r.get('answer') or ''));js=[x['score'] for k,x in judges.items() if k[:3]==key];quality=float(obj if obj is not None else 0)
  if task.get('task_type')=='financial_audit_compliance_qa' and len(js)>=2:quality=.55*quality+.45*statistics.mean(js)
  disagreement=max(js)-min(js) if len(js)>=2 else None
  if task.get('task_type')=='financial_audit_compliance_qa' and (len(js)<2 or disagreement>.25):manual.append({'task_id':tid,'model':model,'repeat':repeat,'objective_score':obj,'judge_scores':js,'judge_disagreement':disagreement,'review_status':'PENDING'})
  if disagreement is not None and disagreement>.25:disagreements.append({'task_id':tid,'model':model,'repeat':repeat,'objective_score':obj,'judge_scores':js,'judge_disagreement':disagreement,'review_status':'PENDING'})
  if task.get('risk_level')=='high' and (len(js)<2 or disagreement>.15 or abs(quality-.6)<=.10):uncertain.append({'task_id':tid,'model':model,'repeat':repeat,'objective_score':obj,'judge_scores':js,'judge_disagreement':disagreement,'fused_quality':quality,'review_status':'PENDING'})
  usage=r.get('usage') or {};scored.append({'task_id':tid,'model':model,'repeat':repeat,'dataset':task.get('dataset'),'task_type':task.get('task_type'),'risk_level':task.get('risk_level'),'objective_score':obj,'judge_scores':js,'quality':quality,'cost_usd':float(r.get('cost_usd') or 0),'latency_ms':float(r.get('latency_ms') or 0),'reliability':1.0,'prompt_tokens':usage.get('prompt_tokens',0),'completion_tokens':usage.get('completion_tokens',0)})
 by=defaultdict(list)
 for x in scored:by[(x['task_id'],x['model'])].append(x)
 matrix=[]
 for (tid,model),rs in sorted(by.items()):
  assert len(rs)==3,(tid,model,len(rs));q=statistics.mean(x['quality'] for x in rs);c=statistics.mean(x['cost_usd'] for x in rs);l=statistics.mean(x['latency_ms'] for x in rs);rel=statistics.mean(x['reliability'] for x in rs);u=.45*q+.2*(1-min(c/.02,1))+.15*(1-min(l/10000,1))+.2*rel;matrix.append({'task_id':tid,'model':model,'quality':q,'cost_usd':c,'latency_ms':l,'reliability':rel,'utility':u,'failure':bool(rel<1 or q<.6),'repeats':3})
 assert len(scored)==len(tasks)*4*3 and len(matrix)==len(tasks)*4
 parse_failures=[{**x,'review_status':'PENDING'} for x in failed.values()]
 outputs={'scored_responses.jsonl':scored,'utility_matrix.jsonl':matrix,'manual_review_pending.jsonl':manual,'high_disagreement_pending.jsonl':disagreements,'judge_parse_failures_pending.jsonl':parse_failures,'high_risk_uncertainty_pending.jsonl':uncertain}
 for name,rows in outputs.items():(DATA/name).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
 required=sum(2 for r in responses.values() if r.get('success') and tasks[r['task_id']].get('task_type')=='financial_audit_compliance_qa')
 report={'scored_responses':len(scored),'matrix_rows':len(matrix),'matrix_shape':[len({x['task_id'] for x in matrix}),len({x['model'] for x in matrix})],'complete_tasks':len({x['task_id'] for x in matrix}),'judge_rows':len(judges),'required_judge_rows':required,'pending_human_review':len(manual),'high_disagreement':len(disagreements),'unresolved_parse_failures':len(parse_failures),'high_risk_uncertainty':len(uncertain),'human_review_contract':'all review_status values remain PENDING; no human conclusion is synthesized','primary_quality':'objective score; compliance=.55*objective+.45*mean(two cross-judges)','matrix_sha256':hashlib.sha256((DATA/'utility_matrix.jsonl').read_bytes()).hexdigest()};(DATA/'matrix_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,default=DATA);a=p.parse_args();main(a.data_dir)
