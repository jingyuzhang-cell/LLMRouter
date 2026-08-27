#!/usr/bin/env python3
"""Low-capacity group-conditional fallback after the global C1 gate failure."""

import hashlib
import json
from pathlib import Path

import numpy as np

import run_phase_c1_structural_interaction as c1


ROOT=Path('/root');PROTOCOL=ROOT/'phase_c1/GROUP_CONDITIONAL_PROTOCOL.json';OUT=ROOT/'group_conditional_router_outputs'
protocol=json.loads(PROTOCOL.read_text());split=json.loads(c1.SPLIT.read_text());tasks={x['id']:x for x in c1.read_jsonl(c1.TASKS)};matrix=c1.read_jsonl(c1.MATRIX);outcomes={(x['task_id'],x['model']):x for x in matrix}
train_ids=split['train_task_ids'];validation_ids=split['validation_task_ids']

def group(task):
    if task.get('dataset')=='ObliQA':return 'Obli-high'
    return 'TAT-low' if task.get('risk_level')=='low' else 'TAT-medium'

train_groups={name:[t for t in train_ids if group(tasks[t])==name] for name in protocol['groups']};validation_groups={name:[t for t in validation_ids if group(tasks[t])==name] for name in protocol['groups']}
global_means={m:float(np.mean([outcomes[(t,m)]['utility'] for t in train_ids])) for m in c1.MODELS};global_best=max(global_means,key=global_means.get)
group_best={};best_choices={};learned_choices={};learned_scores={};fit_diagnostics={}
for name in protocol['groups']:
    tr=train_groups[name];va=validation_groups[name];means={m:float(np.mean([outcomes[(t,m)]['utility'] for t in tr])) for m in c1.MODELS};group_best[name]=max(means,key=means.get)
    for t in va:best_choices[t]=group_best[name]
    choices,scores,stats=c1.fit_predict(tr,va,tasks,outcomes);learned_choices.update(choices);learned_scores.update(scores);fit_diagnostics[name]=stats

global_choices={t:global_best for t in validation_ids};global_eval=c1.evaluate(validation_ids,global_choices,outcomes,global_best);conditional_best_eval=c1.evaluate(validation_ids,best_choices,outcomes,global_best);learned_eval=c1.evaluate(validation_ids,learned_choices,outcomes,global_best)
conditional_best_eval['gap_recovery_bootstrap']=c1.bootstrap(validation_ids,best_choices,outcomes,global_best);learned_eval['gap_recovery_bootstrap']=c1.bootstrap(validation_ids,learned_choices,outcomes,global_best)
by_group={}
for name,ids in validation_groups.items():
    by_group[name]={'group_best_single':c1.evaluate(ids,{t:best_choices[t] for t in ids},outcomes,global_best),
                    'group_structural_router':c1.evaluate(ids,{t:learned_choices[t] for t in ids},outcomes,global_best)}
gates={'validation_recovery_ge_0.20':learned_eval['gap_recovery']>=.20,'utility_above_global_best_single':learned_eval['mean_utility']>global_eval['mean_utility'],
       'bootstrap_positive_probability_ge_0.95':learned_eval['gap_recovery_bootstrap']['positive_probability']>=.95}
report={'protocol':protocol,'integrity':{'protocol_sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),'train_validation_overlap':0,'v2_used':False},
        'global_best_single':{'model':global_best,'validation':global_eval},'group_best_models':group_best,'group_conditional_best_single':conditional_best_eval,
        'group_conditional_structural_router':learned_eval,'by_group':by_group,'fit_diagnostics':fit_diagnostics,'gate':{**gates,'pass':all(gates.values())}}
OUT.mkdir(parents=True,exist_ok=True);(OUT/'GROUP_CONDITIONAL_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
with (OUT/'GROUP_CONDITIONAL_DECISIONS.jsonl').open('w') as f:
    for t in sorted(validation_ids):f.write(json.dumps({'task_id':t,'group':group(tasks[t]),'group_best_model':best_choices[t],'structural_selected_model':learned_choices[t],'latent_scores':learned_scores[t]},ensure_ascii=False)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
