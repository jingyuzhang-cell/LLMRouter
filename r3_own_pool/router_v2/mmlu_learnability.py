"""P1 before MA: repeat delta-Q distributions and fold-isolated simple baselines.

No architecture changes, API calls, or historical val/test labels. A selected
400-query panel is diagnostic, not a representative or independent benchmark.
"""
import argparse,json,re
from pathlib import Path
import numpy as np
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score
from .data import sha
from .diagnose_rank_signal import load_inputs
from . import run_repeat_stability as repeat


def validate_pairs(panel_dir,data_dir):
 p,d=Path(panel_dir),Path(data_dir)
 manifest=json.loads((p/'MANIFEST.json').read_text());status=json.loads((d/'DISTRIBUTION_STATUS.json').read_text())
 if not status['complete'] or status['n_complete']!=manifest['n_panel']:raise ValueError('P0 incomplete: all 400 paired distributions required before P1')
 if status['panel_manifest_sha256']!=sha(p/'MANIFEST.json') or status['label_sha256']!=sha(d/'EXPECTED_UTILITY_LABELS.jsonl'):raise ValueError('Distribution provenance mismatch')
 if set(status['raw_sha256'])!={'large','reasoning'}:raise ValueError('Both model raw files required')
 for s,h in status['raw_sha256'].items():
  if sha(d/(s+'.jsonl'))!=h:raise ValueError('Raw file changed; rebuild distributions')
 for n,h in manifest['files'].items():
  if sha(p/n)!=h:raise ValueError('Panel changed')
 labels={r['query_id']:r for r in repeat.read_jsonl(d/'EXPECTED_UTILITY_LABELS.jsonl')}
 if len(labels)!=manifest['n_panel']:raise ValueError('Duplicate or missing query')
 for q,row in labels.items():
  for s in ('large','reasoning'):
   values=row['distributions'][s]
   if values['n']!=5:raise ValueError('Exactly five scored repeats per slot required')
   for k in ('mean_total_ktokens','mean_latency_seconds'):
    if values.get(k) is None or not np.isfinite(values[k]):raise ValueError(f'Missing paired resource: {q}/{s}/{k}')
 return manifest,labels


def subject_from_query(text):
 m=re.match(r'Answer the following (.+?) question\.',text)
 return m.group(1).casefold() if m else 'unknown'


def subject_mean(train_subject,train_y,eval_subject,strength=20.):
 prior=float(np.mean(train_y));means={}
 for s in set(train_subject):
  values=train_y[train_subject==s];means[s]=(float(values.sum())+strength*prior)/(len(values)+strength)
 return np.array([means.get(s,prior) for s in eval_subject])


def group_ci(values,groups,seed=42):
 _,inv=np.unique(groups,return_inverse=True);n=int(inv.max())+1
 counts=np.bincount(inv);sums=np.bincount(inv,weights=values)
 samples=np.random.default_rng(seed).integers(0,n,size=(2000,n))
 return np.quantile(sums[samples].sum(1)/counts[samples].sum(1),[.025,.975]).tolist()


def metrics(pred,target):
 error=pred-target;variance=float(np.mean((target-target.mean())**2))
 correlation=float(spearmanr(pred,target).statistic) if np.std(pred)>1e-12 and np.std(target)>1e-12 else None
 nonzero=target!=0;direction=target[nonzero]>0
 auc=float(roc_auc_score(direction,pred[nonzero])) if len(np.unique(direction))==2 else None
 return dict(auc_on_nonzero_empirical_delta=auc,auc_n=int(nonzero.sum()),mse=float(np.mean(error**2)),mae=float(np.mean(np.abs(error))),
  r2=1-float(np.mean(error**2))/variance if variance else None,spearman=correlation,
  direction_accuracy_on_nonzero_empirical_delta=float(np.mean((pred[target!=0]>0)==(target[target!=0]>0))) if (target!=0).any() else None)


def main():
 ap=argparse.ArgumentParser(description=__doc__)
 for k in ['panel-dir','data-dir','output']:ap.add_argument('--'+k,required=True)
 a=ap.parse_args();p,d=Path(a.panel_dir),Path(a.data_dir);manifest,labels=validate_pairs(p,d)
 source=Path(manifest['source'])
 for n,h in manifest['source_files'].items():
  if sha(source/n)!=h:raise ValueError('Frozen source changed')
 f,x_all,_=load_inputs(source)
 if sha(manifest['groups'])!=manifest['groups_sha256']:raise ValueError('Group source changed')
 grouping=json.loads(Path(manifest['groups']).read_text())['groups']
 panels={r['query_id']:r for r in repeat.read_jsonl(p/'PANEL.jsonl')};selection=json.loads((p/'FOLD_SELECTION.json').read_text())
 ids=np.array(sorted(labels));index={q:i for i,q in enumerate(f['ids'])};source_index=np.array([index[q] for q in ids]);x=x_all[source_index];folds=f['folds'][source_index]
 groups=np.array([grouping[q] for q in ids]);subjects=np.array([subject_from_query(panels[q]['query']) for q in ids])
 y=np.array([labels[q]['target']['delta_quality_empirical'] for q in ids]);y=np.round(y,12)
 raw={s:{} for s in ('large','reasoning')}
 for s in raw:
  for r in repeat.read_jsonl(d/(s+'.jsonl')):
   if r['status']!='failed' and r.get('quality') in (0,1) and not r.get('error'):raw[s].setdefault(r['query_id'],{})[int(r['repeat_index'])]=r['quality']
 early=np.array([np.mean([raw['reasoning'][q][k] for k in [0,1]])-np.mean([raw['large'][q][k] for k in [0,1]]) for q in ids])
 late=np.array([np.mean([raw['reasoning'][q][k] for k in [2,3,4]])-np.mean([raw['large'][q][k] for k in [2,3,4]]) for q in ids])
 names=['TaskConstant','SubjectMeanShrink20','GTE_Ridge1','GTE_Ridge20']+[f'RandomDelta_seed{s}' for s in (42,43,44)]
 predictions={k:np.empty(len(y)) for k in names};null=np.empty((len(y),20));global_null=np.empty((len(y),20));trace=[]
 for fold in sorted(np.unique(folds)):
  tr=np.array([i for i,q in enumerate(ids) if q in selection[str(fold)]],int);va=np.flatnonzero(folds==fold)
  if set(folds[tr])=={fold} or any(folds[tr]==fold) or set(groups[tr])&set(groups[va]):raise ValueError('Fold leakage')
  predictions['TaskConstant'][va]=y[tr].mean();predictions['SubjectMeanShrink20'][va]=subject_mean(subjects[tr],y[tr],subjects[va])
  for seed in (42,43,44):predictions[f'RandomDelta_seed{seed}'][va]=np.random.default_rng(seed+int(fold)*1000).choice(y[tr],len(va),replace=True)
  shuffled=[]
  for seed in range(20):
   rng=np.random.default_rng(17000+100*int(fold)+seed);v=y[tr].copy()
   for s in sorted(set(subjects[tr])):
    at=np.flatnonzero(subjects[tr]==s);v[at]=rng.permutation(v[at])
   shuffled.append(v)
  global_shuffled=[np.random.default_rng(27000+100*int(fold)+seed).permutation(y[tr]) for seed in range(20)]
  fitted=Ridge(alpha=1.).fit(x[tr],np.column_stack([y[tr],*shuffled,*global_shuffled])).predict(x[va]).clip(-1,1)
  predictions['GTE_Ridge1'][va]=fitted[:,0];null[va]=fitted[:,1:21];global_null[va]=fitted[:,21:]
  predictions['GTE_Ridge20'][va]=Ridge(alpha=20.).fit(x[tr],y[tr]).predict(x[va]).clip(-1,1)
  trace.append(dict(fold=int(fold),n_train=len(tr),n_eval=len(va),train_ids=ids[tr].tolist(),evaluation_ids=ids[va].tolist()))
 results={name:metrics(pred,y) for name,pred in predictions.items()}
 for name,pred in predictions.items():
  paired=(predictions['SubjectMeanShrink20']-y)**2-(pred-y)**2
  results[name]['mse_reduction_vs_subject']=float(paired.mean());results[name]['mse_reduction_vs_subject_ci95']=group_ci(paired,groups)
 null_mse=np.mean((null-y[:,None])**2,axis=0)
 actual_mse=results['GTE_Ridge1']['mse']
 distribution=dict(n=len(y),delta_greater_than_point2=int((y>.2).sum()),delta_less_than_minus_point2=int((y<-.2).sum()),
  abs_delta_at_most_point05=int((np.abs(y)<=.05).sum()),exact_zero=int((y==0).sum()),quantiles=dict(zip(['min','p10','p25','median','p75','p90','max'],np.quantile(y,[0,.1,.25,.5,.75,.9,1]).tolist())),
  note='Five binary repeats give empirical delta in increments of .2; observed tie does not imply equal expected quality.',
  repeated_mean_sampling_variance=float(np.mean([sum(labels[q]['distributions'][s]['empirical_mean_variance'] for s in raw) for q in ids])))
 corr=float(np.corrcoef(early,late)[0,1]) if np.std(early)>0 and np.std(late)>0 else None
 rng=np.random.default_rng(942);posterior=[]
 for q in ids:
  lp=labels[q]['distributions']['large']['beta_posterior'];rp=labels[q]['distributions']['reasoning']['beta_posterior']
  delta=rng.beta(*rp,size=10000)-rng.beta(*lp,size=10000)
  posterior.append(dict(query_id=str(q),delta_ci95=np.quantile(delta,[.025,.975]).tolist(),probability_reasoning_better=float(np.mean(delta>0))))
 distribution['posterior_ci_excludes_zero']=sum(r['delta_ci95'][0]>0 or r['delta_ci95'][1]<0 for r in posterior)
 distribution['posterior_caveat']='Monte Carlo under independent Beta(1,1) priors; descriptive uncertainty, never used to filter training labels.'
 out=Path(a.output);out.mkdir(exist_ok=False)
 protocol=dict(role='P1_selected_panel_learnability_before_MA',primary='GTE_Ridge1 MSE versus subject baseline; same-query group-isolated outer evaluation',ridge_alphas=[1,20],shuffle_controls=20,global_shuffle_controls=20,
  supervision='400 paired repeat empirical quality differences; each fold uses its original fold-local selection only',
  resources='P0 requires both model quality, tokens, latency. Tokens are resource proxy, not verified monetary cost.',
  inputs={str(q):sha(q) for q in [p/'MANIFEST.json',d/'DISTRIBUTION_STATUS.json',Path(__file__)]},
  limits=['Selected opportunity-enriched panel; not representative of all MMLU-Pro and not independent confirmation.',
          'Coarse task is knowledge for all queries; task baseline is training-fold mean. Subject parsed from query only.',
          'Pairwise outcomes are noisy averages of five draws; prediction MSE includes sampling noise.',
          'Null labels shuffled within training subjects preserve task signals. Null rank is diagnostic, not a calibrated formal p-value.',
          'No MA or expected-utility router trained; no historical val/test outcomes loaded.'])
 report=dict(distribution=distribution,split_repeat_correlation=corr,methods=results,
  within_subject_shuffled_metrics=[metrics(null[:,k],y) for k in range(20)],
  global_shuffled_metrics=[metrics(global_null[:,k],y) for k in range(20)],
  within_subject_shuffled_ridge_mse=null_mse.tolist(),real_ridge_beats_null_runs=int((actual_mse<null_mse).sum()),
  signal_gate_pass=bool(results['GTE_Ridge1']['mse_reduction_vs_subject_ci95'][0]>0 and actual_mse<np.quantile(null_mse,.05)),
  gate_meaning='Development screening only; no automatic MA training or independent compatibility claim.')
 np.savez_compressed(out/'PREDICTIONS.npz',ids=ids,target_delta=y,early_delta=early,late_delta=late,**predictions,null_predictions=null,global_null_predictions=global_null)
 (out/'POSTERIOR_DIAGNOSTIC.json').write_text(json.dumps(posterior,indent=2)+'\n')
 (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2)+'\n');(out/'RESULTS.json').write_text(json.dumps(report,indent=2)+'\n');(out/'FOLDS.json').write_text(json.dumps(trace,indent=2)+'\n')
 lines=['# P1：400题ΔQ可学习性','','这是选题面板的开发诊断，尚未训练MA。','',json.dumps(distribution,ensure_ascii=False,indent=2),'',
 '| 基线 | MSE | MAE | R² | Spearman | AUC (nonzero ΔQ) |','|---|---:|---:|---:|---:|---:|']
 for name,r in results.items():lines.append(f"| {name} | {r['mse']:.5f} | {r['mae']:.5f} | {r['r2']} | {r['spearman']} | {r['auc_on_nonzero_empirical_delta']} |")
 lines+=['',f'前2次/后3次ΔQ相关系数：{corr}。',f"GTE_Ridge1优于{report['real_ridge_beats_null_runs']}/20个学科内打乱标签对照。",f"开发信号门禁：{report['signal_gate_pass']}。门禁通过也不自动启动MA。"]
 lines+=['', '## Shuffle Label controls', '', 'Held-fold targets remain unchanged; only training labels are shuffled. Within-subject controls preserve subject signal, so their Spearman need not be zero. Global controls may also fluctuate around chance in this small selected panel.', '', '| Control | Mean MSE | Mean Spearman | Mean AUC |', '|---|---:|---:|---:|']
 for name,key in [('Within subject','within_subject_shuffled_metrics'),('Global','global_shuffled_metrics')]:
  values=report[key]
  averages={k:float(np.mean([v[k] for v in values if v[k] is not None])) if any(v[k] is not None for v in values) else None for k in ['mse','spearman','auc_on_nonzero_empirical_delta']}
  lines.append(f"| {name} | {averages['mse']} | {averages['spearman']} | {averages['auc_on_nonzero_empirical_delta']} |")
 lines+=['', 'AUC excludes observed ties and is auxiliary; 0.65/0.75 are not proof thresholds or MA gates. All ties remain in regression. Neither a two-sided empirical distribution nor a nonzero shuffled correlation alone proves compatibility or leakage.']
 (out/'REPORT.md').write_text('\n'.join(lines)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
