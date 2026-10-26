"""Zero-call binding for allocation-only development pilot; no dispatch code."""
import hashlib
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent
BASE = Path('/root/r3_own_pool')
OLD = BASE/'ab_bounded_numeric_v1'
MODELS = BASE/'ab_numeric_recovery_frozen_v1/MODEL_POOL.json'
paths = [OLD/'TASK_PUBLIC.json', OLD/'INITIAL_REQUEST_TEMPLATES.json',
         OLD/'OUTPUT_SCHEMA.json', OLD/'score_terminal.py', MODELS,
         BASE/'qs_candidate_readiness_v1/score_numeric.py',
         BASE/'qs_candidate_readiness_v1/public/SCOPES.json',
         BASE/'qs_candidate_readiness_v1/public/CONDITIONED_NUMERIC_OUTPUT_SCHEMA.json',
         BASE/'qs_candidate_readiness_v1/eval_only/NUMERIC_REFERENCES.json',
         BASE/'dag_terminal_quality_gates_v1/p0/terminal_scorer.py',
         BASE/'qs_task_scoring_acceptance_v1/score.py']
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
before = {str(p):sha(p) for p in paths}
templates = json.loads((OLD/'INITIAL_REQUEST_TEMPLATES.json').read_text())
pool = json.loads(MODELS.read_text())
task = json.loads((OLD/'TASK_PUBLIC.json').read_text())
branches = [r['node_id'] for r in templates]
assert branches == ['extract_purchase', 'extract_payables']
arms = {
    'S_DS': ['deepseek-flash', 'deepseek-flash'],
    'S_QWEN': ['qwen-plus', 'qwen-plus'],
    'S_GLM': ['glm-5.3', 'glm-5.3'],
    'H_QD': ['qwen-plus', 'deepseek-flash'],
    'H_DQ': ['deepseek-flash', 'qwen-plus'],
}
requests = []
order = []
rng = random.Random(20261025)
for repeat in range(1,3):
    sequence = list(arms)
    if repeat == 1:
        rng.shuffle(sequence)
        first_order = sequence[:]
    else:
        sequence = list(reversed(first_order))
    order.append({'repeat':repeat,'arm_order':sequence})
    for arm in sequence:
        for i,node in enumerate(branches):
            m = arms[arm][i]
            messages = templates[i]['messages']
            body = dict(model=m, messages=messages, temperature=0,
                        max_tokens=8192 if m=='glm-5.3' else 1024,
                        response_format={'type':'json_object'}, **pool[m]['parameters'])
            requests.append(dict(request_id=f'R{repeat}_{arm}_{node}',repeat=repeat,
                                 arm=arm,node_id=node,model=m,endpoint=pool[m]['endpoint'],
                                 body=body,body_sha256=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
                                 messages_sha256=hashlib.sha256(json.dumps(messages,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
                                 input_utf8_bytes=len(json.dumps(messages,ensure_ascii=False).encode()),
                                 certified_input_token_bound=None, worst_cash_native=None))
assert len(requests)==20
for node in branches:
    assert len({r['messages_sha256'] for r in requests if r['node_id']==node})==1
assigned = {r['node_id']: [s['slot_id'] for s in json.loads(r['messages'][1]['content'])['task']['slots']] for r in templates}
assert len(set(assigned[branches[0]]) | set(assigned[branches[1]]))==6
assert not (set(assigned[branches[0]]) & set(assigned[branches[1]]))
binding = {
    'id':'STATIC_ALLOCATION_NUMERIC_PILOT_V1',
    'status':'TASK_AND_REQUESTS_BOUND_PAID_EXECUTION_HOLD',
    'evidence_grade':'SINGLE_DEVELOPMENT_EVENT_TWO_REPEATS_EXPLORATORY',
    'not_reopening_prior_recovery_experiments':True,
    'task':task,'assigned_slots':assigned,
    'graph':{'model_nodes':branches,'edges':[[n,'deterministic_merge'] for n in branches],
             'merge':'No model call; preserve complete submitted rows, no repair, no Gold access.',
             'structure_optimization':False,'recovery':False},
    'arms':{a:dict(zip(branches,ms)) for a,ms in arms.items()},
    'primary_contrast':'H_QD vs S_GLM',
    'secondary_contrasts':'H_QD vs S_DS/S_QWEN; H_DQ is a prespecified alternate, not a post-hoc winner substituted for H_QD.',
    'allocation_basis':'Fixed development assignment reused from prior branch template; not a learned or independently validated Router.',
    'same_model_settings_across_arms':True,
    'glm_output_cap_reason':'Reuse established low-effort@8192 configuration; do not weaken GLM baseline with known problematic 2048 cap.',
    'all_arms_independent_calls':True,'shared_initial_call_cost_discount':False,
    'repeats':2,'independent_event_count':1,'order':order,
    'max_requests':len(requests),'max_output_tokens_total':sum(r['body']['max_tokens'] for r in requests),
    'per_request_timeout_s_proposed':180,'batch_wall_s_proposed':3600,
    'cost_currency_policy':'CNY and USD separate; no combined cost comparison until documented FX and billing entitlement fixed. GLM cost not presumed zero.',
    'execution_lane_contract':{'schema':'Reuse original OUTPUT_SCHEMA.json',
        'extra_requirements':['Exact assigned slot set; no duplicate or foreign IDs.','Evidence IDs must belong to task catalogue.'],
        'full_opinion_semantic_contract':'NOT_EVALUATED'},
    'scoring':{'content':'Reuse original score_terminal.py / evaluate_final without modifying reference.',
        'completion':'Legal correct targets / 6, recorded separately from content Q; illegal branch cannot be submitted.',
        'schema':'Native JSON/schema recorded before any projection.',
        'evidence':'ID validity and existing proof-coverage proxy; not semantic evidence accuracy.',
        'missing_or_failure':'Preserve response; content Q UNKNOWN if unscorable, delivered coverage reflects absence, never overwrite content Q with 0.',
        'extras':'Do not discard wrong, duplicate, extra or conflicting rows to inflate quality.'},
    'measurement':{'parallel':'Dispatch both branches concurrently with capacity 2, wait for both before merge; arm scheduling sequential and balanced by repeat.',
        'latency':'Monotonic arm start to final merge including planner/wait; individual service sum separate.',
        'cost':'All physical calls, tokens and errors; actual bill vs public estimate separate.',
        'fail_stop':'First transport, timeout, truncated output, invalid usage, schema/contract or budget exception stops batch, no retry or top-up; retain partial results.',
        'incomplete_batch':'Unobserved arms remain UNOBSERVED, no invented paired outcomes.'},
    'success_rule':{'level':'Exploratory repeated observation only; no significance/stability claim.',
        'primary':'Both H_QD repeats deliver 6/6 correct legal targets and content Q=1; relative to S_GLM mean comparable monetary cost at least 10% lower and mean arm wall time no more than 10% higher; all meet the same prelaunch deadline.',
        'quality_gain_secondary':'If primary cost path fails, report any observed content/completion difference descriptively, do not relabel it primary success.',
        'unknown_currency_or_missing_pair':'Primary cost benefit NOT_IDENTIFIABLE.',
        'no_gain':'Keep negative results, no outcome-driven rerun, tuning, new arms or event substitution.',
        'best_fixed':'Report all fixed baselines and post-hoc best-fixed envelope separately; envelope is diagnostic, not deployable predictor.'},
    'paid_execution_authorized':False,'dispatch_enabled':False,
    'blockers':['Certified input token bounds including message overhead missing.',
                'Current official rates, account billing entitlements and FX for cross-currency comparison not certified.',
                'Cash envelope, common per-arm deadline and enforceable pre-dispatch reservations require final binding.',
                'New bounded execution runner and explicit authorization required; old START.py and prior permissions must not be reused.'],
    'requests':requests,'source_hashes':before}
checks={'twenty_requests':len(requests)==20,'same_prompt_per_branch':True,
        'six_disjoint_slots':True,'five_arms_two_repeats':len(arms)==5,
        'baseline_parameters_not_weakened':all(r['body']['max_tokens']==8192 for r in requests if r['model']=='glm-5.3'),
        'no_dispatch':not binding['dispatch_enabled'],'no_authorization':not binding['paid_execution_authorized'],
        'no_reference_in_request':all('reference' not in json.loads(t['messages'][1]['content']) for t in templates)}
assert all(checks.values())
assert before == {str(p):sha(p) for p in paths}
for name,obj in [('BINDING.json',binding),('ZERO_CALL_BINDING_CHECK.json',dict(checks=checks,api_calls=0,source_identity_unchanged=True))]:
    p=OUT/name
    assert not p.exists(),f'Refuse overwrite {p}'
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
summary = f'''# 固定DAG静态模型分配：限定数值开发Pilot

任务、两分支Prompt、6项数值参考与确定性汇合已绑定。不会重跑原A/B恢复实验，不测试结构演化。单个已曝光开发事件、2次重复，最多20次真实调用；本轮实际调用0。

|方案|采购分支|应付余额分支|两轮调用|
|---|---|---|---:|
|S_DS|DeepSeek-Flash|DeepSeek-Flash|4|
|S_QWEN|Qwen-Plus|Qwen-Plus|4|
|S_GLM|GLM-5.3|GLM-5.3|4|
|H_QD（主混合方案）|Qwen-Plus|DeepSeek-Flash|4|
|H_DQ（预设辅助方案）|DeepSeek-Flash|Qwen-Plus|4|

同分支输入逐字节一致，所有臂独立执行，不共享收费调用。GLM采用既有low@8192，其他模型非思考@1024；每个模型在各臂设置一致。最大输出合计{binding['max_output_tokens_total']} Token。臂顺序固定随机后第二轮反转；每臂两分支并发，记录真实墙钟与服务时长。

主要比较预先指定H_QD对S_GLM，其他固定基线均展示，不事后换主混合赢家。探索性成功要求H_QD两轮均6/6正确合法交付、Q=1；在统一费用可比的前提下均费至少降低10%、均墙钟增加不超过10%，且满足共同截止时间。这个判据是本新协议的提案，尚未付费授权。

内容Q、合法交付覆盖、原生Schema、数值通道合同、证据proxy分别保留。未评价完整舆情语义合同；UNKNOWN不伪装成准确率0，非法输出也不向下游放行。任一运行异常停止整批，保留未观测臂，不自动补齐。

## 尚未放行

1. 输入Token认证上界及消息封装开销尚未取得。
2. 当前费率、账户计费权益、跨币种统一口径未认证，未知费用不记0。
3. 现金信封、共同截止期和派发前预留护栏需最终绑定。
4. 尚无新批次执行授权，也没有可直接发送的执行入口；历史权限不能沿用。

当前结论：任务/Prompt/分配/评分边界已绑定；付费执行HOLD。可以检验这个开发任务上的分配取舍，不能证明独立事件上的泛化、学习Router、结构优化或联合恢复收益。
'''
(OUT/'BINDING_SUMMARY.md').write_text(summary)
print(json.dumps({'checks':checks,'max_requests':20,'output_tokens_total':binding['max_output_tokens_total'],'api_calls':0,'status':binding['status']},ensure_ascii=False))
