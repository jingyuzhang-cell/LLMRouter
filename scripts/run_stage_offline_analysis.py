#!/usr/bin/env python3
"""Stage-only judge, robustness, Pareto and memory replay analysis. No model calls."""
from __future__ import annotations
import json, math, random, statistics, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from openclaw_router.checkpoint import load_successful
from openclaw_router.experience import RoutingExperienceStore
from openclaw_router.scoring import utility

PROGRESS=ROOT/'run_logs/llmrouter_experiment_progress_v1.json'
CHECKPOINT=ROOT/'run_logs/llmrouter_experiment_checkpoint_v1.jsonl'
DATA=ROOT/'data/finance_router/frozen/v1/finance_benchmark_v1.jsonl'
OUT=ROOT/'run_logs/stage_offline_analysis.json'
OUT_MD=ROOT/'run_logs/stage_offline_analysis.md'
MODELS=['deepseek-chat','qwen-plus','qwen-turbo','glm-5.2']
BASE_W={'quality':.45,'cost':.20,'latency':.15,'reliability':.20}

def pearson(xs,ys):
 if len(xs)<3:return None
 mx,my=statistics.mean(xs),statistics.mean(ys); dx=[x-mx for x in xs];dy=[y-my for y in ys]
 den=math.sqrt(sum(x*x for x in dx)*sum(y*y for y in dy))
 return round(sum(x*y for x,y in zip(dx,dy))/den,4) if den else None

def summarize(rows):
 vals=[float(x.get('disagreement') or 0) for x in rows]
 return {'n':len(rows),'dual_coverage':round(sum(x['dual'] for x in rows)/max(1,len(rows)),4),'mean_disagreement':round(statistics.mean(vals),4) if vals else None,'median_disagreement':round(statistics.median(vals),4) if vals else None,'ge_0_20':sum(v>=.20-1e-9 for v in vals),'ge_0_20_rate':round(sum(v>=.20-1e-9 for v in vals)/max(1,len(vals)),4),'distribution':{'0-0.05':sum(v<.05 for v in vals),'0.05-0.10':sum(.05<=v<.10 for v in vals),'0.10-0.20':sum(.10<=v<.20 for v in vals),'>=0.20':sum(v>=.20 for v in vals)}}

def judge_analysis(completed,tasks):
 rows=[]; attempts=parsed=0
 for (task_id,model,repeat),r in completed.items():
  scores=r.get('judge_scores') or []; ats=r.get('judge_attempts') or []
  attempts+=len(ats); parsed+=sum(bool(a.get('ok')) for a in ats)
  judge_mean=statistics.mean(float(x['score']) for x in scores) if scores else None
  raw_id=task_id.removeprefix('finance_dataset_'); task=tasks.get(raw_id,{})
  rows.append({'task_id':task_id,'model':model,'repeat':repeat,'dataset':task.get('dataset','unknown'),'reference_length':len(str(task.get('gold_answer') or '')),'long_reference':len(str(task.get('gold_answer') or ''))>2000,'dual':len(scores)>=2,'judge_count':len(scores),'disagreement':float(r.get('judge_disagreement') or 0),'objective':r.get('objective_score'),'judge_mean':judge_mean,'manual_review':bool(r.get('manual_review_required'))})
 attempt_by_judge=defaultdict(lambda:{'attempts':0,'parsed':0,'errors':Counter()})
 for (task_id,model,repeat),r in completed.items():
  for attempt in r.get('judge_attempts') or []:
   judge=str(attempt.get('model') or 'unknown'); attempt_by_judge[judge]['attempts']+=1
   if attempt.get('ok'): attempt_by_judge[judge]['parsed']+=1
   else: attempt_by_judge[judge]['errors'][str(attempt.get('error') or 'unknown')[:240]]+=1
 attempt_summary={judge:{'attempts':item['attempts'],'parsed':item['parsed'],'parse_rate':round(item['parsed']/max(1,item['attempts']),4),'errors':dict(item['errors'])} for judge,item in attempt_by_judge.items()}
 overall=summarize(rows); overall.update({'successful_runs':len(rows),'judge_attempts':attempts,'parsed_judge_attempts':parsed,'judge_attempt_parse_rate':round(parsed/max(1,attempts),4),'judge_attempts_by_model':attempt_summary,'manual_review_count':sum(x['manual_review'] for x in rows),'manual_review_rate':round(sum(x['manual_review'] for x in rows)/max(1,len(rows)),4)})
 pairs=[(float(x['objective']),float(x['judge_mean'])) for x in rows if x['objective'] is not None and x['judge_mean'] is not None]
 overall['objective_judge_pearson']=pearson([x for x,y in pairs],[y for x,y in pairs]); overall['objective_judge_pair_count']=len(pairs)
 by_model={m:summarize([x for x in rows if x['model']==m]) for m in MODELS}
 by_dataset={d:summarize([x for x in rows if x['dataset']==d]) for d in sorted({x['dataset'] for x in rows})}
 long=summarize([x for x in rows if x['long_reference']]); normal=summarize([x for x in rows if not x['long_reference']])
 long_compare={'long_reference':long,'normal_reference':normal,'mean_difference':round((long['mean_disagreement'] or 0)-(normal['mean_disagreement'] or 0),4),'sufficient_for_interim_inference':long['n']>=20}
 risks=[]
 if overall['dual_coverage']<.90:risks.append('dual judge coverage below 90%')
 if overall['judge_attempt_parse_rate']<.90:risks.append('judge attempt parse rate below 90%')
 if overall['ge_0_20_rate']>.20:risks.append('at least 20% of runs have judge disagreement >=0.20')
 if pairs and overall['objective_judge_pearson'] is not None and overall['objective_judge_pearson']<.30:risks.append('weak objective-vs-judge correlation below 0.30')
 return {'phase':'interim_development_only','overall':overall,'by_model':by_model,'by_dataset':by_dataset,'long_reference_comparison':long_compare,'risks':risks}

def dominates(a,b):
 return a['quality']>=b['quality'] and a['cost']<=b['cost'] and a['latency']<=b['latency'] and a['reliability']>=b['reliability'] and (a['quality']>b['quality'] or a['cost']<b['cost'] or a['latency']<b['latency'] or a['reliability']>b['reliability'])
def weighted(m,w):return m['quality']*w['quality']+(1-m['cost'])*w['cost']+(1-m['latency'])*w['latency']+m['reliability']*w['reliability']
def aggregate(values):return {k:statistics.mean(x[k] for x in values) for k in ('quality','cost','latency','reliability')}

def robustness(completed,tasks):
 per=defaultdict(lambda:defaultdict(list))
 for (tid,m,rep),r in completed.items(): per[tid][m].append(r['metrics'])
 complete={tid:{m:aggregate(per[tid][m]) for m in MODELS} for tid in per if all(len(per[tid][m])==3 for m in MODELS)}
 if not complete:return {'status':'INSUFFICIENT','complete_tasks':0}
 assignments=defaultdict(list)
 for tid,models in complete.items():
  for m in MODELS: assignments['fixed_'+m].append(models[m])
  assignments['quality_first'].append(max(models.values(),key=lambda x:x['quality']))
  assignments['cost_first'].append(min(models.values(),key=lambda x:x['cost']))
  assignments['latency_first'].append(min(models.values(),key=lambda x:x['latency']))
  assignments['balanced_utility'].append(max(models.values(),key=lambda x:weighted(x,BASE_W)))
  raw=tasks.get(tid.removeprefix('finance_dataset_'),{}); risk=str(raw.get('risk_level','medium')).lower()
  rw={'quality':.55,'cost':.10,'latency':.10,'reliability':.25} if risk=='high' else BASE_W
  assignments['risk_adaptive'].append(max(models.values(),key=lambda x:weighted(x,rw)))
  front=[x for x in models.values() if not any(dominates(y,x) for y in models.values() if y is not x)]
  assignments['pareto_utility'].append(max(front,key=lambda x:weighted(x,BASE_W)))
 summaries={name:aggregate(vals) for name,vals in assignments.items()}
 grid=[]
 for qi in range(350,601,25):
  for ci in range(100,301,25):
   for li in range(100,251,25):
    q,c,l=qi/1000,ci/1000,li/1000; rel=round(1-q-c-l,6)
    if .10-1e-9<=rel<=.30+1e-9:grid.append({'quality':q,'cost':c,'latency':l,'reliability':rel})
 ranks=defaultdict(list); winners=Counter(); top3=Counter()
 for w in grid:
  ordered=sorted(summaries,key=lambda n:weighted(summaries[n],w),reverse=True); winners[ordered[0]]+=1
  for i,n in enumerate(ordered,1):ranks[n].append(i)
  for n in ordered[:3]:top3[n]+=1
 base_order=sorted(summaries,key=lambda n:weighted(summaries[n],BASE_W),reverse=True); base_best=base_order[0]
 pareto=[n for n,a in summaries.items() if not any(dominates(b,a) for other,b in summaries.items() if other!=n)]
 dominated_winners=[n for n in winners if n not in pareto]
 stability={n:{'winner_rate':round(winners[n]/len(grid),4),'top3_rate':round(top3[n]/len(grid),4),'mean_rank':round(statistics.mean(ranks[n]),3),'rank_std':round(statistics.pstdev(ranks[n]),3),'min_rank':min(ranks[n]),'max_rank':max(ranks[n])} for n in summaries}
 stable_top3=sorted((n for n in stability if stability[n]['top3_rate']>=.80),key=lambda n:stability[n]['top3_rate'],reverse=True)
 sensitive=sorted((n for n in stability if stability[n]['rank_std']>=1.0),key=lambda n:stability[n]['rank_std'],reverse=True)
 return {'status':'PASS','phase':'interim_development_only','complete_tasks':len(complete),'weight_vectors':len(grid),'base_ranking':base_order,'base_best':base_best,'base_best_winner_rate':stability[base_best]['winner_rate'],'unique_winners':dict(winners),'strategy_metrics':summaries,'stability':stability,'stable_top3':stable_top3,'weight_sensitive':sensitive,'pareto_strategies':pareto,'pareto_invariant_by_definition':True,'dominated_strategy_winners':dominated_winners,'pareto_validation_passed':not dominated_winners}

def payload(query,model,version='v1',objective=1.0):
 return dict(query=query,user_id=query,selected_model=model,candidate_models=['model-a','model-b'],api_success=True,quality_score=.9,cost_reward=.9,latency_reward=.9,reliability=1.0,estimated_regret=0,regret_epsilon=.1,constraint_violation=False,fallback_count=0,risk_level='high',objective_score=objective,quality_threshold=.75,config_version=version)
def select_from(store,query,mode):
 if mode=='none':return 'model-a'
 stats=store.model_statistics(query,['model-a','model-b'],user_id=query,config_version='v1')
 score={m:(stats[m]['historical_reward'] if stats[m]['history_count']>0 else .5) for m in stats}
 return max(['model-a','model-b'],key=lambda m:score[m])
def replay_mode(mode,path):
 store=RoutingExperienceStore(path); regret=correct=0
 for i in range(100):
  query='alpha-financial-audit' if i%2==0 else 'beta-knowledge-graph'; best='model-a' if i%2==0 else 'model-b'; chosen=select_from(store,query,mode); ok=chosen==best
  regret+=0 if ok else .5; correct+=ok
  if mode!='none':
   e=store.create(**payload(query,chosen))
   if ok:store.apply_feedback(e['request_id'],rating='up',reason='answer_correct')
   elif mode=='full':store.apply_feedback(e['request_id'],rating='down',reason='wrong_model',preferred_model=best)
   else:store.expire(e['request_id'],'positive_only_discards_negative')
 return {'cumulative_regret':round(regret,4),'routing_accuracy':round(correct/100,4)}
def memory_replay():
 with tempfile.TemporaryDirectory(prefix='memory-replay-') as td:
  results={m:replay_mode(m,Path(td)/f'{m}.jsonl') for m in ('none','positive_only','full')}
  store=RoutingExperienceStore(Path(td)/'guards.jsonl'); q='guard-audit'
  pending=store.create(**payload(q,'model-a')); before=store.model_statistics(q,['model-a','model-b'],user_id=q,config_version='v1')
  expired=store.create(**payload(q,'model-a')); store.expire(expired['request_id'],'test')
  after_nonverified=store.model_statistics(q,['model-a','model-b'],user_id=q,config_version='v1')
  negative=store.create(**payload(q,'model-a')); store.apply_feedback(negative['request_id'],rating='down',reason='wrong_model',preferred_model='model-b')
  after_negative=store.model_statistics(q,['model-a','model-b'],user_id=q,config_version='v1')
  high=store.create(**payload('high-risk','model-a',objective=0.0)); high_result=store.apply_feedback(high['request_id'],rating='up',reason='answer_correct')
  version_isolated=store.model_statistics(q,['model-a','model-b'],user_id=q,config_version='v2')
  guards={'pending_and_expired_excluded':before==after_nonverified and before['model-a']['history_count']==0,'negative_lowers_wrong_model':after_negative['model-a']['historical_reward']<.5,'high_risk_wrong_objective_blocked':high_result['routing_correct'] is False and high_result['verification_status']=='disputed','version_change_isolated':version_isolated['model-a']['history_count']==0}
  return {'status':'PASS' if all(guards.values()) and results['full']['cumulative_regret']<results['none']['cumulative_regret'] else 'FAIL','phase':'synthetic_offline_replay','modes':results,'guards':guards,'full_vs_no_memory_regret_reduction':round(results['none']['cumulative_regret']-results['full']['cumulative_regret'],4),'full_vs_positive_only_regret_reduction':round(results['positive_only']['cumulative_regret']-results['full']['cumulative_regret'],4)}

def md(r):
 j,w,m=r['judge_consistency'],r['weight_robustness'],r['memory_replay'];o=j['overall']
 lines=['# Stage Offline Analysis','',f"Snapshot successes: {r['snapshot_successes']} / 1200",'> Interim development-only results; recompute after 1200 successful calls.','', '## Judge consistency',f"- Dual coverage: {o['dual_coverage']:.2%}",f"- Judge attempt parse rate: {o['judge_attempt_parse_rate']:.2%}",f"- Mean/median disagreement: {o['mean_disagreement']} / {o['median_disagreement']}",f"- Disagreement >=0.20: {o['ge_0_20']} ({o['ge_0_20_rate']:.2%})",f"- Objective/judge Pearson: {o['objective_judge_pearson']} (n={o['objective_judge_pair_count']})",f"- Risks: {j['risks'] or 'none'}",'', '## Weight robustness and Pareto',f"- Complete tasks: {w.get('complete_tasks')}",f"- Weight vectors: {w.get('weight_vectors')}",f"- Base best: {w.get('base_best')}",f"- Base-best winner rate: {w.get('base_best_winner_rate')}",f"- Stable top-3: {w.get('stable_top3')}",f"- Weight-sensitive: {w.get('weight_sensitive')}",f"- Pareto validation: {w.get('pareto_validation_passed')}",'', '## Memory replay',f"- Status: {m['status']}",f"- Modes: {m['modes']}",f"- Guards: {m['guards']}",f"- Full vs no-memory regret reduction: {m['full_vs_no_memory_regret_reduction']}"]
 return '\n'.join(lines)+'\n'
def main():
 progress=json.loads(PROGRESS.read_text());sig=progress['signature']; completed=load_successful(CHECKPOINT,sig);tasks={r['id']:r for r in (json.loads(x) for x in DATA.read_text().splitlines() if x.strip())}
 report={'phase':'interim_development_only','snapshot_signature':sig,'snapshot_successes':len(completed),'snapshot_total':1200,'judge_consistency':judge_analysis(completed,tasks),'weight_robustness':robustness(completed,tasks),'memory_replay':memory_replay()}
 OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');OUT_MD.write_text(md(report))
 print(json.dumps({'snapshot_successes':len(completed),'judge':report['judge_consistency']['overall'],'judge_risks':report['judge_consistency']['risks'],'robustness':{k:report['weight_robustness'].get(k) for k in ('status','complete_tasks','weight_vectors','base_best','base_best_winner_rate','stable_top3','weight_sensitive','pareto_validation_passed')},'memory':report['memory_replay'],'json':str(OUT),'markdown':str(OUT_MD)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
