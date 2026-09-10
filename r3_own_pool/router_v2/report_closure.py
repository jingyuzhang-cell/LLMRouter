"""Produce an evidence-backed closure report and scientific figures from completed runs."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .data import sha

ROOT=Path(__file__).resolve().parent


def main():
    mech=ROOT/'mechanism_20260909';early=ROOT/'earlystop_20260909';validation=ROOT/'development_replication_20260909'
    m=json.loads((mech/'RESULTS.json').read_text());e=json.loads((early/'RESULTS.json').read_text());v=json.loads((validation/'RESULTS.json').read_text())
    traces=json.loads((mech/'TRACES.json').read_text())
    selection=json.loads((early/'SELECTION.json').read_text())
    out=ROOT/'closure_20260909';out.mkdir(exist_ok=False)
    manifest=dict(inputs={str(p):sha(p) for p in [mech/'RESULTS.json',mech/'TRACES.json',early/'RESULTS.json',early/'SELECTION.json',validation/'RESULTS.json',validation/'FROZEN.json']},
                  role='closed_development_diagnosis_not_confirmed_paper_superiority',test_labels_loaded=False,
                  independent_confirmation_completed=False,monetary_cost_verified=False)
    means={};variability={}
    for kind in ['original','normalized_model','four_head']:
        values=[m['methods'][f'{kind}_seed{s}']['quality'] for s in [42,43,44]]
        means[kind]=float(np.mean(values));variability[kind]=float(np.std(values,ddof=1))
    values=[e['methods'][str(s)]['quality'] for s in [42,43,44]]
    means['earlystop']=float(np.mean(values));variability['earlystop']=float(np.std(values,ddof=1))
    valmeans={};cleanmeans={}
    for kind in means:
        valmeans[kind]=float(np.mean([v['scopes']['all']['methods'][f'{kind}_seed{s}']['quality'] for s in [42,43,44]]))
        cleanmeans[kind]=float(np.mean([v['scopes']['without_known_pilot']['methods'][f'{kind}_seed{s}']['quality'] for s in [42,43,44]]))
    curve={}
    for kind in ['original','normalized_model','four_head']:
        ts=[t for t in traces if t['kind']==kind]
        curve[kind]={metric:np.mean([[h[metric] for h in t['history']] for t in ts],axis=0) for metric in ['train_mse','held_mse','train_routed_quality','held_routed_quality']}
    labels={'original':'Original (60 epochs)','normalized_model':'Normalized model embedding','four_head':'Four-head network','earlystop':'Nested early stopping'}
    epochs=[h['epoch'] for h in traces[0]['history']]
    fig,axes=plt.subplots(1,3,figsize=(15,4.5),layout='constrained')
    for kind,color in zip(curve,['#3465a4','#dc7633','#39935f']):
        axes[0].plot(epochs,curve[kind]['train_mse'],color=color,linestyle='--',label=labels[kind]+' train')
        axes[0].plot(epochs,curve[kind]['held_mse'],color=color,label=labels[kind]+' OOF')
    axes[0].set(xlabel='Epoch',ylabel='Mean squared error',title='Training and held-fold error')
    axes[0].legend(fontsize=6)
    names=list(means);pos=np.arange(len(names));w=.36
    axes[1].bar(pos-w/2,[100*means[k] for k in names],w,label='Training OOF')
    axes[1].bar(pos+w/2,[100*valmeans[k] for k in names],w,label='Original validation')
    axes[1].axhline(100*v['scopes']['all']['methods']['DatasetBest']['quality'],color='black',linestyle=':',label='Validation dataset baseline')
    axes[1].set_xticks(pos,['Original','Normalized','Four-head','Early stop'],rotation=25)
    axes[1].set(ylabel='Quality (%)',title='Mean of three seeds');axes[1].legend(fontsize=7)
    chosen=[r['selected_epochs'] for r in selection]
    unique,count=np.unique(chosen,return_counts=True)
    axes[2].bar(unique,count,width=2)
    axes[2].set(xlabel='Selected epoch (inner validation only)',ylabel='Outer fits',title='Nested stopping selection')
    for ax in axes:ax.spines[['top','right']].set_visible(False)
    fig.savefig(out/'CLOSURE.png',dpi=180);fig.savefig(out/'CLOSURE.pdf');plt.close(fig)
    lines=['# 实验闭环：失败诊断、干预与开发复核','',
      '已完成一轮真实的机制与开发复核闭环。此结论不等于独立确认了论文方法优越性；原test未打开，完整多目标论文证据仍未齐备。','',
      '## 固定实验链条','',
      '1. 2975道原训练集客观评分题三折诊断：Ridge与DatasetBest同为84.74%，未见逐题建模超越数据集选择。',
      '2. 三seed回归/排序消融：纯回归80.15%，加排序79.59%，不支持当前排序配置收益。',
      '3. 三seed×三折机制对照：原结构、仅归一化模型表示、四输出结构，均60轮，记录训练及留出曲线。',
      '4. 嵌套早停：只在外折训练部分内部选择轮数，再用完整外折训练部分重训。',
      '5. 原验证集开发复核：预定全部方法和三个seed拟合并共同封存后才读取638道客观题标签；其中49题有已知pilot暴露。另报589题排除已知暴露的敏感性切片，不自动认证干净holdout。','',
      '## 方法对照','',
      '| 方法 | 训练OOF均值 | 跨seed SD（pp） | 原验证集均值 | 排除已知pilot后均值 |','|---|---:|---:|---:|---:|']
    for kind in means:
        lines.append(f'| {labels[kind]} | {100*means[kind]:.2f}% | {100*variability[kind]:.2f} | {100*valmeans[kind]:.2f}% | {100*cleanmeans[kind]:.2f}% |')
    for name in ['Ridge','DatasetBest','BestSingle']:
        vv=v['scopes']['all']['methods'][name]['quality'];cc=v['scopes']['without_known_pilot']['methods'][name]['quality']
        lines.append(f'| {name} | 见原诊断 | — | {100*vv:.2f}% | {100*cc:.2f}% |')
    lines+=['','## 早停相对固定60轮：验证集主比较','','| Seed | 质量差（pp） | 95%配对区间（pp） |','|---|---:|---:|']
    for seed,d in v['scopes']['all']['earlystop_minus_original'].items():
        lo,hi=d['ci95'];lines.append(f'| {seed} | {100*d["gain"]:+.2f} | [{100*lo:+.2f}, {100*hi:+.2f}] |')
    lines+=['','## 训练曲线证据','', '| 结构 | 第1轮train MSE | 第60轮train MSE | 第1轮OOF MSE | 第60轮OOF MSE |','|---|---:|---:|---:|---:|']
    for kind,c in curve.items():
        lines.append(f'| {kind} | {c["train_mse"][0]:.4f} | {c["train_mse"][-1]:.4f} | {c["held_mse"][0]:.4f} | {c["held_mse"][-1]:.4f} |')
    lines+=['', '内层选出的轮数：'+str(chosen)+'.', '',
      '尺度对照保持同参数量；四输出对照改变参数量，因此不能把全部差异归因于表示方式。早停增加内层拟合计算，不能宣称同计算预算更优。曲线只作机制诊断，未用外折曲线挑部署checkpoint。', '',
      '## 统计与论文结论边界','',
      '所有seed均保留。跨seed标准差不是置信区间，三seed并未扩大独立query数量。逐seed配对区间条件于拟合模型，不覆盖重训不确定性；多种次要对照为探索性，不据其挑选显著点。', '',
      '原验证集用于开发复核而非未触碰独立确认；已知pilot切片排除由元数据事先决定，不能证明没有其他历史暴露。客观评分也保留其自动评测和解析局限。', '',
      '成本表中本地模型仍为价格代理；失败生成缺失计时不能通过填0认证真实延迟。故本轮不输出美元节省、延迟收益或多目标最优结论。', '',
      '论文可引用本轮作为机制分析和消融证据，不能据此宣布所提方法优于强基线或完整论文闭环已完成。完整主张还需要独立确认、开放题评分可靠性以及可信资源测量。', '',
      '图：CLOSURE.png和可导出的CLOSURE.pdf；原始结果与hash索引见MANIFEST.json。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    manifest['summary']=dict(oof=means,validation=valmeans,validation_without_known_pilot=cleanmeans)
    (out/'MANIFEST.json').write_text(json.dumps(manifest,indent=2))
    print('\n'.join(lines))

if __name__=='__main__':main()
