"""Fixed-alpha query-disjoint, repeat-held-out development diagnostic."""
import itertools
import json
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge
from .data import sha
from .diagnose_rank_signal import load_inputs

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'router_v2/e3_repeat_generalization_20260914'
SRC = ROOT/'router_v2/experiment_repeat_compatibility_400_fold_local'
PANEL = ROOT/'router_v2/mmlu_utility_panel_400'
LABEL = ROOT/'data/repeat_compatibility_400_rescore_v1/EXPECTED_UTILITY_LABELS.jsonl'
SLOTS = ['medium', 'large', 'coder', 'reasoning']

def main():
    OUT.mkdir(exist_ok=False)
    paths = [LABEL, SRC/'PREDICTIONS.npz', SRC/'FOLDS.json', PANEL/'MANIFEST.json', Path(__file__)]
    protocol = dict(role='exploratory; existing opportunity-enriched development panel', alpha=1.0,
        selection='No tuning; all subsets of 1,2,3,4 training repeats; evaluate complementary repeats',
        primary='four-repeat Ridge minus fold-development-selected BestSingle',
        oracle='same-query repeat-assisted diagnostic, unavailable to query-only deployment; not a proven upper bound',
        bootstrap='10000 paired prompt-group resamples, seed 20260914; conditional on fitted predictions',
        limits=['No independent confirmation', 'Repeat positions need not be temporally exchangeable',
                'Pointwise intervals; no simultaneous inference or retraining uncertainty',
                'Cross-repeat/hindsight ratio is not an identified noise fraction'],
        hashes={str(p):sha(p) for p in paths})
    (OUT/'PROTOCOL.json').write_text(json.dumps(protocol, indent=2)+'\n')
    manifest=json.loads((PANEL/'MANIFEST.json').read_text())
    assert sha(manifest['groups']) == manifest['groups_sha256']
    for name,h in manifest['source_files'].items(): assert sha(Path(manifest['source'])/name)==h
    status=json.loads((LABEL.parent/'STATUS.json').read_text()); assert sha(LABEL)==status['labels_sha256']
    z=np.load(SRC/'PREDICTIONS.npz',allow_pickle=False); ids=z['ids'].tolist(); n=len(ids)
    labels={r['query_id']:r for r in map(json.loads,LABEL.open())}
    v=np.array([[labels[q]['models'][m]['values'] for m in SLOTS] for q in ids])
    assert v.shape==(400,4,5) and np.isin(v,[0,1]).all()
    assert np.allclose(v.mean(2),z['quality']) and len(set(ids))==n
    features,xa,_=load_inputs(manifest['source']); index={q:i for i,q in enumerate(features['ids'])}
    x=xa[[index[q] for q in ids]]; ix={q:i for i,q in enumerate(ids)}
    groups=json.loads(Path(manifest['groups']).read_text())['groups']; g=np.array([groups[q] for q in ids])
    folds=json.loads((SRC/'FOLDS.json').read_text()); fold_indices=[]; coverage=np.zeros(n,int)
    for f in folds:
        d=np.array([ix[q] for q in f['development_ids']]); t=np.array([ix[q] for q in f['test_ids']])
        assert not set(g[d])&set(g[t]); assert not set(d)&set(t)
        assert np.all(z['folds'][t]==f['fold']); coverage[t]+=1; fold_indices.append((d,t))
    assert np.all(coverage==1)
    # Reproduce existing baseline before running the new configurations.
    reproduced=np.zeros(n,int)
    for d,t in fold_indices: reproduced[t]=Ridge(alpha=1.).fit(x[d],v[d].mean(2)).predict(x[t]).argmax(1)
    assert np.array_equal(reproduced,z['choice_QueryOnlyRidge'])
    ug,inv=np.unique(g,return_inverse=True); counts=np.bincount(inv)
    boot=np.random.default_rng(20260914).integers(0,len(ug),(10000,len(ug)))
    def ci(diff):
        sums=np.bincount(inv,weights=diff)
        return (100*np.percentile(sums[boot].sum(1)/counts[boot].sum(1),[2.5,97.5])).tolist()
    results={}; arrays={}; detail=[]
    for k in range(1,5):
        rows={m:[] for m in ['BestSingle','Ridge','RepeatAssistedPreferred','RepeatAssistedFractional']}
        for train_r in itertools.combinations(range(5),k):
            held=[r for r in range(5) if r not in train_r]
            train_y=v[:,:,train_r].mean(2); test_y=v[:,:,held].mean(2)
            scores={m:np.zeros(n) for m in rows}
            for d,t in fold_indices:
                best=int(train_y[d].mean(0).argmax())
                pick=Ridge(alpha=1.).fit(x[d],train_y[d]).predict(x[t]).argmax(1)
                scores['BestSingle'][t]=test_y[t,best]; scores['Ridge'][t]=test_y[t,pick]
                candidates=train_y[t]==train_y[t].max(1,keepdims=True)
                preferred=candidates.argmax(1); preferred[candidates[:,best]]=best
                scores['RepeatAssistedPreferred'][t]=test_y[t,preferred]
                scores['RepeatAssistedFractional'][t]=(test_y[t]*candidates).sum(1)/candidates.sum(1)
            for m in rows: rows[m].append(scores[m])
            detail.append(dict(k=k,train_repeats=train_r,held_repeats=held,eq={m:float(a.mean()) for m,a in scores.items()}))
        avg={m:np.mean(a,axis=0) for m,a in rows.items()}; base=avg['BestSingle']
        results[str(k)]={m:dict(eq=float(a.mean()),gain_pp=float(100*(a-base).mean()),ci95_pp=ci(a-base)) for m,a in avg.items()}
        arrays.update({f'k{k}_{m}':a for m,a in avg.items()})
        print(k, json.dumps(results[str(k)]),flush=True)
    # All 24 fixed tie priorities, reported in full rather than choosing a winner.
    tie=[]; y=v.mean(2)
    for order in itertools.permutations(range(4)):
        scores=[]
        for r in range(5):
            tr=v[:,:,[j for j in range(5) if j!=r]].mean(2)
            pick=np.array(order)[tr[:,order].argmax(1)]
            scores.append(v[np.arange(n),pick,r])
        a=np.mean(scores,axis=0)
        tie.append(dict(priority=[SLOTS[j] for j in order],eq=float(a.mean()),gain_ci95_pp=ci(a-y[:,3])))
    np.savez_compressed(OUT/'PER_QUERY.npz',ids=np.array(ids),groups=g,**arrays)
    result=dict(n=n,groups=len(ug),baseline_reproduction=True,learning_curve=results,tie_priorities=tie)
    (OUT/'RESULTS.json').write_text(json.dumps(result,indent=2)+'\n')
    (OUT/'SUBSETS.json').write_text(json.dumps(detail,indent=2)+'\n')
    lines=['# E3：跨题目、跨重复泛化实验','',
        '固定 GTE + Ridge(alpha=1)，沿用冻结 development allowlist，遍历全部重复子集；只在其余重复评分。已精确复现旧 Ridge 决策。',
        '', '| 监督重复数 | 方法 | 质量 | 相对 BestSingle 增益(pp) | 95%配对组bootstrap区间(pp) |','|---|---|---:|---:|---|']
    for k,methods in results.items():
        for m,a in methods.items(): lines.append(f'| {k} | {m} | {a["eq"]:.2%} | {a["gain_pp"]:+.2f} | [{a["ci95_pp"][0]:.2f}, {a["ci95_pp"][1]:.2f}] |')
    lines+=['',f'24种固定并列优先序的四重复辅助选择质量范围：{min(t["eq"] for t in tie):.2%}–{max(t["eq"] for t in tie):.2%}。全部结果保存在 RESULTS.json，未按效果选规则。',
        '', '重复辅助选择使用同题其他回答的正确性，仅用于诊断；普通请求路由拿不到这些标签。它不是已证明的理论上界。旧 E2 的41%不能解释为已识别的生成噪声比例，339题选择一致也不等同于339题存在严格稳定赢家。',
        '', '该400题面板经过机会富集且已用于开发，所有结果为探索性。重复不增加独立题目数；区间按相似题组配对抽样，条件于已训练预测，不覆盖重训不确定性；未校正多重比较。',
        '', '下一步决策：若四重复 Ridge 区间仍跨0，不扩大 MA 或声称稳定收益。优先在开发折内测试更细的题干/选项表示，固定方案后用新代表性题目确认；新增100题的负确认结果仍然有效。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')
    (OUT/'VALIDATION.json').write_text(json.dumps(dict(input_hashes_verified=True,fold_group_disjoint=True,coverage_once=True,binary_complete_400_4_5=True,baseline_choices_exact=True,all_repeat_subsets=30),indent=2)+'\n')

if __name__=='__main__': main()
