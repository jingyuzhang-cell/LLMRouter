"""Unified actual-execution table; paired group uncertainty, no OPE or imputation."""
import json,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path('/root');sys.path.insert(0,str(ROOT));OUT=ROOT/'phase_e5_unified'
import numpy as np
from phase_e5_unified.common import components,WEIGHTS

def rows(p):return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
def main():
 manifest=rows(OUT/'PAIRED_EXECUTION_MANIFEST.jsonl');observed=rows(OUT/'PAIRED_RESULTS.jsonl')
 assert len({r['execution_key'] for r in observed})==len(observed),'duplicate executions'
 results={r['execution_key']:r for r in observed}
 expected={r['execution_key'] for r in manifest};assert set(results)==expected,'incomplete/extra execution keys'
 tasks={r['task_id']:r for r in rows(OUT/'DEVELOPMENT_TASKS.jsonl')}
 numeric={r['task_id'] for r in json.loads((ROOT/'phase_e4_1/E4_1_NUMERIC_UNIT_CONTRACT_FROZEN.json').read_text())['tasks']}
 tab={};observations=[]
 for entry in manifest:
  result=results[entry['execution_key']]; assert result['Q'] is not None
  t=result['T_ms']+entry['routing_overhead_ms'];comp=components(result['Q'],result['C'],t,result['R'])
  r={**entry,**result,'latency_with_routing_ms':t,'group':tasks[entry['task_id']]['leakage_group_id'],'stratum':'deterministic' if entry['task_id'] in numeric else 'machine_only','utility':float(comp@WEIGHTS[entry['objective']]),'Q+T_utility':float(comp@WEIGHTS['Q+T']),'Q+C+T+R_utility':float(comp@WEIGHTS['Q+C+T+R'])}
  observations.append(r)
 for obj in WEIGHTS:
  tab[obj]={}
  for regime in ('Static','Dynamic','DAG'):
   sub=[r for r in observations if r['objective']==obj and r['regime']==regime]
   assert len(sub)==40 and len({r['task_id'] for r in sub})==40
   stats={k:float(np.mean([r[k] for r in sub])) for k in ('Q','C','latency_with_routing_ms','R','utility','Q+T_utility','Q+C+T+R_utility')}
   stats.update(n_tasks=40,cost_saturation_rate=float(np.mean([r['C']>=.02 for r in sub])),latency_saturation_rate=float(np.mean([r['latency_with_routing_ms']>=10000 for r in sub])),unknown_billing_rows=sum(r['cost_is_upper_bound'] for r in sub),quality_by_stratum={st:float(np.mean([r['Q'] for r in sub if r['stratum']==st])) for st in ('deterministic','machine_only')})
   tab[obj][regime]=stats
 comparisons={}
 for obj in WEIGHTS:
  for left,right in (('Dynamic','Static'),('DAG','Dynamic')):
   l={r['task_id']:r for r in observations if r['objective']==obj and r['regime']==left};rr={r['task_id']:r for r in observations if r['objective']==obj and r['regime']==right}
   groups=defaultdict(list)
   for tid in sorted(l):groups[l[tid]['group']].append(l[tid]['utility']-rr[tid]['utility'])
   values=np.array([np.mean(groups[g]) for g in sorted(groups)]);rng=np.random.default_rng(20260905);boot=values[rng.integers(0,len(values),(10000,len(values)))].mean(1)
   comparisons[f'{obj}|{left}-{right}']={'estimate':float(values.mean()),'ci95':np.quantile(boot,[.025,.975]).tolist(),'familywise_bonferroni_ci':np.quantile(boot,[.05/12,1-.05/12]).tolist(),'leakage_groups':len(values),'benefit_supported_familywise':bool(np.quantile(boot,.05/12)>0)}
 report={'status':'UNIFIED_DEVELOPMENT_COMPARISON_COMPLETE','main_table_by_optimization_target':tab,'paired_utility_comparisons':comparisons,'independent_holdout_status':'NOT_RUN_NOT_YET_CERTIFIED_FRESH','methods':'Actual same-task execution of frozen OOF policies; one execution per unique assignment shared across identical policies; not independent repeat replication.','limitations':['Qwen-Max only on 23 open tasks; no human validation.','Shared final schema is strict and part of R and delivered Q.','40 development task groups, single execution per unique arm; no independent confirmatory claim.','DAG policies are associational learners from coupled exploration assignments.','Cost/latency efficiencies use frozen clipped scales; saturation rates reported.','C includes conservative configured-price bounds on unknown billing; report flags.','T includes service, retry backoff and measured router inference, excludes shared experimental scheduling queue.']}
 (OUT/'UNIFIED_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 text=['# Unified development results','']
 for obj,methods in tab.items():
  text += [f'## Optimization target: {obj}','','| Routing | Q | Cost USD | Latency ms | R | Q+T utility | Q+C+T+R utility |','|---|---:|---:|---:|---:|---:|---:|']
  for name,r in methods.items():text.append(f"| {name} | {r['Q']:.4f} | {r['C']:.6f} | {r['latency_with_routing_ms']:.1f} | {r['R']:.4f} | {r['Q+T_utility']:.4f} | {r['Q+C+T+R_utility']:.4f} |")
  text.append('')
 text += ['Development evidence only. Independent holdout validation remains pending.']
 (OUT/'UNIFIED_RESULTS.md').write_text('\n'.join(text)+'\n')
 print(json.dumps({'status':report['status'],'comparisons':comparisons},indent=2))
if __name__=='__main__':main()
