"""Development-only utility experiment; does not alter frozen C8 or R3."""
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.neighbors import KNeighborsRegressor

ROOT = Path('/root')
OUT = Path(__file__).resolve().parent
SEED = 20260831

def read(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def main():
    paths = [ROOT/'phase_c8/C8_PERFORMANCE_MATRIX.jsonl', ROOT/'target_support_expansion_v1/combined_509_tasks_frozen.jsonl']
    rows = read(paths[0])
    tasks = {r['id']: r for r in read(paths[1])}
    models = json.loads((ROOT/'phase_c8/C8_PROTOCOL.json').read_text())['models']
    ids = sorted({r['task_id'] for r in rows})
    lookup = {(r['task_id'], r['model']): r for r in rows}
    assert len(ids) == 419 and len(lookup) == len(rows) == len(ids)*len(models)
    y = np.array([[[lookup[i,m][k] for k in ('quality_mean','cost_mean_usd','latency_mean_ms')] for m in models] for i in ids])
    assert np.isfinite(y).all() and (y >= 0).all()
    texts = []
    for i in ids:
        t = tasks[i]
        table = '\n'.join(' | '.join(map(str,r)) for r in (t.get('table') or []) if isinstance(r,list))
        texts.append(f"[QUESTION] {t.get('question') or ''}\n[CONTEXT] {t.get('context') or ''}\n[TABLE] {table}")
    assert len(set(texts)) == len(texts), 'Duplicate prompts require grouped folds'
    grid = [(l,m) for l in (0,.1,.5,1,2,5) for m in (0,.1,.5,1)]
    protocol = dict(role='exploratory development only; no parameter selection or holdout claims', seed=SEED,
        folds=5, tasks=len(ids), models=models, grid=grid, knn_k=20, ridge_alpha=20,
        features='fold-local word/char TF-IDF; request text only',
        normalization='train-fold median positive cost and latency; no test outcome normalization',
        selection='predict Q,C,L then maximize Q-lambda*C/scale_C-mu*L/scale_L',
        inference_forbidden=['answers','difficulty derived from outcomes','test costs','test latency','test quality'],
        input_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (OUT/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2))
    choices = {name:np.zeros((len(grid),len(ids)),dtype=int) for name in ('best_single','knn_utility','component_ridge','oracle')}
    utilities = np.zeros((len(grid),len(ids),len(models)))
    for tr,te in KFold(5,shuffle=True,random_state=SEED).split(ids):
        vectors = [TfidfVectorizer(ngram_range=(1,2),min_df=3,max_features=12000,sublinear_tf=True),
                   TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),min_df=3,max_features=8000,sublinear_tf=True)]
        xtr = hstack([v.fit_transform([texts[i] for i in tr]) for v in vectors],format='csr')
        xte = hstack([v.transform([texts[i] for i in te]) for v in vectors],format='csr')
        scales = np.ones(3)
        for k in (1,2):
            positive = y[tr,:,k][y[tr,:,k]>0]
            scales[k] = np.median(positive) if positive.size else 1
        target = y[tr]/scales
        fits = {'knn_utility':KNeighborsRegressor(n_neighbors=20,metric='cosine',algorithm='brute'),
                'component_ridge':Ridge(alpha=20)}
        predictions = {}
        for name,fit in fits.items():
            pred = fit.fit(xtr,target.reshape(len(tr),-1)).predict(xte).reshape(len(te),len(models),3)
            pred[:,:,0] = pred[:,:,0].clip(0,1)
            pred[:,:,1:] = pred[:,:,1:].clip(0)
            predictions[name] = pred
        for g,(lam,mu) in enumerate(grid):
            weights=np.array([1,-lam,-mu])
            true = (y[te]/scales)@weights
            utilities[g,te] = true
            choices['oracle'][g,te] = true.argmax(axis=1)
            choices['best_single'][g,te] = (target@weights).mean(axis=0).argmax()
            for name,pred in predictions.items():
                choices[name][g,te] = (pred@weights).argmax(axis=1)
    rng=np.random.default_rng(SEED)
    boot=rng.integers(len(ids),size=(5000,len(ids)))
    results=[]
    index=np.arange(len(ids))
    for g,(lam,mu) in enumerate(grid):
        u=utilities[g]
        base=u[index,choices['best_single'][g]]
        for name in (*choices,'random_expected'):
            if name=='random_expected':
                actual=y.mean(axis=1); value=u.mean(axis=1)
            else:
                picks=choices[name][g]; actual=y[index,picks]; value=u[index,picks]
            delta=value-base
            ci=np.quantile(delta[boot].mean(axis=1),[.025,.975])
            results.append(dict(method=name,lam=lam,mu=mu,quality=float(actual[:,0].mean()),cost_usd=float(actual[:,1].mean()),latency_ms=float(actual[:,2].mean()),utility=float(value.mean()),gain=float(delta.mean()),gain_ci95=ci.tolist()))
    (OUT/'RESULTS.json').write_text(json.dumps(results,indent=2))
    np.savez_compressed(OUT/'OOF.npz',ids=np.array(ids),outcomes=y,utilities=utilities,**choices)
    lines=['# Utility 建议补充实验','', '仅开发集探索；没有重调 C8 参数或使用未触碰测试集。置信区间为固定 OOF 预测下的任务 bootstrap，未计入重训方差；24 个权重组合未作多重比较校正。', '', '## 质量优先（λ=μ=0）','', '| 方法 | Quality | 相对 Best Single 效用差 | 95% CI |','|---|---:|---:|---|']
    for r in results:
        if r['lam']==r['mu']==0:
            lines.append(f"| {r['method']} | {r['quality']:.6f} | {r['gain']:+.6f} | {r['gain_ci95']} |")
    lines += ['', '全部权重结果见 RESULTS.json；不据此挑选最优权重。成本/延迟来自历史观测，跨部署比较仅作探索。', '', 'Oracle 使用事后结果，仅为上界；其他策略选择仅依赖训练折与请求文本。kNN 分项均值后线性组合等价于邻居 utility 均值。固定多输出模型不能自然支持未见模型，扩池后需要重新训练或另做模型条件化验证。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))

if __name__=='__main__':
    main()
