"""Freeze all candidate predictions, then evaluate original objective validation only."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
import torch
from sklearn.linear_model import Ridge
from .data import load_cohort, sha
from .core import SLOTS, paired_ci
from .diagnose_rank_signal import load_inputs
from .diagnose_mechanism import make_model
from .diagnose_earlystop import fit_nested
ROOT=Path(__file__).resolve().parents[1]


def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def validation_quality(ids,cohort,out):
    # Called only after prediction sealing. Never access test score caches.
    sys.path.insert(0,str(ROOT/'collect'))
    import storage
    selected=set(ids); labels={}; provenance={}
    paths=[ROOT/'data/scored_validation_v2/SCORES.jsonl',ROOT/'data/scored_code_validation_v2/SCORES.jsonl']
    for path in paths:
        data=path.read_bytes()
        if data and not data.endswith(b'\n'):data=data[:data.rfind(b'\n')+1]
        provenance[str(path)]=hashlib.sha256(data).hexdigest()
        for line in data.split(b'\n'):
            if not line.strip():continue
            row=json.loads(line)
            if row['query_id'] not in selected:continue
            key=(row['query_id'],row['slot'],row['source_sha256'],row['response_sha256'])
            if key not in labels or labels[key].get('quality') is None:labels[key]=row
    raw={s:storage.canonical_rows(ROOT/'data/raw'/f'{s}.jsonl') for s in SLOTS}
    y=[];bindings=[]
    for qid in ids:
        values=[]
        for slot in SLOTS:
            response=raw[slot][qid]
            key=(qid,slot,digest(cohort[qid]),digest(response))
            if key not in labels or labels[key]['quality'] not in (0,1):
                raise ValueError(f'Missing bound binary validation score: {qid}/{slot}')
            values.append(labels[key]['quality'])
            bindings.append(dict(query_id=qid,slot=slot,source_sha256=key[2],response_sha256=key[3],
                score_sha256=digest(labels[key]),evaluation_status=labels[key].get('evaluation_status')))
        y.append(values)
    (out/'LABEL_BINDINGS.json').write_text(json.dumps(dict(cache_prefix_sha256=provenance,cells=bindings),indent=2))
    return np.asarray(y,dtype=float)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',required=True);ap.add_argument('--output',required=True)
    args=ap.parse_args();torch.set_num_threads(4)
    source=Path(args.source).resolve();out=Path(args.output).resolve()
    frozen,x,datasets=load_inputs(source);y=frozen['quality']
    cohort,split=load_cohort(ROOT/'data/cohort_full_v2')
    ids=[qid for qid in split['validation'] if cohort[qid]['dataset'] in {'gsm8k','mmlupro','humaneval','mbpp'}]
    validation_datasets=np.array([cohort[qid]['dataset'] for qid in ids])
    exposure_path=ROOT/'router_v2/exposure_audit/AUDIT.json'
    exposure=json.loads(exposure_path.read_text())
    exposed=np.array([qid in set(exposure['overlap_ids']['validation']) for qid in ids])
    emb=ROOT/'data/embeddings_full_v2_recovery1/EMBEDDINGS.npz'
    with np.load(emb,allow_pickle=False) as saved:
        if saved['query_sha256'].item()!=sha(ROOT/'data/cohort_full_v2/queries.jsonl'):raise ValueError('Embedding hash mismatch')
        index={qid:i for i,qid in enumerate(saved['ids'].tolist())}
        xv=saved['vectors'][[index[qid] for qid in ids]].astype('float32')
    out.mkdir(parents=True,exist_ok=False)
    code=[Path(__file__),Path(__file__).with_name('diagnose_earlystop.py'),Path(__file__).with_name('diagnose_mechanism.py'),Path(__file__).with_name('experiment.py'),Path(__file__).with_name('core.py'),ROOT/'train_router.py']
    protocol=dict(role='original_validation_development_replication_not_independent_test',seeds=[42,43,44],
        fixed_epochs=60,ridge_alpha=20.,primary='Nested earlystop original versus fixed60 original',
        secondary=['normalized_model60 vs original60','four_head60 vs original60','All methods vs Ridge and DatasetBest'],
        selection='All methods predeclared; no candidate selection by validation outcomes',
        validation_ids=ids,known_pilot_exposed=int(exposed.sum()),
        source_oof_sha256=sha(source/'OOF.npz'),embedding_sha256=sha(emb),exposure_sha256=sha(exposure_path),
        implementation={str(p):sha(p) for p in code},
        limits=['Original validation previously available in project; no claim of untouched independent confirmation',
                'Exclude known pilot exposure only as predefined sensitivity slice, not certified clean holdout',
                'Objective subset only, no money/latency or open-ended quality claim',
                'No test labels accessed; no formal full-cohort gate certification'])
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2))
    predictions={};selections=[]
    for seed in protocol['seeds']:
        for kind in ('original','normalized_model','four_head'):
            started=time.monotonic()
            model=make_model(kind,x.shape[1],seed)
            model.fit(x,y,seed=seed,epochs=60)
            predictions[f'{kind}_seed{seed}']=model.predict_all(xv)
            print(f'{kind}_seed{seed} fitted {time.monotonic()-started:.1f}s',flush=True)
        started=time.monotonic()
        pred,detail=fit_nested(x,y,datasets,xv,seed)
        predictions[f'earlystop_seed{seed}']=pred;selections.append(dict(seed=seed,**detail))
        print(f'earlystop_seed{seed} fitted epochs={detail["selected_epochs"]} {time.monotonic()-started:.1f}s',flush=True)
    predictions['Ridge']=Ridge(alpha=20.).fit(x,y).predict(xv).clip(0,1)
    choices={name:pred.argmax(1) for name,pred in predictions.items()}
    choices['BestSingle']=np.full(len(ids),y.mean(0).argmax())
    choices['DatasetBest']=np.array([y[datasets==ds].mean(0).argmax() for ds in validation_datasets])
    np.savez_compressed(out/'PREDICTIONS.npz',ids=np.array(ids),**predictions,**{'choice_'+k:v for k,v in choices.items()})
    (out/'SELECTION.json').write_text(json.dumps(selections,indent=2))
    for path,signature in protocol['implementation'].items():
        if sha(path)!=signature:raise ValueError('Implementation changed during fit')
    sealed={name:sha(out/name) for name in ('PROTOCOL.json','PREDICTIONS.npz','SELECTION.json')}
    (out/'FROZEN.json').write_text(json.dumps(sealed,indent=2))
    with (out/'VALIDATION_OPENED.json').open('x') as f:json.dump(dict(time=time.time(),frozen_sha256=sha(out/'FROZEN.json')),f)
    yv=validation_quality(ids,cohort,out)
    actual={name:yv[np.arange(len(yv)),decision] for name,decision in choices.items()}
    scopes={}
    masks={'all':np.ones(len(ids),dtype=bool),'without_known_pilot':~exposed}
    masks.update({ds:validation_datasets==ds for ds in sorted(set(validation_datasets))})
    for scope,mask in masks.items():
        if not mask.any():continue
        methods={}
        for name,values in actual.items():
            diff=values[mask]-actual['DatasetBest'][mask]
            methods[name]=dict(quality=float(values[mask].mean()),vs_dataset_best=float(diff.mean()),ci95=paired_ci(diff))
        primary={}
        for seed in protocol['seeds']:
            diff=actual[f'earlystop_seed{seed}'][mask]-actual[f'original_seed{seed}'][mask]
            primary[str(seed)]=dict(gain=float(diff.mean()),ci95=paired_ci(diff))
        scopes[scope]=dict(n=int(mask.sum()),methods=methods,earlystop_minus_original=primary)
    result=dict(role=protocol['role'],scopes=scopes,test_labels_loaded=False,
                source_sha256=sha(source/'OOF.npz'),frozen_sha256=sha(out/'FROZEN.json'))
    (out/'RESULTS.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(scopes['all'],indent=2),flush=True)

if __name__=='__main__':main()
