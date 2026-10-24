"""Offline provenance-normalized conditional recovery observations.
No transport or autonomous policy. Small samples never become production priors.
"""
import json,hashlib
from pathlib import Path
from .history_baseline import HistoricalBaseline
VERSION='conditional-recovery-observation.v1'
QUALITY='task_success_offline_conditioned_on_verified_manual_prestate'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def export_e2(run_directory):
 root=Path(run_directory);run=json.loads((root/'RESULT.json').read_text())
 if run.get('mock') is not False:raise ValueError('MOCK_NOT_REAL_RECOVERY_FEEDBACK')
 graph=json.loads((root.parent/'GRAPH.json').read_text());cfg=json.loads((root.parent/'PROTOCOL.json').read_text());refs={v:k for k,v in graph['provenance']['semantic_ref_map'].items()}
 timeline=[json.loads(x) for x in (root/'TIMELINE.jsonl').read_text().splitlines()]
 available=next(x['utc_unix'] for x in timeline if x['event']=='CLIENT_FINALIZED')
 rows=[]
 for trace in run['traces']:
  arm=root/trace['arm'];request=json.loads((arm/'REQUEST.json').read_text())
  params={k:v for k,v in request.items() if k not in ('messages','model')};physical=trace['physical_requests']
  response=json.loads((arm/'RESPONSE.json').read_text()) if (arm/'RESPONSE.json').exists() else {}
  primary={str(p):sha(p) for p in [root/'RESULT.json',root/'TIMELINE.jsonl',arm/'TRAJECTORY.json',arm/'REQUEST.json',arm/'CALL_LEDGER.jsonl'] if p.exists()}
  if (arm/'RESPONSE.json').exists():primary[str(arm/'RESPONSE.json')]=sha(arm/'RESPONSE.json')
  for name in ['GRAPH.json','TASK_PUBLIC.json','STATE.json','SEMANTIC_ENVELOPE.json','MODEL_POOL.json','PROTOCOL.json','GOLD_EVAL_ONLY.json']:
   primary[str(root.parent/name)]=sha(root.parent/name)
  quality=trace['task_success_offline']
  if type(quality) is not bool:raise ValueError('QUALITY_LABEL_UNKNOWN_MUST_NOT_FILL')
  row=dict(dataset_version=VERSION,observation_id=digest(dict(run=str(root),arm=trace['arm'])),uid=graph['task_id'],task_family='three_facility_public_financial_development',task_type='conditional_recovery_manual_prestate',pool='cloud_e2_qwen_deepseek',model=trace['model'],provider_model=response.get('model'),provider_version=response.get('system_fingerprint'),operation='form_expression_LOCAL_remaining_task',parameters=params,parameters_group=digest(params),graph_hash=trace['result']['graph_hash'] if trace.get('result') else cfg['graph_hash'],state_hash=trace['baseline_state_hash'],Z=trace['Z'],R=trace['R'],R_semantic_refs=sorted(refs[u] for u in trace['R']),pi=trace['pi'],failure_type='CONTROLLED_LOCAL_JSON_PARSER',failure_error_code='OUTPUT_SCHEMA_OR_ARITHMETIC',semantic_contract_version='semantic-fact-contract.v2',prestate_origin=trace['cache_origin'],cohort='E2_MANUAL_STATE_JSON_FAILURE_LOCAL_THREE_FACILITY',synthetic=False,cached=False,controlled_injection=True,quality=int(quality),quality_label_definition=QUALITY,evaluation_reference_sha256=sha(root.parent/'GOLD_EVAL_ONLY.json'),prestate_sha256=sha(root.parent/'STATE.json'),latency_s=trace['recovery_remaining_wall_s'],latency_definition='recovery decision BEGIN through public acceptance END or failure',api_latency_s=[r['client_api_interval_s'] for r in physical],input_tokens=trace.get('known_input_tokens'),output_tokens=trace.get('known_output_tokens'),usage_unknown_count=trace.get('unknown_usage_count'),cost_currency=trace.get('fee_currency'),fee_estimate=trace.get('fee_estimate'),bill_verified=trace['bill_verified'],D=None,on_time=None,error=trace['error'],source_files_sha256=primary,label_available_utc=available,route_decision_utc=trace['decision_monotonic'],route_decision_clock='MONOTONIC_NOT_UTC',end_to_end_label=False)
  # Explicitly separate UTC availability from duration/decision monotonic clocks.
  row['route_decision_monotonic']=row.pop('route_decision_utc');rows.append(row)
 return rows

def validate_rows(rows):
 ids=set()
 for r in rows:
  if r['observation_id'] in ids:raise ValueError('DUPLICATE_OBSERVATION')
  ids.add(r['observation_id'])
  if r.get('synthetic') or r.get('cached') or r.get('end_to_end_label'):raise ValueError('WRONG_OBSERVATION_SCOPE')
  for raw,h in r['source_files_sha256'].items():
   if sha(raw)!=h:raise ValueError('SOURCE_EVIDENCE_CHANGED:'+raw)
 return rows

def predict_before(rows,features,decision_utc,*,heldout_uids=(),min_tasks=20):
 # Never train with the current task, future labels, different state origins or E1.
 allowed={'pool','model','operation','parameters_group','task_type','cohort','uid'}
 if set(features)-allowed:raise ValueError('ORACLE_OR_UNREGISTERED_FEATURE')
 excluded=set(heldout_uids)|({features['uid']} if features.get('uid') else set())
 selected=[r for r in rows if r['uid'] not in excluded and r['label_available_utc']<decision_utc and r['cohort']==features['cohort']]
 stats=HistoricalBaseline(selected,['pool','model','operation','parameters_group','task_type'],min_tasks=min_tasks).predict(features)
 return dict(status=stats['status'],diagnostics=stats,admitted_quality_probability=None,
             admitted_p90_seconds=None,production_gate='NO_GO_UNCALIBRATED',online_choice=None,
             independent_training_tasks=stats['n_quality_tasks'],excluded_tasks=sorted(excluded),
             information_cutoff_utc=decision_utc,calibrated_guarantee=False)
