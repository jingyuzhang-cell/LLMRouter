"""Nested train-only quality-selected regularization, nonlinear kernels and guarded residuals."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from scipy.linalg import solve
from sklearn.model_selection import StratifiedKFold
from .data import sha
from .core import paired_ci
from .diagnose_rank_signal import load_inputs

FAMILIES=('linear','rbf','dataset_residual_linear','dataset_residual_rbf')
ALPHAS=(.01,.1,1.,20.,100.)
GAMMAS=(1.,4.,16.)
THRESHOLDS=(0.,.02,.05,.1)


def predict_kernel(kernel,y,datasets,tr,va,alpha,residual):
    target=y[tr].copy()
    prior_train=np.zeros_like(target);prior_val=np.zeros((len(va),4))
    if residual:
        for ds in set(datasets[tr]):
            mean=y[tr[datasets[tr]==ds]].mean(0)
            prior_train[datasets[tr]==ds]=mean
            prior_val[datasets[va]==ds]=mean
        if not set(datasets[va]) <= set(datasets[tr]):raise ValueError('Unknown diagnostic dataset')
        target-=prior_train
    mean=target.mean(0);target-=mean
    k=kernel[np.ix_(tr,tr)]
    km=k.mean(0);ka=k.mean()
    centered=k-km[None,:]-km[:,None]+ka
    weights=solve(centered+alpha*np.eye(len(tr)),target,assume_a='pos',check_finite=False)
    kv=kernel[np.ix_(va,tr)]
    kv=kv-kv.mean(1,keepdims=True)-km[None,:]+ka
    return (kv@weights+mean+prior_val).clip(0,1)


def anchors(y,datasets,tr,va,residual):
    fixed=int(y[tr].mean(0).argmax())
    choice=np.full(len(va),fixed)
    if residual:
        for ds in set(datasets[va]):
            choice[datasets[va]==ds]=y[tr[datasets[tr]==ds]].mean(0).argmax()
    return choice


def guarded(pred,base,tau):
    winner=pred.argmax(1)
    advantage=pred[np.arange(len(pred)),winner]-pred[np.arange(len(pred)),base]
    return np.where(advantage>tau,winner,base)


def select_config(candidates):
    # Higher regularization and larger fallback margin resolve equal inner quality.
    return max(candidates,key=lambda r:(r['quality'],r['alpha'],r['threshold'],-r['gamma']))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',required=True);ap.add_argument('--output',required=True)
    args=ap.parse_args();source=Path(args.source).resolve();out=Path(args.output).resolve()
    frozen,x,datasets=load_inputs(source);y=frozen['quality'];outer=frozen['folds'];n=len(y)
    out.mkdir(parents=True,exist_ok=False)
    protocol=dict(role='exploratory_nested_gap_improvement',seeds=[42,43,44],outer_folds='Exact earlier three folds',inner_folds=3,
        families=FAMILIES,alphas=ALPHAS,gammas=GAMMAS,thresholds=THRESHOLDS,
        selection='Inner OOF routed quality only; ties prefer higher alpha, higher guard threshold, lower gamma',
        source_sha256=sha(source/'OOF.npz'),implementation_sha256=sha(__file__),
        primary='Query-only linear/RBF versus earlier Ridge and dataset diagnostic baseline',
        limits=['Adaptive development after previous OOF results; not independent confirmation',
          'Dataset residual families require privileged dataset identity; diagnostic upper comparison, not deployment claim',
          'Validation/test labels are never loaded','Binary objective subset only; no cost/latency claims',
          'All candidates and seeds reported; no best outer-fold hyperparameter selection'])
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2))
    gram=x@x.T
    distance=np.maximum(np.diag(gram)[:,None]+np.diag(gram)[None,:]-2*gram,0)
    kernels={0.:gram.astype('float64')}
    for gamma in GAMMAS:kernels[gamma]=np.exp(-gamma*distance).astype('float64')
    choices={};selections=[]
    for seed in protocol['seeds']:
        for family in FAMILIES:choices[f'{family}_seed{seed}']=np.zeros(n,dtype=int)
        for fold in (0,1,2):
            start=time.monotonic();tr=np.flatnonzero(outer!=fold);va=np.flatnonzero(outer==fold)
            inner=[(tr[a],tr[b]) for a,b in StratifiedKFold(3,shuffle=True,random_state=seed).split(tr,datasets[tr])]
            for family in FAMILIES:
                residual=family.startswith('dataset_');gammas=GAMMAS if family.endswith('rbf') else (0.,)
                candidates=[]
                for gamma in gammas:
                    for alpha in ALPHAS:
                        scores={tau:[] for tau in THRESHOLDS}
                        for it,iv in inner:
                            pred=predict_kernel(kernels[gamma],y,datasets,it,iv,alpha,residual)
                            base=anchors(y,datasets,it,iv,residual)
                            for tau in THRESHOLDS:
                                decision=guarded(pred,base,tau)
                                scores[tau].extend(y[iv,decision].tolist())
                        candidates.extend(dict(gamma=gamma,alpha=alpha,threshold=tau,quality=float(np.mean(values))) for tau,values in scores.items())
                chosen=select_config(candidates)
                pred=predict_kernel(kernels[chosen['gamma']],y,datasets,tr,va,chosen['alpha'],residual)
                base=anchors(y,datasets,tr,va,residual)
                choices[f'{family}_seed{seed}'][va]=guarded(pred,base,chosen['threshold'])
                selections.append(dict(seed=seed,fold=fold,family=family,chosen=chosen,candidates=candidates))
            print(f'seed={seed} fold={fold} all families selected internally and refitted {time.monotonic()-start:.1f}s',flush=True)
    if sha(__file__)!=protocol['implementation_sha256']:raise ValueError('Implementation changed')
    np.savez_compressed(out/'OOF_CHOICES.npz',ids=frozen['ids'],**choices)
    (out/'SELECTION.json').write_text(json.dumps(selections,indent=2))
    baselines={name:y[np.arange(n),frozen[name]] for name in ('Ridge','BestSingle','DatasetBest')}
    oracle=y.max(1);reports={}
    for key,decision in choices.items():
        actual=y[np.arange(n),decision];gain=actual-baselines['BestSingle'];gap=float((oracle-baselines['BestSingle']).mean())
        reports[key]=dict(quality=float(actual.mean()),gap_recovery=float(gain.mean()/gap),
            vs_baselines={name:dict(gain=float((actual-base).mean()),ci95=paired_ci(actual-base)) for name,base in baselines.items()},
            by_dataset={ds:float(actual[datasets==ds].mean()) for ds in sorted(set(datasets))},
            routing_fraction=(np.bincount(decision,minlength=4)/n).tolist())
    result=dict(role=protocol['role'],methods=reports,baselines={k:float(v.mean()) for k,v in baselines.items()},
        empirical_oracle=float(oracle.mean()),validation_labels_loaded=False,test_labels_loaded=False,
        files={name:sha(out/name) for name in ('PROTOCOL.json','SELECTION.json','OOF_CHOICES.npz')})
    (out/'RESULTS.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v['quality'] for k,v in reports.items()},indent=2),flush=True)

if __name__=='__main__':main()
