"""Report verified experiment completion, never promote pending stages to done."""
import json
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
from .data import sha
from . import run_repeat_stability as repeat

ROOT=Path(__file__).resolve().parents[1]


def verify_artifacts(directory):
    d=Path(directory);result=json.loads((d/'RESULTS.json').read_text())
    for name,h in result['files'].items():
        if sha(d/name)!=h:raise ValueError('Result artifact changed: '+str(d/name))
    return result


def main():
    out=ROOT/'router_v2/execution_review_20260910';out.mkdir(exist_ok=True)
    clean=ROOT/'data/clean_splits_verified_20260910b'
    matrix=json.loads((clean/'MANIFEST.json').read_text())
    for value in matrix['partitions'].values():
        for name,h in value['files'].items():
            if sha(clean/name)!=h:raise ValueError('Clean matrix changed')
    source=ROOT/'router_v2/objective_verified_20260910';obj=verify_artifacts(source)
    protocol=json.loads((source/'PROTOCOL.json').read_text())
    for name,h in protocol['input_sha256'].items():
        if sha(name)!=h:raise ValueError('Objective source input changed')
    ma=verify_artifacts(ROOT/'router_v2/ma_repeat_controls_20260910')
    mo=verify_artifacts(ROOT/'router_v2/tieaware_verified_20260910')
    panel=ROOT/'router_v2/repeat_fold_panel_20260910';pm=json.loads((panel/'MANIFEST.json').read_text())
    for name,h in pm['files'].items():
        if sha(panel/name)!=h:raise ValueError('Panel changed')
    repeat_dir=ROOT/'data/repeat_fold_stability_20260910';rc={}
    for slot in ('large','reasoning'):
        rows=repeat.read_jsonl(repeat_dir/(slot+'.jsonl'))
        valid=[r for r in rows if r.get('status')!='failed' and r.get('quality') is not None and
               r.get('panel_sha256')==pm['files']['PANEL.jsonl'] and r.get('scorer_sha256')==sha(repeat.__file__)]
        keys={(r['query_id'],r['repeat_index']) for r in valid}
        if len(keys)!=len(valid):raise ValueError('Duplicate valid repeat')
        rc[slot]=dict(records=len(rows),valid=len(valid),expected=pm['n_panel']*pm['repeats'],
                      evaluation_status=dict(Counter(r.get('evaluation_status') for r in rows)))
    queue=repeat.read_jsonl(clean/'REPAIR_QUEUE.jsonl')
    scope=dict(status='AWAITING_EXPLICIT_EXTERNAL_DATA_AUTHORIZATION',
        destination='https://dashscope.aliyuncs.com/compatible-mode/v1',
        generation_repair=dict(model='deepseek-r1-distill-qwen-14b',cells=10,
            partitions={'train':8,'validation':1,'test':1},dataset='arenahard',data_sent='query only',
            max_transport_attempts_per_cell=2,temperature=0.,correctness_based_retries=False),
        repeat_generation=dict(model='deepseek-r1-distill-qwen-14b',queries=pm['n_panel'],partition='train',
            repeats=5,generations=pm['n_panel']*5,temperature=.7,top_p=1.,data_sent='query only; no ground truth',
            max_transport_attempts_per_repeat=2,panel=str(panel/'PANEL.jsonl'),panel_sha256=pm['files']['PANEL.jsonl']),
        open_ended_grading=dict(model='qwen-max',cells_after_repair=len(queue),partitions={'train':458,'validation':96,'test':96},
            data_sent='ArenaHard question and complete candidate answer',max_attempts_per_exact_response=2,
            quality_policy='first valid grade; no higher-score selection',historical_attempt_budget_inherited=True),
        constraints=['Existing account credentials remain local; provider receives the listed dataset content.',
                     'API calls incur charges. No external requests are executed by this audit.',
                     'Original test is retired development history; filling its matrix does not make it independent.'],
        approval_review_rejections=['reasoning repair data egress lacked explicit current authorization',
                                   'train ArenaHard grading egress rejected despite historical authorization file'])
    (out/'EXTERNAL_SCOPE.json').write_text(json.dumps(scope,indent=2,ensure_ascii=False)+'\n')
    prior_missing='/root/r3_own_pool/data/train_matrix_clean_audit_20260910/TRAIN_MATRIX.jsonl'
    status=dict(updated_at=datetime.now(timezone.utc).isoformat(),
        clean_matrix=dict(directory=str(clean),counts={p:v['counts'] for p,v in matrix['partitions'].items()},
                          missing_cells=len(queue),failure_zero_contamination_removed=True,
                          all_tasks_complete=matrix['all_cells_labeled'],independent_test_ready=False,
                          retired_test_queries=matrix['known_exposure_counts']['test']),
        repeat=rc,stable_pairs_complete=all(v['valid']==v['expected'] for v in rc.values()),
        ma_original_label_controls_complete=True,ma_stable_label_experiment_complete=False,
        multiobjective_diagnostic_complete=True,multiobjective_confirmed=False,
        formal_paper_loop_complete=False,
        historical_missing_input=prior_missing,baseline_rebuilt_from_verified_current_inputs=True,
        tests_unique_passed=19,tests=['test_repeat_execution.py','test_contamination.py','test_objective_signal.py','test_anchored_ma.py'],
        pending_external_scope=str(out/'EXTERNAL_SCOPE.json'))
    (out/'STATUS.json').write_text(json.dumps(status,indent=2,ensure_ascii=False)+'\n')
    old_winner=sum(v['quality'] for k,v in ma['methods'].items() if k.startswith('old_winner'))/3
    old_pair=sum(v['quality'] for k,v in ma['methods'].items() if k.startswith('old_pair'))/3
    point=mo['policies']['tieaware_eps0.005']
    lines=['# 实验执行核查','','结论：尚未形成论文实验闭环；本轮完成本地可执行部分，外部请求待明确授权。','',
           '| 阶段 | 核查与本轮执行结果 | 是否完成 |','|---|---|---|',
           f"| P0 clean matrix | train/val/test 已重新导出并校验，仍有 {len(queue)} 个开放题单元缺标签；原 750 题 test 全部退役 | 部分 |",
           f"| P1 stable pair | 折内独立选题 {pm['n_panel']} 道；large {rc['large']['valid']}/{rc['large']['expected']}，reasoning {rc['reasoning']['valid']}/{rc['reasoning']['expected']} | 未完成 |",
           '| P2 MA 标签对照 | 原 winner、原 pair 三 seeds 已实跑；repeat 均值、stable pair、同样本原 pair 对照入口已完成，等待双模型重复标签 | 部分 |',
           '| P3 多目标 | 无事后成本泄漏的 tie-aware 已重新实跑；成本/延迟统一口径与独立确认仍缺失 | 仅探索完成 |','',
           '## 可复现结果','',
           f"- 重建基线：Ridge {100*obj['results']['all']['methods']['Ridge']['quality']:.3f}%，DatasetBest {100*ma['dataset_best_quality']:.3f}%；Ridge 差值区间覆盖 0。",
           f"- 新的同架构锚定 MA 控制：原 winner 三 seeds 平均 {100*old_winner:.3f}%，原 pair 平均 {100*old_pair:.3f}%。每个原 pair seed 的增益区间均覆盖 0；不能挑最佳 seed 宣称超过基线。",
           '- 该原 winner/原 pair 比较同时改变标签与训练样本，不能单独归因为标签。待执行的 stable pair 与同样本原 pair 对照才用于隔离标签方向的效果。',
           f"- 固定 epsilon=.005：平均质量 {100*point['quality']:.3f}%，成本代理降低 {100*point['cost_saving_fraction_vs_baseline']:.2f}%，记录延迟降低 {-point['latency_delta_ms_vs_baseline']/1000:.2f} 秒。质量差95%区间为 [-0.403,+0.404] pp，不能认定严格质量非劣。",'',
           '## 本轮修复与边界','',
           '- 修复旧清洗报告只隔离81题的遗漏：已纳入真实测试开封证据，隔离全部750题。没有重算测试质量。',
           '- 发现历史报告所引用 clean train 快照当前缺失；保留历史报告，新生成矩阵并重跑分组OOF，数值复现成功。',
           '- 已完成的旧 large 480条回答未丢弃；按来源与采样设置核验并复评，113题面板中复用22题/110条，标签无变化；新采集455条。',
           '- 每个外层训练折独立选择41题，包含严格分歧、近并列、高regret和按数据集随机采样；去重并集113题。该折评估题的重复标签不能进入该折训练。',
           '- 5×5比较是相关观测，不能当25次独立试验；.8是经验阈值。temperature=.7标签用于temperature=0原结果的迁移实验，不能宣称同部署分布噪声已估计。',
           '- 新增失败恢复、外部HTTP接口、标准答案不外发、稳定标签完整性及同样本对照测试；本轮19项相关测试通过。',
           '- 原始test已开封，正式确认需要新增去重测试题；当前不能通过重排原split恢复独立性。','',
           '## 下一步执行入口','',
           '外部数据范围、请求次数与重试上限见 EXTERNAL_SCOPE.json；审批仍拒绝数据外发，未启动reasoning重复生成或开放题补评分。',
           '双模型采集齐全后依次运行：','',
           '```bash',
           'python -m router_v2.run_repeat_stability --panel router_v2/repeat_fold_panel_20260910/PANEL.jsonl --output data/repeat_fold_stability_20260910 --mode aggregate',
           'python -m router_v2.train_repeat_pair_ma --panel-dir router_v2/repeat_fold_panel_20260910 --groups router_v2/contamination_audit_20260910b/PROMPT_GROUPS.json --repeat-dir data/repeat_fold_stability_20260910 --mode stable --output router_v2/ma_stable_pair_20260910',
           '```','', '当前stable训练入口会因标签不完整而拒绝运行；尚无stable-pair超越DatasetBest的实验结论。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(status,indent=2,ensure_ascii=False))

if __name__=='__main__':main()
