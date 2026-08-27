#!/usr/bin/env python3
"""Strict-cap, one-attempt response collection for frozen v3 confirmatory tasks."""
import asyncio,json,os,sys,time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
PROJECT=Path('/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main');DATA=Path('/root/v3_confirmatory');TASKS=DATA/'V3_CONFIRMATORY_TASKS.jsonl';OUT=DATA/'V3_NEW_RESPONSES.jsonl';EVENTS=DATA/'V3_RESPONSE_FAILURES.jsonl';CONFIG=PROJECT/'configs/openclaw_multi_provider.yaml'
ALL=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash')
def read(p):return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()] if Path(p).exists() else []
for line in Path('/root/.env').read_text().splitlines():
 line=line.strip()
 if line and not line.startswith('#') and '=' in line:
  k,v=line.split('=',1);os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
sys.path.insert(0,str(PROJECT));from openclaw_router.config import OpenClawConfig;from openclaw_router.server import LLMBackend;from scripts.run_finance_model_evaluation import build_prompt,answer_from_result,usage_from_result,cost_usd
async def main():
 tasks=read(TASKS);expected=set()
 for t in tasks:
  models=ALL if t['_v3_response_plan']=='collect_all_five_models' else ('gemini-2.5-flash',)
  expected.update((t['id'],m,r) for m in models for r in range(3))
 assert len(expected)==1008
 previous=read(OUT);attempted={(x['task_id'],x['model'],int(x['repeat'])) for x in previous};jobs=sorted(expected-attempted);assert len(previous)+len(jobs)<=1008
 print(json.dumps({'expected':1008,'already_attempted':len(attempted),'pending':len(jobs)}),flush=True)
 byid={t['id']:t for t in tasks};cfg=OpenClawConfig.from_yaml(str(CONFIG));backend=LLMBackend(cfg);global_sem=asyncio.Semaphore(4);per={m:asyncio.Semaphore(2) for m in ALL};lock=asyncio.Lock();stats={'success':0,'failed':0};calls=Counter()
 async def one(key):
  tid,model,repeat=key;t=byid[tid];prompt=build_prompt(t);started=time.perf_counter();answer='';usage={};error=None
  try:
   async with global_sem,per[model]:result=await backend.call(model,[{'role':'user','content':prompt}],max_tokens=512,temperature=0,stream=False)
   answer=answer_from_result(result);usage=usage_from_result(result,prompt,answer)
   if not str(answer).strip():raise RuntimeError('empty answer')
  except Exception as exc:error=str(exc)[:1000]
  row={'task_id':tid,'dataset':t['dataset'],'task_type':t['task_type'],'risk_level':t['risk_level'],'model':model,'repeat':repeat,'answer':answer,'success':error is None,'error':error,'attempts':1,'usage':usage,'cost_usd':cost_usd(cfg,model,usage) if usage else 0.0,'latency_ms':round((time.perf_counter()-started)*1000,2),'timestamp':datetime.now(timezone.utc).isoformat()}
  async with lock:
   with OUT.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
   calls[model]+=1;stats['success' if error is None else 'failed']+=1
   if error:
    with EVENTS.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
   done=stats['success']+stats['failed']
   if done%20==0:print(json.dumps({'completed':done,**stats,'calls':dict(calls)}),flush=True)
 await asyncio.gather(*(one(x) for x in jobs));print(json.dumps({'new_calls':len(jobs),**stats,'calls':dict(calls)}),flush=True)
if __name__=='__main__':asyncio.run(main())
