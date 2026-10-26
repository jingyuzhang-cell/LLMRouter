"""Freeze one new HTTP entry; never produces an execution authorization."""
import datetime as dt,hashlib,json,subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
old_path=PARENT/'ab_execution_binding_v2/AB_CONFIG.json'
old=json.loads(old_path.read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for p,h in {**old['source_hashes'],**old['binding_files']}.items():
    assert sha(p)==h,p
pool_path=Path('/root/r3_own_pool/ab_numeric_recovery_frozen_v1/MODEL_POOL.json')
pool=json.loads(pool_path.read_text())
allow={'glm-5.3':'https://open.bigmodel.cn/api/paas/v4/chat/completions',
       'qwen-plus':'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
       'deepseek-flash':'https://api.deepseek.com/chat/completions'}
assert len(old['requests'])==8 and sum(r['body']['max_tokens'] for r in old['requests'])==36864
for r in old['requests']:
    assert r['endpoint']==allow[r['model']]
    assert sha(old_path)==sha(PARENT/'ab_execution_binding_v2/AB_CONFIG.json')
    assert r['body_sha256']==hashlib.sha256(json.dumps(r['body'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
plan={
    'batch_id':'STATIC_ALLOCATION_AB_HTTP_EXECUTION_V1',
    'scope':'One exposed numeric development event, two arms/two repeats; no structure optimization or recovery.',
    'A':old['A'],'B':old['B'],'order':old['order'],'requests':old['requests'],
    'max_requests':8,'max_output_tokens_total':36864,'input_reservation_tokens_per_request':65536,
    'input_bound_certified':False,'cash_hard_limit_certified':False,
    'estimated_envelope_risk_accepted_for_preparation_only':True,'execution_authorized':False,
    'estimate_caps_native':{'CNY':'3.50','USD':'0.05'},'common_arm_caps_native':old['common_arm_caps_native'],
    'request_deadline_s':180,'arm_deadline_s':240,'batch_deadline_s':3600,
    'automatic_retries':0,'resume_or_automatic_additional_requests':False,
    'rates':old['rates'],
    'public_price_snapshot_date_Asia_Shanghai':'2026-10-25',
    'price_snapshot_note':'Public documents checked on 2026-10-25 in preparation; recheck if stale. No account entitlement assumed.',
    'research_FX_USD_to_CNY':'6.7220',
    'FX_note':'Fixed research normalization inherited from prior planning; neither current market nor actual payment FX. Native estimates retained.',
    'accepted_response_models':{m:pool[m]['accepted_response_models'] for m in allow},
    'credential_env':{m:pool[m]['credential_env'] for m in allow},
    'scorer_path':str(PARENT/'terminal_contract_v1/evaluate_terminal.py'),
    'prior_binding_path':str(PARENT/'BINDING.json'),
    'common_failure_rule':'First failure stops future arms; already inflight siblings may finish and are fully recorded. No illegal output to terminal.',
    'cache_policy':'Empty initial cache per arm; no cross-arm reuse. Commit only validated bounded numeric contract with input/output fingerprints.',
    'quality_metrics':'Frozen six-item numerical F1 and legal-correct/6 separate. Complete opinion Q and semantic citation accuracy are unscorable.',
    'primary_descriptive_rule':'B both repeats content F1=1 and 6/6 legal-correct; mean normalized public estimate at least 10% below A, mean wall no more than 10% higher, all within deadline.',
    'actual_cost_benefit_requires_bill_verification':True,
    'single_event_results_are_not_statistical_confirmation':True}
plan['rates']['qwen-plus']['input_tiers']=[{'up_to':128000,'input':'0.8','output':'2'},
    {'up_to':256000,'input':'2.4','output':'20'},{'up_to':1000000,'input':'4.8','output':'48'}]
for name in ['PLAN.json','FREEZE.json','AUTHORIZATION_TEMPLATE.json']:
    assert not (HERE/name).exists(),'Refuse overwrite '+name
(HERE/'PLAN.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
files={**old['source_hashes'],**old['binding_files'],str(old_path):sha(old_path),str(pool_path):sha(pool_path)}
for name in ['binding.py','meter.py','http_transport.py','run.py','START.py','PLAN.json','prepare.py']:
    files[str(HERE/name)]=sha(HERE/name)
freeze={'batch_id':plan['batch_id'],'files':files,'created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'git_head':subprocess.check_output(['git','-C','/root','rev-parse','HEAD'],text=True).strip(),
        'price_basis':'2026-10-25 public snapshot','paid_execution_authorized':False}
(HERE/'FREEZE.json').write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+'\n')
template={'batch_id':plan['batch_id'],'freeze_sha256':sha(HERE/'FREEZE.json'),
          'execution_authorized':False,'accept_estimated_envelope_not_hard_cash_limit':True,
          'allow_public_task_material_to_bound_official_endpoints':False,
          'max_requests':8,'max_output_tokens_total':36864,'input_reservation_tokens_per_request':65536,
          'estimate_caps_native':plan['estimate_caps_native'],
          'request_deadline_s':180,'arm_deadline_s':240,'batch_deadline_s':3600,
          'automatic_retries':0,'operator_statement':'','not_after_utc':None}
(HERE/'AUTHORIZATION_TEMPLATE.json').write_text(json.dumps(template,ensure_ascii=False,indent=2)+'\n')
(HERE/'PREPARATION_RISK_ACKNOWLEDGEMENT.json').write_text(json.dumps({
    'statement':'接受小额探索性信封，入口完成后另行授权执行',
    'meaning':'Preparation under estimated CNY3.50/USD0.05 envelope accepted; NO paid execution authorized.',
    'execution_authorized':False},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'freeze_sha256':sha(HERE/'FREEZE.json'),'requests':8,'output_cap':36864,'execution_authorized':False,'model_requests':0}))
