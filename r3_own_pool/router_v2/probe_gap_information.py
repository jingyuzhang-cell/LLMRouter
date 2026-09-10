"""Train-only information intervention: small-model draft vs shuffled draft, plus learning curves."""
import argparse,json,hashlib,sys,time
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import StratifiedKFold
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from .data import sha,read_rows
from .core import paired_ci
from .diagnose_rank_signal import load_inputs
from .improve_gap_text import predict
from .improve_gap import guarded,select_config
ROOT=Path(__file__).resolve().parents[1]


def fingerprint(row):
    return hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def draft_features(row):
    answer=row.get('answer') or ''
    status=row.get('status')
    # Only the delivered draft and generation status; no quality, tests, gold, cost or other models.
    numbers=[np.log1p(len(answer)),np.log1p(len(answer.split())),float('```' in answer),
             float(status=='failed'),float(status=='truncated'),float(not answer.strip())]
    return ('draft '+answer[:16000]),numbers


def shuffled_indices(indices,datasets,seed):
    result=indices.copy();rng=np.random.default_rng(seed)
    for ds in sorted(set(datasets[indices])):
        locations=np.flatnonzero(datasets[indices]==ds)
        result[locations]=rng.permutation(indices[locations])
    return result


def kernels(x,text,numeric,datasets,tr,va,mode,seed):
    qtr=x[tr]@x[tr].T;qva=x[va]@x[tr].T
    if mode=='query':return qtr,qva,None,None
    a,b=tr,va
    if mode=='shuffled_draft':
        a=shuffled_indices(tr,datasets,seed);b=shuffled_indices(va,datasets,seed+1000)
    vectorizer=TfidfVectorizer(ngram_range=(1,2),min_df=2,max_features=16000,sublinear_tf=True)
    ta=vectorizer.fit_transform(text[a]);tb=vectorizer.transform(text[b])
    scaler=StandardScaler().fit(numeric[a]);na=scaler.transform(numeric[a]);nb=scaler.transform(numeric[b])
    # Fixed 1/number-of-features scale; scaler fits training rows only.
    return qtr,qva,(ta@ta.T).toarray()+na@na.T/6,(tb@ta.T).toarray()+nb@na.T/6


def nested_subset(indices,datasets,seed,fraction):
    rng=np.random.default_rng(seed);selected=[]
    for ds in sorted(set(datasets[indices])):
        pool=indices[datasets[indices]==ds].copy();rng.shuffle(pool)
        selected.extend(pool[:max(1,int(len(pool)*fraction))])
    return np.array(sorted(selected),dtype=int)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',required=True);ap.add_argument('--output',required=True)
    args=ap.parse_args();source=Path(args.source).resolve();out=Path(args.output).resolve()
    frozen,x,datasets=load_inputs(source);y=frozen['quality'];folds=frozen['folds'];ids=frozen['ids'].tolist();n=len(y)
    old=json.loads((source/'PROTOCOL.json').read_text());matrix_path=next(p for p in old['input_sha256'] if Path(p).name=='TRAIN_MATRIX.jsonl')
    matrix={r['query_id']:r for r in read_rows(matrix_path)}
    sys.path.insert(0,str(ROOT/'collect'));import storage
    raw=storage.canonical_rows(ROOT/'data/raw/small.jsonl')
    texts=[];features=[];hashes={}
    for qid in ids:
        saved=next(r for r in matrix[qid]['responses'] if r['slot']=='small')
        if fingerprint(raw[qid])!=saved['response_sha256']:raise ValueError('Draft no longer matches outcome snapshot')
        text,feature=draft_features(raw[qid]);texts.append(text);features.append(feature);hashes[qid]=saved['response_sha256']
    text=np.array(texts);numeric=np.array(features)
    out.mkdir(parents=True,exist_ok=False)
    protocol=dict(role='exploratory_train_only_information_probe',seeds=[42,43,44],modes=['query','draft','shuffled_draft'],
        alphas=[1.,20.,100.],draft_weights=[.25,1.,4.],thresholds=[0.,.05],fractions=[.25,.5,1.],learning_curve_alpha=20.,
        source_sha256=sha(source/'OOF.npz'),draft_hashes=hashes,implementation_sha256=sha(__file__),
        design='Same outer folds; inner threefold quality selection. Shuffle draft within dataset separately in fit/held portions. Ridge learning subsets are nested within each outer train.',
        limits=['Draft-assisted routing requires the small call first; query-only and draft policies have different inference budgets',
         'Cached endpoint simulation, not online end-to-end cascade or dollar/latency claim',
         'Shuffled draft is an undeployable negative control; uses other drafts only to break same-query information',
         'Draft text limited to first16000 characters; numeric features computed from full delivered draft',
         'Adaptive development on original train; not independent confirmation','No validation/test labels or gold as input'])
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2))
    choices={};selections=[];curve_choices={};subset_records=[]
    for seed in protocol['seeds']:
        for mode in protocol['modes']:choices[f'{mode}_seed{seed}']=np.zeros(n,dtype=int)
        for fraction in protocol['fractions']:curve_choices[f'f{fraction}_seed{seed}']=np.zeros(n,dtype=int)
        for fold in (0,1,2):
            started=time.monotonic();tr=np.flatnonzero(folds!=fold);va=np.flatnonzero(folds==fold)
            for fraction in protocol['fractions']:
                subset=nested_subset(tr,datasets,seed+fold,fraction)
                pred=Ridge(alpha=20.).fit(x[subset],y[subset]).predict(x[va]).clip(0,1)
                curve_choices[f'f{fraction}_seed{seed}'][va]=pred.argmax(1)
                subset_records.append(dict(seed=seed,fold=fold,fraction=fraction,n=len(subset),ids=[ids[i] for i in subset]))
            inner=[(tr[a],tr[b]) for a,b in StratifiedKFold(3,shuffle=True,random_state=seed).split(tr,datasets[tr])]
            for mode in protocol['modes']:
                cached=[(it,iv,kernels(x,text,numeric,datasets,it,iv,mode,seed)) for it,iv in inner]
                candidates=[]
                for weight in ([0.] if mode=='query' else protocol['draft_weights']):
                    for alpha in protocol['alphas']:
                        scores={tau:[] for tau in protocol['thresholds']}
                        for it,iv,(kt,kv,dt,dv) in cached:
                            pred=predict(kt if dt is None else kt+weight*dt,kv if dv is None else kv+weight*dv,y[it],alpha)
                            base=np.full(len(iv),y[it].mean(0).argmax())
                            for tau in scores:scores[tau].extend(y[iv,guarded(pred,base,tau)].tolist())
                        candidates.extend(dict(gamma=weight,alpha=alpha,threshold=tau,quality=float(np.mean(v))) for tau,v in scores.items())
                chosen=select_config(candidates);kt,kv,dt,dv=kernels(x,text,numeric,datasets,tr,va,mode,seed)
                pred=predict(kt if dt is None else kt+chosen['gamma']*dt,kv if dv is None else kv+chosen['gamma']*dv,y[tr],chosen['alpha'])
                choices[f'{mode}_seed{seed}'][va]=guarded(pred,np.full(len(va),y[tr].mean(0).argmax()),chosen['threshold'])
                selections.append(dict(seed=seed,fold=fold,mode=mode,chosen=chosen,candidates=candidates))
            print(f'seed={seed} fold={fold} information probe and curves complete {time.monotonic()-started:.1f}s',flush=True)
    if sha(__file__)!=protocol['implementation_sha256']:raise ValueError('Implementation changed')
    np.savez_compressed(out/'OOF_CHOICES.npz',ids=frozen['ids'],**choices,**curve_choices)
    (out/'SELECTION.json').write_text(json.dumps(selections,indent=2));(out/'LEARNING_SUBSETS.json').write_text(json.dumps(subset_records,indent=2))
    baseline=y[np.arange(n),frozen['DatasetBest']];fixed=y[np.arange(n),frozen['BestSingle']];oracle=y.max(1);gap=float((oracle-fixed).mean())
    actual={key:y[np.arange(n),choice] for key,choice in choices.items()};reports={};comparisons={}
    for key,values in actual.items():
        reports[key]=dict(quality=float(values.mean()),vs_dataset_best=float((values-baseline).mean()),ci95=paired_ci(values-baseline),
            gap_recovery=float((values-fixed).mean()/gap),
            mean_model_calls=1. if key.startswith('query_') else float(1+(choices[key]!=0).mean()),
            by_dataset={ds:float(values[datasets==ds].mean()) for ds in sorted(set(datasets))})
    for seed in protocol['seeds']:
        comparisons[str(seed)]={}
        for other in ['query','shuffled_draft']:
            diff=actual[f'draft_seed{seed}']-actual[f'{other}_seed{seed}']
            comparisons[str(seed)][f'draft_minus_{other}']=dict(gain=float(diff.mean()),ci95=paired_ci(diff))
    curves={key:dict(quality=float(y[np.arange(n),choice].mean()),by_dataset={ds:float(y[np.flatnonzero(datasets==ds),choice[datasets==ds]].mean()) for ds in sorted(set(datasets))}) for key,choice in curve_choices.items()}
    result=dict(role=protocol['role'],methods=reports,comparisons=comparisons,learning_curves=curves,
        files={name:sha(out/name) for name in ['PROTOCOL.json','SELECTION.json','LEARNING_SUBSETS.json','OOF_CHOICES.npz']},
        validation_labels_loaded=False,test_labels_loaded=False)
    (out/'RESULTS.json').write_text(json.dumps(result,indent=2));print(json.dumps(reports,indent=2),flush=True)

if __name__=='__main__':main()
