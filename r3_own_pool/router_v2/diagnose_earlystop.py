"""Nested train-only stopping-time intervention; no outer-fold checkpoint selection."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
import torch
from sklearn.model_selection import train_test_split
from .data import sha
from .core import paired_ci
from .experiment import Router
from .diagnose_rank_signal import load_inputs
from .diagnose_mechanism import diagnostic_fit


def select_epoch(history):
    if not history or any(not np.isfinite(r['held_mse']) for r in history):
        raise ValueError('Invalid inner-validation loss')
    return min(history,key=lambda r:(r['held_mse'],r['epoch']))['epoch']


def fit_nested(xt,yt,datasets,xv,seed):
    indices=np.arange(len(xt))
    inner_train,inner_val=train_test_split(indices,test_size=.2,random_state=seed,stratify=datasets)
    _,history,_=diagnostic_fit('original',xt[inner_train],yt[inner_train],xt[inner_val],yt[inner_val],seed)
    epochs=select_epoch(history)
    model=Router(q_dim=xt.shape[1],seed=seed,alpha=0.)
    model.fit(xt,yt,seed=seed,epochs=epochs)
    return model.predict_all(xv),dict(selected_epochs=epochs,inner_history=history,
        inner_train_indices=inner_train.tolist(),inner_validation_indices=inner_val.tolist())


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',required=True);ap.add_argument('--output',required=True)
    args=ap.parse_args();torch.set_num_threads(4)
    source=Path(args.source).resolve();out=Path(args.output).resolve()
    frozen,x,datasets=load_inputs(source);y=frozen['quality'];folds=frozen['folds']
    out.mkdir(parents=True,exist_ok=False)
    code=[Path(__file__),Path(__file__).with_name('diagnose_mechanism.py'),Path(__file__).with_name('experiment.py'),Path(__file__).with_name('core.py'),Path(__file__).parents[1]/'train_router.py']
    protocol=dict(role='exploratory_train_only_nested_earlystop',seeds=[42,43,44],inner_fraction=.2,
        epoch_candidates=[1,5,10,20,40,60],selection='Min inner-validation MSE; tie chooses earliest; refit on all outer-training rows',
        source_oof_sha256=sha(source/'OOF.npz'),implementation={str(p):sha(p) for p in code},
        architecture='Original Hybrid, alpha=0; only training duration selection changes',
        limits=['Extra inner fitting compute versus fixed-epoch control','No outer-fold labels used for epoch selection',
                'Training-only exploratory evidence, not independent confirmation'])
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2))
    predictions={};records=[]
    for seed in protocol['seeds']:
        predictions[str(seed)]=np.zeros_like(y)
        for fold in (0,1,2):
            start=time.monotonic();tr=folds!=fold;va=folds==fold
            pred,details=fit_nested(x[tr],y[tr],datasets[tr],x[va],seed)
            predictions[str(seed)][va]=pred
            records.append(dict(seed=seed,fold=fold,**details))
            print(f'seed={seed} fold={fold} epochs={details["selected_epochs"]} seconds={time.monotonic()-start:.1f}',flush=True)
        np.savez_compressed(out/f'SEED_{seed}.npz',predicted_quality=predictions[str(seed)])
    for path,digest in protocol['implementation'].items():
        if sha(path)!=digest:raise ValueError('Implementation changed during run')
    (out/'SELECTION.json').write_text(json.dumps(records,indent=2))
    base=y[np.arange(len(y)),frozen['DatasetBest']];reports={}
    for seed,pred in predictions.items():
        values=y[np.arange(len(y)),pred.argmax(1)];diff=values-base
        reports[seed]=dict(quality=float(values.mean()),vs_dataset_best=float(diff.mean()),ci95=paired_ci(diff),
            by_dataset={ds:float(values[datasets==ds].mean()) for ds in sorted(set(datasets))})
    (out/'RESULTS.json').write_text(json.dumps(dict(role=protocol['role'],methods=reports,
        files={p.name:sha(p) for p in out.glob('*.npz')},validation_labels_loaded=False,test_labels_loaded=False),indent=2))
    print(json.dumps(reports,indent=2),flush=True)

if __name__=='__main__':main()
