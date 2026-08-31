#!/usr/bin/env python3
"""Build and freeze the complete v3 120x5x3 matrix, preserving four GLM failures."""
import hashlib,json,sys
from collections import defaultdict
from pathlib import Path
import numpy as np
ROOT=Path('/root');PROJECT=ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main';DATA_ROOT=PROJECT/'data/finance_router';V3=ROOT/'v3_confirmatory';MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash');OLD=MODELS[:-1]
sys.path.insert(0,str(PROJECT));from openclaw_router.experiment_protocol import objective_score
def read(p):return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def write(p,rows):Path(p).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
def util(q,c,l,r):return .45*q+.20*(1-min(c/.02,1))+.15*(1-min(l/10000,1))+.20*r
tasks=read(V3/'V3_CONFIRMATORY_TASKS.jsonl');responses={};last={}
for x in read(V3/'V3_NEW_RESPONSES.jsonl'):
 k=(x['task_id'],x['model'],int(x['repeat']));last[k]=x
 if x['success'] and str(x.get('answer') or '').strip():responses[k]=x
judges={(x['task_id'],int(x['repeat']),x['judge_model']):x for x in read(V3/'V3_GEMINI_COMPLIANCE_JUDGES.jsonl') if x['parsed']};assert len(judges)==240
sources={}
for source in sorted({x['_source_dataset_dir'] for x in tasks if x['_v3_response_plan']=='gemini_only_existing_four_models'}):
 latest={}
 for x in read(DATA_ROOT/source/'scored_responses.jsonl'):latest[(x['task_id'],x['model'],int(x.get('repeat',0)))]=x
 sources[source]=latest
rows=[];forced_fail=[]
for t in tasks:
 tid=t['id']
 for m in MODELS:
  for r in range(3):
   if m in OLD and t['_v3_response_plan']=='gemini_only_existing_four_models':
    x=sources[t['_source_dataset_dir']][(tid,m,r)];rows.append({'task_id':tid,'model':m,'repeat':r,'dataset':t['dataset'],'task_type':t['task_type'],'risk_level':t['risk_level'],'quality':float(x['quality']),'cost_usd':float(x.get('cost_usd') or 0),'latency_ms':float(x.get('latency_ms') or 0),'reliability':float(x.get('reliability',1)),'scoring_rule':'frozen_project_scored_response'});continue
   key=(tid,m,r);x=responses.get(key)
   if x is None:
    assert m=='glm-5.2' and key in last and last[key].get('error')=='empty answer';f=last[key];rows.append({'task_id':tid,'model':m,'repeat':r,'dataset':t['dataset'],'task_type':t['task_type'],'risk_level':t['risk_level'],'quality':0.0,'cost_usd':float(f.get('cost_usd') or 0),'latency_ms':float(f.get('latency_ms') or 0),'reliability':0.0,'scoring_rule':'persistent_empty_answer_as_real_failure'});forced_fail.append(key);continue
   objective=float(objective_score(t,str(x.get('answer') or '')+'\n') or 0);quality=objective;js=[];rule='objective_score'
   if t['task_type']=='financial_audit_compliance_qa':
    assert m=='gemini-2.5-flash';js=[float(judges[(tid,r,j)]['score']) for j in ('deepseek-chat','qwen-plus')];quality=.55*objective+.45*float(np.mean(js));rule='0.55*objective+0.45*dual_judge_mean'
   rows.append({'task_id':tid,'model':m,'repeat':r,'dataset':t['dataset'],'task_type':t['task_type'],'risk_level':t['risk_level'],'quality':quality,'objective_score':objective,'judge_scores':js,'cost_usd':float(x.get('cost_usd') or 0),'latency_ms':float(x.get('latency_ms') or 0),'reliability':1.0,'scoring_rule':rule})
assert len(rows)==1800 and len({(x['task_id'],x['model'],x['repeat']) for x in rows})==1800 and len(forced_fail)==4
g=defaultdict(list)
for x in rows:g[(x['task_id'],x['model'])].append(x)
matrix=[]
for (tid,m),v in sorted(g.items()):
 assert sorted(x['repeat'] for x in v)==[0,1,2];q=float(np.mean([x['quality'] for x in v]));c=float(np.mean([x['cost_usd'] for x in v]));l=float(np.mean([x['latency_ms'] for x in v]));rel=float(np.mean([x['reliability'] for x in v]));matrix.append({'task_id':tid,'model':m,'dataset':v[0]['dataset'],'task_type':v[0]['task_type'],'risk_level':v[0]['risk_level'],'quality':q,'failure':bool(rel<1 or q<.6),'cost_usd':c,'latency_ms':l,'reliability':rel,'utility':util(q,c,l,rel),'repeats':3,'repeat_aggregation':'mean'})
assert len(matrix)==600
rp=V3/'V3_REPEAT_MATRIX_FROZEN.jsonl';mp=V3/'V3_TASK_MODEL_MATRIX_FROZEN.jsonl';write(rp,rows);write(mp,matrix);manifest={'tasks':120,'models':5,'repeats':3,'repeat_rows':1800,'aggregate_rows':600,'duplicate_keys':0,'missing_keys':0,'persistent_glm_failures':len(forced_fail),'persistent_glm_failure_keys':[list(x) for x in forced_fail],'judges':240,'sha256':{rp.name:hashlib.sha256(rp.read_bytes()).hexdigest(),mp.name:hashlib.sha256(mp.read_bytes()).hexdigest()}};(V3/'V3_MATRIX_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');print(json.dumps(manifest,ensure_ascii=False,indent=2))
