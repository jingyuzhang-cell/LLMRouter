#!/usr/bin/env python3
"""Controlled resume entry point for frozen E4.0-B collection."""
import argparse,asyncio,hashlib,json,os,sys,time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from phase_e4_0.execution_controls import ProviderHealth,attempts_by_key,balanced,classify,dependency_ready,generation_ceiling_binding,health_audit,http_status,latest_by_key,PENDING
from run_e4_0_b_exploration import ROOT,OUT,PROJECT,CONFIG,PLAN,SPLIT,SOURCE,EVENTS,LOG,MODELS,API,NODES,MAX_COST,load_env,parse,prompt,rows,state_from

PREFLIGHT=OUT/'E4_0_B_PROVIDER_PREFLIGHT.json'; AUDITS=OUT/'collection_health_audits'
MAX_ATTEMPTS=3; BACKOFF=(30,120); MAX_GAP=20

def finish_reason(result):
 try:return result['choices'][0].get('finish_reason')
 except Exception:return None

def append(path,row):
 with path.open('a') as handle:handle.write(json.dumps(row,ensure_ascii=False)+'\n'); handle.flush(); os.fsync(handle.fileno())

def preflight_passed():
 if not PREFLIGHT.exists():return False
 data=json.loads(PREFLIGHT.read_text()); required={'glm-5.2','gemini-2.5-flash','qwen-plus'}
 return data.get('status')=='PASS' and required<={x['model'] for x in data.get('results',[]) if x.get('provider_success') and x.get('format_valid')}

async def preflight(backend,cfg,answer_from_result,usage_from_result,cost_usd):
 request='Return exactly one JSON object and no markdown: {"ok":true}'
 tasks={x['task_id']:x for x in rows(SOURCE)}; qwen_plans=[p for p in rows(PLAN) if p['assignment']['N1']=='qwen-plus']; qwen_plan=max(qwen_plans,key=lambda p:len(tasks[p['task_id']]['context']))
 results=[]
 for model in ('glm-5.2','gemini-2.5-flash','qwen-plus'):
  actual_request=prompt(tasks[qwen_plan['task_id']],'N1',[]) if model=='qwen-plus' else request; ceiling=2400 if model=='qwen-plus' else (512 if model=='glm-5.2' else 128)
  started=time.perf_counter(); answer=''; usage={}; error=None; result={}
  try:
   result=await backend.call(API[model],[{'role':'user','content':actual_request}],max_tokens=ceiling,temperature=0,stream=False); answer=answer_from_result(result); usage=usage_from_result(result,actual_request,answer)
   if not answer.strip():raise RuntimeError('empty answer')
  except Exception as exc:error=f'{type(exc).__name__}: {exc!r}'[:1200]
  parsed,valid=parse(answer) if error is None else ({},False); reason=finish_reason(result)
  results.append({'model':model,'provider_success':error is None,'provider_error':error,'format_valid':valid and (isinstance(parsed,dict) and 'evidence_items' in parsed and 'confidence' in parsed if model=='qwen-plus' else parsed=={'ok':True}),'finish_reason':reason,'max_tokens':ceiling,'tokens':usage,'generation_ceiling_binding':generation_ceiling_binding(reason,usage,ceiling),'latency_ms':round((time.perf_counter()-started)*1000,2),'cost_usd':float(cost_usd(cfg,API[model],usage)) if usage else 0,'timestamp':datetime.now(timezone.utc).isoformat(),'raw_output':answer})
 payload={'status':'PASS' if all(x['provider_success'] and x['format_valid'] for x in results) else 'FAIL','results':results}; PREFLIGHT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(payload,ensure_ascii=False,indent=2)); return payload['status']=='PASS'

async def main():
 parser=argparse.ArgumentParser(); parser.add_argument('--preflight',action='store_true'); parser.add_argument('--audit-only',action='store_true'); parser.add_argument('--max-outcomes',type=int); parser.add_argument('--concurrency',type=int,default=4); parser.add_argument('--cooldown-seconds',type=int,default=600); args=parser.parse_args()
 load_env(); sys.path.insert(0,str(PROJECT)); from openclaw_router.config import OpenClawConfig; from openclaw_router.server import LLMBackend; from scripts.run_finance_model_evaluation import answer_from_result,cost_usd,usage_from_result
 cfg=OpenClawConfig.from_yaml(str(CONFIG)); backend=LLMBackend(cfg)
 if args.preflight:sys.exit(0 if await preflight(backend,cfg,answer_from_result,usage_from_result,cost_usd) else 2)
 plans=rows(PLAN); tasks={x['task_id']:x for x in rows(SOURCE)}; expected=len(plans)*4; events=rows(EVENTS); attempts=attempts_by_key(events); logged=latest_by_key(rows(LOG)); outcomes={key:record for key,record in logged.items() if classify(record,attempts[key],MAX_ATTEMPTS)!=PENDING}
 if args.audit_only:print(json.dumps(health_audit(events,outcomes,MODELS,NODES,expected,MAX_COST),ensure_ascii=False,indent=2)); return
 if not preflight_passed():raise RuntimeError('provider preflight missing or failed; run --preflight before bulk collection')
 allowed=set(json.loads(SPLIT.read_text())['exploration_train_task_ids']); assert {p['task_id'] for p in plans}<=allowed
 target=min(expected,args.max_outcomes or expected); spent=sum(float(x.get('cost_usd') or 0) for x in events); health=ProviderHealth(args.cooldown_seconds); last_audit=(len(outcomes)//50)*50
 while len(outcomes)<target:
  completed=Counter(x['selected_model'] for x in outcomes.values()); ready=[]
  for plan in plans:
   candidate=dependency_ready(plan,outcomes,attempts,NODES,MAX_ATTEMPTS)
   if not candidate:continue
   node,key,previous=candidate; model=plan['assignment'][node]
   if not health.available(model,time.time()) or not balanced(model,completed,MODELS,MAX_GAP):continue
   priority=hashlib.sha256(f"{plan['ready_queue_priority_seed']}|{node}".encode()).hexdigest(); ready.append((priority,plan,node,key,previous,model))
  ready.sort(key=lambda x:x[0]); batch=[]; trajectories=set()
  for item in ready:
   if item[1]['trajectory_id'] not in trajectories:batch.append(item); trajectories.add(item[1]['trajectory_id'])
   if len(batch)>=max(1,args.concurrency):break
  if not batch:
   waits=[until-time.time() for until in health.cooldown_until.values() if until>time.time()]
   if waits:await asyncio.sleep(min(min(waits),60)); continue
   raise RuntimeError('no schedulable node; inspect preflight, balance, and terminal states')
  async def call(item):
   _,plan,node,key,previous,model=item; request=prompt(tasks[plan['task_id']],node,previous); ceiling={'N1':2400,'N2':1200,'N3':1600,'N4':1200}[node]; started=time.perf_counter(); answer=''; usage={}; error=None; result={}
   try:
    result=await backend.call(API[model],[{'role':'user','content':request}],max_tokens=ceiling,temperature=0,stream=False); answer=answer_from_result(result); usage=usage_from_result(result,actual_request,answer)
    if not answer.strip():raise RuntimeError('empty answer')
   except Exception as exc:error=f'{type(exc).__name__}: {exc!r}'[:1200]
   parsed,valid=parse(answer) if error is None else ({},False); reason=finish_reason(result); billed=float(cost_usd(cfg,API[model],usage)) if usage else 0
   post={'provider_success':error is None,'provider_error':error,'format_valid':valid,'first_token_latency_ms':None,'total_latency_ms':round((time.perf_counter()-started)*1000,2),'cost_usd':billed,'tokens':usage,'timestamp':datetime.now(timezone.utc).isoformat(),'attempt':attempts[key]+1,'finish_reason':reason,'max_tokens':ceiling,'generation_ceiling_binding':generation_ceiling_binding(reason,usage,ceiling)}
   return item,post,parsed,answer
  for item,post,parsed,answer in await asyncio.gather(*(call(x) for x in batch)):
   _,plan,node,key,previous,model=item; attempts[key]+=1; spent+=post['cost_usd']; append(EVENTS,{'task_id':plan['task_id'],'trajectory_id':plan['trajectory_id'],'node_id':node,'selected_model':model,**post}); status=http_status(post['provider_error']); health.observe(model,status,time.time())
   final=post['provider_success'] or attempts[key]>=MAX_ATTEMPTS
   if final:
    post['outcome_status']='SUCCESS' if post['provider_success'] else 'PERMANENT_FAILURE'; post['semantic_quality']=None if not post['provider_success'] else 'NOT_ACCESSED_DURING_COLLECTION'; post['delivered_quality']=0 if not post['provider_success'] else 'NOT_ACCESSED_DURING_COLLECTION'
    rec={'task_id':plan['task_id'],'trajectory_id':plan['trajectory_id'],'node_id':node,'node_type':{'N1':'evidence_localization','N2':'structured_extraction','N3':'financial_reasoning','N4':'final_synthesis'}[node],'request_features':tasks[plan['task_id']]['observable_features'],'pre_action_state':state_from(previous,spent-post['cost_usd'],MAX_COST),'selected_model':model,'behavior_probability':.2,'randomization_seed':plan['randomization_seed'],'post_action_outcome':post,'parsed_output':parsed,'raw_output':answer}; append(LOG,rec); outcomes[key]=rec
   elif status in {401,408,409,425,429,500,502,503,504} or status is None:await asyncio.sleep(BACKOFF[min(attempts[key]-1,1)])
   print(json.dumps({'key':key,'model':model,'attempt':attempts[key],'final':final,'success':post['provider_success'],'valid':post['format_valid'],'unique_outcomes':len(outcomes),'target':target,'cost_usd':round(spent,4)},ensure_ascii=False),flush=True)
  if spent>=MAX_COST:raise RuntimeError(f'$10 hard cost cap reached: {spent:.4f}')
  milestone=(len(outcomes)//50)*50
  if milestone>=50 and milestone>last_audit:
   payload=health_audit(rows(EVENTS),outcomes,MODELS,NODES,expected,MAX_COST); AUDITS.mkdir(exist_ok=True); path=AUDITS/f'health_{milestone:04d}.json'; path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n'); last_audit=milestone
   if not payload['cost_gate_pass']:raise RuntimeError('projected total cost exceeds $10 gate')
 print(json.dumps({'status':'TARGET_COMPLETE','unique_outcomes':len(outcomes),'api_attempts':sum(attempts.values()),'cost_usd':round(spent,4)}))

if __name__=='__main__':asyncio.run(main())
