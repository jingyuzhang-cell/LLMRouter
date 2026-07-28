#!/usr/bin/env python3
"""Offline judge calibration and threshold sensitivity; performs no model calls."""
from __future__ import annotations
import json, math, statistics, sys
from collections import Counter, defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from openclaw_router.checkpoint import load_successful
PROGRESS=ROOT/'run_logs/llmrouter_experiment_progress_v1.json';CHECKPOINT=ROOT/'run_logs/llmrouter_experiment_checkpoint_v1.jsonl';DATA=ROOT/'data/finance_router/frozen/v1/finance_benchmark_v1.jsonl';OUT=ROOT/'run_logs/judge_calibration_analysis.json';OUT_MD=ROOT/'run_logs/judge_calibration_analysis.md'
MODELS=['deepseek-chat','qwen-plus','qwen-turbo','glm-5.2']
def pearson(xs,ys):
 if len(xs)<3:return None
 mx,my=statistics.mean(xs),statistics.mean(ys);dx=[x-mx for x in xs];dy=[y-my for y in ys];den=math.sqrt(sum(x*x for x in dx)*sum(y*y for y in dy));return round(sum(x*y for x,y in zip(dx,dy))/den,4) if den else None
def ranks(values):
 order=sorted(range(len(values)),key=lambda i:values[i]);out=[0.]*len(values);i=0
 while i<len(order):
  j=i
  while j+1<len(order) and values[order[j+1]]==values[order[i]]:j+=1
  rank=(i+j+2)/2
  for k in range(i,j+1):out[order[k]]=rank
  i=j+1
 return out
def main():
 progress=json.loads(PROGRESS.read_text());completed=load_successful(CHECKPOINT,progress['signature']);tasks={r['id']:r for r in (json.loads(x) for x in DATA.read_text().splitlines() if x.strip())}
 rows=[];judge_values=defaultdict(list);pair_values=defaultdict(list);attempts=defaultdict(lambda:Counter());fallback_responses=0
 for (tid,candidate,repeat),r in completed.items():
  scores={str(x['model']):float(x['score']) for x in (r.get('judge_scores') or []) if x.get('model') is not None and x.get('score') is not None}
  for m,v in scores.items():judge_values[m].append(v)
  if len(scores)>=2:
   names=sorted(scores);pair_values[' + '.join(names)].append(scores[names[0]]-scores[names[1]])
  ats=r.get('judge_attempts') or []
  fallback_responses+=len(ats)>2
  for i,a in enumerate(ats):
   m=str(a.get('model') or 'unknown');attempts[m]['attempts']+=1;attempts[m]['parsed']+=bool(a.get('ok'));attempts[m]['fallback_position']+=i>=2;attempts[m]['failed']+=not bool(a.get('ok'));attempts[m]['cost_microusd']+=round(float(a.get('cost_usd') or 0)*1_000_000)
  raw=tasks.get(tid.removeprefix('finance_dataset_'),{})
  rows.append({'task_id':tid,'candidate':candidate,'dataset':raw.get('dataset','unknown'),'objective':r.get('objective_score'),'judge_mean':statistics.mean(scores.values()) if scores else None,'disagreement':float(r.get('judge_disagreement') or 0),'scores':scores})
 thresholds=[]
 for t in [x/100 for x in range(10,51,5)]:
  count=sum(x['disagreement']>=t-1e-12 for x in rows);thresholds.append({'threshold':t,'review_count':count,'review_rate':round(count/max(1,len(rows)),4)})
 by_candidate={}
 for m in MODELS:
  vals=[x for x in rows if x['candidate']==m];by_candidate[m]={'n':len(vals),'thresholds':{f'{t:.2f}':round(sum(x['disagreement']>=t-1e-12 for x in vals)/max(1,len(vals)),4) for t in (.15,.20,.25,.30,.35)}}
 judge_summary={m:{'n':len(v),'mean':round(statistics.mean(v),4),'median':round(statistics.median(v),4),'std':round(statistics.pstdev(v),4),'zero_rate':round(sum(x==0 for x in v)/max(1,len(v)),4),'one_rate':round(sum(x==1 for x in v)/max(1,len(v)),4)} for m,v in judge_values.items()}
 pair_summary={pair:{'n':len(v),'mean_signed_first_minus_second':round(statistics.mean(v),4),'mean_absolute_difference':round(statistics.mean(abs(x) for x in v),4),'median_absolute_difference':round(statistics.median(abs(x) for x in v),4),'ge_0_20_rate':round(sum(abs(x)>=.20-1e-12 for x in v)/max(1,len(v)),4)} for pair,v in pair_values.items()}
 objective_rows=[x for x in rows if x['objective'] is not None and x['judge_mean'] is not None];obj=[float(x['objective']) for x in objective_rows];jm=[float(x['judge_mean']) for x in objective_rows]
 calibration={'n':len(obj),'pearson':pearson(obj,jm),'mae':round(statistics.mean(abs(a-b) for a,b in zip(obj,jm)),4) if obj else None,'judge_minus_objective_bias':round(statistics.mean(b-a for a,b in zip(obj,jm)),4) if obj else None,'by_objective_bucket':{}}
 for label,pred in [('zero',lambda x:x==0),('partial',lambda x:0<x<1),('one',lambda x:x==1)]:
  vals=[x['judge_mean'] for x in objective_rows if pred(float(x['objective']))];calibration['by_objective_bucket'][label]={'n':len(vals),'mean_judge':round(statistics.mean(vals),4) if vals else None}
 mix={};base_order=None
 for alpha in (.5,.6,.7,.8):
  model_vals=defaultdict(list)
  for x in objective_rows:model_vals[x['candidate']].append(alpha*float(x['objective'])+(1-alpha)*float(x['judge_mean']))
  means={m:statistics.mean(v) for m,v in model_vals.items()};order=sorted(means,key=means.get,reverse=True)
  if alpha==.6:base_order=order
  mix[str(alpha)]={'ranking':order,'means':{m:round(v,4) for m,v in means.items()}}
 base_ranks={m:i for i,m in enumerate(base_order or [])};mix_changed={a:sum(base_ranks.get(m,i)!=i for i,m in enumerate(v['ranking'])) for a,v in mix.items()}
 attempt_summary={m:{'attempts':c['attempts'],'parsed':c['parsed'],'parse_rate':round(c['parsed']/max(1,c['attempts']),4),'failed':c['failed'],'fallback_position_attempts':c['fallback_position'],'recorded_cost_usd':round(c['cost_microusd']/1_000_000,6)} for m,c in attempts.items()}
 glm=attempt_summary.get('glm-5.2',{});diagnosis={'responses_requiring_third_or_later_judge':fallback_responses,'fallback_response_rate':round(fallback_responses/max(1,len(rows)),4),'glm_parse_rate':glm.get('parse_rate'),'glm_failed_attempts':glm.get('failed'),'result_level_dual_coverage':round(sum(len(x['scores'])>=2 for x in rows)/max(1,len(rows)),4),'interpretation':'GLM judge outputs are unparseable, but fallback judges preserve result-level dual coverage. Do not claim GLM contributed valid judge scores.'}
 recommendation={'keep_current_formal_threshold':.20,'do_not_change_mid_run':True,'post_run_sensitivity_thresholds':[.20,.25,.30,.35],'recommended_calibration_actions':['store raw failed judge text after the frozen run','repair GLM reasoning/content JSON extraction','report result-level coverage separately from attempt parse rate','report sensitivity at thresholds 0.20/0.25/0.30/0.35','do not describe GLM as a successful judge in the current run']}
 report={'phase':'interim_development_only','snapshot_successes':len(rows),'threshold_sensitivity':thresholds,'by_candidate_model':by_candidate,'judge_score_bias':judge_summary,'judge_pair_bias':pair_summary,'objective_calibration':calibration,'quality_mix_sensitivity':mix,'quality_mix_rank_changes_vs_0.6':mix_changed,'attempts_by_judge':attempt_summary,'fallback_diagnosis':diagnosis,'recommendation':recommendation}
 OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 lines=['# Judge Calibration Analysis','',f"Snapshot: {len(rows)} successful runs (interim only)",'','## Threshold sensitivity']+[f"- {x['threshold']:.2f}: {x['review_count']} ({x['review_rate']:.2%})" for x in thresholds]+['','## Judge parsing']+[f"- {m}: {x['parsed']}/{x['attempts']} ({x['parse_rate']:.2%})" for m,x in attempt_summary.items()]+['','## Objective calibration',f"- Pearson: {calibration['pearson']}",f"- MAE: {calibration['mae']}",f"- Judge minus objective bias: {calibration['judge_minus_objective_bias']}",'','## Recommendation']+[f"- {x}" for x in recommendation['recommended_calibration_actions']]
 OUT_MD.write_text('\n'.join(lines)+'\n')
 print(json.dumps({'snapshot':len(rows),'thresholds':thresholds,'judge_bias':judge_summary,'pairs':pair_summary,'calibration':calibration,'mix_rank_changes':mix_changed,'fallback':diagnosis,'json':str(OUT),'markdown':str(OUT_MD)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
