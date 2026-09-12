"""Nested two-stage residual gate on corrected five-repeat labels."""
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge

from .data import read_rows, sha
from .mmlu_learnability import group_ci
from .train_repeat_pairwise_compatibility_115 import inner_split, subject

ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = ROOT / "router_v2/repeat_compatibility_115"
DATA = ROOT / "data/repeat_compatibility_115_rescore_v1"
EMBEDDINGS = ROOT / "data/embeddings_full_v2_recovery1/EMBEDDINGS.npz"
OUT = ROOT / "router_v2/experiment_two_stage_residual_gate_115"
SLOTS = ["medium", "large", "coder", "reasoning"]
THRESHOLDS = np.arange(0.20, 0.81, 0.05)


def fit_gate(x, target, indices):
    labels = target[indices].astype(int)
    if len(np.unique(labels)) == 1:
        return None, float(labels[0])
    model = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000, random_state=42)
    model.fit(x[indices], labels)
    return model, None


def gate_probability(model, constant, x):
    return np.full(len(x), constant, dtype=float) if model is None else model.predict_proba(x)[:, 1]


def route(probability, residual, threshold):
    alternative = residual.argmax(1)
    return np.where(probability > threshold, alternative, 3)


def summarize(y, choices, groups):
    row = np.arange(len(y)); baseline = y[:, 3]; oracle = y.max(1); gap = float((oracle-baseline).mean())
    result = {"n": len(y), "oracle_expected_quality": float(oracle.mean()),
              "datasetbest_expected_quality": float(baseline.mean()), "oracle_gap": gap, "methods": {}}
    for name, choice in choices.items():
        actual=y[row,choice]; gain=actual-baseline; ci=group_ci(gain,groups)
        result["methods"][name]={"expected_quality":float(actual.mean()),"gain":float(gain.mean()),
          "gain_ci95":ci,"gap_recovery":float(gain.mean()/gap),
          "gap_recovery_ci95":[float(v/gap) for v in ci],
          "selection_counts":dict(zip(SLOTS,np.bincount(choice,minlength=4).tolist()))}
    return result


def main():
    if OUT.exists(): raise FileExistsError(OUT)
    status=json.loads((DATA/'STATUS.json').read_text()); labels_path=DATA/'EXPECTED_UTILITY_LABELS.jsonl'
    if status.get('phase')!='REPEAT_LABELS_COMPLETE' or sha(labels_path)!=status['labels_sha256']:
        raise ValueError('Corrected labels incomplete or changed')
    panel=read_rows(PANEL_DIR/'PANEL.jsonl'); labels={r['query_id']:r for r in read_rows(labels_path)}
    ids=np.array([r['query_id'] for r in panel]); folds=np.array([r['fold'] for r in panel]); groups=np.array([r['prompt_group'] for r in panel])
    subjects=np.array([subject(r['query']) for r in panel]); y=np.array([[labels[q]['models'][s]['mean'] for s in SLOTS] for q in ids],dtype='float32')
    with np.load(EMBEDDINGS,allow_pickle=False) as saved:
        index={q:i for i,q in enumerate(saved['ids'].tolist())}; x=saved['vectors'][[index[q] for q in ids]].astype('float32')
    target=(y[:,:3].max(1)>y[:,3]); choices={"DatasetBest":np.full(len(y),3,dtype=int),"TwoStageResidualGate":np.empty(len(y),dtype=int)}
    probability=np.empty(len(y)); residual=np.empty((len(y),3)); trace=[]
    OUT.mkdir(parents=True)
    for fold in sorted(set(folds)):
        development=np.flatnonzero(folds!=fold); test=np.flatnonzero(folds==fold); train,validation=inner_split(development,subjects,int(fold))
        if set(groups[development]) & set(groups[test]) or set(groups[train]) & set(groups[validation]): raise ValueError('Group leakage')
        gate,constant=fit_gate(x,target,train); pval=gate_probability(gate,constant,x[validation])
        delta=y[:,:3]-y[:,[3]]; rmodel=Ridge(alpha=1.0).fit(x[train],delta[train]); rval=rmodel.predict(x[validation])
        utilities=[]
        for threshold in THRESHOLDS:
            choice=route(pval,rval,float(threshold)); utilities.append(float(y[validation,choice].mean()))
        best_value=max(utilities); threshold=float(max(t for t,u in zip(THRESHOLDS,utilities) if np.isclose(u,best_value)))
        gate,constant=fit_gate(x,target,development); ptest=gate_probability(gate,constant,x[test]); rmodel=Ridge(alpha=1.0).fit(x[development],delta[development]); rtest=rmodel.predict(x[test])
        probability[test]=ptest; residual[test]=rtest; choices['TwoStageResidualGate'][test]=route(ptest,rtest,threshold)
        trace.append({'fold':int(fold),'development_ids':ids[development].tolist(),'inner_train_ids':ids[train].tolist(),
          'inner_validation_ids':ids[validation].tolist(),'test_ids':ids[test].tolist(),'train_gate_positives':int(target[train].sum()),
          'validation_gate_positives':int(target[validation].sum()),'test_gate_positives':int(target[test].sum()),
          'threshold':threshold,'validation_expected_quality':best_value})
    report=summarize(y,choices,groups)
    metadata={'role':'method-development diagnostic; not representative or final test','architecture':'stage 1 class-balanced logistic any-alternative-beats-R1 gate; stage 2 three-output Ridge residual selector',
      'threshold_selection':'fixed 0.20..0.80 grid on inner validation only; conservative largest threshold on ties','ridge_alpha':1.0,'logistic_C':1.0,
      'source_sha256':{'labels':sha(labels_path),'panel':sha(PANEL_DIR/'PANEL.jsonl'),'embeddings':sha(EMBEDDINGS),'trainer':sha(Path(__file__))}}
    (OUT/'PROTOCOL.json').write_text(json.dumps(metadata,indent=2)+'\n'); (OUT/'RESULTS.json').write_text(json.dumps(report,indent=2)+'\n'); (OUT/'FOLDS.json').write_text(json.dumps(trace,indent=2)+'\n')
    np.savez_compressed(OUT/'PREDICTIONS.npz',ids=ids,folds=folds,quality=y,gate_probability=probability,predicted_residual=residual,**{f'choice_{k}':v for k,v in choices.items()})
    lines=['# Two-stage Residual Gate（115题方法开发诊断）','',f"Oracle={report['oracle_expected_quality']:.2%}；R1={report['datasetbest_expected_quality']:.2%}；Gap={report['oracle_gap']:.2%}。",'', '| 方法 | Expected quality | Gap Recovery | 95%区间 | 选择分布 |','|---|---:|---:|---|---|']
    for name,v in report['methods'].items(): lines.append(f"| {name} | {v['expected_quality']:.2%} | {v['gap_recovery']:.2%} | {v['gap_recovery_ci95']} | {v['selection_counts']} |")
    lines += ['','阈值仅由每个外层折的内部验证集选择。该115题集合按先前单次分歧富集，只用于方法开发；需要新的冻结样本确认。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n'); print(json.dumps(report,indent=2))

if __name__=='__main__': main()
