"""Metadata/provenance audit for unified Static-Dynamic-DAG comparison; no API calls."""
import hashlib,json
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path('/root');OUT=ROOT/'phase_e5_unified'
def rows(p):
 return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 split=json.loads((ROOT/'phase_e4_0_v2/E4_0_B_V2_SPLIT.json').read_text())
 ids=set(split['exploration_train_task_ids']);models=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo');nodes=('N1','N2','N3','N4')
 plans=rows(ROOT/'phase_e4_0_v2/E4_0_B_V2_EXPLORATION_PLAN.jsonl')
 whole=[]
 for line in (ROOT/'phase_c9_0/C9_TRAIN_RESPONSES.jsonl').open():
  r=json.loads(line)
  if r['task_id'] in ids and r['model'] in models:
   whole.append({'task_id':r['task_id'],'model':r['model'],'repeat':r['repeat'],'source':'phase_c9_0/C9_TRAIN_RESPONSES.jsonl'})
 keys=Counter((r['task_id'],r['model'],r['repeat']) for r in whole)
 missing=[(t,m,k) for t in sorted(ids) for m in models for k in range(3) if (t,m,k) not in keys]
 assignments=defaultdict(set)
 for p in plans:assignments[p['task_id']].add(tuple(p['assignment'][n] for n in nodes))
 assert len(ids)==40 and set(assignments)==ids
 result={'status':'NOT_READY_FOR_UNIFIED_FINAL_EXECUTION','development_tasks':40,'common_models':list(models),'whole_query_records':len(whole),'expected_whole_query_records':480,'missing_whole_query_keys':len(missing),'duplicate_whole_query_keys':sum(n-1 for n in keys.values()),'dag_trajectories':len(plans),'dag_terminal_nodes':640,'dag_sequence_support_per_task':sorted(set(map(len,assignments.values()))),'possible_four_model_four_node_sequences':256,'node_propensity_warning':'0.25 is marginal node coverage only. Given task and prior assigned model the next assignment is deterministic in the frozen ladder; it is not conditional sequential propensity 0.25.','joint_policy_value_identified_from_existing_logs':False,'legacy_request_evidence':{'tasks':419,'models':5,'role':'historical experiment; not a row in the 40-task 4-model unified table'},'stateaware_evidence_status':'QUARANTINED_PENDING_ESTIMATOR_CORRECTION','stateaware_audit_findings':['policy_value uses mean q(observed action) for DR baseline instead of q(target policy).','StateAware action selection compares predictions from different realized trajectory states rather than all candidate actions at the same decision state.','bootstrap samples duplicate tasks but collapses matched correction to unique sampled tasks, changing weights.','bootstrap error difference is StateAware minus RequestOnly whereas protocol improvement is RequestOnly minus StateAware.','state shuffle is global before cross-fitting, rather than training-fold-local.','reported N2 DR point difference -0.0715357 differs from bootstrap mean -0.0454886; bootstrap mean is not the point estimate.'],'blockers':['Common final-answer delivery contract and inference settings are not yet shared between historical whole-query and DAG execution.','DAG full-policy outcome must be obtained by actual execution; cannot splice outcomes from incompatible upstream histories.','Objective-specific policy artifacts and paired execution manifest must be frozen before final validation.','Internal holdout freshness needs lineage/leakage-group audit; do not assume the named 20-task holdout is fresh across all historical training.'],'new_api_calls':0,'holdout_outcomes_accessed':False,'label_values_used_for_policy_selection':False}
 inputs=['ROUTING_REGIME_OBJECTIVE_PROTOCOL.json','phase_e3_0/E3_0_PROTOCOL.json','phase_e4_0_v2/E4_0_B_V2_SPLIT.json','phase_e4_0_v2/E4_0_B_V2_EXPLORATION_PLAN.jsonl','phase_e4_1/E4_SCORER_FROZEN.json','phase_e4_1/E4_PHASE_D_MAIN_EXPERIMENT.json','phase_e4_1/run_phase_d_main_experiment.py']
 result['input_sha256']={p:sha(ROOT/p) for p in inputs}
 (OUT/'UNIFIED_READINESS_AUDIT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 (OUT/'WHOLE_QUERY_DEVELOPMENT_INDEX.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in sorted(whole,key=lambda r:(r['task_id'],r['model'],r['repeat']))))
 print(json.dumps({k:result[k] for k in ('status','whole_query_records','missing_whole_query_keys','dag_trajectories','dag_sequence_support_per_task','joint_policy_value_identified_from_existing_logs')},indent=2))
if __name__=='__main__':main()
