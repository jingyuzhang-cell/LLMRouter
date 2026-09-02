#!/usr/bin/env python3
"""Resume-safe real-chain executor for frozen E4.0-B balanced exploration."""
import argparse,asyncio,hashlib,json,os,re,sys,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent; OUT=ROOT/'phase_e4_0'; PROJECT=ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main'; CONFIG=PROJECT/'configs/openclaw_multi_provider.yaml'
PLAN=OUT/'E4_0_B_EXPLORATION_PLAN.jsonl'; SPLIT=OUT/'E4_0_B_SPLIT.json'; SOURCE=ROOT/'phase_c9_0/C9_DEV_TASKS.jsonl'; EVENTS=OUT/'E4_0_B_EXPLORATION_EVENTS.jsonl'; LOG=OUT/'E4_0_B_EXPLORATION_NODE_LOG.jsonl'
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash'); API={'deepseek-chat':'deepseek-chat','glm-5.2':'glm-5.2','qwen-plus':'qwen-plus','qwen-turbo':'qwen-turbo','gemini-2.5-flash':'gemini-2.5-flash'}; NODES=('N1','N2','N3','N4'); MAX_ATTEMPTS=1000; MAX_COST=375.0
def rows(p): return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
def load_env():
 p=ROOT/'.env'
 if p.exists():
  for line in p.read_text().splitlines():
   if line.strip() and not line.lstrip().startswith('#') and '=' in line:
    k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
def parse(answer):
 s=answer.strip(); s=re.sub(r'^```(?:json)?\s*|\s*```$','',s,flags=re.I)
 try: return json.loads(s),True
 except Exception: return {'raw_text':answer},False
def state_from(previous,spent,budget):
 if not previous:return {'upstream_success':None,'upstream_format_valid':None,'evidence_count':0,'extraction_field_count':0,'upstream_confidence':None,'upstream_output_length':0,'cumulative_latency_ms':0.0,'cumulative_cost_usd':0.0,'remaining_budget_usd':budget,'retry_count':0}
 last=previous[-1]; obj=last.get('parsed_output') or {}; ev=obj.get('evidence_items',[]) if isinstance(obj,dict) else []; fields=obj.get('fields',{}) if isinstance(obj,dict) else {}; conf=obj.get('confidence') if isinstance(obj,dict) else None
 return {'upstream_success':last['post_action_outcome']['provider_success'],'upstream_format_valid':last['post_action_outcome']['format_valid'],'evidence_count':len(ev) if isinstance(ev,list) else 0,'extraction_field_count':len(fields) if isinstance(fields,dict) else 0,'upstream_confidence':conf if isinstance(conf,(int,float)) and 0<=conf<=1 else None,'upstream_output_length':len(last.get('raw_output','')),'cumulative_latency_ms':sum(x['post_action_outcome']['total_latency_ms'] for x in previous),'cumulative_cost_usd':sum(x['post_action_outcome']['cost_usd'] for x in previous),'remaining_budget_usd':max(0,budget-spent),'retry_count':sum(max(0,x['post_action_outcome']['attempt']-1) for x in previous)}
def prompt(task,node,previous):
 q=task['question']; lineage='\n\n'.join(f"[{x['node_id']} OUTPUT]\n{x.get('raw_output') or '[PROVIDER FAILURE: NO OUTPUT]'}" for x in previous)
 if node=='N1': body=f"TASK_CONTEXT:\n{task['context']}\n\nTABLE:\n{json.dumps(task.get('table') or [],ensure_ascii=False)}"; inst='Locate at most 8 minimal sufficient passages or table cells needed to answer the question. Limit each quote to 240 characters. Return JSON with evidence_items (each has quote and source_hint) and confidence.'
 elif node=='N2': body=lineage; inst='Using only upstream evidence, extract entities, periods, quantities, units, relations, and regulatory facts. Return JSON with fields, missing, and confidence. Do not answer the question.'
 elif node=='N3': body=lineage; inst='Using the upstream extraction and evidence, perform the required financial reasoning. Return JSON with intermediate_result, assumptions, evidence_links, and confidence. Do not write the final response.'
 else: body=lineage; inst='Synthesize the final answer only from upstream reasoning and evidence. Return JSON with answer, citations, and confidence. Do not introduce unsupported facts.'
 return f"QUESTION:\n{q}\n\n{body}\n\nINSTRUCTION:\n{inst}\nReturn exactly one JSON object and no markdown."
async def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--max-trajectories',type=int); args=ap.parse_args(); load_env(); sys.path.insert(0,str(PROJECT))
 from openclaw_router.config import OpenClawConfig
 from openclaw_router.server import LLMBackend
 from scripts.run_finance_model_evaluation import answer_from_result,cost_usd,usage_from_result
 cfg=OpenClawConfig.from_yaml(str(CONFIG)); backend=LLMBackend(cfg); tasks={x['task_id']:x for x in rows(SOURCE)}; plans=rows(PLAN); allowed=set(json.loads(SPLIT.read_text())['exploration_train_task_ids']); assert {p['task_id'] for p in plans}<=allowed
 if args.max_trajectories is not None: plans=plans[:args.max_trajectories]
 old=rows(LOG); by_traj={p['trajectory_id']:[] for p in plans}
 for x in old:
  if x['trajectory_id'] in by_traj: by_traj[x['trajectory_id']].append(x)
 for v in by_traj.values(): v.sort(key=lambda x:NODES.index(x['node_id']))
 events=rows(EVENTS); attempts=len(events); spent=sum(float(x.get('cost_usd') or 0) for x in events)
 while any(len(by_traj[p['trajectory_id']])<4 for p in plans):
  ready=[]
  for p in plans:
   done=by_traj[p['trajectory_id']]; i=len(done)
   if i<4:
    key=hashlib.sha256(f"{p['ready_queue_priority_seed']}|{NODES[i]}".encode()).hexdigest(); ready.append((key,p,NODES[i]))
  _,p,node=min(ready,key=lambda x:x[0]); previous=by_traj[p['trajectory_id']]; model=p['assignment'][node]
  if attempts>=MAX_ATTEMPTS or spent>=MAX_COST: raise RuntimeError(f'hard cap attempts={attempts} cost={spent:.4f}')
  pre=state_from(previous,spent,MAX_COST); req=prompt(tasks[p['task_id']],node,previous); started=time.perf_counter(); answer=''; usage={}; error=None; attempt=1; attempts+=1
  try:
   max_tokens={'N1':2400,'N2':1200,'N3':1600,'N4':1200}[node]
   result=await backend.call(API[model],[{'role':'user','content':req}],max_tokens=max_tokens,temperature=0,stream=False); answer=answer_from_result(result); usage=usage_from_result(result,req,answer)
   if not answer.strip(): raise RuntimeError('empty answer')
  except Exception as exc: error=str(exc)[:1200]
  latency=(time.perf_counter()-started)*1000; billed=float(cost_usd(cfg,API[model],usage)) if usage else 0.; spent+=billed; parsed,valid=parse(answer) if error is None else ({},False); now=datetime.now(timezone.utc).isoformat()
  post={'provider_success':error is None,'provider_error':error,'format_valid':valid,'first_token_latency_ms':None,'total_latency_ms':round(latency,2),'cost_usd':billed,'tokens':usage,'timestamp':now,'attempt':attempt}
  event={'task_id':p['task_id'],'trajectory_id':p['trajectory_id'],'node_id':node,'selected_model':model,**post}
  with EVENTS.open('a') as h: h.write(json.dumps(event,ensure_ascii=False)+'\n'); h.flush(); os.fsync(h.fileno())
  rec={'task_id':p['task_id'],'trajectory_id':p['trajectory_id'],'node_id':node,'node_type':{'N1':'evidence_localization','N2':'structured_extraction','N3':'financial_reasoning','N4':'final_synthesis'}[node],'request_features':tasks[p['task_id']]['observable_features'],'pre_action_state':pre,'selected_model':model,'behavior_probability':.2,'randomization_seed':p['randomization_seed'],'post_action_outcome':post,'parsed_output':parsed,'raw_output':answer}
  with LOG.open('a') as h: h.write(json.dumps(rec,ensure_ascii=False)+'\n'); h.flush(); os.fsync(h.fileno())
  by_traj[p['trajectory_id']].append(rec); print(json.dumps({'trajectory':p['trajectory_id'],'node':node,'model':model,'success':error is None,'valid':valid,'completed_nodes':sum(map(len,by_traj.values())),'target_nodes':len(plans)*4,'cost_usd':round(spent,4)}),flush=True)
 print(json.dumps({'status':'EXPLORATION_SUBSET_COMPLETE','trajectories':len(plans),'nodes':sum(map(len,by_traj.values())),'attempts':attempts,'cost_usd':round(spent,4)}))
if __name__=='__main__': asyncio.run(main())
