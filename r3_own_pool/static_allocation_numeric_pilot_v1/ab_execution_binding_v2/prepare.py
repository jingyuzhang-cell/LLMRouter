"""Bind A/B-only revision and resource-history summaries. Never reads answers."""
import hashlib,json,math
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
ROOT=Path('/root/r3_own_pool')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
old=json.loads((PARENT/'BINDING.json').read_text())
budget=json.loads((PARENT/'BUDGET_PREFLIGHT.json').read_text())
requests=[]
for r in old['requests']:
    if r['arm'] not in ['S_GLM','H_QD']:continue
    q=dict(r);q['arm']='A' if r['arm']=='S_GLM' else 'B'
    q['request_id']=f"R{r['repeat']}_{q['arm']}_{r['node_id']}"
    requests.append(q)
assert len(requests)==8
rates=budget['rates']
conditional={'CNY':D(0),'USD':D(0)}
for r in requests:
    rate=rates[r['model']]
    r['reservation_input_assumption']=65536
    r['conditional_reserve_native']=str((D(65536)*D(rate['input'])+D(r['body']['max_tokens'])*D(rate['output']))/D(1000000))
    conditional[rate['currency']]+=D(r['conditional_reserve_native'])
config={'id':'STATIC_ALLOCATION_AB_EXECUTION_BINDING_V2',
        'revision_reason':'Operator narrowed trial to A fixed single model and B predeclared static heterogeneous assignment; prior five-arm proposal is not executed or overwritten.',
        'task_id':old['task']['task_id'],'evidence_class':'ONE_DEVELOPMENT_EVENT_TWO_REPEATS',
        'A':'glm-5.3 on both branches; best observed content-quality baseline in existing development pilot, not globally best model.',
        'B':{'extract_purchase':'qwen-plus','extract_payables':'deepseek-flash'},
        'order':[{'repeat':1,'arms':['A','B']},{'repeat':2,'arms':['B','A']}],
        'requests':requests,'max_requests':8,'max_output_tokens':sum(r['body']['max_tokens'] for r in requests),
        'retry_calls_allowed':0,'recovery_enabled':False,'structure_change_enabled':False,
        'initial_cache':{},'reuse_across_arms':False,'max_concurrency':2,
        'common_arm_deadline_s':240,'batch_wall_s':3600,'per_request_client_timeout_s_proposed':180,
        'proposed_caps_native':{'CNY':'3.50','USD':'0.05'},
        'common_arm_caps_native':{'CNY':'3.50','USD':'0.05'},
        'conditional_total':{k:str(v) for k,v in conditional.items()},
        'input_upper_certified':False,'real_dispatch_enabled':False,'paid_authorization':False,
        'FX':budget['FX_proposal'],'rates':rates,
        'full_opinion_Q':None,'semantic_citation_accuracy':None,
        'metric_limits':'Preserve numeric F1 and legal-correct/6 separately; evidence-ID validity and coverage proxy are not semantic citation accuracy.',
        'fairness':'Same DAG, branch messages, evidence, deadline, scoring, available models and monetary limits; only allocation changes. Model-specific parameters held constant.',
        'benefit_claim':'No actual or confirmatory benefit claim from FakeMeter. One event/two repeats cannot establish generalization or statistical noninferiority.',
        'source_hashes':old['source_hashes'],
        'binding_files':{str(PARENT/'BINDING.json'):sha(PARENT/'BINDING.json'),
                         str(PARENT/'terminal_contract_v1/TERMINAL_SCORING_CONTRACT.json'):sha(PARENT/'terminal_contract_v1/TERMINAL_SCORING_CONTRACT.json'),
                         str(PARENT/'terminal_contract_v1/evaluate_terminal.py'):sha(PARENT/'terminal_contract_v1/evaluate_terminal.py'),
                         str(PARENT/'reservation_guard.py'):sha(PARENT/'reservation_guard.py')}}
# Only historical accounting metadata is projected below. No model payload,
# numeric quality labels or historical output is evaluated or changed.
history_files=[]
initial=ROOT/'ab_numeric_recovery_execution_v1/REAL_RUN_20261019_021050'
history_files += [(p,'initial_or_recovery') for p in sorted(initial.glob('[AB][124].json'))]
control=ROOT/'ab_numeric_recovery_controlled_execution_v1/REAL_RUN_20261019_023824'
history_files += [(p,'recovery') for p in sorted(control.glob('[AB]_RESULT.json'))]
repeat_root=ROOT/'ab_numeric_recovery_repeat_v1/REAL_BATCH_20261019_030355'
history_files += [(p,'recovery') for p in sorted(repeat_root.glob('P*/REAL_RUN*/*_RESULT.json')) if p.name in ['A_RESULT.json','B_RESULT.json']]
numeric=ROOT/'qs_numeric_16_execution_binding_v1/REAL_RUN_20261016_133454'
history_files += [(p,'whole_task_resource_proxy') for p in sorted(numeric.glob('QSDEV_OFG_FLOW_BALANCE__NUMERIC_SCOPE_V1__*/RECORD.json'))]
seen=set();history=[];source_hashes={}
for path,phase in history_files:
    if phase=='initial_or_recovery':
        phase='initial' if path.stem in ['A1','A2','B1','B2'] else 'recovery'
    d=json.loads(path.read_text());source_hashes[str(path)]=sha(path)
    model=d.get('model_requested',d.get('model_id_requested'))
    if model not in rates:continue
    uid=d.get('response_id') or d.get('request_id') or (str(path),d.get('start_utc'))
    if uid in seen:continue
    seen.add(uid)
    usage=d.get('usage',{})
    tin=usage.get('prompt_tokens');tout=usage.get('completion_tokens')
    node=d.get('node') or d.get('claim',{}).get('node') or 'whole_six_slot_task'
    request_path=path.with_name(path.stem+'_REQUEST.json') if path.name in ['A1.json','A2.json','A4.json','B1.json','B2.json'] else path.with_name(path.name.replace('_RESULT.json','_REQUEST.json'))
    exact=False
    if request_path.exists():
        rq=json.loads(request_path.read_text());source_hashes[str(request_path)]=sha(request_path)
        msgs=rq.get('messages',rq.get('body',{}).get('messages'))
        if msgs:
            mh=hashlib.sha256(json.dumps(msgs,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            exact=any(r['node_id']==node and r['messages_sha256']==mh for r in requests)
    if type(tin)!=int or type(tout)!=int:
        tin=tout=None
    rate=rates[model]
    cost=None if tin is None else str((D(tin)*D(rate['input'])+D(tout)*D(rate['output']))/D(1000000))
    history.append({'source':str(path),'source_sha256':sha(path),'physical_response_id':uid,
                    'model':model,'node':node,'phase':phase,'exact_current_branch_messages':exact,
                    'input_tokens':tin,'output_tokens':tout,
                    'client_wall_s':d.get('client_call_wall_s',d.get('api_roundtrip_s')),
                    'finish_reason':d.get('finish_reason'),'currency':rate['currency'],
                    'repriced_public_cache_miss_estimate':cost,'actual_cash':d.get('actual_cash',d.get('actual_bill',d.get('cost_actual'))),
                    'not_an_actual_bill':True})
def stats(values):
    a=sorted(x for x in values if x is not None)
    return {'n':len(a),'p50_nearest_rank':a[math.ceil(.5*len(a))-1] if a else None,
            'p95_nearest_rank':a[math.ceil(.95*len(a))-1] if a else None,
            'max_observed':a[-1] if a else None,'certified_hard_upper':None}
groups=defaultdict(list)
for r in history:groups[(r['model'],r['node'],r['phase'])].append(r)
summary=[]
for (model,node,phase),rows in sorted(groups.items()):
    summary.append({'model':model,'node':node,'phase':phase,'input':stats([r['input_tokens'] for r in rows]),
                    'output':stats([r['output_tokens'] for r in rows]),'wall':stats([r['client_wall_s'] for r in rows]),
                    'exact_current_messages_samples':sum(r['exact_current_branch_messages'] for r in rows)})
cert={'status':'HOLD_NO_CERTIFIED_INPUT_UPPER','history_rows':history,'groups':summary,
      'method':'Physical response deduplication; nearest-rank P50/P95 per model/node/phase. Metadata only, no quality rescore.',
      'empirical_is_hard_bound':False,'scenarios':{'historical_p50_p95':'Per-group descriptive observations; not a predictive bound for unmatched prompts.',
          'hard_allowed':'Not identifiable until complete billable-input upper certified. Output caps alone are known.',
          'conditional_65536':config['conditional_total'],'retries':0},
      'history_hashes':source_hashes,'model_requests':0}
for f,obj in [('AB_CONFIG.json',config),('HISTORICAL_BUDGET_AUDIT.json',cert)]:
    p=HERE/f;assert not p.exists(),f'Refuse overwrite {p}'
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
assert all(sha(Path(p))==h for p,h in source_hashes.items())
print(json.dumps({'requests_proposed':8,'output_cap':config['max_output_tokens'],'history_rows':len(history),'groups':len(summary),'conditional_total':config['conditional_total'],'hard_budget_certified':False,'api_calls':0},ensure_ascii=False))
