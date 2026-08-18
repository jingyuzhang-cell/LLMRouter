#!/usr/bin/env python3
"""Paired confirmatory statistics for frozen Fin-RoME v3 policies."""
import hashlib,json,math
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data/finance_router/finrome_300_confirmatory_v3';RUN=ROOT/'run_logs/finrome_300_confirmatory_v3';OUT=RUN/'final_analysis';SEED=20260813;NBOOT=10000
def load(p):return json.loads(p.read_text())
def rows(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def metrics(rs):
 h=[x for x in rs if x['risk']=='high'];return {'n':len(rs),'utility':float(np.mean([x['utility'] for x in rs])),'failure_rate':float(np.mean([x['failure'] for x in rs])),'high_risk_failure_rate':float(np.mean([x['failure'] for x in h])) if h else None,'mean_regret':float(np.mean([x['regret'] for x in rs])),'accuracy':float(np.mean([x['selected']==x['oracle'] for x in rs]))}
def holm(ps):
 order=sorted(range(len(ps)),key=lambda i:ps[i]);adj=[0.]*len(ps);running=0.
 for rank,i in enumerate(order):running=max(running,(len(ps)-rank)*ps[i]);adj[i]=min(1.,running)
 return adj
def paired(a,b,metric,rng):
 if metric=='high_risk_failure_rate':a=[x for x in a if x['risk']=='high'];b=[x for x in b if x['risk']=='high']
 field={'utility':'utility','failure_rate':'failure','high_risk_failure_rate':'failure','mean_regret':'regret'}[metric];d=np.array([x[field] for x in a])-np.array([x[field] for x in b]);means=np.empty(NBOOT)
 for s in range(0,NBOOT,500):
  z=rng.integers(0,len(d),size=(min(500,NBOOT-s),len(d)));means[s:s+len(z)]=d[z].mean(1)
 lo,hi=np.quantile(means,[.025,.975]);p=min(1.,2*min((means<=0).mean(),(means>=0).mean()))
 return {'delta':float(d.mean()),'ci95':[float(lo),float(hi)],'p_two_sided':float(p)}
def main():
 if not (RUN/'CONFIRMATORY_COMPLETE.json').exists():raise SystemExit('Confirmatory evaluation is not complete.')
 legacy=load(RUN/'m5_legacy_v1/report.json');sparse=load(RUN/'m5_sparse_v2/report.json')
 methods={'weighted_M1_v2':legacy['M2'],'M3_v2':legacy['M3'],'M5_legacy_v1':legacy['M5'],'M5_sparse_v2':sparse['M5']}
 assert legacy['M2']['rows']==sparse['M2']['rows'] and legacy['M3']['rows']==sparse['M3']['rows']
 comparisons=[('M3_v2','weighted_M1_v2'),('M5_legacy_v1','M3_v2'),('M5_sparse_v2','M3_v2')];family=[];rng=np.random.default_rng(SEED)
 for a,b in comparisons:
  for metric in ('utility','failure_rate','high_risk_failure_rate','mean_regret'):family.append({'comparison':a+'_vs_'+b,'metric':metric,**paired(methods[a]['rows'],methods[b]['rows'],metric,rng)})
 adj=holm([x['p_two_sided'] for x in family])
 for x,p in zip(family,adj):x['holm_p']=p;x['significant_holm_0.05']=p<.05
 bycomp=defaultdict(dict)
 for x in family:bycomp[x['comparison']][x['metric']]={k:v for k,v in x.items() if k not in ('comparison','metric')}
 success={}
 for a,b in comparisons:
  c=bycomp[a+'_vs_'+b];u=c['utility']['ci95'];f=c['failure_rate']['ci95'];success[a+'_vs_'+b]={'benefit_gate':u[0]>0 and f[1]<=0,'safety_only_gate':f[1]<0 and u[0]>=-.01}
 tasks={x['id']:x for x in rows(DATA/'tasks.jsonl')};groups={}
 for name,m in methods.items():
  g=defaultdict(list)
  for r in m['rows']:
   t=tasks[r['task_id']]
   for k,v in [('risk',r['risk']),('dataset',t.get('dataset','unknown')),('task_type',t.get('task_type','unknown'))]:g[k+'='+str(v)].append(r)
  groups[name]={k:metrics(v) for k,v in sorted(g.items())}
 risk_coverage={'M3_v2':{'router_conformal':legacy['router_conformal'],'conditional_model_safety':legacy['conditional_model_safety']},'M5_legacy_v1':{'escalation_rate':legacy['M5'].get('escalation_rate'),'manual_review_rate':legacy['M5'].get('manual_review_rate')},'M5_sparse_v2':{'escalation_rate':sparse['M5'].get('escalation_rate'),'manual_review_rate':sparse['M5'].get('manual_review_rate')}}
 report={'report_type':'finrome_confirmatory_v3_frozen_policy_analysis','bootstrap':{'paired':True,'resamples':NBOOT,'seed':SEED},'multiplicity':{'method':'Holm','family':'3 preregistered comparisons x 4 primary metrics','tests':12},'methods':{k:metrics(v['rows'])|{z:v[z] for z in ('selection_counts','escalation_rate','manual_review_rate') if z in v} for k,v in methods.items()},'comparisons':dict(bycomp),'success_gates':success,'risk_coverage':risk_coverage,'grouped_results':groups,'human_review_contract':'all review items remain PENDING; no human labels or conclusions synthesized','artifacts':{'frozen_policy_sha256':hashlib.sha256((RUN/'FROZEN_POLICY.json').read_bytes()).hexdigest(),'matrix_sha256':hashlib.sha256((DATA/'utility_matrix.jsonl').read_bytes()).hexdigest()}}
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');lines=['# Fin-RoME Confirmatory v3','']+[f"- {k}: utility={v['utility']:.6f}, failure={v['failure_rate']:.2%}, high-risk failure={v['high_risk_failure_rate']:.2%}, regret={v['mean_regret']:.6f}" for k,v in report['methods'].items()]+['','## Success gates']+[f"- {k}: benefit={v['benefit_gate']}, safety_only={v['safety_only_gate']}" for k,v in success.items()]+['','人工审核项全部保持 `PENDING`。'];(OUT/'report.md').write_text('\n'.join(lines)+'\n');print(json.dumps({'out':str(OUT),'methods':report['methods'],'success_gates':success},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
