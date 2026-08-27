#!/usr/bin/env python3
"""Resume-safe Gemini response collection for target-support expansion v1."""

import asyncio,json,os,random,sys,time
from pathlib import Path

PROJECT=Path('/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main');DATA=Path('/root/target_support_expansion_v1')
TASKS=DATA/'TARGET_SUPPORT_EXPANSION_TASKS.jsonl';OUT=DATA/'gemini_responses.jsonl';EVENTS=DATA/'gemini_response_events.jsonl'
for line in Path('/root/.env').read_text().splitlines():
    line=line.strip()
    if line and not line.startswith('#') and '=' in line:
        key,value=line.split('=',1);os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))
sys.path.insert(0,str(PROJECT))
from openclaw_router.config import OpenClawConfig
from openclaw_router.server import LLMBackend
from scripts.run_finance_model_evaluation import build_prompt,answer_from_result,usage_from_result,cost_usd

def read(path):return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []

async def main():
    cfg=OpenClawConfig.from_yaml(str(PROJECT/'configs/openclaw_multi_provider.yaml'));backend=LLMBackend(cfg);tasks=read(TASKS)
    done={(x['task_id'],int(x['repeat'])) for x in read(OUT) if x.get('success') and str(x.get('answer') or '').strip()};jobs=[(t,r) for t in tasks for r in range(3) if (t['id'],r) not in done]
    print(json.dumps({'expected':900,'done':len(done),'pending':len(jobs)}),flush=True);sem=asyncio.Semaphore(2);lock=asyncio.Lock();stats={'ok':0,'failed':0,'retried':0}
    async def one(t,repeat):
        prompt=build_prompt(t);error=''
        for attempt in range(1,10):
            try:
                async with sem:
                    started=time.perf_counter();result=await backend.call('gemini-2.5-flash',[{'role':'user','content':prompt}],max_tokens=512,temperature=0,stream=False)
                answer=answer_from_result(result);usage=usage_from_result(result,prompt,answer)
                if not answer:raise RuntimeError('empty answer')
                row={'task_id':t['id'],'dataset':t.get('dataset'),'task_type':t.get('task_type'),'risk_level':t.get('risk_level'),'source_dataset_dir':t.get('_source_dataset_dir'),'model':'gemini-2.5-flash','repeat':repeat,'answer':answer,'success':True,'error':None,'attempts':attempt,'usage':usage,'cost_usd':cost_usd(cfg,'gemini-2.5-flash',usage),'latency_ms':round((time.perf_counter()-started)*1000,2)}
                async with lock:
                    with OUT.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
                    stats['ok']+=1
                    if stats['ok']%20==0:print(json.dumps({'new_ok':stats['ok'],'total_ok':len(done)+stats['ok'],'pending_start':len(jobs),**stats}),flush=True)
                return
            except Exception as exc:
                error=str(exc)[:800];kind='429' if '429' in error else '403' if '403' in error else type(exc).__name__;stats['retried']+=1
                async with lock:
                    with EVENTS.open('a',encoding='utf-8') as f:f.write(json.dumps({'task_id':t['id'],'repeat':repeat,'attempt':attempt,'kind':kind,'error':error,'timestamp':time.time()})+'\n')
                if kind=='403':break
                await asyncio.sleep(35 if kind=='429' else min(45,2**attempt)+random.random())
        async with lock:stats['failed']+=1;print(json.dumps({'failed_key':[t['id'],repeat],'error':error}),flush=True)
    await asyncio.gather(*(one(t,r) for t,r in jobs));print(json.dumps({'expected':900,'previously_done':len(done),**stats}),flush=True)

asyncio.run(main())
