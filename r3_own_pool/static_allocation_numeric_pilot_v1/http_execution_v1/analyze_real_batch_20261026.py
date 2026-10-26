"""Offline analysis of the single authorized batch. No network or credentials.

Reads immutable raw responses and the frozen scorer, writes a NEW analysis
directory, and never changes execution records or experimental definitions.
"""
import datetime as dt
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path
from binding import HERE, load_plan, sha
from run import get_terminal


def main():
    plan = load_plan()
    run = HERE / 'REAL_RUN_20261026_012116'
    out = HERE / 'ANALYSIS_REAL_RUN_20261026_012116'
    out.mkdir(exist_ok=False)
    result = json.loads((run / 'RESULT.json').read_text())
    manifest = json.loads((run / 'RESULT_MANIFEST.json').read_text())
    assert all(sha(run / name) == digest for name, digest in manifest['files'].items())
    assert result['real_request_attempts'] == 8 and result['automatic_retries'] == 0
    assert result['status'] == 'COMPLETE'
    scorer = get_terminal(plan)
    refs = {r['item_id']: r for r in scorer.CONTRACT['reference']['items']}
    catalog = json.loads(Path(plan['prior_binding_path']).read_text())['task']['evidence_catalog']
    events = [json.loads(line) for line in (run / 'EVENTS.jsonl').read_text().splitlines()]
    nodes, arms, targets = [], [], []
    for request in plan['requests']:
        rid = request['request_id']
        record = json.loads((run / (rid + '_RECORD.json')).read_text())
        raw = (run / (rid + '_HTTP_RESPONSE.bin')).read_bytes()
        response = json.loads(raw)
        content = response['choices'][0]['message']['content']
        assert content == (run / (rid + '_MODEL_OUTPUT.txt')).read_text() == record['raw_output']
        assert response['usage'] == record['usage']
        assert hashlib.sha256(raw).hexdigest() == record['transport']['original_raw_sha256']
        assert record['cache_committed'] and record['input_fingerprint'] == request['messages_sha256']
        assert sha(run / (rid + '_REQUEST_BODY.bin')) == request['body_sha256']
        u = response['usage']
        hit = u.get('prompt_cache_hit_tokens', u.get('prompt_tokens_details', {}).get('cached_tokens', 0))
        cold = D(record['public_cold_miss_estimate'])
        # Supplementary public-rate estimates only; never overwrite frozen cold-miss accounting.
        if request['model'] == 'glm-5.3':
            cache_est = (D(u['prompt_tokens'] - hit)*8 + D(hit)*2 + D(u['completion_tokens'])*28) / 1000000
        elif request['model'] == 'deepseek-flash':
            cache_est = (D(u['prompt_tokens'] - hit)*D('.3') + D(hit)*D('.006') + D(u['completion_tokens'])*D('1.2')) / 1000000
        else:
            assert hit == 0
            cache_est = cold
        node = {k: record[k] for k in ['request_id', 'arm', 'repeat', 'node', 'model_requested', 'model_returned', 'status', 'usage', 'client_node_wall_s', 'start_utc', 'end_utc', 'currency', 'branch_check']}
        node.update(cold_miss_public_estimate=str(cold), cache_aware_peak_public_estimate=str(cache_est), cached_input_tokens=hit, actual_cash=None,
                    source='REAL_HTTP_RESPONSE', reasoning_tokens=u.get('completion_tokens_details', {}).get('reasoning_tokens'),
                    response_sha256=sha(run/(rid+'_HTTP_RESPONSE.bin')), http_worker_wall_s=record['transport']['http_worker_wall_s'])
        nodes.append(node)
        rows = json.loads(content)['items']
        details = scorer.old.evaluate_final({'items': rows})['content_details']['items']
        statuses = {x['item_id']: x['status'] for x in details}
        for row in rows:
            ref = refs[row['item_id']]
            targets.append({'request_id': rid, 'arm': record['arm'], 'repeat': record['repeat'], 'item_id': row['item_id'],
                            'submitted': row['fields']['amount'], 'reference': ref['fields']['amount']['expected'],
                            'period': row['item_id'].rsplit('_', 1)[-1], 'source_proofs': ref['proofs'],
                            'cited_evidence': [catalog[x] for x in row['evidence_ids']], 'contract_legal': True,
                            'numeric_status': statuses[row['item_id']], 'missing': False, 'scorable': True,
                            'error_reason': None, 'full_semantic_entailment': None})
    for arm in result['arms']:
        label, repeat = arm['arm'], arm['repeat']
        ns = [n for n in nodes if n['arm'] == label and n['repeat'] == repeat]
        outputs = {n['node']: (run / (n['request_id']+'_MODEL_OUTPUT.txt')).read_text() for n in ns}
        ev = scorer.evaluate(outputs)
        assert ev == arm['evaluation']
        dispatch = {e['request_id']: e['monotonic_s'] for e in events if e['kind']=='NODE_DISPATCH' and e['request_id'] in {n['request_id'] for n in ns}}
        commit = {e['request_id']: e['monotonic_s'] for e in events if e['kind']=='NODE_COMMIT' and e['request_id'] in dispatch}
        merge = next(e['monotonic_s'] for e in events if e['kind']=='MERGE_START' and e.get('arm')==label and e.get('repeat')==repeat)
        overlap = min(commit.values()) - max(dispatch.values())
        assert overlap > 0 and merge >= max(commit.values())
        cost = {cur: str(sum(D(n['cold_miss_public_estimate']) for n in ns if n['currency']==cur)) for cur in ['CNY','USD']}
        assert all(D(cost[cur])==D(arm['cost']['estimate_spent_native'][cur]) for cur in cost)
        cache_cost = {cur: str(sum(D(n['cache_aware_peak_public_estimate']) for n in ns if n['currency']==cur)) for cur in cost}
        q = ev['content_evaluation']['content_details']
        arms.append({'arm':label,'repeat':repeat,'content_F1':ev['content_Q'],'TP':q['TP'],'FP':q['FP'],'FN':q['FN'],'UNKNOWN':q['UNKNOWN'],
                     'legal_correct_targets':ev['legal_correct_targets'],'required_targets':6,'numeric_correct_over_six':q['TP']/6,
                     'schema_legal_branches':sum(n['branch_check']['schema'] for n in ns),'branch_count':2,
                     'source_ID_validity':ev['content_evaluation']['source_id_validity'],'source_proof_coverage_proxy':ev['content_evaluation']['source_proof_coverage_proxy'],
                     'input_tokens':sum(n['usage']['prompt_tokens'] for n in ns),'output_tokens':sum(n['usage']['completion_tokens'] for n in ns),
                     'total_tokens':sum(n['usage']['total_tokens'] for n in ns),'cached_input_tokens':sum(n['cached_input_tokens'] for n in ns),
                     'cold_miss_estimate_native':cost,'cache_aware_peak_estimate_native':cache_cost,'actual_cash':None,
                     'makespan_s':arm['arm_wall_s'],'cold_start_including_shared_preflight_s':arm['cold_start_wall_s'],
                     'amortized_preflight_makespan_s':arm['amortized_wall_s'],'node_service_sum_s':arm['sum_client_node_service_s'],
                     'dispatch_to_commit_overlap_s':overlap,'critical_branch':max(ns,key=lambda n:n['client_node_wall_s'])['node'],
                     'critical_branch_wall_s':max(n['client_node_wall_s'] for n in ns),
                     'arm_minus_longest_node_s':arm['arm_wall_s']-max(n['client_node_wall_s'] for n in ns),
                     'merge_wait_after_last_commit_s':merge-max(commit.values()),'deadline_met':arm['deadline_met']})
    fx=D(plan['research_FX_USD_to_CNY'])
    summary={}
    for label in ['A','B']:
        aa=[a for a in arms if a['arm']==label]
        native={c:sum(D(a['cold_miss_estimate_native'][c]) for a in aa) for c in ['CNY','USD']}
        cache={c:sum(D(a['cache_aware_peak_estimate_native'][c]) for a in aa) for c in native}
        summary[label]={'paired_runs':2,'requests':4,'Q_mean':sum(a['content_F1'] for a in aa)/2,
                        'legal_correct_targets_per_run':[a['legal_correct_targets'] for a in aa],
                        'input_tokens':sum(a['input_tokens'] for a in aa),'output_tokens':sum(a['output_tokens'] for a in aa),
                        'total_tokens':sum(a['total_tokens'] for a in aa),'cached_input_tokens':sum(a['cached_input_tokens'] for a in aa),
                        'total_cold_miss_estimate_native':{k:str(v) for k,v in native.items()},
                        'total_cache_aware_peak_estimate_native':{k:str(v) for k,v in cache.items()},
                        'mean_normalized_cold_miss_estimate_CNY':str((native['CNY']+fx*native['USD'])/2),
                        'mean_normalized_cache_aware_peak_estimate_CNY':str((cache['CNY']+fx*cache['USD'])/2),
                        'mean_makespan_s':sum(a['makespan_s'] for a in aa)/2,
                        'mean_cold_start_s':sum(a['cold_start_including_shared_preflight_s'] for a in aa)/2,
                        'deadline_met_runs':sum(a['deadline_met'] for a in aa),'actual_cash':None}
    a,b=summary['A'],summary['B']
    reduction=1-D(b['mean_normalized_cold_miss_estimate_CNY'])/D(a['mean_normalized_cold_miss_estimate_CNY'])
    increase=b['mean_makespan_s']/a['mean_makespan_s']-1
    pairs=[]
    for repeat in [1,2]:
        x=next(x for x in arms if x['arm']=='A' and x['repeat']==repeat)
        y=next(x for x in arms if x['arm']=='B' and x['repeat']==repeat)
        pairs.append({'repeat':repeat,'B_minus_A_makespan_s':y['makespan_s']-x['makespan_s'],'B_minus_A_content_F1':y['content_F1']-x['content_F1']})
    report={'source_run':str(run),'freeze_sha256':sha(HERE/'FREEZE.json'),'raw_manifest_verified':True,
            'frozen_scorer_recomputed_equal':True,'real_requests':8,'automatic_retries':0,'independent_events':1,'paired_repeats':2,
            'development_event':True,'nodes':nodes,'arms':arms,'targets':targets,'aggregate':summary,'pairs':pairs,
            'research_FX_USD_to_CNY':str(fx),'FX_is_fixed_research_assumption_not_current_or_paid':True,
            'frozen_primary':result['primary_exploratory_result'],'primary_all_conditions_pass':False,
            'normalized_cold_miss_estimated_cost_reduction_fraction':str(reduction),'makespan_increase_fraction':increase,
            'pareto_relation':'NONDOMINATED_TRADEOFF_EQUAL_BOUNDED_Q_B_CHEAPER_ESTIMATE_A_FASTER',
            'actual_cash':None,'full_opinion_Q':None,'full_semantic_contract':None,'semantic_citation_accuracy':None,
            'independent_generalization':None,'planning_search_learning_gain':None,
            'observed_conclusion':'Equal bounded quality and legal delivery; B lower public-rate estimated cost but slower in both pairs. Frozen joint success criterion not met.',
            'no_more_calls_authorized_or_planned':True}
    (out/'QCL_ANALYSIS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    # Build report directly from recomputed values; no manually supplied results.
    lines=['# 静态模型分配 A/B 真实数值 Pilot 综合结论', '',
           '本批已完整执行并停止：8次真实HTTP请求，0重试，4个合法终端交付物；同一开发事件、两次配对，非8个独立样本。', '',
           '**结论：限定数值质量持平，B公开价估费更低，但两次都更慢；冻结的联合成功标准未通过。不能报告总体胜利，也不据此补跑或调参。**', '',
           'A两个分支均为GLM-5.3；B采购为Qwen-Plus、年末应付余额为DeepSeek-Flash。冻结顺序AB/BA；分支真实并发，确定性汇合，无结构搜索或恢复。', '',
           '|运行|内容F1|合法正确目标|输入/输出Token|原币冷未命中估费|端到端秒|按期|',
           '|---|---:|---:|---|---|---:|---|']
    for x in arms:
        lines.append(f"|R{x['repeat']}-{x['arm']}|{x['content_F1']:.3f}|{x['legal_correct_targets']}/6|{x['input_tokens']}/{x['output_tokens']}|¥{x['cold_miss_estimate_native']['CNY']} + ${x['cold_miss_estimate_native']['USD']}|{x['makespan_s']:.6f}|是|")
    lines+=['', '|聚合指标|A|B|', '|---|---:|---:|',
            f"|均值限定F1|{a['Q_mean']:.3f}|{b['Q_mean']:.3f}|",
            f"|平均makespan秒|{a['mean_makespan_s']:.6f}|{b['mean_makespan_s']:.6f}|",
            f"|计入共享初始化的平均冷启动秒|{a['mean_cold_start_s']:.6f}|{b['mean_cold_start_s']:.6f}|",
            f"|总输入/输出Token|{a['input_tokens']}/{a['output_tokens']}|{b['input_tokens']}/{b['output_tokens']}|",
            f"|两轮总原币估费|¥{a['total_cold_miss_estimate_native']['CNY']}|¥{b['total_cold_miss_estimate_native']['CNY']} + ${b['total_cold_miss_estimate_native']['USD']}|",
            f"|每轮固定汇率归一估费CNY|{a['mean_normalized_cold_miss_estimate_CNY']}|{b['mean_normalized_cold_miss_estimate_CNY']}|",
            '', f'按冻结研究汇率1美元={fx}元，B平均公开价估费降低{float(reduction)*100:.2f}%；平均时延增加{increase*100:.2f}%。该汇率不是实时汇率或实际付款汇率。',
            '', '冻结标准要求B两轮6/6且F1=1、归一估费降低至少10%、时延增幅不超过10%、全程按期。前三项中的时延条件失败；其他条件通过。两臂在估费—时延上各有优势，未形成支配关系。',
            '', '质量使用原评分器F1=2TP/(2TP+FP+FN)：四次均TP=6、FP=FN=UNKNOWN=0，分母12，F1=1。另行报告数值正确覆盖6/6。8/8原生Schema及限定数值通道合同通过；数值错误、缺失、弃答、截断、HTTP失败均为0。完整语义合同成功概率不可由这8次通过率推断。',
            '', '引用ID全部有效，原冻结proof覆盖代理均为0.5；这不是50%引用正确率。逐目标原文位置、实际值、参考值及引用保存在QCL_ANALYSIS.json。完整证据蕴含准确率、完整舆情质量、因果/立场/风险结论均为UNKNOWN；参考为已验收的原文数值核对，并非双人盲评。',
            '', '原币全批冷未命中估费为¥'+result['estimate_meter']['estimate_spent_native']['CNY']+'和$'+result['estimate_meter']['estimate_spent_native']['USD']+'，均低于已授权估费阈值。实际账单未核验，现金费用为UNKNOWN，不声称实际扣费降低。',
            '', '补充缓存敏感性（不改冻结账本或主判据）：GLM第2轮余额命中4864输入Token，DeepSeek第2轮命中4605；Qwen无命中。按GLM命中2元/百万、DeepSeek峰时命中$0.006/百万估算，两臂两轮合计为：A ¥'+a['total_cache_aware_peak_estimate_native']['CNY']+'；B ¥'+b['total_cache_aware_peak_estimate_native']['CNY']+' + $'+b['total_cache_aware_peak_estimate_native']['USD']+'。均仍是公共价格推算，缓存时段、账户权益、最终账单未认证。无应用层跨臂复用，但供应商自动缓存影响不能完全消除。',
            '', '时延按实际ARM_START到确定性终端提交计算，不是节点耗时相加。每臂的并发重叠、汇合等待、最长分支及残余开销均保存。共享预检耗时'+str(result['preflight_wall_s'])+'秒；整批执行'+str(result['batch_wall_s'])+'秒，控制器约21.65秒。不存在单独测得的在线学习或结构搜索收益。',
            '', 'B的关键路径两轮均为采购Qwen-Plus（约6.72/6.71秒），余额DeepSeek约1.38/1.29秒；A最长分支约3.29/3.03秒。轨迹支持“本次Qwen采购分支决定B时延”，不能推断Qwen普遍较慢或调度算法本身存在普遍因果缺陷。较低单价、不同Tokenizer与输出格式长度均影响估费，不能仅归因为节点能力适配。',
            '', '本实验没有异构方案对最佳低价固定模型的对照，也没有学习分配对随机分配的消融。因此可支持特定分配组合的探索性降估费与时延权衡，不能识别异构性本身或智能控制器的独立增益。全部质量满分也提示本任务的质量天花板。',
            '', '机制已运行：有真实记录。收益已观测：质量相同、估费下降、时延退化。机制归因：仅节点关键路径与公开价关联，其他未证。统计稳定性：未证明。两对属于同一开发事件，不能做跨事件显著性或泛化声明。',
            '', '论文可写：固定两分支数值DAG上，预定异构分配保持6/6正确交付并大幅降低公开价估费，同时增加端到端时延，未满足冻结联合收益标准。不能写：完整舆情Q提升、动态图森林有效、V5/RL胜出、稳定Pareto优势或实际账单节省已证实。',
            '', '本轮到此结束，不补跑、不调参、不自动进入结构优化。后续独立实验仍需独立事件、可评分终端参考、公平配对及单独授权；本次不能自动解除其他研究门禁。',
            '', '原始记录：'+str(run), '冻结SHA256：'+sha(HERE/'FREEZE.json'),
            '', '官方价格核对（2026-10-26）：[DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/)、[Qwen](https://help.aliyun.com/zh/model-studio/model-pricing)、[GLM](https://docs.bigmodel.cn/cn/guide/start/pricing)。',
            '', '复算：python '+str(Path(__file__).resolve())+'（脚本拒绝覆盖已存在分析目录；读取原始响应及冻结评分器，不发送请求）。']
    (out/'COMPREHENSIVE_RESULT.md').write_text('\n'.join(lines)+'\n')
    (out/'ANALYSIS_MANIFEST.json').write_text(json.dumps({'source_run_manifest_sha256':sha(run/'RESULT_MANIFEST.json'),
        'analysis_script_sha256':sha(Path(__file__)), 'files':{p.name:sha(p) for p in out.iterdir() if p.is_file()}},indent=2)+'\n')
    print(json.dumps({'out':str(out),'aggregate':summary,'primary_pass':False,'estimated_cost_reduction':str(reduction),'wall_increase':increase},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
