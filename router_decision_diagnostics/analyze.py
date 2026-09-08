"""Read-only postprocessing of frozen OOF outcomes. No fitting or API calls."""
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT=Path('/root')
OUT=Path(__file__).resolve().parent
EPS=(0,.001,.01,.05)

def envelope(points):
    """Upper, nondecreasing convex-mixture boundary (concave as Q(C)).
    Include null policy for low-budget extension and hold final quality to right.
    """
    points=np.asarray(points,dtype=float)
    if points.ndim!=2 or points.shape[1]!=2 or not np.isfinite(points).all() or (points<0).any():
        raise ValueError('Expected finite nonnegative [cost,quality] points')
    best={0.:0.}
    for c,q in points:best[float(c)]=max(best.get(float(c),0.),float(q))
    nd=[]
    for c,q in sorted(best.items()):
        if not nd or q>nd[-1][1]:nd.append((c,q))
    hull=[]
    for p in nd:
        while len(hull)>=2:
            a,b=hull[-2:]
            cross=(b[0]-a[0])*(p[1]-b[1])-(b[1]-a[1])*(p[0]-b[0])
            if cross>=0:hull.pop()
            else:break
        hull.append(p)
    return np.array(hull)

def aiq(points,lo,hi):
    if not 0<=lo<hi:raise ValueError('Empty or invalid common cost range')
    h=envelope(points)
    x=np.unique(np.r_[lo,h[(h[:,0]>lo)&(h[:,0]<hi),0],hi])
    return float(np.trapezoid(np.interp(x,h[:,0],h[:,1]),x)/(hi-lo))

def iso_cost(points,target):
    h=envelope(points)
    if target>h[-1,1]+1e-12:return None
    if target<=h[0,1]:return float(h[0,0])
    return float(np.interp(target,h[:,1],h[:,0]))

def pareto3(values):
    # Per-policy values are [quality,cost,latency].
    x=np.asarray(values)*np.array([-1,1,1])
    return [i for i,a in enumerate(x) if not np.any(np.all(x<=a,axis=1)&np.any(x<a,axis=1))]

def read(path):
    with path.open() as f:return [json.loads(line) for line in f if line.strip()]

def main():
    paths=[ROOT/'router_suggestion_audit/OOF.npz',ROOT/'router_suggestion_audit/RESULTS.json',ROOT/'router_suggestion_audit/PROTOCOL.json',
           ROOT/'five_model_routability_audit/five_model_training_repeats_frozen.jsonl',
           ROOT/'target_support_expansion_v1/expanded_five_model_repeats_frozen.jsonl']
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    protocol=json.loads(paths[2].read_text())
    a=np.load(paths[0],allow_pickle=False)
    y=a['outcomes'];ids=a['ids'].tolist();models=protocol['models'];q,c,t=np.moveaxis(y,2,0)
    n,m=q.shape;ii=np.arange(n)
    assert (n,m)==(419,5) and np.isfinite(y).all()
    assert np.all((q>=0)&(q<=1)) and (c>=0).all() and (t>=0).all()
    # Check artifact metrics independently before constructing any envelope.
    previous=json.loads(paths[1].read_text())
    for row in previous:
        g=protocol['grid'].index([row['lam'],row['mu']])
        actual=y.mean(axis=1) if row['method']=='random_expected' else y[ii,a[row['method']][g]]
        assert np.allclose(actual.mean(0),[row['quality'],row['cost_usd'],row['latency_ms']])
    bs=int(q.mean(0).argmax());bq=q[:,bs];best=q.max(1)
    margin=np.sort(q,axis=1)[:,-1]-np.sort(q,axis=1)[:,-2]
    widths=q.max(1)-q.min(1)
    summary={'n_queries':n,'n_models':m,'label_type':'graded quality averaged over three repeats, NOT Bernoulli outcomes',
        'best_single':models[bs],'best_single_quality':float(bq.mean()),'oracle_three_repeat_mean':float(best.mean()),
        'empirical_gap':float((best-bq).mean()),
        'margin_cdf':{str(e):float((margin<=e+1e-12).mean()) for e in EPS},
        'all_models_close_cdf':{str(e):float((widths<=e+1e-12).mean()) for e in EPS},
        'oracle_gain_by_top2_margin':{str(e):float(np.mean((best-bq)*(margin<=e+1e-12))) for e in EPS},
        'quality_correlations':np.corrcoef(q.T).tolist(),
        'quality_only_leave_one_out':{models[j]:float(np.mean(best-np.delete(q,j,axis=1).max(1))) for j in range(m)}}
    # Binary ceiling must use the SAME thresholded metric for baseline and oracle.
    summary['thresholded_success_diagnostics']={}
    for threshold in (.6,.8,1.):
        z=q>=threshold
        beta=float((~z.any(1)).mean())
        summary['thresholded_success_diagnostics'][str(threshold)]={'all_fail_rate':beta,'success_oracle':1-beta,
            'best_single_success':float(z.mean(0).max()),'success_gap':float(1-beta-z.mean(0).max())}
    # Oracle selection and scoring on separate repeats. Diagnostic, not debiased truth.
    lookup={}
    for p in paths[3:]:
        for row in read(p):
            if row['task_id'] not in set(ids):continue
            key=(row['task_id'],row['model'],int(row['repeat']))
            if key in lookup:raise ValueError(f'Duplicate repeat key {key}')
            lookup[key]=float(row['quality'])
    repeats=np.array([[[lookup[i,model,r] for r in range(3)] for model in models] for i in ids])
    assert np.allclose(repeats.mean(2),q)
    split_scores=[];single_draw=[]
    for r in range(3):
        other=np.delete(repeats,r,axis=2).mean(2)
        picks=other.argmax(1)
        split_scores.append(repeats[ii,picks,r])
        single_draw.append(repeats[:,:,r].max(1))
    repeat_score=np.array(split_scores).mean(0)
    summary['repeat_diagnostic']={'same_draw_oracle_mean':float(np.mean(single_draw)),
        'select_on_two_evaluate_on_third':float(repeat_score.mean()),
        'difference_from_three_repeat_max_mean':float(best.mean()-repeat_score.mean()),
        'warning':'Three repeats only. Argmax ties use fixed model order. Not a certified noise decomposition; do not import 12-36% from another pool.'}
    # Use observed single-model range consistently for every descriptive curve.
    lo,hi=float(c.mean(0).min()),float(c.mean(0).max())
    single=np.column_stack([c.mean(0),q.mean(0)])
    groups={'zero_router':np.repeat(y[:,None,bs,:],1,axis=1)} # overwritten below with all fixed models
    groups['zero_router']=y
    for name in ('knn_utility','component_ridge','oracle'):
        picked=np.stack([y[ii,p] for p in a[name]],axis=1)
        groups[name+'_mu0']=picked[:,[k for k,(_,mu) in enumerate(protocol['grid']) if mu==0]]
        groups[name+'_all24']=picked
    curves={};policy_means={}
    for name,values in groups.items():
        means=values.mean(0);points=means[:,[1,0]]
        hull=envelope(points);iso=iso_cost(points,float(bq.mean()))
        eligible=np.flatnonzero(means[:,0]>=bq.mean()-1e-12)
        raw_iso=None if not len(eligible) else float(means[eligible,1].min())
        curves[name]={'aiq':aiq(points,lo,hi),'iso_quality_mixture_cost':iso,
                     'iso_quality_mixture_saving':None if iso is None else 1-iso/float(c[:,bs].mean()),
                     'iso_quality_discrete_cost':raw_iso,
                     'iso_quality_discrete_saving':None if raw_iso is None else 1-raw_iso/float(c[:,bs].mean()),
                     'hull_cost_quality':hull.tolist(),'points_quality_cost_latency':means.tolist(),
                     'nondominated_3d_policy_indices':pareto3(means)}
        policy_means[name]=means
    for name in curves:curves[name]['aiq_gain_vs_zero']=curves[name]['aiq']-curves['zero_router']['aiq']
    summary['cost_domain_usd_per_query']=[lo,hi]
    summary['curves']=curves
    summary['zero_router_leave_one_out_aiq_loss']={models[j]:curves['zero_router']['aiq']-aiq(np.delete(single,j,axis=0),lo,hi) for j in range(m)}
    # Exact observed quality ties: opportunity bound, not a deployable decision rule.
    tie_choices=np.argmin(np.where(q>=best[:,None]-1e-12,c,np.inf),axis=1)
    summary['hindsight_cheapest_quality_oracle']={'quality':float(q[ii,tie_choices].mean()),'cost':float(c[ii,tie_choices].mean()),
         'warning':'Uses actual outcomes of every candidate; upper-bound diagnostic only, not a learned tie breaker.'}
    # Paired task bootstrap with fixed predictions; selection envelope remains descriptive.
    rng=np.random.default_rng(20260908);B=2000
    idx=rng.integers(n,size=(B,n))
    gains=q[ii,a['component_ridge'][0]]-bq
    summary['observed_effect_power_sensitivity']={'paired_sd':float(gains.std(ddof=1)),
        'delta':float(gains.mean()),'approx_test_n_80pct_power_two_sided_5pct':None if gains.mean()==0 else int(np.ceil((1.96+.841621)**2*gains.var(ddof=1)/gains.mean()**2)),
        'warning':'Normal-approximation planning at fixed effect/variance, not a claim that more training data cannot help.'}
    summary['paired_ci95']={'ridge_quality_gain':np.quantile(gains[idx].mean(1),[.025,.975]).tolist(),
        'split_repeat_quality_minus_best_single':np.quantile((repeat_score-bq)[idx].mean(1),[.025,.975]).tolist()}
    boot_aiq={name:[] for name in ('knn_utility_mu0','component_ridge_mu0')}
    for sample in idx:
        z=aiq(y[sample].mean(0)[:,[1,0]],lo,hi)
        for name in boot_aiq:
            boot_aiq[name].append(aiq(groups[name][sample].mean(0)[:,[1,0]],lo,hi)-z)
    summary['aiq_gain_ci95_fixed_oof']={name:np.quantile(values,[.025,.975]).tolist() for name,values in boot_aiq.items()}
    summary['limitations']=['Exploratory reuse of 419 development queries, no untouched evaluation.',
        'Convex mixtures and same-quality point selection are post-hoc descriptive envelopes, not validation-selected deployed policies.',
        'All24 is a projection over different latency preferences, not a latency-constrained quality-cost comparison.',
        'Cost currency/price and latency deployment comparability inherited from historical data, not independently verified.',
        'Task bootstrap conditions on fitted OOF models, omits retraining variation; no multiple-testing correction.',
        'No new model fitting. OOF predicted Q/C/L scores were not saved, so learned epsilon tie breaking cannot be reconstructed from argmax decisions.']
    (OUT/'INPUT_MANIFEST.json').write_text(json.dumps(hashes,indent=2))
    (OUT/'DIAGNOSTICS.json').write_text(json.dumps(summary,indent=2,allow_nan=False))
    make_report(summary)
    plot(summary)
    assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    print((OUT/'REPORT.md').read_text())

def make_report(s):
    lines=['# 419-query 决策诊断（只读后处理）','',f"Best Single ({s['best_single']}): {s['best_single_quality']:.6f}; 三重复均值 Oracle: {s['oracle_three_repeat_mean']:.6f}; empirical gap: {s['empirical_gap']:.6f}。",'',
       '## Margin 与模型贡献','', '| ε | Top-2 margin≤ε | 所有模型质量范围≤ε |','|---|---:|---:|']
    for e in EPS:lines.append(f"| {e} | {s['margin_cdf'][str(e)]:.2%} | {s['all_models_close_cdf'][str(e)]:.2%} |")
    lines+=['','Top-2 tie 不表示全部模型相同，也不证明 ranking 必优。','', '| 模型 | 移除后的质量 Oracle 损失 | 移除后的 Zero Router AIQ 损失 |','|---|---:|---:|']
    for m,d in s['quality_only_leave_one_out'].items():lines.append(f"| {m} | {d:.6f} | {s['zero_router_leave_one_out_aiq_loss'][m]:.6f} |")
    lines+=['','## AIQ 与同质量成本（描述性开发集曲线）','', '积分区间为各固定模型平均成本的最小到最大值，所有方法共用；null 插值扩展低成本端，高成本端保持最高质量。Zero Router 为固定模型的概率混合，不是永远调用最强模型。','', '| 曲线 | AIQ | ΔAIQ vs Zero | 同质量节省：离散策略 | 同质量节省：凸包混合 |','|---|---:|---:|---:|---:|']
    def pct(x):return '不可达' if x is None else f'{x:.2%}'
    for name,r in s['curves'].items():lines.append(f"| {name} | {r['aiq']:.6f} | {r['aiq_gain_vs_zero']:+.6f} | {pct(r['iso_quality_discrete_saving'])} | {pct(r['iso_quality_mixture_saving'])} |")
    lines+=['','μ=0 为主展示；all24 是不同延迟偏好的投影，不能声称同延迟公平比较。Oracle 行属于事后上界。', '', '固定 OOF 的 AIQ 增益 95% 区间：']
    for name,ci in s['aiq_gain_ci95_fixed_oof'].items():lines.append(f'- {name}: [{ci[0]:.6f}, {ci[1]:.6f}]')
    rep=s['repeat_diagnostic'];power=s['observed_effect_power_sensitivity']
    lines+=['','## 重复稳定性与样本量', '', f"单重复事后 Oracle 平均 {rep['same_draw_oracle_mean']:.6f}；两次重复选模型、第三次评分 {rep['select_on_two_evaluate_on_third']:.6f}；三重复均值上取最大 {s['oracle_three_repeat_mean']:.6f}。三次重复不足以提供认证去偏上界，不能套用其他论文的噪声百分比。",'',f"实际 ridge 配对差的 SD={power['paired_sd']:.6f}。固定当前效应和方差的正态近似，需要约 {power['approx_test_n_80pct_power_two_sided_5pct']} 个独立测试 query 才有 80% 功效；这不是所需训练集大小，也不证明扩大训练集无效。",'', '## 限制','']
    lines += ['- '+x for x in s['limitations']]
    lines += ['', 'AIQ 定义来源：[RouterBench §3](https://arxiv.org/html/2403.12031v2#S3)。其余文献核查与执行计划见 EXECUTION_PLAN.md。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')

def plot(s):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    lo,hi=s['cost_domain_usd_per_query'];xs=np.linspace(lo,hi,400)
    for name in ('zero_router','knn_utility_mu0','component_ridge_mu0','oracle_mu0'):
        h=np.array(s['curves'][name]['hull_cost_quality'])
        ax[0].plot(xs*1000,np.interp(xs,h[:,0],h[:,1]),label=name)
    ax[0].axhline(s['best_single_quality'],color='gray',ls=':',lw=1)
    ax[0].set(xlabel='Historical USD / 1,000 queries',ylabel='Mean quality',title='Exploratory quality-cost envelopes (mu=0)')
    ax[0].legend(fontsize=8)
    x=np.arange(len(EPS));ax[1].bar(x-.18,[s['margin_cdf'][str(e)] for e in EPS],.36,label='Top-two margin')
    ax[1].bar(x+.18,[s['all_models_close_cdf'][str(e)] for e in EPS],.36,label='Full-pool range')
    ax[1].set(xticks=x,xticklabels=[str(e) for e in EPS],xlabel='epsilon',ylabel='Fraction <= epsilon',ylim=(0,1),title='Top-two ties vs entire-pool similarity')
    ax[1].legend()
    fig.savefig(OUT/'DIAGNOSTICS.svg');fig.savefig(OUT/'DIAGNOSTICS.png',dpi=160)
    plt.close(fig)

if __name__=='__main__':main()
