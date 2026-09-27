"""Read-only recomputation of existing artifacts; no execution engine imports or model calls."""
import json, math, statistics as st
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
B=ROOT/'static_dag_v0'; A=B/'adaptive_benchmark'
def read(p):return json.loads(p.read_text())
def mean(rows,key):return st.mean(float(r[key]) for r in rows.values())
def pair(a,b):
 h=sum(a[u]['ok'] and not b[u]['ok'] for u in a);d=sum(b[u]['ok'] and not a[u]['ok'] for u in a);n=h+d
 return dict(help=h,harm=d,p=min(1,2*sum(math.comb(n,k) for k in range(min(h,d)+1))/2**n) if n else 1)
seeds=(20260923,20260924,20260925)
f=read(B/'frozen200/FROZEN200_RESULTS.json')['results']; summary={}
for arm in ('single','static','dynamic'):
 rows=[f[f'f30_s{s}|{arm}'] for s in seeds];qs=[mean(r,'ok') for r in rows]
 summary[arm]=dict(clean={k:mean(f[f'clean|{arm}'],k) for k in ('ok','used','lat')},fault_q=qs,mean=st.mean(qs),population_std=st.pstdev(qs),sample_std=st.stdev(qs),fault_cost=st.mean(mean(r,'used') for r in rows),fault_latency=st.mean(mean(r,'lat') for r in rows))
fs={}
for s in seeds:
 a=f[f'f30_s{s}|single'];d=f[f'f30_s{s}|dynamic'];c=f['clean|single']; t=f[f'f30_s{s}|static']
 groups={'survived':[u for u in c if c[u]['ok'] and a[u]['ok']], 'broken':[u for u in c if c[u]['ok'] and not a[u]['ok']], 'clean_wrong':[u for u in c if not c[u]['ok']]}
 fs[s]=dict(dynamic_vs_static=pair(d,t),dynamic_vs_single=pair(d,a),groups={k:dict(n=len(us),dynamic_correct=sum(d[u]['ok'] for u in us)) for k,us in groups.items()},oracle_union=sum(a[u]['ok'] or d[u]['ok'] for u in a),zero_cost_fault_tasks=sum(r.get('injected',False) and r['used']==0 for r in a.values()))
# Panel identity audit and exact McNemar consistency check.
old_frozen={r['task_id'] for r in read(B/'frozen_eval/FROZEN_TASKS_200.json')}
new_frozen={r['uid'] for r in read(B/'frozen200/FROZEN200_POLICY.json')['tasks']}
main_uids={r['uid'] for r in read(B/'multidag_dynamic_120/POLICY.json')['tasks']}
panel_identity=dict(two_frozen_overlap=len(old_frozen & new_frozen),main120_overlap=len(main_uids & new_frozen))
oof_exact_p=2*sum(math.comb(30,k) for k in range(11))/2**30
# Exact configuration raw summaries (not a validation of execution semantics).
e=read(A/'exact_pareto/CONFIG_RESULTS.json')['results'];ep={}
for cfg,ss in e.items():
 ep[cfg]={k:st.mean(mean(rows,key) for rows in ss.values()) for k,key in [('Q','ok'),('C','used'),('L','lat')]}
def front(pts,keys):
 return [m for m in pts if not any(all((pts[o][k]>=pts[m][k] if k=='Q' else pts[o][k]<=pts[m][k]) for k in keys) and any(pts[o][k]!=pts[m][k] for k in keys) for o in pts if o!=m)]
# Replicate deployed seed-calibration selection, without invoking source scripts (which write results).
clean=read(A/'CLEAN_RESULTS.json');uids=list(clean['router']);pool=('router','static','dynamic');rates=(0,.1,.2,.3);budgets=(600,800,1000,1200,1500,2000,2500,3000)
perf={}
for rate in rates:
 for seed in seeds:
  rows=clean if rate==0 else read(A/(f'fault_p{int(rate*100)}'+('' if seed==20260923 else f'_seed{seed}'))/'FAULT_RESULT.json')
  perf[rate,seed]={m:dict(Q=mean(rows[m],'ok'),C=mean(rows[m],'used'),qb={b:sum(rows[m][u]['ok'] and rows[m][u]['used']<=b for u in uids)/len(uids) for b in budgets}) for m in pool}
grid=[]
for r in rates:
 for b in budgets:
  vals=[];fixed={m:[] for m in pool};choices=[]
  for test in seeds:
   cal=[s for s in seeds if s!=test];pts={m:{k:st.mean(perf[r,s][m][k] for s in cal) for k in ('Q','C')} for m in pool};fr=front(pts,('Q','C'))
   score={m:st.mean(perf[r,s][m]['qb'][b] for s in cal) for m in fr};best=max(score.values());pick=min((m for m in fr if score[m]==best),key=lambda m:pts[m]['C'])
   vals.append(perf[r,test][pick]['qb'][b]);choices.append(pick)
   for m in pool:fixed[m].append(perf[r,test][m]['qb'][b])
  fm={m:st.mean(v) for m,v in fixed.items()};sel=st.mean(vals)
  grid.append(dict(rate=r,budget=b,selector=sel,fixed=fm,choices=choices,below_best_fixed=sel<max(fm.values())-1e-12))
# latest() in exact_pareto.py selects base-prefix keys, not ep: prefixed execution keys.
keys=['e1:task','e2:task','r:task','v:task','ep:r:task:large_medium_none_20260923','ep:v:task:large_medium_none_20260923']
exact_key_check={p:[k for k in keys if k.split(':')[0]==p][-1] for p in ('r','v')}
out=dict(panel_identity=panel_identity,oof_20_10_exact_p=oof_exact_p,frozen_summary=summary,frozen_per_seed=fs,exact_recorded_summary=ep,exact_recorded_front2d=front(ep,('Q','C')),exact_recorded_front3d=front(ep,('Q','C','L')),exact_prefix_check=exact_key_check,scheduler_grid=grid,scheduler_counterexamples=[x for x in grid if x['below_best_fixed']],scheduler_grid_mean=st.mean(x['selector'] for x in grid))
path=Path(__file__).with_name('RECOMPUTED_AUDIT.json');path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k not in ('exact_recorded_summary','scheduler_grid')},ensure_ascii=False,indent=2))
