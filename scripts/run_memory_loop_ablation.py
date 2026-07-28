#!/usr/bin/env python3
"""Controlled offline memory-loop ablation over the frozen 100-task response pool. No API calls."""
from __future__ import annotations
import hashlib,json,statistics,sys,tempfile
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from openclaw_router.experience import RoutingExperienceStore,automatic_verification
RESULT=ROOT/'run_logs/formal_100_final_result.json'
OUT=ROOT/'run_logs/memory_loop_ablation.json';OUT_MD=ROOT/'run_logs/memory_loop_ablation.md'
MODELS=['qwen-plus','deepseek-chat','qwen-turbo','glm-5.2'];EPS=.02;EPOCHS=5

def f(x):
 try:return float(x)
 except:return 0.0
def utility(r):return .45*f(r.get('quality'))+.20*(1-min(f(r.get('raw_cost_usd'))/.02,1))+.15*(1-min(f(r.get('latency_ms'))/10000,1))+.20*(1 if r.get('ok') else 0)
def build_pool(d):
 grouped=defaultdict(lambda:defaultdict(list))
 for r in d['raw_model_runs']:grouped[r['task_id']][r['model']].append(utility(r))
 return {tid:{m:statistics.mean(grouped[tid][m]) for m in MODELS} for tid in grouped if all(len(grouped[tid][m])==3 for m in MODELS)}
def payload(query,selected,correct,regret,disputed=False):
 return dict(query=query,user_id='ablation',selected_model=selected,candidate_models=MODELS,
  api_success=True,quality_score=.90 if correct else .20,cost_reward=.85,latency_reward=.80,reliability=1.0,
  estimated_regret=regret,regret_epsilon=EPS,constraint_violation=False,fallback_count=0,
  risk_level='high',objective_score=1.0 if correct else 0.0,quality_threshold=.75,
  manual_review_required=disputed,config_version='memory-ablation-v1')
def select(store,query,attempted):
 stats=store.model_statistics(query,MODELS,user_id='ablation',config_version='memory-ablation-v1')
 learned=[m for m in MODELS if stats[m]['history_count']>0]
 if learned:
  best=max(learned,key=lambda m:stats[m]['historical_reward'])
  if stats[best]['historical_reward']>.5:return best
 for m in MODELS:
  if m not in attempted:return m
 return max(MODELS,key=lambda m:stats[m]['historical_reward'])
def run(mode,pool,path):
 store=RoutingExperienceStore(path);legacy={};attempts=defaultdict(set);events=[];feedback_down=0
 for epoch in range(EPOCHS):
  for tid in sorted(pool):
   query='frozen-task '+tid
   if mode=='none':chosen=MODELS[0]
   elif mode=='legacy_query_model':chosen=legacy.get(query,MODELS[0])
   else:chosen=select(store,query,attempts[query])
   attempts[query].add(chosen);oracle=max(pool[tid],key=pool[tid].get);regret=max(0,pool[tid][oracle]-pool[tid][chosen]);correct=regret<=EPS
   events.append({'task_id':tid,'epoch':epoch,'selected':chosen,'oracle':oracle,'correct':correct,'regret':regret,'reward':pool[tid][chosen]})
   if mode=='legacy_query_model':legacy[query]=chosen
   elif mode in {'positive_verified','full_feedback','full_no_user_feedback'}:
    disputed=(int(hashlib.sha256(tid.encode()).hexdigest()[:8],16)%5==0)
    e=store.create(**payload(query,chosen,correct,regret,disputed))
    if mode=='positive_verified':
     if correct:store.apply_feedback(e['request_id'],rating='up',reason='answer_correct')
     else:store.expire(e['request_id'],'negative_discarded_by_ablation')
    elif mode=='full_feedback':
     if correct:store.apply_feedback(e['request_id'],rating='up',reason='answer_correct')
     else:
      store.apply_feedback(e['request_id'],rating='down',reason='wrong_model',preferred_model=oracle);feedback_down+=1
    else:
     state=automatic_verification(**{k:payload(query,chosen,correct,regret,disputed)[k] for k in ('api_success','quality_score','quality_threshold','risk_level','objective_score','constraint_violation','estimated_regret','regret_epsilon','manual_review_required','cost_reward','latency_reward','reliability','fallback_count')})
     current=store.get(e['request_id']);current.update(state);store._append(current)
 corrected=opportunities=0;prev={}
 for e in events:
  tid=e['task_id']
  if tid in prev and not prev[tid]['correct']:
   opportunities+=1;corrected+=bool(e['correct'])
  prev[tid]=e
 return {'events':len(events),'routing_accuracy':round(sum(e['correct'] for e in events)/len(events),6),'average_regret':round(statistics.mean(e['regret'] for e in events),6),'cumulative_regret':round(sum(e['regret'] for e in events),6),'cumulative_reward':round(sum(e['reward'] for e in events),6),'negative_feedback_rate':round(feedback_down/len(events),6),'correction_rate':round(corrected/max(1,opportunities),6),'correction_opportunities':opportunities,'final_epoch_accuracy':round(sum(e['correct'] for e in events if e['epoch']==EPOCHS-1)/len(pool),6),'experience_metrics':store.metrics() if mode not in {'none','legacy_query_model'} else None}
def main():
 d=json.loads(RESULT.read_text());pool=build_pool(d)
 with tempfile.TemporaryDirectory(prefix='memory-loop-ablation-') as td:
  modes={m:run(m,pool,Path(td)/f'{m}.jsonl') for m in ('none','legacy_query_model','positive_verified','full_feedback','full_no_user_feedback')}
 report={'experiment_type':'separate_memory_loop_ablation','excluded_from_frozen_main_experiment':True,'source_result':str(RESULT.relative_to(ROOT)),'source_sha256':hashlib.sha256(RESULT.read_bytes()).hexdigest(),'tasks':len(pool),'epochs':EPOCHS,'events_per_mode':len(pool)*EPOCHS,'regret_epsilon':EPS,'mode_definitions':{'none':'No historical experience.','legacy_query_model':'Memorize query to selected model regardless of outcome.','positive_verified':'Retrieve verified positive experience; discard negatives.','full_feedback':'Use verified positive and negative experience plus structured user feedback.','full_no_user_feedback':'Use automatic objective/judge state only; disputed cases remain excluded.'},'modes':modes,'guards':{'all_100_tasks_complete':len(pool)==100,'pending_expired_disputed_excluded':'covered by routing experience regression tests','no_external_model_calls':True},'best_by_accuracy':max(modes,key=lambda m:modes[m]['routing_accuracy']),'best_by_regret':min(modes,key=lambda m:modes[m]['average_regret'])}
 OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 lines=['# 记忆闭环消融实验（独立实验）','', '> 本实验复用冻结回答池，不调用外部模型，不写回冻结主实验。','',f'- 任务：{len(pool)}','- 每组回放：500个路由事件','- 正确判定：所选模型效用距离任务最优模型不超过 ε=0.02','', '| 模式 | 路由准确率 | 最终轮准确率 | 平均regret | 累计regret | 累计奖励 | 负反馈率 | 纠错率 |','|---|---:|---:|---:|---:|---:|---:|---:|']
 for m,x in modes.items():lines.append(f"| {m} | {x['routing_accuracy']:.2%} | {x['final_epoch_accuracy']:.2%} | {x['average_regret']:.4f} | {x['cumulative_regret']:.4f} | {x['cumulative_reward']:.4f} | {x['negative_feedback_rate']:.2%} | {x['correction_rate']:.2%} |")
 lines+=['',f"- 准确率最佳：{report['best_by_accuracy']}",f"- regret最低：{report['best_by_regret']}",'']
 OUT_MD.write_text('\n'.join(lines))
 print(json.dumps({'json':str(OUT),'markdown':str(OUT_MD),'modes':modes,'best_accuracy':report['best_by_accuracy'],'best_regret':report['best_by_regret']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
