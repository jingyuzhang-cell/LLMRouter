#!/usr/bin/env python3
"""Audit harmful switches and evaluate the single frozen C3 safety veto."""
import contextlib,hashlib,importlib.util,io,json
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path('/root');OUT=ROOT/'phase_c3';PROTO=OUT/'C3_SAFETY_VETO_PROTOCOL.json'
spec=importlib.util.spec_from_file_location('c3run',ROOT/'run_phase_c3.py');c3=importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):spec.loader.exec_module(c3)
def family(t):return f"{c3.tasks[t]['dataset']}:{c3.tasks[t]['risk_level']}"
def detailed(name,choices,baselines,means,stds):
 rows=[]
 for t in c3.ids:
  b=baselines[t];m=choices[t]
  if m==b:continue
  gain=c3.outcomes[(t,m)]['utility']-c3.outcomes[(t,b)]['utility'];rows.append({'task_id':t,'family':family(t),'risk_level':c3.tasks[t]['risk_level'],'source_model':b,'target_model':m,'gain':gain,'beneficial':gain>0,'predicted_advantage':means[t].get(m),'prediction_std':stds[t].get(m)})
 transitions=defaultdict(list);families=defaultdict(list);risks=defaultdict(list)
 for r in rows:transitions[f"{r['source_model']}->{r['target_model']}"] .append(r['gain']);families[r['family']].append(r['gain']);risks[r['risk_level']].append(r['gain'])
 def agg(d):return {k:{'switch_count':len(v),'beneficial_count':sum(x>0 for x in v),'harmful_count':sum(x<0 for x in v),'beneficial_rate':sum(x>0 for x in v)/len(v),'mean_gain':sum(v)/len(v),'total_gain':sum(v)} for k,v in sorted(d.items())}
 harmful=sorted((r for r in rows if not r['beneficial']),key=lambda r:r['gain']);total_loss=-sum(r['gain'] for r in harmful);top5=-sum(r['gain'] for r in harmful[:5])
 return {'method':name,'switch_rows':rows,'by_transition':agg(transitions),'by_family':agg(families),'by_risk':agg(risks),'harmful_loss_concentration':{'harmful_count':len(harmful),'total_harmful_loss':total_loss,'worst_5_loss':top5,'worst_5_share':top5/total_loss if total_loss else None}}
diagnostic={'advantage_ridge':detailed('advantage_ridge',c3.adv_choices,c3.un_base,c3.un_mean,c3.un_std),'selective_advantage':detailed('selective_advantage',c3.select_choices,c3.wt_base,c3.wt_mean,c3.wt_std)}
safety={}
for t in c3.ids:
 b=c3.wt_base[t];coef=1.96 if c3.tasks[t]['risk_level']=='high' else 1.645;scores={m:c3.wt_mean[t][m]-coef*c3.wt_std[t][m] for m in c3.wt_mean[t]};m=max(scores,key=scores.get);safety[t]=m if scores[m]>0 else b
metrics=c3.metrics(safety,c3.wt_base);switch=c3.switch_audit(safety,c3.wt_base);gate={'gap_recovery_above_0':metrics['gap_recovery']>0,'bootstrap_probability_ge_0.90':metrics['bootstrap_probability_delta_positive']>=.90,'failure_not_above_best':metrics['failure_rate']<=metrics['best_single_failure_rate'],'high_risk_failure_not_above_best':metrics['high_risk_failure_rate']<=metrics['best_single_high_risk_failure_rate']};status='C3_SAFETY_VETO_PASS' if all(gate.values()) else 'C3_SAFETY_VETO_FAIL'
report={'status':status,'protocol_sha256':hashlib.sha256(PROTO.read_bytes()).hexdigest(),'metrics':metrics,'switch_audit':switch,'gate':{**gate,'pass':all(gate.values())},'external_api_calls':0};(OUT/'C3_HARMFUL_SWITCH_DIAGNOSTIC.json').write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2)+'\n');(OUT/'C3_SAFETY_VETO_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
