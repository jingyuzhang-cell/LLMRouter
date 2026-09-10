"""Small Ridge-anchored model-conditioned correction, nested group-safe development."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
import torch
from torch import nn
from sklearn.decomposition import TruncatedSVD
from sklearn.linear_model import Ridge
from sklearn.model_selection import StratifiedGroupKFold
from .data import sha
from .core import paired_ci
from .diagnose_rank_signal import load_inputs

EPOCHS=(0,5,15,30)
THRESHOLDS=(0.,.02,.05,.1,2.)


class AnchoredMA(nn.Module):
    def __init__(self, dim, seed):
        super().__init__();torch.manual_seed(seed)
        self.query=nn.Sequential(nn.Linear(dim+4,32),nn.ReLU(),nn.Linear(32,16))
        self.model=nn.Parameter(torch.randn(4,16)*.25)
        nn.init.zeros_(self.query[-1].weight);nn.init.zeros_(self.query[-1].bias)
    def forward(self,x,base):
        correction=self.query(torch.cat([x,base],dim=1))@self.model.T
        return base+.1*torch.tanh(correction)


def trajectory(xt,yt,xe,seed):
    ridge=Ridge(alpha=20.).fit(xt,yt)
    bt=ridge.predict(xt).clip(0,1).astype('float32')
    be=ridge.predict(xe).clip(0,1).astype('float32')
    dim=min(64,len(xt)-1,xt.shape[1]-1)
    svd=TruncatedSVD(n_components=dim,random_state=42).fit(xt)
    zt=svd.transform(xt);ze=svd.transform(xe)
    scale=np.maximum(zt.std(0),.01);mean=zt.mean(0)
    zt=torch.tensor((zt-mean)/scale,dtype=torch.float32)
    ze=torch.tensor((ze-mean)/scale,dtype=torch.float32)
    bt=torch.tensor(bt);be=torch.tensor(be);target=torch.tensor(yt,dtype=torch.float32)
    model=AnchoredMA(dim,seed)
    opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
    rng=np.random.default_rng(seed);saved={0:be.numpy()};trace=[]
    for epoch in range(1,max(EPOCHS)+1):
        order=rng.permutation(len(xt));model.train()
        for start in range(0,len(xt),128):
            idx=order[start:start+128];p=model(zt[idx],bt[idx]);truth=target[idx]
            # Query-centered errors emphasize relative model compatibility; ties also constrain drift.
            error=p-truth
            loss=error.square().mean()+.5*(error-error.mean(1,keepdim=True)).square().mean()
            loss=loss+.1*(p-bt[idx]).square().mean()
            opt.zero_grad();loss.backward();opt.step()
        if epoch in EPOCHS:
            model.eval()
            with torch.no_grad():
                saved[epoch]=model(ze,be).clamp(0,1).numpy()
                pred=model(zt,bt).clamp(0,1).numpy()
            trace.append(dict(epoch=epoch,train_mse=float(np.mean((pred-yt)**2)),
                train_quality=float(yt[np.arange(len(yt)),pred.argmax(1)].mean())))
    return saved,dict(parameters=sum(p.numel() for p in model.parameters()),trace=trace)


def guarded(pred,fallback,threshold):
    best=pred.argmax(1)
    advantage=pred[np.arange(len(pred)),best]-pred[np.arange(len(pred)),fallback]
    return np.where(advantage>threshold,best,fallback)


def select(candidates, neural):
    allowed=candidates if neural else [r for r in candidates if r['epoch']==0]
    return max(allowed,key=lambda r:(r['quality'],-r['epoch'],r['threshold']))


def fit_outer(x,y,datasets,groups,tr,va,seed):
    inner_predictions={e:np.empty((len(tr),4)) for e in EPOCHS}
    inner_fallback=np.empty(len(tr),dtype=int);splits=[]
    for a,b in StratifiedGroupKFold(3,shuffle=True,random_state=seed).split(x[tr],datasets[tr],groups[tr]):
        if set(groups[tr[a]])&set(groups[tr[b]]):raise ValueError('Inner group overlap')
        pred,_=trajectory(x[tr[a]],y[tr[a]],x[tr[b]],seed)
        for e,p in pred.items():inner_predictions[e][b]=p
        inner_fallback[b]=y[tr[a]].mean(0).argmax()
        splits.append(dict(train_ids=tr[a].tolist(),validation_ids=tr[b].tolist()))
    candidates=[]
    for epoch,pred in inner_predictions.items():
        for threshold in THRESHOLDS:
            c=guarded(pred,inner_fallback,threshold)
            candidates.append(dict(epoch=epoch,threshold=threshold,quality=float(y[tr,c].mean())))
    configurations={key:select(candidates,neural) for key,neural in [('RidgeGuard',False),('AnchoredMA',True)]}
    # Refit on outer training; outer labels are never passed into model or selection.
    pred,trace=trajectory(x[tr],y[tr],x[va],seed)
    fallback=np.full(len(va),y[tr].mean(0).argmax())
    choices={key:guarded(pred[c['epoch']],fallback,c['threshold']) for key,c in configurations.items()}
    choices['AnchoredMA_fixed30']=pred[30].argmax(1)
    return choices,dict(configurations=configurations,candidates=candidates,inner_splits=splits,**trace)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',required=True);ap.add_argument('--groups',required=True);ap.add_argument('--output',required=True)
    a=ap.parse_args();torch.set_num_threads(4)
    source=Path(a.source).resolve();out=Path(a.output).resolve()
    frozen,x,datasets=load_inputs(source);y=frozen['quality'];folds=frozen['folds'];ids=frozen['ids']
    grouping=json.loads(Path(a.groups).read_text())
    protocol_source=json.loads((source/'PROTOCOL.json').read_text())
    query_path=next(p for p in protocol_source['input_sha256'] if Path(p).name=='queries.jsonl')
    if grouping['queries_sha256']!=sha(query_path):raise ValueError('Grouping query hash mismatch')
    groups=np.array([grouping['groups'][q] for q in ids])
    out.mkdir(parents=True,exist_ok=False)
    code=[Path(__file__),Path(__file__).with_name('diagnose_rank_signal.py'),Path(__file__).with_name('integrity.py'),Path(__file__).with_name('core.py')]
    protocol=dict(role='exploratory_clean_train_nested_group_anchored_ma',seeds=[42,43,44],epochs=EPOCHS,thresholds=THRESHOLDS,
        source_files={name:sha(source/name) for name in ['PROTOCOL.json','RESULTS.json','OOF.npz']},groups_sha256=sha(a.groups),
        code_sha256={str(p):sha(p) for p in code},ridge_alpha=20.,svd_dimensions=64,correction_cap=.1,
        weight_decay=.01,learning_rate=.001,loss='MSE + .5 query-centered MSE + .1 correction L2',
        selection='Inner group OOF routed quality; ties earlier epoch then larger threshold; epoch0 is Ridge, threshold2 is train BestSingle',
        primary='AnchoredMA versus RidgeGuard; both also compared with frozen Ridge and DatasetBest',
        limits=['Adaptive original-train development; no independent confirmation',
                'Dataset identity only for split stratification and diagnostic baseline, not predictor inputs',
                'Only query features, training labels, and training cost-free quality predictions',
                'Epoch0/base predictions on fitting rows are in-sample Ridge; inner/outer evaluation remain held out',
                'Conditional paired intervals do not include retraining uncertainty; all seeds reported'])
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2)+'\n')
    choices={};selections=[];n=len(y);index=np.arange(n)
    for seed in protocol['seeds']:
        for key in ['RidgeGuard','AnchoredMA','AnchoredMA_fixed30']:choices[f'{key}_seed{seed}']=np.zeros(n,dtype=int)
        for fold in np.unique(folds):
            tr=np.flatnonzero(folds!=fold);va=np.flatnonzero(folds==fold)
            if set(groups[tr])&set(groups[va]):raise ValueError('Outer group overlap')
            start=time.monotonic();result,detail=fit_outer(x,y,datasets,groups,tr,va,seed)
            for key,c in result.items():choices[f'{key}_seed{seed}'][va]=c
            selections.append(dict(seed=seed,fold=int(fold),**detail))
            print(f'seed={seed} fold={fold} chosen={detail["configurations"]} seconds={time.monotonic()-start:.1f}',flush=True)
    for p,h in protocol['code_sha256'].items():
        if sha(p)!=h:raise ValueError('Code changed during run')
    np.savez_compressed(out/'CHOICES.npz',ids=ids,**choices)
    (out/'SELECTION.json').write_text(json.dumps(selections,indent=2)+'\n')
    baseline={k:y[index,frozen[k]] for k in ['Ridge','BestSingle','DatasetBest']};reports={}
    for key,c in choices.items():
        actual=y[index,c];ref=baseline['DatasetBest'];d=actual-ref
        reports[key]=dict(quality=float(actual.mean()),vs_dataset_best=float(d.mean()),ci95=paired_ci(d),
            wins=int((d>0).sum()),losses=int((d<0).sum()),switches=int((c!=frozen['DatasetBest']).sum()),
            by_dataset={ds:float(actual[datasets==ds].mean()) for ds in sorted(set(datasets))})
    ablation={}
    for seed in protocol['seeds']:
        diff=y[index,choices[f'AnchoredMA_seed{seed}']]-y[index,choices[f'RidgeGuard_seed{seed}']]
        ablation[str(seed)]=dict(gain=float(diff.mean()),ci95=paired_ci(diff))
    result=dict(role=protocol['role'],n=n,methods=reports,baselines={k:float(v.mean()) for k,v in baseline.items()},ma_minus_guard=ablation,
        validation_labels_loaded=False,test_labels_loaded=False,files={name:sha(out/name) for name in ['PROTOCOL.json','SELECTION.json','CHOICES.npz']})
    (out/'RESULTS.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# Ridge锚定的小型MA实验','', '原训练集2975题，内外层均隔离相似题组；三个seed；不是独立测试。','',
           '| 方法 | 质量 | 相对DatasetBest | 救回/损失题数 |','|---|---:|---:|---:|']
    for key,r in reports.items():lines.append(f"| {key} | {100*r['quality']:.3f}% | {100*r['vs_dataset_best']:+.3f} pp | {r['wins']}/{r['losses']} |")
    lines+=['','MA增量消融（AnchoredMA−RidgeGuard）：',json.dumps(ablation,ensure_ascii=False,indent=2),
        '', 'epoch0被选中意味着该折采用Ridge，不能记作MA表示学习的胜利。所有阈值与轮数仅在内层选定；没有在外层挑最高分seed。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(result['methods'],indent=2),flush=True)

if __name__=='__main__':main()
