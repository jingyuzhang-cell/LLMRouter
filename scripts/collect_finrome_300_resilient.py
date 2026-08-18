#!/usr/bin/env python3
"""Resumable collector with per-model concurrency and transient retries."""
import argparse,asyncio,json,os,random,time
from pathlib import Path
from openclaw_router.config import OpenClawConfig
from openclaw_router.server import LLMBackend
from scripts.run_finance_model_evaluation import call_one
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data/finance_router/finrome_300';CONFIG=ROOT/'configs/openclaw_multi_provider.yaml'
def read(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
def transient(error):return str(error or '').startswith(('429','500','502','503','504')) or any(x in str(error or '').lower() for x in ('timeout','temporar','connection'))
async def run(a):
 data=a.data_dir.resolve();protocol=json.loads((data/'protocol.json').read_text());tasks=read(data/'tasks.jsonl');jobs=[(t,m,r) for t in tasks for m in protocol['models'] for r in range(3)];existing=read(a.output);done={(x['task_id'],x['model'],x['repeat']) for x in existing if x.get('success')};pending=[x for x in jobs if (x[0]['id'],x[1],x[2]) not in done];pending=pending[:a.limit] if a.limit else pending
 if a.dry_run:
  print(json.dumps({'data_dir':str(data),'required':len(jobs),'completed':len(done),'pending':len(pending),'models':protocol['models']},ensure_ascii=False));return
 providers={'deepseek-chat':'DEEPSEEK_API_KEY','qwen-plus':'QWEN_API_KEY','qwen-turbo':'QWEN_API_KEY','glm-5.2':'ZHIPU_API_KEY'};missing=sorted({providers[m] for _,m,_ in pending if m in providers and not os.getenv(providers[m])})
 if missing:raise SystemExit('Missing required API credentials: '+', '.join(missing))
 cfg=OpenClawConfig.from_yaml(str(CONFIG));backend=LLMBackend(cfg);global_sem=asyncio.Semaphore(a.workers);model_sem={m:asyncio.Semaphore(1 if 'seed' in m else 2) for m in protocol['models']};lock=asyncio.Lock();stats={'ok':0,'failed':0,'retried':0};start=time.perf_counter()
 async def one(job):
  task,model,repeat=job;result=None;attempt=0
  async with global_sem,model_sem[model]:
   while attempt<=a.retries:
    result=await call_one(backend,cfg,task,model,max_tokens=a.max_tokens,temperature=.2,dry_run=False)
    if result.get('success') or not transient(result.get('error')):break
    attempt+=1;stats['retried']+=1
    if attempt<=a.retries:await asyncio.sleep(min(60,2**attempt+random.random()))
  rec={'task_id':task['id'],'dataset':task.get('dataset'),'task_type':task.get('task_type'),'risk_level':task.get('risk_level'),'model':model,'repeat':repeat,'attempts':attempt+1,**result};stats['ok' if result.get('success') else 'failed']+=1
  async with lock:
   with a.output.open('a',encoding='utf-8') as h:h.write(json.dumps(rec,ensure_ascii=False)+'\n');h.flush();os.fsync(h.fileno())
   n=stats['ok']+stats['failed']
   if n%20==0:print(json.dumps({'this_run':n,'pending_start':len(pending),**stats,'elapsed_s':round(time.perf_counter()-start,1)},ensure_ascii=False),flush=True)
 await asyncio.gather(*(one(x) for x in pending));print(json.dumps({'output':str(a.output),'completed_this_run':stats['ok']+stats['failed'],**stats},ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,default=DATA);p.add_argument('--output',type=Path,default=None);p.add_argument('--workers',type=int,default=7);p.add_argument('--dry-run',action='store_true');p.add_argument('--limit',type=int,default=0);p.add_argument('--max-tokens',type=int,default=512);p.add_argument('--retries',type=int,default=2);a=p.parse_args();a.output=a.output or a.data_dir/'responses.jsonl';a.output.parent.mkdir(parents=True,exist_ok=True);asyncio.run(run(a))
