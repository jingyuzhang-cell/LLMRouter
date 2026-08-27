#!/usr/bin/env python3
"""Build the frozen 300-task expansion matrix and combined target-support matrix."""
import hashlib, json, sys
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT=Path('/root'); PROJECT=ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main'
DATA_ROOT=PROJECT/'data/finance_router'; EXP=ROOT/'target_support_expansion_v1'; OLD=ROOT/'five_model_routability_audit'
OLD_SPLIT=ROOT/'target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json'; OLD_TASKS=ROOT/'gemini_frar_pilot/five_model_v1/gemini_training_pilot_tasks.jsonl'
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash'); OLD_MODELS=MODELS[:-1]
sys.path.insert(0,str(PROJECT)); from openclaw_router.experiment_protocol import objective_score

def read(path): return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
def write(path,rows): Path(path).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
def util(q,c,l,r): return .45*q+.20*(1-min(c/.02,1))+.15*(1-min(l/10000,1))+.20*r

tasks=read(EXP/'TARGET_SUPPORT_EXPANSION_TASKS.jsonl'); responses={(x['task_id'],int(x['repeat'])):x for x in read(EXP/'gemini_responses.jsonl')}
judges={(x['task_id'],int(x['repeat']),x['judge_model']):x for x in read(EXP/'gemini_compliance_judges.jsonl')}
sources={}
for source in sorted({x['_source_dataset_dir'] for x in tasks}):
    latest={}
    for row in read(DATA_ROOT/source/'scored_responses.jsonl'): latest[(row['task_id'],row['model'],int(row.get('repeat',0)))]=row
    sources[source]=latest
repeats=[]
for task in tasks:
    tid=task['id']
    for model in OLD_MODELS:
        for repeat in range(3):
            old=sources[task['_source_dataset_dir']][(tid,model,repeat)]
            repeats.append({'task_id':tid,'model':model,'repeat':repeat,'dataset':task['dataset'],'task_type':task['task_type'],'risk_level':task['risk_level'],'quality':float(old['quality']),'cost_usd':float(old.get('cost_usd') or 0),'latency_ms':float(old.get('latency_ms') or 0),'reliability':float(old.get('reliability',1)),'scoring_rule':'frozen_project_scored_response'})
    for repeat in range(3):
        response=responses[(tid,repeat)]
        # The newline avoids the known terminal-marker edge case without changing answer content.
        objective=float(objective_score(task,str(response.get('answer') or '')+'\n') or 0)
        scores=[]; quality=objective; rule='objective_score'
        if task['task_type']=='financial_audit_compliance_qa':
            scores=[float(judges[(tid,repeat,j)]['score']) for j in ('deepseek-chat','qwen-plus')]
            quality=.55*objective+.45*float(np.mean(scores)); rule='0.55*objective+0.45*dual_judge_mean'
        repeats.append({'task_id':tid,'model':'gemini-2.5-flash','repeat':repeat,'dataset':task['dataset'],'task_type':task['task_type'],'risk_level':task['risk_level'],'quality':quality,'objective_score':objective,'judge_scores':scores,'cost_usd':float(response.get('cost_usd') or 0),'latency_ms':float(response.get('latency_ms') or 0),'reliability':float(response.get('error') is None),'scoring_rule':rule})
assert len(repeats)==4500 and len({(x['task_id'],x['model'],x['repeat']) for x in repeats})==4500
grouped=defaultdict(list)
for row in repeats: grouped[(row['task_id'],row['model'])].append(row)
matrix=[]
for (tid,model),rows in sorted(grouped.items()):
    assert sorted(x['repeat'] for x in rows)==[0,1,2]
    q=float(np.mean([x['quality'] for x in rows])); c=float(np.mean([x['cost_usd'] for x in rows])); l=float(np.mean([x['latency_ms'] for x in rows])); r=float(np.mean([x['reliability'] for x in rows]))
    matrix.append({'task_id':tid,'model':model,'dataset':rows[0]['dataset'],'task_type':rows[0]['task_type'],'risk_level':rows[0]['risk_level'],'quality':q,'failure':bool(r<1 or q<.6),'cost_usd':c,'latency_ms':l,'reliability':r,'utility':util(q,c,l,r),'repeats':3,'repeat_aggregation':'mean'})
assert len(matrix)==1500
write(EXP/'expanded_five_model_repeats_frozen.jsonl',repeats); write(EXP/'expanded_five_model_matrix_frozen.jsonl',matrix)
old_split=json.loads(OLD_SPLIT.read_text()); old_ids=set(old_split['train_task_ids']+old_split['validation_task_ids'])
old_matrix=[x for x in read(OLD/'five_model_task_model_matrix_frozen.jsonl') if x['task_id'] in old_ids]
combined=old_matrix+matrix
assert len(old_ids)==209 and len(combined)==(209+300)*5 and len({(x['task_id'],x['model']) for x in combined})==len(combined)
write(EXP/'combined_509_task_model_matrix_frozen.jsonl',combined)
old_tasks={x['id']:x for x in read(OLD_TASKS)}; combined_tasks=[old_tasks[x] for x in sorted(old_ids)]+tasks
write(EXP/'combined_509_tasks_frozen.jsonl',combined_tasks)
manifest={'repeat_rows':len(repeats),'expansion_matrix_rows':len(matrix),'combined_tasks':len(combined_tasks),'combined_matrix_rows':len(combined),'missing_keys':0,'duplicate_keys':0,'scoring_rule':'unchanged frozen rule','sha256':{}}
for name in ('gemini_responses.jsonl','gemini_compliance_judges.jsonl','expanded_five_model_repeats_frozen.jsonl','expanded_five_model_matrix_frozen.jsonl','combined_509_task_model_matrix_frozen.jsonl','combined_509_tasks_frozen.jsonl'):
    manifest['sha256'][name]=hashlib.sha256((EXP/name).read_bytes()).hexdigest()
(EXP/'EXPANDED_MATRIX_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
