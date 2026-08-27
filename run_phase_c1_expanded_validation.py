#!/usr/bin/env python3
"""Repeat the frozen C1 protocol on expanded development and fresh holdout."""
import hashlib, json
from collections import Counter
from pathlib import Path
import numpy as np

ROOT=Path('/root'); SOURCE=ROOT/'run_phase_c1_structural_interaction.py'; EXP=ROOT/'target_support_expansion_v1'; OUT=ROOT/'phase_c1_expanded'; OUT.mkdir(exist_ok=True)
# Load only the frozen function definitions/constants, never the old top-level experiment.
source=SOURCE.read_text(); prefix=source.split("protocol=json.loads(PROTOCOL.read_text())",1)[0]
ns={'__name__':'phase_c1_frozen_functions'}; exec(compile(prefix,str(SOURCE),'exec'),ns)
MODELS=ns['MODELS']; structural_features=ns['structural_features']; oof=ns['oof']; evaluate=ns['evaluate']; fit_predict=ns['fit_predict']; bootstrap=ns['bootstrap']

def read(path): return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
protocol=json.loads((ROOT/'phase_c1/C1_PROTOCOL.json').read_text())
old_split=json.loads((ROOT/'target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json').read_text())
new_split=json.loads((EXP/'EXPANSION_DEV_VALIDATION_SPLIT.json').read_text())
tasks={x['id']:x for x in read(EXP/'combined_509_tasks_frozen.jsonl')}; matrix=read(EXP/'combined_509_task_model_matrix_frozen.jsonl'); outcomes={(x['task_id'],x['model']):x for x in matrix}
old_ids=old_split['train_task_ids']+old_split['validation_task_ids']; train_ids=sorted(set(old_ids+new_split['train_task_ids'])); validation_ids=sorted(new_split['validation_task_ids'])
assert len(train_ids)==419 and len(validation_ids)==90 and not set(train_ids)&set(validation_ids)
assert all((t,m) in outcomes for t in train_ids+validation_ids for m in MODELS)
train_mean={m:float(np.mean([outcomes[(t,m)]['utility'] for t in train_ids])) for m in MODELS}; best=max(train_mean,key=train_mean.get)
oof_choices,_,pair_acc,prior_acc=oof(train_ids,tasks,outcomes); oof_result=evaluate(train_ids,oof_choices,outcomes,best)
validation_choices,validation_scores,fit_stats=fit_predict(train_ids,validation_ids,tasks,outcomes); validation=evaluate(validation_ids,validation_choices,outcomes,best); validation['gap_recovery_bootstrap']=bootstrap(validation_ids,validation_choices,outcomes,best)
groups={
 'TAT-low':[t for t in train_ids+validation_ids if tasks[t].get('dataset')=='TAT-QA' and tasks[t].get('risk_level')=='low'],
 'TAT-medium':[t for t in train_ids+validation_ids if tasks[t].get('dataset')=='TAT-QA' and tasks[t].get('risk_level')=='medium'],
 'Obli-high':[t for t in train_ids+validation_ids if tasks[t].get('dataset')=='ObliQA' and tasks[t].get('risk_level')=='high']}
logo={}; all_support=sorted(set(sum(groups.values(),[])))
for name,heldout in groups.items():
    training=sorted(set(all_support)-set(heldout)); means={m:float(np.mean([outcomes[(t,m)]['utility'] for t in training])) for m in MODELS}; group_best=max(means,key=means.get); choices,_,_=fit_predict(training,heldout,tasks,outcomes); logo[name]=evaluate(heldout,choices,outcomes,group_best); logo[name]['gap_recovery_bootstrap']=bootstrap(heldout,choices,outcomes,group_best)
gates={
 'validation_recovery_ge_0.20':validation['gap_recovery']>=.20,
 'validation_utility_above_best_single':validation['mean_utility']>validation['best_single_utility'],
 'pairwise_accuracy_lift_ge_0.03':pair_acc-prior_acc>=.03,
 'oof_recovery_ge_0.20':oof_result['gap_recovery']>=.20,
 'validation_oracle_match_lift_ge_0.05':validation['oracle_match']-validation['best_single_oracle_match']>=.05,
 'bootstrap_positive_probability_ge_0.95':validation['gap_recovery_bootstrap']['positive_probability']>=.95}
report={
 'protocol':protocol,
 'integrity':{'training_tasks':len(train_ids),'fresh_validation_tasks':len(validation_ids),'matrix_rows':len(matrix),'missing_keys':0,'overlap':0,'v2_used':False,'dataset_id_feature':False,'task_type_id_feature':False,'feature_count':len(structural_features(tasks[train_ids[0]])),'protocol_sha256':hashlib.sha256((ROOT/'phase_c1/C1_PROTOCOL.json').read_bytes()).hexdigest(),'split_sha256':hashlib.sha256((EXP/'EXPANSION_DEV_VALIDATION_SPLIT.json').read_bytes()).hexdigest()},
 'training_best_single':{'model':best,'utilities':train_mean},
 'pairwise_interaction':{'oof_sign_accuracy':pair_acc,'oof_global_prior_accuracy':prior_acc,'lift':pair_acc-prior_acc,'full_fit_diagnostics':fit_stats},
 'oof':oof_result,'independent_validation':validation,'leave_one_group_out':logo,'c1_gate':{**gates,'pass':all(gates.values())}}
(OUT/'C1_EXPANDED_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
with (OUT/'C1_EXPANDED_VALIDATION_DECISIONS.jsonl').open('w') as f:
    for t in validation_ids: f.write(json.dumps({'task_id':t,'latent_scores':validation_scores[t],'selected_model':validation_choices[t]},ensure_ascii=False)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
