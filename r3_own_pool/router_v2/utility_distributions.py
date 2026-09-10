"""Repeated quality distributions and component differences; no winner filtering."""
import argparse,json,math,fcntl
from pathlib import Path
import numpy as np
from .data import sha
from . import run_repeat_stability as engine


def distribution(rows):
 q=np.array([r['quality'] for r in rows],float)
 if len(q)<2 or not np.isin(q,[0.,1.]).all():raise ValueError('At least two valid binary repeats required')
 n=len(q);k=int(q.sum());a,b=k+1,n-k+1
 result=dict(n=n,successes=k,empirical_mean=float(q.mean()),
  empirical_outcome_variance=float(q.var(ddof=1)),empirical_mean_variance=float(q.var(ddof=1)/n),
  posterior_mean=a/(a+b),posterior_mean_variance=a*b/((a+b)**2*(a+b+1)),
  beta_prior=[1,1],beta_posterior=[a,b])
 costs=[(r.get('cost') or {}).get('tokens_input') for r in rows];outputs=[(r.get('cost') or {}).get('tokens_output') for r in rows]
 times=[(r.get('latency') or {}).get('total_ms') for r in rows]
 def valid(v):return all(isinstance(z,(int,float)) and math.isfinite(z) and z>=0 for z in v)
 tokens=(np.array(costs)+np.array(outputs))/1000 if valid(costs) and valid(outputs) else None
 seconds=np.array(times)/1000 if valid(times) else None
 result['mean_total_ktokens']=float(tokens.mean()) if tokens is not None else None
 result['mean_latency_seconds']=float(seconds.mean()) if seconds is not None else None
 result['component_sample_covariance']=np.cov(np.stack([q,tokens,seconds],axis=1),rowvar=False,ddof=1).tolist() if tokens is not None and seconds is not None else None
 return result


def pair_target(large,reasoning):
 def delta(k):return reasoning[k]-large[k] if reasoning[k] is not None and large[k] is not None else None
 return dict(delta_quality_empirical=delta('empirical_mean'),delta_quality_posterior=delta('posterior_mean'),
  delta_quality_mean_variance=reasoning['posterior_mean_variance']+large['posterior_mean_variance'],
  delta_total_ktokens=delta('mean_total_ktokens'),delta_latency_seconds=delta('mean_latency_seconds'))


def expected_difference(pair,lambda_tokens=0.,mu_seconds=0.):
 t=pair['target'];value=t['delta_quality_posterior']
 for weight,key in [(lambda_tokens,'delta_total_ktokens'),(mu_seconds,'delta_latency_seconds')]:
  if weight and t[key] is None:raise ValueError('Missing utility component; no implicit zero')
  if weight:value-=weight*t[key]
 return value


def run(panel_dir,data_dir):
 panel_dir=Path(panel_dir);d=Path(data_dir);manifest=json.loads((panel_dir/'MANIFEST.json').read_text())
 for n,h in manifest['files'].items():
  if sha(panel_dir/n)!=h:raise ValueError('Panel changed')
 panel={r['query_id']:r for r in engine.bind_panel(engine.read_jsonl(panel_dir/'PANEL.jsonl'),engine.ROOT/'data/cohort_full_v2')}
 protocol=json.loads((d/'COLLECTION_PROTOCOL.json').read_text())
 if protocol['panel_sha256']!=sha(panel_dir/'PANEL.jsonl'):raise ValueError('Collection panel mismatch')
 grouped={s:{} for s in ['large','reasoning']};invalid={s:0 for s in grouped}
 for slot in grouped:
  raw_path=d/(slot+'.jsonl')
  if raw_path.exists():
   with raw_path.open() as stream:
    fcntl.flock(stream,fcntl.LOCK_SH);raw_rows=[json.loads(line) for line in stream if line.strip()]
  else:raw_rows=[]
  for r in raw_rows:
   if r['query_id'] not in panel:raise ValueError('Unknown query')
   if r['panel_sha256']!=protocol['panel_sha256'] or r['cohort_sha256']!=protocol['cohort_sha256']:raise ValueError('Response provenance mismatch')
   if r['slot']!=slot or r['temperature']!=protocol['temperature'] or r['top_p']!=protocol['top_p']:raise ValueError('Response protocol mismatch')
   if r['status']=='failed' or r.get('error') or r.get('quality') not in (0,1):invalid[slot]+=1;continue
   k=int(r['repeat_index'])
   if k not in range(5):raise ValueError('Repeat index outside budget')
   per=grouped[slot].setdefault(r['query_id'],{})
   if k in per:raise ValueError('Duplicate valid repeat')
   per[k]=r
 labels=[];missing=[]
 for q in sorted(panel):
  counts={s:len(grouped[s].get(q,{})) for s in grouped}
  if any(v!=5 for v in counts.values()):missing.append(dict(query_id=q,**counts));continue
  params={s:distribution(list(grouped[s][q].values())) for s in grouped}
  labels.append(dict(query_id=q,dataset='mmlupro',orientation='reasoning minus large',distributions=params,target=pair_target(params['large'],params['reasoning'])))
 path=d/'EXPECTED_UTILITY_LABELS.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in labels))
 status=dict(complete=len(labels)==len(panel),n_panel=len(panel),n_complete=len(labels),missing=missing,
  invalid_excluded=invalid,label_sha256=sha(path),panel_manifest_sha256=sha(panel_dir/'MANIFEST.json'),
  raw_sha256={s:sha(d/(s+'.jsonl')) for s in grouped if (d/(s+'.jsonl')).exists()},
  estimator='Independent Beta(1,1) posteriors for each Bernoulli success rate; no hard label filtering',
  caveats=['posterior mean variance is conditional on the prior and iid repeat assumption; not calibrated neural epistemic uncertainty',
           'total ktokens are a resource proxy, not money; latency is recorded mixed-deployment measurement',
           'sampling at temperature .7; transfer evaluation at temperature0 must be separately identified'])
 (d/'DISTRIBUTION_STATUS.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps({k:status[k] for k in ['complete','n_panel','n_complete','invalid_excluded']},indent=2))
 return status

if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--panel-dir',required=True);ap.add_argument('--data-dir',required=True)
 a=ap.parse_args();run(a.panel_dir,a.data_dir)
