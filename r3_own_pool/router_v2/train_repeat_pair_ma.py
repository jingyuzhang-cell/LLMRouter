"""Fold-isolated MA label ablation; fail closed when repeat supervision is missing.

All results are original-train OOF development, never independent confirmation.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from sklearn.linear_model import Ridge
from sklearn.decomposition import TruncatedSVD
from .anchored_ma import AnchoredMA, guarded
from .core import paired_ci
from .data import sha
from .diagnose_rank_signal import load_inputs

SEEDS = (42,43,44)
EPOCHS = 15
THRESHOLD = .05
ARMS = ('old_winner_all', 'old_pair_panel', 'repeat_mean_panel', 'stable_pair', 'old_pair_stable_matched')


def load_repeats(path, manifest):
    path = Path(path); summary = json.loads((path/'LABEL_SUMMARY.json').read_text())
    if summary['panel_sha256'] != manifest['files']['PANEL.jsonl']:
        raise ValueError('Repeat panel mismatch')
    if summary['n_complete'] != manifest['n_panel'] or summary['n_incomplete']:
        raise ValueError('Repeat labels incomplete; no stable-pair training')
    for key in ('temperature','top_p','repeats','stable_threshold'):
        if summary[key] != manifest[key]: raise ValueError('Repeat protocol mismatch: '+key)
    for section in ('files','source_files'):
        for name,digest in summary[section].items():
            if sha(path/name) != digest: raise ValueError('Repeat artifact changed')
    if set(summary['source_files']) != {'large.jsonl','reasoning.jsonl'}:
        raise ValueError('Both models require verified raw repeat responses')
    rows = [json.loads(l) for l in (path/'STABLE_LABELS.jsonl').read_text().splitlines()]
    by = {r['query_id']:r for r in rows}
    if len(by) != len(rows): raise ValueError('Duplicate repeat query')
    for r in rows:
        if r['cross_products_are_independent'] is not False or r['independent_generations_per_slot'] != manifest['repeats']:
            raise ValueError('Invalid repeat sample-count interpretation')
        for key in ('large_quality_mean','reasoning_quality_mean'):
            if not np.isfinite(r[key]) or not 0 <= r[key] <= 1: raise ValueError('Invalid mean quality')
    return by


def training_rows(ids, y, selected, repeats, arm):
    if arm == 'old_winner_all': return np.arange(len(ids)), y, 'winner'
    chosen = [i for i,q in enumerate(ids) if q in selected]
    if arm in ('stable_pair','old_pair_stable_matched'):
        chosen = [i for i in chosen if repeats[ids[i]]['stable_label'] in ('large>reasoning','reasoning>large')]
    idx = np.array(chosen, dtype=int)
    if arm in ('old_pair_panel','old_pair_stable_matched'):
        return idx, y[idx,2:4], 'pair'
    target = np.array([[repeats[ids[i]]['large_quality_mean'],repeats[ids[i]]['reasoning_quality_mean']] for i in idx], dtype=np.float32).reshape(-1,2)
    return idx, target, 'mean' if arm == 'repeat_mean_panel' else 'pair'


def fit_arm(zt, bt, ze, be, ids, y, selected, repeats, arm, seed):
    idx, labels, kind = training_rows(ids,y,selected,repeats,arm)
    detail = {'n_supervised':len(idx),'objective':kind}
    if kind == 'pair':
        classes = np.bincount(labels.argmax(1),minlength=2) if len(labels) else np.zeros(2,dtype=int)
        detail['class_counts'] = classes.tolist()
        if min(classes) < 5:
            detail['fallback'] = 'Fewer than five training examples in either pair direction'
            return be.copy(), detail
    if not len(idx):
        detail['fallback'] = 'No supervision';return be.copy(),detail
    model = AnchoredMA(zt.shape[1],seed)
    opt = torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
    tx,tb,ex,eb = [torch.tensor(a,dtype=torch.float32) for a in (zt,bt,ze,be)]
    target = torch.tensor(labels,dtype=torch.float32)
    rng = np.random.default_rng(seed)
    model.train()
    for _ in range(EPOCHS):
        order=rng.permutation(len(idx))
        for start in range(0,len(idx),64):
            k=order[start:start+64];p=model(tx[idx[k]],tb[idx[k]])
            if kind=='winner':loss=F.cross_entropy(10*p,target[k].argmax(1))
            elif kind=='pair':loss=F.cross_entropy(10*p[:,2:4],target[k].argmax(1))
            else:loss=F.mse_loss(p[:,2:4],target[k])
            loss=loss+.1*(p-tb[idx[k]]).square().mean()
            opt.zero_grad();loss.backward();opt.step()
    model.eval()
    with torch.no_grad():pred=model(ex,eb).clamp(0,1).numpy()
    detail['fallback']=None
    return pred,detail


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--panel-dir',required=True);ap.add_argument('--groups',required=True);ap.add_argument('--output',required=True)
    ap.add_argument('--repeat-dir');ap.add_argument('--mode',choices=['baseline','stable'],default='stable')
    a=ap.parse_args();torch.set_num_threads(4)
    panel=Path(a.panel_dir);manifest=json.loads((panel/'MANIFEST.json').read_text())
    if manifest['role']!='outer_train_only_repeat_selection':raise ValueError('Outer-fold panel required')
    for n,h in manifest['files'].items():
        if sha(panel/n)!=h:raise ValueError('Panel selection changed')
    source=Path(manifest['source'])
    for n,h in manifest['source_files'].items():
        if sha(source/n)!=h:raise ValueError('Panel source changed')
    if sha(a.groups)!=manifest['groups_sha256']:raise ValueError('Prompt groups changed')
    frozen,x,ds=load_inputs(source);ids=frozen['ids'];y=frozen['quality'];folds=frozen['folds']
    grouping=json.loads(Path(a.groups).read_text());groups=np.array([grouping['groups'][q] for q in ids])
    selections=json.loads((panel/'FOLD_SELECTION.json').read_text())
    repeats=load_repeats(a.repeat_dir,manifest) if a.mode=='stable' and a.repeat_dir else {}
    if a.mode=='stable' and not repeats:raise ValueError('Complete stable labels required; use baseline mode only for controls')
    arms=ARMS if a.mode=='stable' else ARMS[:2]
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    protocol=dict(role='fold_isolated_repeat_label_ma_development',mode=a.mode,seeds=SEEDS,epochs=EPOCHS,
        threshold=THRESHOLD,arms=arms,source=str(source.resolve()),panel_dir=str(panel.resolve()),
        panel_manifest_sha256=sha(panel/'MANIFEST.json'),source_files=manifest['source_files'],
        repeat_summary_sha256=sha(Path(a.repeat_dir)/'LABEL_SUMMARY.json') if a.mode=='stable' else None,
        implementation={str(p.resolve()):sha(p) for p in [Path(__file__),Path(__file__).with_name('anchored_ma.py')]},
        architecture='Same 64-dimensional train-only SVD and Ridge-anchored model-conditioned adapter, cap .1, AdamW .001, 15 epochs',
        selection='Fixed epochs/threshold/seeds before this run; panel selection restricted to each outer training fold',
        primary='stable_pair minus old_pair_stable_matched; also report original winner, repeat means, RidgeGuard and DatasetBest',
        tie_policy='Original argmax labels break ties by slot order, deliberately retained as old-label control',
        fallback='Ridge predictions when a supervised pair arm has fewer than five examples per class; count every fallback',
        limits=['Development OOF only; all original test outcomes retired',
                'Transfer from temperature .7 repeat labels to original temperature 0 evaluation; not same-distribution stability',
                'Only stable-vs-old matched arms isolate label direction on the same queries',
                'Smaller adapter is a new controlled ablation, not the old 967425-parameter architecture',
                'DatasetBest uses dataset metadata as diagnostic baseline; not a general online feature',
                'Paired CIs condition on OOF fits and do not include retraining uncertainty'])
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2)+'\n')
    choices={f'{arm}_seed{s}':np.zeros(len(ids),dtype=int) for arm in arms for s in SEEDS}
    choices['RidgeGuard']=np.zeros(len(ids),dtype=int);trace=[]
    for fold in sorted(np.unique(folds)):
        tr=np.flatnonzero(folds!=fold);va=np.flatnonzero(folds==fold)
        selected=selections[str(fold)]
        if not set(selected)<=set(ids[tr]) or set(groups[tr])&set(groups[va]):raise ValueError('Held-fold supervision leakage')
        ridge=Ridge(alpha=20.).fit(x[tr],y[tr]);bt=ridge.predict(x[tr]).clip(0,1).astype('float32');be=ridge.predict(x[va]).clip(0,1).astype('float32')
        svd=TruncatedSVD(n_components=64,random_state=42).fit(x[tr]);zt=svd.transform(x[tr]);ze=svd.transform(x[va])
        mean=zt.mean(0);scale=np.maximum(zt.std(0),.01);zt=(zt-mean)/scale;ze=(ze-mean)/scale
        fallback=frozen['DatasetBest'][va]
        choices['RidgeGuard'][va]=guarded(be,fallback,THRESHOLD)
        for seed in SEEDS:
            for arm in arms:
                pred,detail=fit_arm(zt,bt,ze,be,ids[tr],y[tr],selected,repeats,arm,seed)
                if arm!='old_winner_all':pred[:,:2]=be[:,:2]
                choices[f'{arm}_seed{seed}'][va]=guarded(pred,fallback,THRESHOLD)
                trace.append(dict(fold=int(fold),seed=seed,arm=arm,**detail))
            print(f'fold={fold} seed={seed} arms={len(arms)} finished',flush=True)
    for p,h in protocol['implementation'].items():
        if sha(p)!=h:raise ValueError('Implementation changed during training')
    index=np.arange(len(ids));reference=y[index,frozen['DatasetBest']];oracle=y.max(1);gap=float((oracle-reference).mean())
    result={}
    for name,c in choices.items():
        actual=y[index,c];diff=actual-reference
        result[name]=dict(quality=float(actual.mean()),gain_vs_dataset_best=float(diff.mean()),ci95=paired_ci(diff),
                         wins=int((diff>0).sum()),losses=int((diff<0).sum()),net_gap_recovery=float(diff.mean()/gap) if gap else None)
    comparisons={}
    if a.mode=='stable':
        for seed in SEEDS:
            diff=y[index,choices[f'stable_pair_seed{seed}']]-y[index,choices[f'old_pair_stable_matched_seed{seed}']]
            comparisons[str(seed)]=dict(gain=float(diff.mean()),ci95=paired_ci(diff))
    np.savez_compressed(out/'CHOICES.npz',ids=ids,**choices)
    (out/'TRACE.json').write_text(json.dumps(trace,indent=2)+'\n')
    report=dict(n=len(ids),methods=result,stable_minus_old_matched=comparisons,
                dataset_best_quality=float(reference.mean()),validation_labels_loaded=False,test_labels_loaded=False,
                all_requested_arms_completed=a.mode=='stable',
                files={n:sha(out/n) for n in ['PROTOCOL.json','CHOICES.npz','TRACE.json']})
    (out/'RESULTS.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# MA repeat-label controls','','Mode: '+a.mode+'. Original-train OOF development only.','',
           '| Arm | Quality | Versus DatasetBest | Wins/losses |','|---|---:|---:|---:|']
    for n,r in result.items():lines.append(f"| {n} | {100*r['quality']:.3f}% | {100*r['gain_vs_dataset_best']:+.3f} pp | {r['wins']}/{r['losses']} |")
    lines+=['','Stable-label arms '+('completed.' if a.mode=='stable' else 'NOT RUN: repeat labels required.'),
            'See TRACE.json for class coverage and fallback; a fallback is not evidence of learned MA benefit.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
