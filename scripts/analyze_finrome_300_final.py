#!/usr/bin/env python3
"""Paired bootstrap CIs, risk coverage, groups, and M0--M5 decisions."""
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data/finance_router/finrome_300';RUN=ROOT/'run_logs/finrome_300';OUT=RUN/'final_analysis'
SEED=20260810;N_BOOT=10000
def load(p):return json.loads(p.read_text())
def rows(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def slim(x):return {k:v for k,v in x.items() if k!='rows'}
def metrics(rs):return {'n':len(rs),'utility':float(np.mean([x['utility'] for x in rs])),'failure_rate':float(np.mean([x['failure'] for x in rs])),'mean_regret':float(np.mean([x['regret'] for x in rs])),'accuracy':float(np.mean([x['selected']==x['oracle'] for x in rs]))}
def boot(a,b):
 rng=np.random.default_rng(SEED);fields={'utility':'utility','failure':'failure','regret':'regret'};out={}
 for k,field in fields.items():
  d=np.array([x[field] for x in a])-np.array([x[field] for x in b]);means=np.empty(N_BOOT)
  for start in range(0,N_BOOT,500):
   z=rng.integers(0,len(d),size=(min(500,N_BOOT-start),len(d)));means[start:start+len(z)]=d[z].mean(1)
  lo,hi=np.quantile(means,[.025,.975]);out[k]={'delta':float(d.mean()),'ci95':[float(lo),float(hi)],'p_improvement':float(np.mean(means>0 if k=='utility' else means<0))}
 return out
def main():
 OUT.mkdir(parents=True,exist_ok=True);tasks={x['id']:x for x in rows(DATA/'tasks.jsonl')};f=load(RUN/'formal_oof/report.json');t=load(RUN/'oof_tuning/report.json');x=load(RUN/'m3_m5/report.json')
 methods={**{'M0_'+k:v for k,v in f['test']['M0'].items()},'M1':t['test']['M1'],'M2':x['M2'],'M3':x['M3'],'M4':x['M4'],'M5':x['M5']};base=methods['M1'];comparisons={m+'_vs_M1':boot(v['rows'],base['rows']) for m,v in methods.items() if m!='M1'};comparisons.update({m+'_vs_'+p:boot(methods[m]['rows'],methods[p]['rows']) for p,m in [('M2','M3'),('M3','M4'),('M4','M5')]})
 groups={}
 for m,v in methods.items():
  g=defaultdict(list)
  for r in v['rows']:
   q=tasks[r['task_id']]
   for key,val in [('risk',r['risk']),('task_type',q.get('task_type','unknown')),('dataset',q.get('dataset','unknown'))]:g[key+'='+str(val)].append(r)
  groups[m]={k:metrics(z) for k,z in sorted(g.items())}
 def verdict(c):
  u=c['utility'];r=c['regret'];z=c['failure'];gain=u['ci95'][0]>0 and r['ci95'][1]<0;harm=u['ci95'][1]<0 or r['ci95'][0]>0 or z['ci95'][0]>0
  return 'BENEFIT' if gain else 'HARM' if harm else 'INCONCLUSIVE'
 decisions={'M2_vs_M1':verdict(comparisons['M2_vs_M1']),'M3_increment':verdict(comparisons['M3_vs_M2']),'M4_increment':verdict(comparisons['M4_vs_M3']),'M5_increment':verdict(comparisons['M5_vs_M4'])};report={'bootstrap':{'resamples':N_BOOT,'seed':SEED,'paired_on_test_tasks':True},'methods':{k:slim(v) for k,v in methods.items()},'comparisons':comparisons,'decisions':decisions,'risk_coverage':{'meta_validation':f.get('meta_validation'),'router_conformal':x.get('router_conformal'),'conditional_model_safety':x.get('conditional_model_safety')},'grouped_results':groups,'human_review_contract':'PENDING only; this analysis contains no fabricated human labels'}
 (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');lines=['# Fin-RoME-300 最终统计分析','',f"- 配对 Bootstrap：{N_BOOT} 次，95% CI",f"- M2 是否真正超过 M1：{decisions['M2_vs_M1']}",f"- M3 增量：{decisions['M3_increment']}",f"- M4 增量：{decisions['M4_increment']}",f"- M5 增量：{decisions['M5_increment']}",'','人工审核结论未生成，所有审核列保持 `PENDING`。'];(OUT/'report.md').write_text('\n'.join(lines)+'\n');print(json.dumps({'out':str(OUT),'decisions':decisions},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
