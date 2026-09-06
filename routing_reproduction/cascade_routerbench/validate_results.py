"""Validate reports against raw offline outcomes, without rerunning optimization."""
import hashlib,json,pathlib,subprocess,sys
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
R=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(R/'cascade-routing/src'))
from selection.utils import auc_all
source=json.loads((R/'data/SOURCE.json').read_text())
for name,key in [('routerbench_0shot.pkl','sha256'),('routerbench_0shot.csv','csv_sha256')]:
 assert hashlib.sha256((R/'data'/name).read_bytes()).hexdigest()==source[key]
protocol=json.loads((R/'REPRO_PROTOCOL.json').read_text())
for repo,commit in protocol['repositories'].items():
 assert subprocess.check_output(['git','-C',str(R/repo),'rev-parse','HEAD'],text=True).strip()==commit
 assert not subprocess.check_output(['git','-C',str(R/repo),'diff','HEAD'],text=True).strip()
data=pd.read_csv(R/'data/routerbench_0shot.csv')
count=0;settings=[]
for p in sorted((R/'runs').glob('*/REPRO_RESULTS.json')):
 d=json.loads(p.read_text())
 if d['status'] not in ('PASS','FAIL'):continue
 m=d['metadata'];train=m['train_indices'];test=m['test_indices'];models=m['models']
 assert not set(train)&set(test)
 subset=data[data.eval_name.str.contains({'gsm8k':'grade-school-math'}.get(m['dataset'],m['dataset']),case=False,regex=False)]
 a,b=train_test_split(subset.index.to_numpy(),test_size=.95,random_state=42)
 assert list(a)==train and list(b)==test
 raw=json.loads(next((p.parent/'data/results/routerbench').glob('*.json')).read_text())
 for key,auc_key in [('test','aucs'),('cascade_test','aucs_cascade'),('router_test','aucs_router')]:
  recomputed=auc_all(raw[key]['quality'],raw[key]['cost'],raw['qualities_baseline'],raw['costs_baseline'])
  assert np.isclose(recomputed['auc'],raw[auc_key]['auc'])
 denom=data.loc[test,[x+'|total_cost' for x in models]].mean().max()
 for row in d['results']:
  assert row['sample_count']==len(test)
  key={'Routing':'router_test','Cascade':'cascade_test','Cascade Routing':'test'}.get(row['policy'])
  if key:
   i=row['point'];q=raw[key]['quality_all'][i];c=raw[key]['cost_all'][i]
   assert len(q)==len(c)==len(test)
   assert np.isclose(np.mean(q),row['quality'])
   assert np.isclose(np.sum(c),row['total_cost'])
   assert np.isclose(np.mean(c)/denom,row['normalized_cost'])
   auc={'Routing':'aucs_router','Cascade':'aucs_cascade','Cascade Routing':'aucs'}[row['policy']]
   assert row['auc']==raw[auc]['auc']
   count+=1
  elif row['policy']=='Oracle':assert np.isclose(row['quality'],data.loc[test,models].max(axis=1).mean())
  else:
   best=data.loc[train,models].mean().idxmax()
   assert best==d['static_model']
   assert np.isclose(row['quality'],data.loc[test,best].mean())
   assert np.isclose(row['total_cost'],data.loc[test,best+'|total_cost'].sum())
 settings.append(p.parent.name)
result=dict(status='PASS' if len(settings)==9 else 'PASS_FOR_COMPLETED_RUNS',completed_settings=settings,curve_points=count,checks=['data SHA256','repository commits and no tracked edits','exact original split','sample counts','per-sample quality and total/normalized cost','upstream AUC recomputed from raw curves','training-selected Static and Oracle'])
(R/'VALIDATION.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
