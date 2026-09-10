"""Fixed-architecture pair-supervision audit: raw replay versus repeat soft replay.
No API calls and no validation/test labels; no tuning on outer-fold outcomes.
"""
import json
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from sklearn.linear_model import Ridge
from sklearn.decomposition import TruncatedSVD
from .anchored_ma import AnchoredMA, guarded
from .diagnose_rank_signal import load_inputs
from .train_repeat_pair_ma import load_repeats
from .data import sha
from .report_gap_recovery import gap_summary

ROOT=Path(__file__).resolve().parents[1]
ARMS=('raw_soft_all','raw_soft_panel_replay','repeat_soft_panel_replay')


def soft_loss(pred, margin):
    target=.5+.5*margin
    weights=.1+margin.abs()
    loss=F.binary_cross_entropy_with_logits(10*(pred[:,3]-pred[:,2]),target,reduction='none')
    return (loss*weights).sum()/weights.sum()


def train(zt,bt,ze,be,y,selected,repeat_margin,arm,seed):
    model=AnchoredMA(zt.shape[1],seed)
    opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
    tx,tb,ex,eb=[torch.tensor(v,dtype=torch.float32) for v in (zt,bt,ze,be)]
    margin=torch.tensor(y[:,3]-y[:,2],dtype=torch.float32)
    extra=torch.tensor(repeat_margin if arm=='repeat_soft_panel_replay' else (y[selected,3]-y[selected,2]),dtype=torch.float32)
    rng=np.random.default_rng(seed)
    for epoch in range(15):
        for idx in np.array_split(rng.permutation(len(y)),max(1,int(np.ceil(len(y)/128)))):
            p=model(tx[idx],tb[idx]);loss=soft_loss(p,margin[idx])+.1*(p-tb[idx]).square().mean()
            if arm!='raw_soft_all':
                q=model(tx[selected],tb[selected]);loss=loss+.5*soft_loss(q,extra)
            opt.zero_grad();loss.backward();opt.step()
    model.eval()
    with torch.no_grad():result=model(ex,eb).clamp(0,1).numpy()
    result[:,:2]=be[:,:2]
    return result


def main():
    torch.set_num_threads(4)
    source=ROOT/'router_v2/objective_verified_20260910';panel=ROOT/'router_v2/repeat_fold_panel_20260910'
    out=ROOT/'router_v2/soft_pair_replay_20260910';out.mkdir(exist_ok=False)
    f,x,ds=load_inputs(source);ids=f['ids'];y=f['quality'];folds=f['folds'];n=len(ids)
    pm=json.loads((panel/'MANIFEST.json').read_text())
    for k,h in pm['files'].items():
        if sha(panel/k)!=h:raise ValueError('Panel changed')
    repeats=load_repeats(ROOT/'data/repeat_fold_stability_20260910',pm)
    selection=json.loads((panel/'FOLD_SELECTION.json').read_text())
    gp=ROOT/'router_v2/contamination_audit_20260910b/PROMPT_GROUPS.json'
    if sha(gp)!=pm['groups_sha256']:raise ValueError('Groups changed')
    g=json.loads(gp.read_text());groups=np.array([g['groups'][q] for q in ids])
    protocol=dict(role='fixed_architecture_soft_pair_replay_development',arms=ARMS,seeds=[42,43,44],epochs=15,threshold=.05,
        architecture='Unchanged AnchoredMA, SVD64, correction cap .1',learning_rate=.001,weight_decay=.01,
        targets='p=0.5+0.5*(q_reasoning-q_large); BCE at logit 10*(pred_R-pred_L)',weights='.1+abs(empirical quality margin)',
        repeat_weight=.5,batch_size=128,selection='Fixed protocol before this run; no outer tuning',
        primary='repeat_soft_panel_replay versus raw_soft_panel_replay; identical rows, updates, architecture and seeds, only panel targets/weights differ',
        source_hashes={str(p):sha(p) for p in [source/'RESULTS.json',panel/'MANIFEST.json',ROOT/'data/repeat_fold_stability_20260910/LABEL_SUMMARY.json',gp,Path(__file__),Path(__file__).with_name('anchored_ma.py')]},
        limits=['Same architecture as experiment A but training schedule/objective differ; not single-factor comparison with old pair CE.',
                'Temperature .7 labels transferred to temperature 0 original-train OOF outcomes.',
                'No independent test or formal quality/cost claim.'])
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2)+'\n')
    choices={f'{a}_seed{s}':np.zeros(n,int) for a in ARMS for s in (42,43,44)}
    for fold in sorted(np.unique(folds)):
        tr=np.flatnonzero(folds!=fold);va=np.flatnonzero(folds==fold)
        sel=selection[str(fold)]
        if not set(sel)<=set(ids[tr]) or set(groups[tr])&set(groups[va]):raise ValueError('Fold leakage')
        selected=np.array([i for i,q in enumerate(ids[tr]) if q in sel],int)
        repeat_margin=np.array([repeats[ids[tr[i]]]['reasoning_quality_mean']-repeats[ids[tr[i]]]['large_quality_mean'] for i in selected])
        ridge=Ridge(alpha=20.).fit(x[tr],y[tr]);bt=ridge.predict(x[tr]).clip(0,1).astype('float32');be=ridge.predict(x[va]).clip(0,1).astype('float32')
        svd=TruncatedSVD(n_components=64,random_state=42).fit(x[tr]);zt=svd.transform(x[tr]);ze=svd.transform(x[va]);m=zt.mean(0);sc=np.maximum(zt.std(0),.01);zt=(zt-m)/sc;ze=(ze-m)/sc
        for seed in (42,43,44):
            for arm in ARMS:
                p=train(zt,bt,ze,be,y[tr],selected,repeat_margin,arm,seed)
                choices[f'{arm}_seed{seed}'][va]=guarded(p,f['DatasetBest'][va],.05)
            print('fold',int(fold),'seed',seed,'done',flush=True)
    for p,h in protocol['source_hashes'].items():
        if sha(p)!=h:raise ValueError('Inputs changed during run')
    index=np.arange(n);ref=y[index,f['DatasetBest']];opp=y.max(1)-ref
    result={}
    for arm in ARMS:
        actual=np.array([y[index,choices[f'{arm}_seed{s}']] for s in (42,43,44)])
        result[arm]=dict(quality=float(actual.mean()),**gap_summary(actual-ref,opp,groups))
    np.savez_compressed(out/'CHOICES.npz',ids=ids,**choices)
    report=dict(n=n,methods=result,files={p:sha(out/p) for p in ['PROTOCOL.json','CHOICES.npz']})
    (out/'RESULTS.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
