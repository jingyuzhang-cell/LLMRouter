import json
from pathlib import Path
from collections import Counter
import numpy as np
from scipy.special import betainc
from scipy.integrate import quad
from scipy.stats import beta
from router_v2.diagnose_rank_signal import load_inputs
source=Path('router_v2/objective_verified_20260910');f,x,ds=load_inputs(source)
y=f['quality'];n=len(y);i=np.arange(n);b=f['DatasetBest'];base=y[i,b];opp=y.max(1)-base;p=f['predicted_quality']
upperpair=y[:,2:4].max(1)-base
reachable=np.zeros(n,bool)
for j in (2,3):
 reachable |= (y[:,j]>base)&(j!=b)&(p[:,j]+.1-(p[i,b]-.1)>.05)
labels=[json.loads(s) for s in Path('data/repeat_fold_stability_20260910/STABLE_LABELS.jsonl').read_text().splitlines()]
rows=[]
for r in labels:
 a=1+5*r['reasoning_quality_mean'];bb=6-5*r['reasoning_quality_mean'];c=1+5*r['large_quality_mean'];d=6-5*r['large_quality_mean']
 prob=quad(lambda z:beta.pdf(z,a,bb)*betainc(c,d,z),0,1)[0]
 rows.append(dict(query_id=r['query_id'],posterior_r_better=prob,empirical_margin=r['reasoning_quality_mean']-r['large_quality_mean']))
result=dict(n=n,gap_queries=int(opp.sum()),target_20_net_queries=float(.2*opp.sum()),target_30_net_queries=float(.3*opp.sum()),pair_oracle_net_queries=int(upperpair.sum()),pair_oracle_recovery=float(upperpair.sum()/opp.sum()),bounded_adapter_reachable_opportunity_queries=int(reachable.sum()),by_dataset={d:dict(n=int((ds==d).sum()),gap_queries=int(opp[ds==d].sum()),pair_gap_queries=int(upperpair[ds==d].sum())) for d in sorted(set(ds))},repeats=dict(queries=len(rows),nonzero_mean_margin=sum(r['empirical_margin']!=0 for r in rows),hard_stable=8,posterior_80_direction_counts=dict(Counter('reasoning' if r['posterior_r_better']>=.8 else 'large' if r['posterior_r_better']<=.2 else 'uncertain' for r in rows))))
out=Path('router_v2/gap_capacity_20260910');out.mkdir(exist_ok=True);(out/'RESULTS.json').write_text(json.dumps(result,indent=2));(out/'POSTERIOR_DIAGNOSTIC.json').write_text(json.dumps(rows,indent=2));print(json.dumps(result,indent=2))
