#!/usr/bin/env python3
"""Concurrent, append-only and resumable collection for Fin-RoME-300."""
import argparse,asyncio,json,os,time
from pathlib import Path
from openclaw_router.config import OpenClawConfig
from openclaw_router.server import LLMBackend
from scripts.run_finance_model_evaluation import call_one
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data/finance_router/finrome_300';CONFIG=ROOT/'configs/openclaw_multi_provider.yaml'
def rows(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
async def main(a):
 protocol=json.loads((DATA/'protocol.json').read_text());tasks=rows(DATA/'tasks.jsonl');jobs=[(t,m,r) for t in tasks for m in protocol['models'] for r in range(3)];done={}
 if a.output.exists():
  for x in rows(a.output):done[(x['task_id'],x['model'],x['repeat'])]=x
 pending=[x for x in jobs if (x[0]['id'],x[1],x[2]) not in done]
 if a.limit:pending=pending[:a.limit]
 cfg=OpenClawConfig.from_yaml(str(CONFIG));backend=LLMBackend(cfg);sem=asyncio.Semaphore(a.workers);lock=asyncio.Lock();started=time.perf_counter();counts={'ok':0,'failed':0}
 async def one(item):
  task,model,repeat=item
  async with sem:
   result=await call_one(backend,cfg,task,model,max_tokens=a.max_tokens,temperature=.2,dry_run=False);record={'task_id':task['id'],'dataset':task.get('dataset'),'task_type':task.get('task_type'),'risk_level':task.get('risk_level'),'model':model,'repeat':repeat,**result};counts['ok' if result.get('success') else 'failed']+=1
   async with lock:
    with a.output.open('a',encoding='utf-8') as h:h.write(json.dumps(record,ensure_ascii=False)+'\n');h.flush();os.fsync(h.fileno())
    n=counts['ok']+counts['failed']
    if n%10==0:print(json.dumps({'completed_this_run':n,'pending_at_start':len(pending),'ok':counts['ok'],'failed':counts['failed'],'elapsed_s':round(time.perf_counter()-started,1)},ensure_ascii=False),flush=True)
 await asyncio.gather(*(one(x) for x in pending));print(json.dumps({'output':str(a.output),'completed_this_run':sum(counts.values()),**counts},ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=DATA/'responses.jsonl');p.add_argument('--workers',type=int,default=4);p.add_argument('--limit',type=int,default=0);p.add_argument('--max-tokens',type=int,default=512);a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True);asyncio.run(main(a))
