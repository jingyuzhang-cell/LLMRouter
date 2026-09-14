"""Independent artifact audit; does not call models or alter routing."""
import json
from collections import Counter
from pathlib import Path
from .core import OUT,sha,write,lines
from .run import verify

def main():
 protocol=verify();tasks=json.loads((OUT/'TASKS.json').read_text());plans=json.loads((OUT/'PLANS.json').read_text());records=lines(OUT/'NODES.jsonl');requests=lines(OUT/'REQUESTS.jsonl');metrics=json.loads((OUT/'PER_TASK.json').read_text());summary=json.loads((OUT/'RESULTS.json').read_text());checks=[]
 assert len(tasks)==len(plans)==len(metrics)==20
 assert len(records)==80 and len({(r['task_id'],r['node_id']) for r in records})==80
 assert len(requests)<=80 and len({(r['task_id'],r['node_id']) for r in requests})==len(requests)
 assert all(r['unix_time']>=protocol['created_unix'] for r in requests)
 checks.append('Unique nodes and request positions; frozen before any generation; <=80 requests')
 ri={(r['task_id'],r['node_id']):r for r in records};qi={(r['task_id'],r['node_id']):r for r in requests}
 for task,plan,metric in zip(tasks,plans,metrics):
  tid=task['task_id'];assert tid==plan['task_id']==metric['task_id']
  for node in plan['nodes']:
   key=tid,node['id'];r=ri[key]
   assert r['model']==node['model']
   c=node['predictions'];assert node['model']==max(sorted(c),key=lambda s:c[s]['score'])
   if r['status']=='blocked_dependency':
    assert key not in qi and any(ri[(tid,d)]['status']!='schema_valid' for d in node['deps'])
   else:
    assert key in qi and qi[key]['model']==r['model']
    assert qi[key]['prompt_sha256']==__import__('hashlib').sha256(qi[key]['prompt'].encode()).hexdigest()
    for d in node['deps']:
     assert ri[(tid,d)]['status']=='schema_valid'
     assert qi[key]['unix_time']>=ri[(tid,d)]['end_unix']
    if r.get('usage'):
     u=r['usage'];assert u['total_tokens']==u['prompt_tokens']+u['completion_tokens']
  x=task['input'];count=sum(x['departments'])+x['reserve']-x['stock'];feasible=[]
  for s in x['suppliers']:
   charge=(s['unit_cents']-s['discount_cents'])*count+s['freight_cents']+s['handling_cents']
   if s['capacity']>=count and s['days']<=x['deadline_days'] and charge<=x['budget_cents']:feasible.append((charge,s['vendor']))
  total,vendor=min(feasible) if feasible else (0,'NONE');expected=dict(vendor=vendor,total_cents=total)
  assert metric['expected']==expected
  final=ri[(tid,'decision')].get('parsed');infra=any(ri[(tid,n['id'])]['status']=='infrastructure_failure' for n in plan['nodes'])
  q=None if infra else sum(final.get(k)==v for k,v in expected.items())/2 if final else 0.
  assert metric['quality']==q and metric['task_success']==(q==1)
  assert metric['known_tokens']==sum((ri[(tid,n['id'])].get('usage') or {}).get('total_tokens',0) for n in plan['nodes'])
 checks.extend(['Assignments match frozen initial utility argmax','Dependency completion precedes downstream submission; blocked nodes never sent','Independent integer procurement scoring reproduces final quality','Recorded token accounting reconciles'])
 assert summary['task_success_rate']==sum(r['task_success'] for r in metrics)/20
 assert summary['total_known_tokens']==sum(r['known_tokens'] for r in metrics)
 assert summary['node_status_counts']==dict(Counter(r['status'] for r in records))
 assert summary['failure_recovery_rate'] is None and summary['pareto_hypervolume'] is None
 write(OUT/'VALIDATION.json',dict(passed=True,checks=checks,requests=len(requests),nodes=len(records),validator_sha256=sha(Path(__file__))))
 write(OUT/'ARTIFACT_MANIFEST.json',{p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name not in ['ARTIFACT_MANIFEST.json','MODEL_SERVER.log','EXECUTION.log']})
 print(json.dumps(dict(passed=True,requests=len(requests),checks=checks)))
if __name__=='__main__':main()
