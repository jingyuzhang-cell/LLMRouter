"""Experiment A: net DatasetBest-relative Gap Recovery on identical held-out queries.

This reporter does not train or change MA. Group bootstrap conditions on fitted
OOF policies; all declared seeds are averaged, never best-seed selected.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from .data import sha
from .diagnose_rank_signal import load_inputs


def gap_summary(gains, opportunity, groups, repeats=2000, seed=42):
    gains=np.asarray(gains,float);opportunity=np.asarray(opportunity,float)
    if gains.ndim==1:gains=gains[None,:]
    if gains.shape[1]!=len(opportunity) or not np.isfinite(gains).all() or not np.isfinite(opportunity).all():
        raise ValueError('Invalid paired observations')
    if (opportunity<0).any():raise ValueError('Oracle gap cannot be negative')
    if len(groups)!=len(opportunity):raise ValueError('Grouping shape mismatch')
    _,inverse=np.unique(groups,return_inverse=True);ng=int(inverse.max())+1
    group_size=np.bincount(inverse);group_gap=np.bincount(inverse,weights=opportunity)
    per_query=gains.mean(0);group_gain=np.bincount(inverse,weights=per_query)
    draws=np.random.default_rng(seed).integers(0,ng,size=(repeats,ng))
    numerator=group_gain[draws].sum(1);denominator=group_gap[draws].sum(1)
    gains_ci=np.quantile(numerator/group_size[draws].sum(1),[.025,.975]).tolist()
    valid=denominator>1e-12;gap=float(opportunity.mean());gain=float(per_query.mean())
    return dict(gain_vs_dataset_best=gain,gain_ci95=gains_ci,
        oracle_gap_vs_dataset_best=gap,gap_recovery=gain/gap if gap>1e-12 else None,
        gap_recovery_ci95=np.quantile(numerator[valid]/denominator[valid],[.025,.975]).tolist() if valid.any() else None,
        bootstrap_zero_denominator_draws=int((~valid).sum()),seed_count=len(gains),
        mean_seed_wins=float((gains>0).sum(1).mean()),mean_seed_losses=float((gains<0).sum(1).mean()),
        per_seed_gain=gains.mean(1).tolist(),groups=ng)


def load_choices(directory, expected_ids):
    d=Path(directory);result=json.loads((d/'RESULTS.json').read_text())
    for name,h in result['files'].items():
        if sha(d/name)!=h:raise ValueError('Experiment artifact changed')
    with np.load(d/'CHOICES.npz',allow_pickle=False) as z:
        if not np.array_equal(z['ids'],expected_ids):raise ValueError('Evaluation query order changed')
        return {k:z[k].astype(int) for k in z.files if k!='ids'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('source','controls','groups','output'):ap.add_argument('--'+k,required=True)
    ap.add_argument('--stable');a=ap.parse_args()
    source=Path(a.source);frozen,_,_=load_inputs(source)
    grouping=json.loads(Path(a.groups).read_text());sp=json.loads((source/'PROTOCOL.json').read_text())
    if sp['prompt_groups_sha256']!=sha(a.groups):raise ValueError('Group artifact mismatch')
    ids=frozen['ids'];y=frozen['quality'];index=np.arange(len(y));groups=np.array([grouping['groups'][q] for q in ids])
    baseline=y[index,frozen['DatasetBest']];oracle=y.max(1);opportunity=oracle-baseline
    choices=load_choices(a.controls,ids)
    actual={'DatasetBest':baseline[None,:], 'Ridge':y[index,frozen['Ridge']][None,:]}
    actual['MA(raw)']=np.array([y[index,choices[f'old_pair_panel_seed{s}']] for s in (42,43,44)])
    actual['MA(original winner)']=np.array([y[index,choices[f'old_winner_all_seed{s}']] for s in (42,43,44)])
    trained_folds=None
    if a.stable:
        stable=load_choices(a.stable,ids)
        for name,arm in [('MA(stable)','stable_pair'),('MA(raw matched stable queries)','old_pair_stable_matched'),('MA(repeat mean)','repeat_mean_panel')]:
            actual[name]=np.array([y[index,stable[f'{arm}_seed{s}']] for s in (42,43,44)])
        trace=json.loads((Path(a.stable)/'TRACE.json').read_text())
        trained_folds=sum(r['arm']=='stable_pair' and r.get('fallback') is None for r in trace)
    reports={name:dict(quality=float(v.mean()),**gap_summary(v-baseline,opportunity,groups)) for name,v in actual.items()}
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    report=dict(role='experiment_A_net_gap_recovery_development',n=len(y),oracle_quality=float(oracle.mean()),
                dataset_best_quality=float(baseline.mean()),oracle_gap=float(opportunity.mean()),
                opportunity_queries=int((opportunity>0).sum()),methods=reports,
                ma_stable_status='evaluated' if a.stable else 'NOT_RUN_MISSING_REASONING_REPEATS',stable_trained_fold_seed_runs=trained_folds,
                formula='(Q_method-Q_DatasetBest)/(Q_Oracle-Q_DatasetBest)',
                limits=['Signed all-query net gain; losses outside opportunity queries are included.',
                        'Group bootstrap recalculates numerator and denominator in the same resample.',
                        'Intervals condition on fitted OOF models, not retraining uncertainty; three seeds do not triple n.',
                        'Raw-panel versus stable changes sample filtering as well as labels; matched control isolates label direction.',
                        'Original-train development only; no independent test confirmation.'],
                evidence={str(source/'RESULTS.json'):sha(source/'RESULTS.json'),str(Path(a.controls)/'RESULTS.json'):sha(Path(a.controls)/'RESULTS.json'),str(Path(a.groups)):sha(a.groups)},
                reporter_sha256=sha(__file__))
    if a.stable:report['evidence'][str(Path(a.stable)/'RESULTS.json')]=sha(Path(a.stable)/'RESULTS.json')
    (out/'RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['# 实验A：净Gap Recovery','',
           '固定MA实现；原训练集相似题分组OOF开发比较。三seed取平均，不挑最高seed。','',
           f"Oracle={100*report['oracle_quality']:.3f}%，DatasetBest={100*report['dataset_best_quality']:.3f}%，Gap={100*report['oracle_gap']:.3f}个百分点；严格机会题{report['opportunity_queries']}道。",'',
           '`Gap Recovery=(Q方法−QDatasetBest)/(QOracle−QDatasetBest)`，允许负值。','',
           '| 方法 | Quality | 净增益(pp) | Gap Recovery | Recovery 95%区间 |','|---|---:|---:|---:|---:|']
    for name,r in reports.items():
        recovery='未定义' if r['gap_recovery'] is None else f"{100*r['gap_recovery']:.2f}%"
        ci=r['gap_recovery_ci95'];interval='未定义' if ci is None else f'[{100*ci[0]:.2f}%, {100*ci[1]:.2f}%]'
        lines.append(f"| {name} | {100*r['quality']:.3f}% | {100*r['gain_vs_dataset_best']:+.3f} | {recovery} | {interval} |")
    if not a.stable:lines.append('| MA(stable) | 待reasoning重复标签 | — | — | — |')
    lines+=['','当前MA(raw)为折内面板原pair监督；原winner另列。MA(stable)未运行时不得填0%冒充结果。',
            '区间按相似题组配对重采样，同一重采样同时计算净增益和Oracle gap；仍是条件于既有OOF拟合的开发区间。',
            '严格机会子集之外的误切换同样计入损失。该统计口径不会因只挑救回题而虚增恢复率。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines))

if __name__=='__main__':main()
