"""Read-only adapter for frozen V5/RL. No HTTP client, key reader or paid sender.

The scheduler sees public contract/evidence/cache feedback, never reference values.
"""
import copy,hashlib,json,math,re
from pathlib import Path
from decimal import Decimal
from jsonschema import Draft202012Validator
P=Path('/root/r3_own_pool/ab_numeric_recovery_frozen_v1')
TASK=json.loads((P/'TASK_PUBLIC.json').read_text())
SCHEMA=json.loads((P/'OUTPUT_SCHEMA.json').read_text())
TEMPLATES={x['node_id']:x for x in json.loads((P/'INITIAL_REQUEST_TEMPLATES.json').read_text())}
VARIANTS={(x['node_id'],x['model_id']):x for x in json.loads((P/'REQUEST_BODY_VARIANTS.json').read_text())}
MODEL_POOL=json.loads((P/'MODEL_POOL.json').read_text())

def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def body_digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def slots(node):return {x['slot_id'] for x in json.loads(TEMPLATES[node]['messages'][1]['content'])['task']['slots']}
def finite(x):return type(x) in (int,float) and math.isfinite(x) and x>=0

def inspect_contract(raw,node):
    if node not in TEMPLATES:raise ValueError('unknown_node')
    try:data=json.loads(raw) if isinstance(raw,str) else copy.deepcopy(raw)
    except (ValueError,TypeError):return {'status':'SCHEMA_REJECTED','native_schema':False,'payload':None,'reasons':['JSON_PARSE']}
    schema_ok=not list(Draft202012Validator(SCHEMA).iter_errors(data))
    reasons=[];status='VALID'
    if not schema_ok:status='SCHEMA_REJECTED';reasons=['NATIVE_SCHEMA']
    else:
        ids=[r['item_id'] for r in data['items']]
        if len(ids)!=len(slots(node)) or set(ids)!=slots(node):status='SCHEMA_REJECTED';reasons=['ASSIGNED_SLOT_COVERAGE_OR_DUPLICATE']
        else:
            abstain=False
            for row in data['items']:
                v=row['fields']['amount']['number'];unit=row['fields']['amount']['unit']
                if v is None:abstain=True
                elif isinstance(v,bool) or (isinstance(v,str) and not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)',v)) or not math.isfinite(float(v)):
                    status='SCHEMA_REJECTED';reasons=['NON_PLAIN_FINITE_NUMBER'];break
                if not unit.strip():status='SCHEMA_REJECTED';reasons=['UNIT_EMPTY'];break
                if any(e not in TASK['evidence_catalog'] for e in row['evidence_ids']):status='EVIDENCE_REJECTED';reasons=['UNAUTHORIZED_EVIDENCE_ID'];break
                if v is not None and not row['evidence_ids']:status='EVIDENCE_REJECTED';reasons=['EVIDENCE_MISSING'];break
            if status=='VALID' and abstain:status='ABSTAIN'
    return {'status':status,'native_schema':schema_ok,'payload':data,'reasons':reasons,'bounded_contract_valid':status=='VALID','full_opinion_contract':'NOT_EVALUATED'}

def adapt_shared_state(shared):
    """Derive identical effective hard feedback for either arm. No Gold access."""
    s=copy.deepcopy(shared);outputs={};feedback=[];valid={};cache_model={};audit=[]
    for node,b in sorted(s['branches'].items()):
        cache_model[node]=b.get('expected_identity',{}).get('model_id')
        raw=b.get('payload');cache=b.get('cache')
        c=inspect_contract(raw,node) if raw is not None else {'status':'COMMIT_LOST','native_schema':False,'bounded_contract_valid':False,'payload':None,'reasons':['MISSING_COMMITTED_OUTPUT']}
        lineage_ok=False
        if cache is not None and raw is not None:
            # Two explicitly documented encodings: legacy sorted-spaced and controlled canonical.
            hashes={digest(raw),hashlib.sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
            lineage_ok=(cache.get('identity')==b.get('expected_identity') and cache.get('guard_pass') is True and cache.get('complete') is True and cache.get('bytes_sha256') in hashes)
        valid[node]=bool(c['bounded_contract_valid'] and lineage_ok)
        if valid[node]:outputs[node]=copy.deepcopy(raw)
        else:feedback.append({'node':node,'class':'CONFIRMED-INVALID','kind':'numeric_contract_or_cache_identity','evidence_ref':'controlled-state:'+digest(shared)+':'+node,'detail':c['status'] if not c['bounded_contract_valid'] else 'CACHE_IDENTITY_INVALID'})
        audit.append({'node':node,'contract':c,'lineage_valid':lineage_ok,'release':valid[node]})
    # Original diagnostic suspicion retained in audit, but full contract wins over optional advice.
    if all(valid.values()):
        outputs['merge_numeric']=deterministic_merge(outputs)
    return {'outputs':outputs,'feedback_records':feedback,'contract_valid':valid,'cache_model':cache_model,'source_state_sha256':digest(shared),'effective_feedback_sha256':digest(feedback),'audit':audit,'original_feedback_records':copy.deepcopy(shared.get('feedback_records',[]))}

def make_scheduler_state(shared,cells,cash_limits,tool_latency_reservation_s=None):
    """No guessed cost/latency. Caller supplies sourced cells and native limits."""
    if not isinstance(cash_limits,dict) or not cash_limits:raise ValueError('CASH_ENVELOPE_UNCERTIFIED')
    if any(not finite(v) for v in cash_limits.values()):raise ValueError('INVALID_CASH_LIMIT')
    if not finite(tool_latency_reservation_s):raise ValueError('TOOL_LATENCY_UNIDENTIFIED')
    effective=adapt_shared_state(shared);cl={};cc={};cell_sources={}
    for c in cells:
        if c.get('status')!='IDENTIFIED_HISTORICAL_HEURISTIC':continue
        if c.get('prompt_body_sha256')!=VARIANTS[(c['node'],c['model'])]['body_sha256']:raise ValueError('CALIBRATION_INPUT_MISMATCH')
        if not c.get('source_records') or not finite(c.get('tokens_observed_max')) or not finite(c.get('latency_observed_max_s')):raise ValueError('UNCERTIFIED_CELL')
        # Empirical max is a heuristic, never a guaranteed future quantile.
        cl[(c['node'],c['model'])]=(c['tokens_observed_max'],c['latency_observed_max_s'])
        if isinstance(c.get('current_native_estimate'),dict):cc[(c['node'],c['model'])]=c['current_native_estimate']
        cell_sources[(c['node'],c['model'])]=copy.deepcopy(c)
    state={'children_map':{'extract_purchase':['merge_numeric'],'extract_payables':['merge_numeric'],'merge_numeric':[]},'model_nodes':{'extract_purchase','extract_payables'},'terminal_nodes':['merge_numeric'],'cache_model':effective['cache_model'],'contract_valid':effective['contract_valid'],'missing_outputs':[n for n,v in effective['contract_valid'].items() if not v],'feedback_records':effective['feedback_records'],'pools':{n:shared['candidate_models'] for n in shared['branches']},'availability':shared['availability'],'cost_lat':cl,'cash_cost':cc,'cash_budget':copy.deepcopy(cash_limits),'token_budget_remaining':shared['remaining_resources']['token_ceiling'],'deadline_remaining_s':shared['remaining_resources']['deadline_seconds'],'terminal_q_min':shared.get('terminal_q_min'),'resource_limit':1,'deterministic_latency':{'merge_numeric':tool_latency_reservation_s},'quality_evaluator':None}
    # Supplied tool reservation and measured actual runtime remain distinct.
    return state,effective

def request_for(node,model):
    v=VARIANTS[(node,model)];body=copy.deepcopy(v['body'])
    if body_digest(body)!=v['body_sha256'] or body.get('max_tokens')!=1024:raise ValueError('REQUEST_IDENTITY')
    return {'body':body,'endpoint':v['endpoint'],'body_sha256':v['body_sha256'],'node':node,'model':model}

def observe_response(request,raw_model_text,usage,wall_s,estimated_native=None,actual_bill=None,response_model=None,http_status=None):
    """Observation converter; records actual bill independently from token estimate."""
    if body_digest(request['body'])!=request['body_sha256']:raise ValueError('REQUEST_DRIFT')
    c=inspect_contract(raw_model_text,request['node'])
    u=usage if isinstance(usage,dict) else {}
    usage_ok=all(type(u.get(k)) is int and u[k]>=0 for k in ('prompt_tokens','completion_tokens','total_tokens')) and u.get('total_tokens')==u.get('prompt_tokens',0)+u.get('completion_tokens',0) and finite(wall_s)
    fees_ok=isinstance(estimated_native,dict) and bool(estimated_native) and all(finite(x) for x in estimated_native.values())
    identity_ok=http_status==200 and response_model in MODEL_POOL[request['model']]['accepted_response_models']
    if actual_bill is not None and (not isinstance(actual_bill,dict) or not actual_bill or not all(finite(x) for x in actual_bill.values())):raise ValueError('INVALID_BILL')
    callback={'contract_ok':c.get('bounded_contract_valid',False) and identity_ok,'output':c['payload'],'tokens':u.get('total_tokens') if usage_ok else None,'wall_s':wall_s if usage_ok else None,'cash_cost':estimated_native if fees_ok else None}
    return {'executor_callback':callback,'actual_usage':copy.deepcopy(usage),'native_schema_valid':c['native_schema'],'bounded_contract':c['status'],'response_identity_valid':identity_ok,'raw_model_text':raw_model_text,'request_identity':request['body_sha256'],'estimated_native_fee':estimated_native,'actual_bill':actual_bill,'usage_identified':usage_ok,'executor_meter_identified':usage_ok and fees_ok,'cash_cost_semantics':'executor field is settlement estimate, NOT actual cash bill; wrapper must not expose core actual_cash as a verified bill','stop_required':not(usage_ok and fees_ok and identity_ok),'abstention':c['status']=='ABSTAIN'}

def deterministic_merge(inputs):
    if set(inputs)!={'extract_purchase','extract_payables'}:raise ValueError('MISSING_REQUIRED_BRANCH')
    rows=[]
    for node in sorted(inputs):
        if inspect_contract(inputs[node],node)['status']!='VALID':raise ValueError('INVALID_BRANCH')
        rows.extend(copy.deepcopy(inputs[node]['items']))
    return {'items':rows}

def evaluate_delivery(outputs):
    """Use frozen scorer after execution only. Partial coverage is not full delivery."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('bounded_terminal_eval',P/'score_terminal.py')
    scorer=importlib.util.module_from_spec(spec);spec.loader.exec_module(scorer)
    legal={n:copy.deepcopy(outputs[n]) for n in TEMPLATES if n in outputs and inspect_contract(outputs[n],n)['status']=='VALID'}
    partial={'items':[row for n in sorted(legal) for row in legal[n]['items']]}
    report=scorer.evaluate_final(partial);details=report.get('content_details',{})
    identified=report.get('status')=='SCORABLE' and details.get('UNKNOWN',0)==0
    tp=details.get('TP') if identified else None
    complete=set(legal)==set(TEMPLATES)
    return {'frozen_numeric_score_details':report,'legal_branch_count':len(legal),'legal_branch_correct_targets':tp,'legal_branch_correct_target_coverage':tp/6 if tp is not None else None,'terminal_complete':complete,'legal_terminal_correct_target_coverage':tp/6 if complete and tp is not None else (0.0 if not complete else None),'terminal_Q_full_opinion':None,'scope':'six conditional numeric targets only; incomplete final delivery differs from partial branch correctness'}

class PaidExecutionBlocked(RuntimeError):pass

def execution_gate(shared,cells,current_price_certificate,certified_cash_limits,authorization):
    """Gate only; this package intentionally does not ship a network sender."""
    gaps=[]
    if authorization is None:gaps.append('NO_EXPERIMENT_SPECIFIC_PAID_AUTHORIZATION')
    if not current_price_certificate:gaps.append('NO_CURRENT_PRICE_AND_ENTITLEMENT_CERTIFICATE')
    if not certified_cash_limits:gaps.append('NO_ENFORCEABLE_NATIVE_CURRENCY_CASH_CAP')
    if not cells:gaps.append('NO_MATCHED_MODEL_CELLS')
    if gaps:raise PaidExecutionBlocked(';'.join(gaps))
    raise PaidExecutionBlocked('NETWORK_SENDER_NOT_INCLUDED; counted executor/transport binding still requires a separately frozen authorized package')
