"""Four-model repeat-label routing with the frozen fold-local panel protocol."""
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
import torch

from .data import read_rows, sha
from .diagnose_rank_signal import load_inputs
from .mmlu_learnability import group_ci, subject_from_query
from .train_repeat_pairwise_compatibility_115 import SEEDS, fit as fit_pairwise, inner_split, pairwise_ridge
from .train_two_stage_residual_gate_115 import THRESHOLDS, fit_gate, gate_probability, route

ROOT=Path(__file__).resolve().parents[1]
PANEL_DIR=ROOT/'router_v2/mmlu_utility_panel_400'
DATA=ROOT/'data/repeat_compatibility_400_rescore_v1'
OUT=ROOT/'router_v2/experiment_repeat_compatibility_400_fold_local'
SLOTS=['medium','large','coder','reasoning']


def summarize(y,choices,groups):
    row=np.arange(len(y)); baseline=y[row,choices['DatasetBest']]; oracle=y.max(1); gap=float((oracle-baseline).mean()); methods={}
    for name,choice in choices.items():
        actual=y[row,choice]; gain=actual-baseline; ci=group_ci(gain,groups)
        methods[name]={'expected_quality':float(actual.mean()),'gain':float(gain.mean()),'gain_ci95':ci,
          'gap_recovery':float(gain.mean()/gap),'gap_recovery_ci95':[float(v/gap) for v in ci],
          'rescued':int((gain>0).sum()),'harmed':int((gain<0).sum()),
          'selection_counts':dict(zip(SLOTS,np.bincount(choice,minlength=4).tolist()))}
    seed_actual=np.array([y[row,choices[f'RepeatPairwiseMA_seed{s}']] for s in SEEDS]); gain=seed_actual.mean(0)-baseline; ci=group_ci(gain,groups)
    methods['RepeatPairwiseMA_seed_mean']={'expected_quality':float(seed_actual.mean()),'gain':float(gain.mean()),'gain_ci95':ci,
      'gap_recovery':float(gain.mean()/gap),'gap_recovery_ci95':[float(v/gap) for v in ci]}
    return {'n':len(y),'oracle_expected_quality':float(oracle.mean()),'datasetbest_expected_quality':float(baseline.mean()),'oracle_gap':gap,'methods':methods}


def main():
    torch.set_num_threads(4)
    if OUT.exists(): raise FileExistsError(OUT)
    manifest=json.loads((PANEL_DIR/'MANIFEST.json').read_text()); status=json.loads((DATA/'STATUS.json').read_text()); labels_path=DATA/'EXPECTED_UTILITY_LABELS.jsonl'
    if sha(PANEL_DIR/'PANEL.jsonl')!=manifest['files']['PANEL.jsonl'] or sha(labels_path)!=status['labels_sha256']: raise ValueError('Panel or labels changed')
    panel={r['query_id']:r for r in read_rows(PANEL_DIR/'PANEL.jsonl')}; labels={r['query_id']:r for r in read_rows(labels_path)}
    if set(panel)!=set(labels) or len(panel)!=400: raise ValueError('Panel/label mismatch')
    source=Path(manifest['source'])
    for name,digest in manifest['source_files'].items():
        if sha(source/name)!=digest: raise ValueError(f'Frozen source changed: {name}')
    features,x_all,_=load_inputs(source); source_index={q:i for i,q in enumerate(features['ids'])}; ids=np.array(sorted(panel)); ix=np.array([source_index[q] for q in ids]); x=x_all[ix].astype('float32'); folds=features['folds'][ix]
    y=np.array([[labels[q]['models'][slot]['mean'] for slot in SLOTS] for q in ids],dtype='float32')
    grouping=json.loads(Path(manifest['groups']).read_text())['groups']; groups=np.array([grouping[q] for q in ids]); subjects=np.array([subject_from_query(panel[q]['query']) for q in ids]); selection=json.loads((PANEL_DIR/'FOLD_SELECTION.json').read_text())
    names=['BestSingle','DatasetBest','QueryOnlyRidge','PairwiseRidge','TwoStageResidualGate']+[f'RepeatPairwiseMA_seed{s}' for s in SEEDS]
    choices={name:np.empty(len(ids),dtype=int) for name in names}; trace=[]; OUT.mkdir(parents=True)
    for fold in sorted(np.unique(folds)):
        development=np.array([i for i,q in enumerate(ids) if q in selection[str(int(fold))]],dtype=int); test=np.flatnonzero(folds==fold)
        if np.any(folds[development]==fold) or set(groups[development])&set(groups[test]): raise ValueError('Outer fold leakage')
        train,validation=inner_split(development,subjects,int(fold))
        if set(groups[train])&set(groups[validation]): raise ValueError('Inner fold leakage')
        best=int(y[development].mean(0).argmax()); choices['BestSingle'][test]=choices['DatasetBest'][test]=best
        pred=Ridge(alpha=1.0).fit(x[development],y[development]).predict(x[test]); choices['QueryOnlyRidge'][test]=pred.argmax(1)
        pred=pairwise_ridge(x,y,development,test); choices['PairwiseRidge'][test]=pred.argmax(1)
        fit_details={}
        for seed in SEEDS:
            pred,state,detail=fit_pairwise(x,y,train,validation,development,test,seed); name=f'RepeatPairwiseMA_seed{seed}'; choices[name][test]=pred.argmax(1); torch.save(state,OUT/f'model_fold{int(fold)}_seed{seed}.pt'); fit_details[str(seed)]=detail
        gate_target=y[:,:3].max(1)>y[:,3]; gate,constant=fit_gate(x,gate_target,train); pval=gate_probability(gate,constant,x[validation]); delta=y[:,:3]-y[:,[3]]; rmodel=Ridge(alpha=1.0).fit(x[train],delta[train]); rval=rmodel.predict(x[validation])
        utilities=[]
        for threshold in THRESHOLDS:
            choice=route(pval,rval,float(threshold)); utilities.append(float(y[validation,choice].mean()))
        best_utility=max(utilities); threshold=float(max(t for t,u in zip(THRESHOLDS,utilities) if np.isclose(u,best_utility)))
        gate,constant=fit_gate(x,gate_target,development); ptest=gate_probability(gate,constant,x[test]); rmodel=Ridge(alpha=1.0).fit(x[development],delta[development]); choices['TwoStageResidualGate'][test]=route(ptest,rmodel.predict(x[test]),threshold)
        trace.append({'fold':int(fold),'development_ids':ids[development].tolist(),'inner_train_ids':ids[train].tolist(),'inner_validation_ids':ids[validation].tolist(),'test_ids':ids[test].tolist(),
          'gate_positives':{'train':int(gate_target[train].sum()),'validation':int(gate_target[validation].sum()),'test':int(gate_target[test].sum())},'gate_threshold':threshold,'gate_validation_expected_quality':best_utility,'pairwise_fit':fit_details})
        print('finished fold',int(fold),flush=True)
    report=summarize(y,choices,groups)
    protocol={'role':'selected-panel fold-local method-development diagnostic; not representative or final test',
      'outer_training':'frozen per-fold allowlists from FOLD_SELECTION.json; each evaluation query uses its source OOF fold',
      'inner_validation':'subject-stratified 20% within the fold-local development allowlist',
      'methods':['BestSingle','DatasetBest','QueryOnlyRidge','PairwiseRidge','RepeatPairwiseMA 3 seeds','TwoStageResidualGate'],
      'pairwise_target':'0.5+(mean_i-mean_j)/2 soft-label BCE','gate':'class-balanced any-alternative-beats-R1 logistic; fixed threshold grid selected on inner validation; residual Ridge alternative selector',
      'source_sha256':{'manifest':sha(PANEL_DIR/'MANIFEST.json'),'selection':sha(PANEL_DIR/'FOLD_SELECTION.json'),'labels':sha(labels_path),'trainer':sha(Path(__file__))},
      'limits':['Opportunity-enriched development panel; no population-level MMLU claim.','Five repeats add label precision but not independent query count.','A newly frozen representative panel is required after method selection.']}
    (OUT/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2)+'\n'); (OUT/'RESULTS.json').write_text(json.dumps(report,indent=2)+'\n'); (OUT/'FOLDS.json').write_text(json.dumps(trace,indent=2)+'\n'); np.savez_compressed(OUT/'PREDICTIONS.npz',ids=ids,folds=folds,quality=y,**{f'choice_{k}':v for k,v in choices.items()})
    lines=['# 400题五次重复标签：四模型兼容性路由','',f"Oracle={report['oracle_expected_quality']:.2%}；DatasetBest={report['datasetbest_expected_quality']:.2%}；Gap={report['oracle_gap']:.2%}。",'','| 方法 | Expected quality | Gap Recovery | 95%区间 | Rescued/Harmed | 选择分布 |','|---|---:|---:|---|---:|---|']
    for name,v in report['methods'].items(): lines.append(f"| {name} | {v['expected_quality']:.2%} | {v['gap_recovery']:.2%} | {v['gap_recovery_ci95']} | {v.get('rescued','-')}/{v.get('harmed','-')} | {v.get('selection_counts','-')} |")
    lines+=['','该面板按训练折机会富集，只用于方法开发。外层训练使用冻结 allowlist，内部验证选择 epoch/门限；需要新的代表性冻结 panel 做确认。']; (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n'); print(json.dumps(report,indent=2))

if __name__=='__main__': main()
