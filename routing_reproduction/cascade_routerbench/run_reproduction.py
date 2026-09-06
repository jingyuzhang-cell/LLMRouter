"""Offline wrapper: upstream algorithm and settings remain unchanged."""
import argparse, hashlib, json, os, pathlib, runpy, sys
ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT

def dump(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False))

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', default='gsm8k')
    p.add_argument('--models', default='9,4,5')
    p.add_argument('--output-dir', default='.')
    a = p.parse_args()
    global OUT
    OUT = (ROOT / a.output_dir).resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    import numpy as np
    from sklearn.model_selection import train_test_split
    source = ROOT / 'data/routerbench_0shot.csv'
    if not source.exists():
        raise FileNotFoundError('Verified official data/routerbench_0shot.csv required')
    data = pd.read_csv(source)
    candidates = [c for c in data.columns if c in ('dataset', 'dataset_name', 'eval_name')]
    if len(candidates) != 1:
        raise ValueError(f'Inspect dataset schema before running: {list(data.columns[:3])}')
    dataset_key = {'gsm8k': 'grade-school-math'}.get(a.dataset.lower(), a.dataset)
    subset = data[data[candidates[0]].astype(str).str.contains(dataset_key, case=False, regex=False)].copy()
    if subset.empty:
        raise ValueError(f'No rows for {a.dataset}: {data[candidates[0]].unique()}')
    train, test = train_test_split(subset.index.to_numpy(), test_size=.95, random_state=42)
    names = list(data.columns[3:14])
    selected = [names[int(i)] for i in a.models.split(',')]
    meta = dict(dataset=a.dataset, models=selected, model_indices=a.models,
                sample_count=len(subset), train_count=len(train), test_count=len(test),
                train_indices=train.tolist(), test_indices=test.tolist(),
                seed=0, split_seed=42, noise_level='low', source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                adaptation='Filter requested dataset before the unchanged upstream 5/95 split; subset reproduction, not full-paper score.')
    dump('SMOKE_METADATA.json',meta)
    # Exact upstream experiment via a narrowly scoped input adapter; no algorithm edits.
    real_read = pd.read_csv
    def read_csv(path, *args, **kwargs):
        if str(path) == 'data/routerbench_0shot.csv':
            return subset.copy()
        return real_read(path,*args,**kwargs)
    pd.read_csv = read_csv
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import socket
    def deny_network(*args,**kwargs):
        raise RuntimeError('Network disabled during offline reproduction')
    socket.socket.connect = deny_network
    sys.path.insert(0,str(ROOT/'cascade-routing/src'))
    os.chdir(OUT)
    sys.argv = ['routerbench.py','--models',a.models,'--noise-level','low']
    runpy.run_path(str(ROOT/'cascade-routing/scripts/routerbench.py'),run_name='__main__')
    raw = json.loads((OUT/f'data/results/routerbench/{a.models}_low_0shot.json').read_text())
    rows=[]
    denom=float(subset.loc[test,[m+'|total_cost' for m in selected]].mean().max())
    for label,key,auc in [('Routing','router_test','aucs_router'),('Cascade','cascade_test','aucs_cascade'),('Cascade Routing','test','aucs')]:
        for i,(q,c) in enumerate(zip(raw[key]['quality'],raw[key]['cost'])):
            rows.append(dict(policy=label,point=i,quality=q,mean_cost=c,total_cost=c*len(test),normalized_cost=c/denom,auc=raw[auc]['auc'],sample_count=len(test)))
    best=subset.loc[train,selected].mean().idxmax()
    q=float(subset.loc[test,best].mean()); c=float(subset.loc[test,best+'|total_cost'].mean())
    rows.append(dict(policy='Best Single / Static',point=0,quality=q,mean_cost=c,total_cost=c*len(test),normalized_cost=c/denom,auc=None,sample_count=len(test)))
    oracle=float(subset.loc[test,selected].max(axis=1).mean())
    rows.append(dict(policy='Oracle',point=0,quality=oracle,mean_cost=None,total_cost=None,normalized_cost=None,auc=None,sample_count=len(test)))
    passed=raw['aucs']['auc']>raw['aucs_router']['auc'] and raw['aucs']['auc']>raw['aucs_cascade']['auc']
    pd.DataFrame(rows).to_csv(OUT/'REPRO_RESULTS.csv',index=False)
    dump('REPRO_RESULTS.json',dict(status='PASS' if passed else 'FAIL',scope=f'{a.dataset} {len(selected)}-model subset',results=rows,metadata=meta,static_model=best))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for label in ('Routing','Cascade','Cascade Routing'):
        rr=[r for r in rows if r['policy']==label]
        plt.plot([r['normalized_cost'] for r in rr],[r['quality'] for r in rr],marker='.',label=label)
    plt.scatter([c/denom],[q],label='Best Single / Static')
    plt.axhline(oracle,linestyle='--',label='Oracle quality upper bound')
    plt.xlabel('Mean cost / most expensive single-model mean cost')
    plt.ylabel('Mean quality'); plt.legend(); plt.tight_layout()
    for ext in ('png','pdf'): plt.savefig(OUT/f'fig_cost_quality_curve.{ext}')
    (OUT/'REPRO_SUMMARY.md').write_text(f'# {a.dataset} {len(selected)}-model subset reproduction: {"PASS" if passed else "FAIL"}\n\nTest samples: {len(test)}; train samples: {len(train)}. Seed 0; split seed 42.\n\nUses unmodified upstream algorithms and low-noise ground-truth estimators. This is a simulated-estimator experiment. AUC uses upstream integration; Static is a single point, Oracle a quality bound, so their AUC/cost respectively are undefined.\n\n'+pd.DataFrame(rows).to_string(index=False)+'\n')
if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        import traceback
        detail=traceback.format_exc()
        dump('REPRO_RESULTS.json',dict(status='EXECUTION_ERROR',results=[],error=str(exc),traceback=detail))
        (OUT/'REPRO_RESULTS.csv').write_text('policy,point,quality,mean_cost,total_cost,normalized_cost,auc,sample_count\n')
        (OUT/'REPRO_SUMMARY.md').write_text('# Reproduction not completed\n\nExecution error; no scientific PASS/FAIL conclusion. No results or curves fabricated.\n\n```\n'+detail+'```\n')
        raise
