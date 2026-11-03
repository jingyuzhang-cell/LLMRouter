"""Read-only provenance / outcome audit; never imports an executor or transport."""
import json,hashlib,copy,sys,ast
from pathlib import Path
from decimal import Decimal
from collections import Counter
ROOT=Path('/root/capital_opinion_pilot');OUT=Path(__file__).parent
FINAL=ROOT/'v5_final_acceptance_20261022_v1'
BASE=Path('/root/r3_own_pool');REPEAT=BASE/'ab_numeric_recovery_repeat_v1/REAL_BATCH_20261019_030355'
SINGLE=BASE/'ab_numeric_recovery_controlled_execution_v1/REAL_RUN_20261019_023824'
CONTROL=BASE/'ab_numeric_recovery_controlled_v1'
SOURCES={}
def h(data):return hashlib.sha256(data).hexdigest()
def track(p):
 p=Path(p);b=p.read_bytes();SOURCES[str(p)]={'sha256':h(b),'bytes':len(b)};return b
def load(p):return json.loads(track(p))
def lines(p):return [json.loads(t) for t in track(p).decode().splitlines() if t.strip()]
def encode(v):
 if isinstance(v,dict):
  if any(not isinstance(k,str) for k in v):return {'__items__':[[encode(k),encode(x)] for k,x in sorted(v.items(),key=lambda t:str(t[0]))]}
  return {k:encode(x) for k,x in v.items()}
 if isinstance(v,set):return {'__set__':sorted(v)}
 if isinstance(v,tuple):return {'__tuple__':[encode(x) for x in v]}
 if isinstance(v,list):return [encode(x) for x in v]
 return v
def dump(name,value):
 payload=json.dumps(encode(value),ensure_ascii=False,indent=2)
 path=OUT/name
 if path.exists():
  assert json.loads(path.read_text())==json.loads(payload),name
  return  # preserve the prior successful artifact, never overwrite it
 with path.open('x') as f:f.write(payload+'\n')
def decode(v):
 if isinstance(v,list):return [decode(x) for x in v]
 if isinstance(v,dict):
  if '__items__' in v:return {decode(k):decode(x) for k,x in v['__items__']}
  if '__set__' in v:return set(v['__set__'])
  if '__tuple__' in v:return tuple(decode(x) for x in v['__tuple__'])
  return {k:decode(x) for k,x in v.items()}
 return v
freeze=load(OUT/'ALGORITHM_FREEZE.json')
for name,digest in freeze['algorithm_sha256'].items():assert h(track(name))==digest
rows=decode(load(FINAL/'V5_VS_RL_DECISIONS.json'));diff=[r for r in rows if not r['same_action']]
assert [r['id'] for r in diff]==['S01','S02','S03','S10','S11']
for p in [FINAL/'V5_VS_RL_DECISION_AUDIT.md',FINAL/'JOINT_OPTIMIZER_V5_MIGRATION_REPORT.md',FINAL/'SCENARIO_MATRIX.json',FINAL/'MATRIX_FREEZE.json',ROOT/'V5_VS_RL_DECISION_AUDIT.md',ROOT/'JOINT_OPTIMIZER_V5_MIGRATION_REPORT.md',ROOT/'task_quality.py',ROOT/'S6_V5_DECISION_GATE.md']:track(p)
# Reconstruct only original, own-input observations, not V5/RL actions.
post=load(CONTROL/'POST_FAULT_SNAPSHOT.json');common=load(CONTROL/'COMMON_VALID_SNAPSHOT.json');deps=load(CONTROL/'DEPENDENCY_IDENTITIES.json')
dep_checks={p:h(track(p))==digest for p,digest in deps.items()}
assert all(dep_checks.values())
prefix=post['branches']['extract_purchase'];prefix_hash=h(json.dumps(prefix['payload'],ensure_ascii=False,sort_keys=True).encode())
assert prefix_hash==prefix['cache']['bytes_sha256']
assert prefix['cache']['identity']==prefix['expected_identity']
assert post['branches']['extract_payables']['cache'] is None and post['audit_payload_in_executable_cache'] is False
records=load(REPEAT/'ALL_REQUEST_RECORDS.json');paired=load(REPEAT/'PAIRED_ANALYSIS.json');diagnostics=load(REPEAT/'ATTEMPT_CONTENT_DIAGNOSTICS.json')
repeat_manifest=load(REPEAT/'RESULT_MANIFEST.json')
rate_snapshot=load(REPEAT/'PRICE_CHECK.json')
observations=[]
def inspect_call(directory,arm,rec,pair_id,dataset,manifest=None):
 body=load(directory/(arm+'_REQUEST.json'));raw_bytes=track(directory/(arm+'_HTTP_RESPONSE.bin'))
 raw=json.loads(raw_bytes);text=track(directory/(arm+'_MODEL_OUTPUT.txt')).decode()
 saved=load(directory/(arm+'_RESULT.json'));action=load(directory/(arm+'_ACTION.json'));terminal=load(directory/(arm+'_TERMINAL.json'))
 binding=load(directory/'EXECUTION_BINDING.json')
 checks={'canonical_body_hash_matches':h(json.dumps(body,ensure_ascii=False,separators=(',',':')).encode())==rec['body_sha256'],
  'canonical_messages_hash_matches':h(json.dumps(body['messages'],ensure_ascii=False,separators=(',',':')).encode())==rec['messages_sha256'],
  'requested_model_matches':body['model']==rec['model_requested'],
  'raw_text_matches_http_content':text==raw['choices'][0]['message']['content'],
  'usage_matches_http':rec['usage']==raw['usage'],
  'raw_result_body_hash_matches':saved['body_sha256']==rec['body_sha256'],
  'snapshot_hash_matches_binding':binding['initial_conditions_sha256']==h(track(CONTROL/'POST_FAULT_SNAPSHOT.json')),
  'cached_branch_identity_matches_expected':action['state']['nodes']['extract_purchase']['cache']['identity']==prefix['expected_identity'],
  'cached_branch_payload_fingerprint_matches':action['state']['nodes']['extract_purchase']['cache']['bytes_sha256']==prefix_hash,
  'source_snapshot_identity_matches':action['state']['nodes']['extract_payables']['expected_identity']['source_hash']==post['branches']['extract_payables']['expected_identity']['source_hash'],
  'action_assignment_matches_request':action['action']['pi'].get('extract_payables')==rec['model_requested'],
  'action_R_matches_original_recovery':['extract_payables']==action['action']['R']}
 if manifest is not None:
  for name in [arm+'_REQUEST.json',arm+'_HTTP_RESPONSE.bin',arm+'_MODEL_OUTPUT.txt',arm+'_RESULT.json',arm+'_ACTION.json',arm+'_TERMINAL.json']:
   key=str((directory/name).relative_to(REPEAT))
   checks['frozen_artifact:'+name]=manifest['files'][key]==h(track(directory/name))
 try:parsed=json.loads(text)
 except json.JSONDecodeError:parsed=None
 checks['parsed_raw_payload_equals_saved']=parsed==rec['payload']
 legal=bool(rec['bounded_contract_pass'])
 if legal:
  assert isinstance(parsed,dict) and isinstance(parsed.get('items'),list)
  rebuilt={'items':prefix['payload']['items']+parsed['items']}
  checks['committed_nodes_match']={'extract_purchase','extract_payables'}==set(terminal['committed_nodes'])
 else:
  # Invalid arrays are inspected only; NEVER normalized or submitted.
  rebuilt={'items':prefix['payload']['items']}
  checks['invalid_response_not_committed']='extract_payables' not in terminal['committed_nodes']
 checks['own_input_terminal_submission_matches']=rebuilt==terminal['merged']
 assert all(checks.values()),(dataset,pair_id,arm,[k for k,v in checks.items() if not v])
 out={'dataset':dataset,'pair_id':pair_id,'arm':arm,'source_class':'HISTORICAL_REAL_EXECUTION_OBSERVATION',
  'reconstruction_class':'OWN_INPUT_OBSERVATION_RECONSTRUCTION_NOT_POLICY_REEXECUTION',
  'strict_current_v5_rl_replay_eligible':False,'model_requested':rec['model_requested'],
  'body_sha256':rec['body_sha256'],'messages_sha256':rec['messages_sha256'],
  'source_directory':str(directory),'raw_response_sha256':h(raw_bytes),'raw_text_sha256':h(text.encode()),
  'checks':checks,'native_schema_pass_recorded':rec['native_schema_pass'],
  'bounded_contract_pass_recorded':legal,'full_opinion_contract':rec.get('full_opinion_contract'),
  'payload_replay_allowed_for_original_commit':legal,'invalid_response_released':False,
  'original_action':action['action'],'original_core_state_sha256':action['core_state_sha256'],
  'terminal_score_recorded':terminal['score'],'committed_nodes_recorded':terminal['committed_nodes'],
  'usage_recorded':rec['usage'],'client_call_s_recorded':rec.get('client_call_wall_s'),
  'api_s_recorded':rec.get('api_wall_s'),'cold_miss_peak_estimate_recorded':rec.get('cold_miss_peak_estimate'),
  'currency':rec.get('currency'),'actual_cash':rec.get('actual_cash'),'bill_status':rec.get('bill_status')}
 observations.append(out)
for rec in records:
 dirs=list((REPEAT/rec['pair_id']).glob('REAL_RUN_*'));assert len(dirs)==1
 inspect_call(dirs[0],rec['arm'],rec,rec['pair_id'],'NUMERIC_REPEAT',repeat_manifest)
for arm in ['A','B']:
 rec=load(SINGLE/(arm+'_RESULT.json'))
 inspect_call(SINGLE,arm,rec,'CONTROLLED_SINGLE','NUMERIC_CONTROLLED_SINGLE')
# Old capital-market traces have response/ledger identity but lack full request inputs.
f7res=lines(ROOT/'f7v2_resp.jsonl');f7led=lines(ROOT/'f7v2_ledger.jsonl');f7results=load(ROOT/'f7v2_results.json')
f7_identity=[]
for r in f7res:
 matches=[(i,l) for i,l in enumerate(f7led,1) if (l['call_id'],l['run_id'],l['node'],l['model'])==(r['call_id'],r['run_id'],r['node'],r['model'])]
 assert len(matches)==1
 i,l=matches[0]
 f7_identity.append({'call_id':r['call_id'],'run_id':r['run_id'],'node':r['node'],'model':r['model'],
 'response_text_sha256':h(r['text'].encode()),'ledger_line':i,'tokens':{'input':l['in'],'output':l['out']},
 'latency_recorded_s':l['lat'],'truncated_recorded':l['truncated'],
 'strict_replay_eligible':False,'reason':'original body/source/cache consumed-version identity not supplied by this trace schema'})
for p in [BASE/'runtime_real_task_binding_v1/RESULT.md',BASE/'runtime_real_task_binding_v1/VERDICT.json',BASE/'runtime_real_task_binding_v1/OBSERVED_REPLAY_RESULT.json',REPEAT/'REPEATED_RECOVERY_RESULT.md',SINGLE/'CONTROLLED_AB_RECOVERY_RESULT.md']:track(p)
# Recorded branch diagnostics: keep assignment scope and failed submissions separate.
diag_summary={'recorded_response_count':len(diagnostics),'assigned_amount_matches':0,'assigned_amount_observations':0,'invalid_arrays_with_correct_numeric_items':[]}
for r in diagnostics:
 items=r['score']['content_details']['items'];diag_summary['assigned_amount_observations']+=len(items)
 diag_summary['assigned_amount_matches']+=sum(i['status']=='MATCH' for i in items)
 if not r['score']['raw_schema_pass']:diag_summary['invalid_arrays_with_correct_numeric_items'].append(r['pair_id']+':'+r['arm'])
# Match gate: synthetic actions have NO frozen provider request or model alias mapping.
scenario_reports=[]
for r in diff:
 a,b=r['V5'],r['RL'];dims=[]
 for key in ['Z','R','pi']:
  if a['decision'][key]!=b['decision'][key]:dims.append(key)
 gates={'task_and_material_identity':'MISMATCH_SYNTHETIC_VS_REAL_EVENT',
 'model_identity':'NO_FROZEN_fast_cheap_TO_PROVIDER_MAPPING',
 'request_body_identity':'ABSENT_FOR_SYNTHETIC_CALLBACK_ACTION',
 'cache_input_and_version_identity':'NO_EQUIVALENT_REAL_SNAPSHOT',
 'contract_identity':'SYNTHETIC_NUMERIC_CALLBACK_NOT_REAL_ITEMS_OR_REPORT_CONTRACT'}
 synthetic_delta=r['comparison']
 scenario_reports.append({'scenario_id':r['id'],'dimension':r['dimension'],'difference_dimensions':dims,
  'V5_action':a['decision'],'RL_action':b['decision'],'prepared_state_sha256':a['prepared_state_sha256'],
  'same_prepared_state':a['prepared_state_sha256']==b['prepared_state_sha256'],
  'state_source':str(FINAL/'V5_VS_RL_DECISIONS.json'),'scenario_full_state':r['complete_input'],
  'feedback':a['prepared_state']['feedback'],'candidate_counts':{'V5':a['n_candidates'],'RL':b['n_candidates']},
  'feasible_counts':{'V5':a['n_feasible'],'RL':b['n_feasible']},
  'hard_constraint_rejection_counts':{'V5':a['rejection_counts'],'RL':b['rejection_counts']},
  'existing_synthetic_predictions':{'V5':a['prediction'],'RL':b['prediction']},
  'existing_synthetic_execution':{'V5':a['execution'],'RL':b['execution']},
  'existing_synthetic_comparison':synthetic_delta,
  'strict_real_response_matching_gates':gates,'eligible_real_response_count':0,
  'real_outcomes':{'V5':None,'RL':None,'delta_Q':None,'delta_C':None,'delta_L':None},
  'fair_real_comparison_possible':False,'benefit_status':'UNIDENTIFIABLE_NOT_ZERO_NOT_NO_EFFECT',
  'history_relevance':'Related historical recovery/format failures exist, but are NOT executions of these actions.',
  'real_experiment_gate':'NO_GO_NOW',
  'priority':{'S01':'conditional model-allocation study only','S02':'mechanism already checked; paid test only if a real downstream model role and reference exist',
              'S03':'combine with allocation study; no distinct scope difference',
              'S10':'highest conditional research priority for joint-scope evidence; not ready',
              'S11':'do not pay for deterministically resolvable checks; semantic verifier reference required'}[r['id']]})
# Conditional budgets use archived rates, not current certified prices.
rates=rate_snapshot['rates_per_million'];budgets=[]
for n in [2,5,6,15]:
 per={}
 for model,(currency,inp,outp) in rates.items():
  unit=(Decimal(16384)*Decimal(inp)+Decimal(1024)*Decimal(outp))/Decimal(1000000)
  per[model]={'currency':currency,'per_call_conditional_estimate':str(unit),'all_calls_same_model_estimate':str(unit*n)}
 budgets.append({'recovery_calls':n,'input_monitor_total':n*16384,'output_cap_total':n*1024,'conditional_prices':per,
  'historical_rate_date':'2026-10-19','price_verified_for_next_run':False,'certified_input_token_upper':False,'cash_hard_limit':None})
summary={'kind':'ZERO_CALL_OUTCOME_AUDIT','algorithm_modified':False,'difference_scenarios':5,
 'differences':{'pi_only':['S01','S02','S03','S11'],'Z_R_pi':['S10']},
 'selected_history_real_calls':len(observations)+len(f7_identity),'numeric_response_records':len(observations),
 'own_input_legal_commit_reconstructions':sum(o['payload_replay_allowed_for_original_commit'] for o in observations),
 'invalid_response_inspection_only':sum(not o['payload_replay_allowed_for_original_commit'] for o in observations),
 'f7_response_ledger_identity_links':len(f7_identity),'current_V5_RL_strict_matching_replays':0,
 'actual_current_v5_rl_quality_or_net_benefit':'UNIDENTIFIABLE','real_execution_GO':False,
 'new_model_requests':0,'new_fake_responses':0,'new_executions_or_simulations':0,
 'historical_negative_result_preserved':True,'source_inventory_scope':'Selected canonical numeric repeat/single and F7 originals; excludes sandbox copies and sealed datasets'}
quality={'historical_numeric_branch_diagnostics':diag_summary,'end_to_end_full_opinion_quality':None,
 'terminal_numeric_scope':'Only the frozen six conditional numeric targets; not full semantic support',
 'completion_and_contract':'Preserve original bounded success and native schema separately; full opinion contract NOT_EVALUATED',
 'repeat_analysis_recorded':paired,'single_summary_recorded':load(SINGLE/'SUMMARY.json'),
 'task_quality_formula_audit':load(FINAL/'QUALITY_CALCULATION_AUDIT.json'),
 'actual_cash':None,'new_independent_quality_scores_computed':False,
 'source_traceability_note':'Rate constants have aggregate labels; per-response derivation / independently calibrated terminal survival is not certified.'}
dump('HISTORICAL_OBSERVATION_RECONSTRUCTION.json',{'observations':observations,'f7_identity_links':f7_identity,'dependency_checks':dep_checks})
dump('V5_ZERO_CALL_OUTCOME_AUDIT.json',{'summary':summary,'scenarios':scenario_reports,'quality_metrics':quality,
 'minimum_future_plan':{'cheapest_pattern':'S02-like: one existing model downstream of a deterministic join, two calls per pair',
 'joint_scope_pattern':'S10-like: 2 vs 3 model nodes, five recovery calls per pair',
 'repetition':'one pair is a mechanism observation; three predeclared pairs are still exploratory',
 'no_extra_nodes_for_advantage':True,'require_natural_real_task_role':True,'requests_exclude_unverified_initial_prefix':True,
 'no_automatic_launch':True,'conditional_budgets':budgets}})
dump('SOURCE_INDEX.json',SOURCES)
dump('AUDIT_SUMMARY.json',summary)
print(json.dumps(summary,ensure_ascii=False))
