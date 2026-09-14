"""Outer-only metrics and paired factorial contrasts for E6."""
import json
from pathlib import Path
import numpy as np
from .data import sha
from .run_e6_representation_objective_2x2 import OUT, ARMS, SLOTS, verify, write, status


def summarize():
    verify()
    if (OUT/'RESULTS.json').exists():raise FileExistsError('E6 already evaluated')
    frozen=json.loads((OUT/'PREDICTIONS_FROZEN.json').read_text())
    if sha(OUT/'PREDICTIONS.npz')!=frozen['predictions_sha256'] or sha(OUT/'PROTOCOL.json')!=frozen['protocol_sha256']:
        raise ValueError('Predictions/protocol changed')
    if sha(OUT/'FIT_AUDIT.json')!=frozen['fit_audit_sha256']:raise ValueError('Fit audit changed')
    for fold, files in frozen['fold_hashes'].items():
        for name,digest in files.items():
            if sha(OUT/f'fold{fold}'/name)!=digest:raise ValueError('Fold artifact changed')
    z=np.load(OUT/'PREDICTIONS.npz',allow_pickle=False);data=np.load(OUT/'INPUTS.npz',allow_pickle=False)
    ids=z['ids'].tolist();y=z['quality'];rows=np.arange(len(ids));base=y[rows,z['bestsingle_choice']];oracle=y.max(1)
    observed={a:y[rows,z[a+'_choice']] for a in ARMS}
    if not all(np.array_equal(z[a+'_scores'].argmax(1),z[a+'_choice']) for a in ARMS):raise ValueError('Argmax mismatch')
    boot=np.random.default_rng(20260914).integers(0,len(ids),(10000,len(ids)))
    def distribution(v):return v[boot].mean(1)
    def interval(v,coverage=.95):return np.quantile(distribution(v),[(1-coverage)/2,1-(1-coverage)/2]).tolist()
    def contrast(v):return dict(mean=float(v.mean()),ci95=interval(v))
    gap=oracle-base;gap_samples=distribution(gap)
    if np.any(gap_samples<=0):raise ValueError('Unstable oracle denominator')
    methods={};per_fold=[]
    for a in ARMS:
        q=observed[a];diff=q-observed[ARMS[0]];gain=q-base;choice=z[a+'_choice'];ref=z[ARMS[0]+'_choice']
        ci=interval(diff)
        methods[a]=dict(expected_quality=float(q.mean()),eq_ci95=interval(q),
            gap_recovery=float(gain.mean()/gap.mean()),gap_recovery_ci95=np.quantile(distribution(gain)/gap_samples,[.025,.975]).tolist(),
            vs_queryonly=dict(mean=float(diff.mean()),ci95=ci,ci98333_bonferroni=interval(diff,1-.05/3)),
            vs_bestsingle=contrast(gain),success_vs_queryonly=bool(a!=ARMS[0] and diff.mean()>0 and ci[0]>0),
            selection_counts=dict(zip(SLOTS,np.bincount(choice,minlength=4).tolist())),
            switches_vs_queryonly=dict(queries=int((choice!=ref).sum()),helped=int((diff>0).sum()),harmed=int((diff<0).sum()),
                                      tied=int(((choice!=ref)&(diff==0)).sum())))
        for f in range(3):
            mask=data['outer_fold']==f;local_gain=gain[mask];local_gap=gap[mask]
            per_fold.append(dict(fold=f,method=a,n=int(mask.sum()),expected_quality=float(q[mask].mean()),
                gain_vs_queryonly=float(diff[mask].mean()),gain_vs_bestsingle=float(local_gain.mean()),
                gap_recovery=float(local_gain.mean()/local_gap.mean()),
                selection_counts=dict(zip(SLOTS,np.bincount(choice[mask],minlength=4).tolist()))))
    A,B,C,D=[observed[a] for a in ARMS]
    contrasts={name:contrast(v) for name,v in {
        'B_minus_A':B-A,'C_minus_A':C-A,'D_minus_A':D-A,'D_minus_B':D-B,'D_minus_C':D-C,
        'interaction_D_minus_B_minus_C_plus_A':D-B-C+A,
        'representation_average_effect':((B-A)+(D-C))/2,
        'objective_average_effect':((C-A)+(D-B))/2}.items()}
    passed=[a for a in ARMS[1:] if methods[a]['success_vs_queryonly']]
    if not passed:
        interpretation='no_scheme_passed'
    elif ARMS[1] in passed and ARMS[2] not in passed:
        interpretation='capability_intervention_supported'
    elif ARMS[2] in passed and ARMS[1] not in passed:
        interpretation='weighting_intervention_supported'
    elif ARMS[1] not in passed and ARMS[2] not in passed and ARMS[3] in passed:
        interpretation='joint_scheme_only_supported'
    else:
        interpretation='both_individual_interventions_supported'
    decision=dict(successful_schemes=passed,interpretation=interpretation,
        positive_interaction_ci=contrasts['interaction_D_minus_B_minus_C_plus_A']['ci95'][0]>0,
        criterion='EQ>A and paired query CI95 lower>0; no change to frozen user criterion',
        expansion_executed=False,next_experiment_started=False,
        caution='A nonsignificant arm is not statistically equivalent to A; no causal identification of former MA failure.')
    result=dict(experiment='E6 Representation × Objective 2×2',n=400,methods=methods,
                bestsingle_eq=float(base.mean()),empirical_oracle_eq=float(oracle.mean()),empirical_oracle_gap=float(gap.mean()),
                factorial_contrasts=contrasts,decision=decision,
                protocol_sha256=sha(OUT/'PROTOCOL.json'),predictions_sha256=sha(OUT/'PREDICTIONS.npz'))
    write(OUT/'RESULTS.json',result)
    (OUT/'PER_FOLD.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in per_fold))
    report(result)
    status('COMPLETE',successful_schemes=passed,next_experiment_started=False)


def fmt(row):return f'{100*row["mean"]:+.2f} [{100*row["ci95"][0]:.2f}, {100*row["ci95"][1]:.2f}]'


def report(r):
    m=r['methods'];decision=r['decision']
    lines=['# E6：Representation × Objective 2×2','',
           '只运行四组固定实验，使用原始提示GTE、400-query×4-model×5-repeat corrected labels和原有三个frozen outer folds。每折development168/168/167题，outer test不变。无新回答、编码、扩数据、MLP或超参数搜索。','',
           '| 模型表示 | 当前等权目标 | 稳定性加权目标 |','|---|---|---|',
           '| 原始独立输出坐标 | A：QueryOnlyRidge | C：Stability |',
           '| development区域能力画像 | B：Capability | D：Capability + Stability |','',
           '## Outer-test结果','',
           f'BestSingle={r["bestsingle_eq"]:.2%}；经验五重复均值Oracle={r["empirical_oracle_eq"]:.2%}。','',
           '| 组 | EQ | Gap Recovery | 对A增益 pp [95% paired CI] | 达到冻结成功标准 |','|---|---:|---:|---|---|']
    for a in ARMS:
        v=m[a]
        lines.append(f'| {a} | {v["expected_quality"]:.2%} | {v["gap_recovery"]:.2%} | {fmt(v["vs_queryonly"])} | '+('基线' if a==ARMS[0] else ('是' if v['success_vs_queryonly'] else '否'))+' |')
    lines+=['','成功标准严格为EQ>A且配对query bootstrap CI95下界>0。使用10000次固定种子query重采样；GapRecovery的分子和分母同步重算。RESULTS.json另报三个与A比较的98.333% Bonferroni区间作为多重比较背景，不改变用户冻结判据。','',
            '## 2×2效应与交互','', '| 对比 | EQ变化 pp [95% CI] |','|---|---|']
    for name,v in r['factorial_contrasts'].items():lines.append(f'| {name} | {fmt(v)} |')
    explanations={'no_scheme_passed':'B、C、D均未通过成功标准。本次行为画像和稳定性权重未证明能改善QueryOnly，不扩大这些方案。没有显著差异不等同于证明四组等价。',
        'capability_intervention_supported':'B通过而C未通过，更支持本次行为画像干预；这不等于证明objective没有作用。D的结果及交互项独立报告。',
        'weighting_intervention_supported':'C通过而B未通过，更支持本次稳定性加权干预；这不等于证明model representation没有作用。D的结果及交互项独立报告。',
        'joint_scheme_only_supported':'仅D通过，联合方案成为开发候选；是否有统计上的正交互，仍需检查D−B−C+A区间，不能从两个单独组不显著直接推出必须联合。',
        'both_individual_interventions_supported':'B和C各自通过，两个单独干预均有开发证据；D是否进一步改善由交互及D−B/D−C比较判断。'}
    lines+=['','## 判定','',explanations[decision['interpretation']], '',
            '未启动扩大采集或任何后续实验。','',
            '## 冻结实现与隔离','',
            '1. 所有组预测ΔQ(q,m)=mean5(q,m)−mean5(q,R1)，R1分数为0。相同设计矩阵、alpha与截距下，等权Ridge的质量差预测等于直接对质量差做Ridge；A须精确复现历史400题QueryOnly选择。这样A/C和B/D的objective差异只有权重。',
            '2. KMeans只拟合development GTE，固定K=8、random_state=42、n_init=10。c_m为8个region的平均质量，固定5个全局development均值伪样本作收缩。记录原始与收缩画像、区域大小及中心；outer特征不参与聚类，outer标签不参与画像。',
            '3. B/D用d_m=c_m−c_R1，并将全部三个d_m共同缩放到平方范数和3，与A/C的单位模型核trace3一致。使用线性双线性交互e_q⊗d_m的Ridge，alpha=1。没有简单加法拼接或神经网络。模型特征满秩时只是不同的参数共享/正则化几何，不能声称增加了query信息或识别了旧learned-ID的因果缺陷。',
            '4. S(q,m)=clip(1−2[Var5(m)+Var5(R1)],0,1)，方差ddof=0；raw w=0.05+0.95|ΔQ|S。按每个alternative在development内归一化到均值1，C和D共享完全相同的权重。所有tie保留且raw w=0.05。重复编号之间不假定模型配对。',
            '5. 四组使用同一个凸线性求解器，截距在各自模型特征张成空间内不受惩罚。固定K/alpha/收缩/权重下限与随机种子，不用outer结果重试或选择参数。只报告outer质量作为效果证据；求解残差仅用于数值检查。','',
            '## 选择分布','', '| 组 | medium | large | coder | reasoning |','|---|---:|---:|---:|---:|']
    for a in ARMS:lines.append(f'| {a} | '+' | '.join(str(m[a]['selection_counts'][s]) for s in SLOTS)+' |')
    lines+=['','## 结论边界','',
            '- 本实验是已使用、机会富集面板上的开发诊断。bootstrap条件于拟合后的模型与区域，不含完整重训不确定性。',
            '- 五次重复构造的S是经验一致性指标，不是稳定偏好的真概率。旧E2不能识别精确的生成噪声占比，也不能预先保证加权有效。',
            '- 以QueryOnly为A的2×2检验两项具体干预；不能单凭它确定旧非线性MA失败的唯一原因。',
            '- 单次固定K和权重定义不成功，不等于排除所有行为表示、目标函数或编码器；不再在此面板盲搜配置。',
            '', '文件：PROTOCOL.json保存冻结方案；PREDICTIONS.npz保存逐题预测；fold*/保存能力画像、权重、线性系数和来源；PER_FOLD.jsonl保存逐折outer指标。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':summarize()
