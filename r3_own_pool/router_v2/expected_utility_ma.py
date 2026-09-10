"""Expected quality/utility difference with an explicit uncertainty head.

400-query MMLU supervision, fold-local train-only development. No hard labels.
"""
import argparse,json
from pathlib import Path
import numpy as np
import torch
from torch import nn
from sklearn.linear_model import Ridge
from sklearn.decomposition import TruncatedSVD
from .anchored_ma import AnchoredMA
from .data import sha
from .diagnose_rank_signal import load_inputs
from .report_gap_recovery import gap_summary

SEEDS=(42,43,44)


class MeanVarianceMA(nn.Module):
 def __init__(self,dim,seed):
  super().__init__();self.mean=AnchoredMA(dim,seed)
  self.variance_query=nn.Sequential(nn.Linear(dim+4,16),nn.Tanh(),nn.Linear(16,16))
  nn.init.zeros_(self.variance_query[-1].weight);nn.init.zeros_(self.variance_query[-1].bias)
 def forward(self,x,base):
  mean=self.mean(x,base)
  z=self.variance_query(torch.cat([x,base],dim=1))@self.mean.model.T
  variance=.001+.06*torch.sigmoid(z)
  return mean,variance


def pair_difference(mean,variance,i=3,j=2):
 return mean[:,i]-mean[:,j],variance[:,i]+variance[:,j]


def fit(x,base,xe,be,target,variance,seed,weighted):
 model=MeanVarianceMA(x.shape[1],seed);opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
 x,base,xe,be,target,variance=[torch.tensor(v,dtype=torch.float32) for v in (x,base,xe,be,target,variance)]
 rng=np.random.default_rng(seed)
 for epoch in range(15):
  for idx in np.array_split(rng.permutation(len(x)),max(1,int(np.ceil(len(x)/64)))):
   mean,var=model(x[idx],base[idx]);delta,_=pair_difference(mean,var)
   true_delta=target[idx,1]-target[idx,0]
   loss=(delta-true_delta).square()
   if weighted:loss=loss/(variance[idx].sum(1).clamp_min(.01))
   loss=loss.mean()+.1*(mean[:,2:4].mean(1)-target[idx].mean(1)).square().mean()
   loss=loss+.1*(torch.log(var[:,2:4])-torch.log(variance[idx])).square().mean()+.1*(mean-base[idx]).square().mean()
   opt.zero_grad();loss.backward();opt.step()
 model.eval()
 with torch.no_grad():m,v=model(xe,be)
 return m.clamp(0,1).numpy(),v.numpy()


def load_data(panel_dir,data_dir):
 p=Path(panel_dir);d=Path(data_dir);manifest=json.loads((p/'MANIFEST.json').read_text());status=json.loads((d/'DISTRIBUTION_STATUS.json').read_text())
 if not status['complete'] or status['n_complete']!=400:raise ValueError('All 400 expected-utility distributions must be complete before training')
 if status['panel_manifest_sha256']!=sha(p/'MANIFEST.json') or status['label_sha256']!=sha(d/'EXPECTED_UTILITY_LABELS.jsonl'):raise ValueError('Label binding changed')
 for slot,h in status['raw_sha256'].items():
  if sha(d/(slot+'.jsonl'))!=h:raise ValueError('Raw generations changed')
 for n,h in manifest['files'].items():
  if sha(p/n)!=h:raise ValueError('Panel changed')
 rows=[json.loads(s) for s in (d/'EXPECTED_UTILITY_LABELS.jsonl').read_text().splitlines()]
 labels={r['query_id']:r for r in rows}
 if len(labels)!=400:raise ValueError('Duplicate or missing query')
 return manifest,labels


def main():
 ap=argparse.ArgumentParser(description=__doc__)
 for n in ['panel-dir','data-dir','output']:ap.add_argument('--'+n,required=True)
 ap.add_argument('--learnability-report',help='P1 result directory; required before any MA fit')
 a=ap.parse_args()
 if not a.learnability_report:raise ValueError('P1 learnability analysis is required before MA training')
 lr=Path(a.learnability_report);decision=json.loads((lr/'RESULTS.json').read_text());lp=json.loads((lr/'PROTOCOL.json').read_text())
 if decision.get('signal_gate_pass') is not True:raise ValueError('P1 did not establish incremental query signal; MA remains paused')
 status_path=Path(a.data_dir)/'DISTRIBUTION_STATUS.json'
 if lp['inputs'].get(str(status_path)) != sha(status_path) and lp['inputs'].get(str(status_path.resolve())) != sha(status_path):raise ValueError('P1 data does not match current distributions')
 torch.set_num_threads(4);manifest,labels=load_data(a.panel_dir,a.data_dir)
 p=Path(a.panel_dir);source=Path(manifest['source'])
 for n,h in manifest['source_files'].items():
  if sha(source/n)!=h:raise ValueError('Source changed')
 f,x,ds=load_inputs(source);ids=f['ids'];y=f['quality'];folds=f['folds'];n=len(ids)
 if sha(manifest['groups'])!=manifest['groups_sha256']:raise ValueError('Groups changed')
 g=json.loads(Path(manifest['groups']).read_text());groups=np.array([g['groups'][q] for q in ids])
 selection=json.loads((p/'FOLD_SELECTION.json').read_text());out=Path(a.output);out.mkdir(exist_ok=False)
 protocol=dict(role='MMLU_expected_difference_development',epochs=15,seeds=SEEDS,architecture='AnchoredMA mean unchanged; shared model-embedding variance head added',
  regression_target='reasoning-minus-large expected quality, Beta(1,1) posterior mean; no winner classes',
  arms=['raw_expected_difference','repeat_expected_difference','repeat_uncertainty_weighted','repeat_uncertainty_guarded'],
  primary='Gap Recovery relative to unchanged full objective DatasetBest/Oracle, 2975 queries; only MMLU decisions may change',
  uncertainty='Predict posterior mean-estimation variance; not certified epistemic calibration. Guard adds .25*predicted delta standard deviation.',
  preferences=[dict(lambda_ktokens=0.,mu_seconds=0.),dict(lambda_ktokens=.01,mu_seconds=0.),dict(lambda_ktokens=0.,mu_seconds=.001)],
  resource_heads='Ridge log1p mean total ktokens / latency seconds trained on outer training repeat records only',
  threshold=.05,limits=['Temperature .7 supervision transfer to temperature0 objective outcomes.',
   'Token penalty is not monetary cost. Mixed-deployment timing remains exploratory.',
   'Fixed hyperparameters before run, no selection on outer folds.',
   'Original test is retired; this is development only.'],
  inputs={str(q):sha(q) for q in [p/'MANIFEST.json',Path(a.data_dir)/'DISTRIBUTION_STATUS.json',Path(__file__),Path(__file__).with_name('anchored_ma.py'),source/'RESULTS.json']})
 (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2)+'\n')
 choices={};trace=[];calibration=[]
 for fold in sorted(np.unique(folds)):
  tr=np.flatnonzero(folds!=fold);va=np.flatnonzero((folds==fold)&(ds=='mmlupro'));sel=selection[str(fold)]
  if not set(sel)<=set(ids[tr]) or set(groups[tr])&set(groups[va]):raise ValueError('Outer fold leakage')
  selected=np.array([i for i in tr if ids[i] in sel],int)
  ridge=Ridge(alpha=20).fit(x[tr],y[tr]);bt=ridge.predict(x[selected]).clip(0,1);be=ridge.predict(x[va]).clip(0,1)
  svd=TruncatedSVD(n_components=64,random_state=42).fit(x[tr]);z=svd.transform(x[tr]);mean=z.mean(0);scale=np.maximum(z.std(0),.01)
  zt=(svd.transform(x[selected])-mean)/scale;ze=(svd.transform(x[va])-mean)/scale
  distributions=[[labels[ids[i]]['distributions'][s] for s in ('large','reasoning')] for i in selected]
  target=np.array([[d['posterior_mean'] for d in row] for row in distributions]);var=np.array([[d['posterior_mean_variance'] for d in row] for row in distributions])
  raw_target=(y[selected,2:4]+1)/3;raw_variance=np.full_like(raw_target,1/18)
  resources=[]
  for name in ['mean_total_ktokens','mean_latency_seconds']:
   values=np.array([[r[name] for r in row] for row in distributions],float)
   if not np.isfinite(values).all():raise ValueError('Missing resource labels; no imputation')
   resources.append(np.expm1(Ridge(alpha=20).fit(zt,np.log1p(values)).predict(ze)).clip(0,None))
  for seed in SEEDS:
   predictions={}
   for arm,t,v,weighted in [('raw_expected_difference',raw_target,raw_variance,False),('repeat_expected_difference',target,var,False),('repeat_uncertainty_weighted',target,var,True)]:
    predictions[arm]=fit(zt,bt,ze,be,t,v,seed,weighted)
   predictions['repeat_uncertainty_guarded']=predictions['repeat_uncertainty_weighted']
   observed=np.array([j for j,q in enumerate(ids[va]) if q in labels],int)
   if len(observed):
    truth=np.array([labels[ids[va[j]]]['target']['delta_quality_empirical'] for j in observed])
    for arm,(mp,vp) in predictions.items():
     delta=mp[observed,3]-mp[observed,2]
     calibration.append(dict(fold=int(fold),seed=seed,arm=arm,n=len(observed),rmse_to_held_repeat_mean=float(np.sqrt(np.mean((delta-truth)**2))),mean_predicted_delta_sd=float(np.sqrt(vp[observed,3]+vp[observed,2]).mean()),scope='Selection-conditioned held-repeat diagnostic; not independent population calibration'))
   np.savez_compressed(out/f'FOLD{fold}_SEED{seed}_PREDICTIONS.npz',ids=ids[va],predicted_ktokens=resources[0],predicted_latency_seconds=resources[1],**{name+'_'+kind:value for name,values in predictions.items() for kind,value in zip(['mean','mean_variance'],values)})
   for arm,(mq,vq) in predictions.items():
    for pref in protocol['preferences']:
     l,m=pref['lambda_ktokens'],pref['mu_seconds'];u=mq[:,2:4]-l*resources[0]-m*resources[1]
     best=u.argmax(1)+2;base=f['DatasetBest'][va]
     if not np.isin(base,[2,3]).all():raise ValueError('Expected MMLU pair baseline')
     advantage=u[np.arange(len(va)),best-2]-u[np.arange(len(va)),base-2]
     penalty=.25*np.sqrt(vq[:,2]+vq[:,3]) if arm=='repeat_uncertainty_guarded' else 0.
     c=np.where(advantage>.05+penalty,best,base)
     key=f'{arm}_l{l}_m{m}_seed{seed}'
     choices.setdefault(key,f['DatasetBest'].copy())[va]=c
   trace.append(dict(fold=int(fold),seed=seed,supervised_queries=len(selected)))
   print('fold',int(fold),'seed',seed,'done',flush=True)
 for q,h in protocol['inputs'].items():
  if sha(q)!=h:raise ValueError('Input changed during training')
 ix=np.arange(n);reference=y[ix,f['DatasetBest']];opp=y.max(1)-reference;results={}
 for arm in protocol['arms']:
  for pref in protocol['preferences']:
   l,m=pref['lambda_ktokens'],pref['mu_seconds'];keys=[f'{arm}_l{l}_m{m}_seed{s}' for s in SEEDS]
   actual=np.array([y[ix,choices[k]] for k in keys]);results[f'{arm}_l{l}_m{m}']=dict(quality=float(actual.mean()),**gap_summary(actual-reference,opp,groups))
 np.savez_compressed(out/'CHOICES.npz',ids=ids,**choices)
 (out/'RESULTS.json').write_text(json.dumps(dict(methods=results,trace=trace,held_repeat_diagnostics=calibration,files={k:sha(out/k) for k in ['PROTOCOL.json','CHOICES.npz']}),indent=2)+'\n')
 print(json.dumps(results,indent=2))

if __name__=='__main__':main()
