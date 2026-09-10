"""Nested word-feature and GTE-combination diagnostic; every vocabulary fits inner train only."""
import argparse,json,time
from pathlib import Path
import numpy as np
from scipy.linalg import solve
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import StratifiedKFold
from .data import load_cohort,sha
from .core import paired_ci
from .diagnose_rank_signal import load_inputs
from .improve_gap import guarded,select_config


def text_kernels(train_text,eval_text,xt,xv,beta):
    vectorizer=TfidfVectorizer(ngram_range=(1,2),min_df=2,max_features=20000,sublinear_tf=True)
    tt=vectorizer.fit_transform(train_text);tv=vectorizer.transform(eval_text)
    return (tt@tt.T).toarray()+beta*(xt@xt.T),(tv@tt.T).toarray()+beta*(xv@xt.T)


def predict(kt,kv,y,alpha):
    km=kt.mean(0);ka=kt.mean();target=y-y.mean(0)
    weights=solve(kt-km[None,:]-km[:,None]+ka+alpha*np.eye(len(y)),target,assume_a='pos',check_finite=False)
    return ((kv-kv.mean(1,keepdims=True)-km[None,:]+ka)@weights+y.mean(0)).clip(0,1)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',required=True);ap.add_argument('--output',required=True)
    args=ap.parse_args();source=Path(args.source).resolve();out=Path(args.output).resolve()
    frozen,x,datasets=load_inputs(source);y=frozen['quality'];folds=frozen['folds'];n=len(y)
    old=json.loads((source/'PROTOCOL.json').read_text())
    cp=next(Path(p).parent for p in old['input_sha256'] if Path(p).name=='queries.jsonl')
    cohort,_=load_cohort(cp);text=np.array([cohort[q]['query'] for q in frozen['ids']])
    out.mkdir(parents=True,exist_ok=False)
    protocol=dict(role='exploratory_nested_text_gap',seeds=[42,43,44],families=['text','text_gte'],alphas=[.1,1.,10.,100.],
        beta={'text':[0.],'text_gte':[.25,1.,4.]},thresholds=[0.,.02,.05,.1],
        feature='word TF-IDF unigram/bigram min_df2 max20000 sublinear tf, vocabulary/idf fitted separately inside every inner-training fold',
        selection='Inner OOF routed quality; conservative ties',source_oof_sha256=sha(source/'OOF.npz'),implementation_sha256=sha(__file__),
        limits=['Adaptive train-only development, not independent confirmation','No answer/ground-truth features','No validation/test labels','No cost claims'])
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2))
    choices={};selections=[]
    for seed in protocol['seeds']:
        for family in protocol['families']:choices[f'{family}_seed{seed}']=np.zeros(n,dtype=int)
        for fold in (0,1,2):
            started=time.monotonic();tr=np.flatnonzero(folds!=fold);va=np.flatnonzero(folds==fold)
            inner=[(tr[a],tr[b]) for a,b in StratifiedKFold(3,shuffle=True,random_state=seed).split(tr,datasets[tr])]
            cached=[]
            for it,iv in inner:
                kt,kv=text_kernels(text[it],text[iv],x[it],x[iv],0.)
                cached.append((it,iv,kt,kv))
            kt_outer,kv_outer=text_kernels(text[tr],text[va],x[tr],x[va],0.)
            for family in protocol['families']:
                candidates=[]
                for beta in protocol['beta'][family]:
                    for alpha in protocol['alphas']:
                        scores={tau:[] for tau in protocol['thresholds']}
                        for it,iv,kt,kv in cached:
                            pred=predict(kt+beta*(x[it]@x[it].T),kv+beta*(x[iv]@x[it].T),y[it],alpha)
                            base=np.full(len(iv),y[it].mean(0).argmax())
                            for tau in scores:scores[tau].extend(y[iv,guarded(pred,base,tau)].tolist())
                        candidates.extend(dict(gamma=beta,alpha=alpha,threshold=tau,quality=float(np.mean(vals))) for tau,vals in scores.items())
                chosen=select_config(candidates);beta=chosen['gamma']
                pred=predict(kt_outer+beta*(x[tr]@x[tr].T),kv_outer+beta*(x[va]@x[tr].T),y[tr],chosen['alpha'])
                choices[f'{family}_seed{seed}'][va]=guarded(pred,np.full(len(va),y[tr].mean(0).argmax()),chosen['threshold'])
                selections.append(dict(seed=seed,fold=fold,family=family,chosen=chosen,candidates=candidates))
            print(f'seed={seed} fold={fold} complete {time.monotonic()-started:.1f}s',flush=True)
    if sha(__file__)!=protocol['implementation_sha256']:raise ValueError('Implementation changed')
    np.savez_compressed(out/'OOF_CHOICES.npz',ids=frozen['ids'],**choices)
    (out/'SELECTION.json').write_text(json.dumps(selections,indent=2))
    bases={name:y[np.arange(n),frozen[name]] for name in ['Ridge','DatasetBest','BestSingle']};reports={}
    gap=float((y.max(1)-bases['BestSingle']).mean())
    for key,decision in choices.items():
        actual=y[np.arange(n),decision]
        reports[key]=dict(quality=float(actual.mean()),gap_recovery=float((actual-bases['BestSingle']).mean()/gap),
            vs_baselines={name:dict(gain=float((actual-base).mean()),ci95=paired_ci(actual-base)) for name,base in bases.items()},
            by_dataset={ds:float(actual[datasets==ds].mean()) for ds in sorted(set(datasets))})
    result=dict(role=protocol['role'],methods=reports,validation_labels_loaded=False,test_labels_loaded=False,
        files={name:sha(out/name) for name in ['PROTOCOL.json','SELECTION.json','OOF_CHOICES.npz']})
    (out/'RESULTS.json').write_text(json.dumps(result,indent=2));print(json.dumps(reports,indent=2),flush=True)

if __name__=='__main__':main()
