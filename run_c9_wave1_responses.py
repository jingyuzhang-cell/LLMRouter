#!/usr/bin/env python3
"""Resume-safe C9 Wave 1 collection: 480 train tasks x 5 models x 3 repeats."""
import argparse, asyncio, json, os, random, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path('/root'); PROJECT=ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main'; DATA=ROOT/'phase_c9_0'
TASKS=DATA/'C9_DEV_TASKS.jsonl'; OUT=DATA/'C9_TRAIN_RESPONSES.jsonl'; EVENTS=DATA/'C9_TRAIN_RESPONSE_EVENTS.jsonl'
CONFIG=PROJECT/'configs/openclaw_multi_provider.yaml'
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash')

def read(path): return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()] if Path(path).exists() else []
for line in (ROOT/'.env').read_text().splitlines():
    line=line.strip()
    if line and not line.startswith('#') and '=' in line:
        key,value=line.split('=',1); os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))
sys.path.insert(0,str(PROJECT))
from openclaw_router.config import OpenClawConfig
from openclaw_router.server import LLMBackend
from scripts.run_finance_model_evaluation import build_prompt,answer_from_result,usage_from_result,cost_usd

async def main(max_new):
    gate=json.loads((DATA/'C9_0_PREFLIGHT_GATE.json').read_text())
    if gate.get('status')!='C9_0_PREFLIGHT_PASS' or not gate.get('api_authorized'): raise SystemExit('C9 preflight is not authorized')
    tasks=[x for x in read(TASKS) if x['split']=='development_train']; assert len(tasks)==480
    byid={x['task_id']:x for x in tasks}; expected={(tid,m,r) for tid in byid for m in MODELS for r in range(3)}; assert len(expected)==7200
    previous=read(OUT); attempted={(x['task_id'],x['model'],int(x['repeat'])) for x in previous}; jobs=sorted(expected-attempted)
    if max_new is not None: jobs=jobs[:max_new]
    print(json.dumps({'wave':1,'expected':7200,'already_attempted':len(attempted),'pending_total':7200-len(attempted),'starting_now':len(jobs)}),flush=True)
    cfg=OpenClawConfig.from_yaml(str(CONFIG)); backend=LLMBackend(cfg); global_sem=asyncio.Semaphore(4); per={m:asyncio.Semaphore(2) for m in MODELS}; lock=asyncio.Lock(); stats=Counter()
    async def one(key):
        tid,model,repeat=key; task=byid[tid]; prompt=build_prompt(task); answer=''; usage={}; error=None; attempts=0; started=time.perf_counter()
        for attempts in range(1,4):
            try:
                async with global_sem,per[model]:
                    result=await backend.call(model,[{'role':'user','content':prompt}],max_tokens=512,temperature=0,stream=False)
                answer=answer_from_result(result); usage=usage_from_result(result,prompt,answer)
                if not answer.strip(): raise RuntimeError('empty answer')
                error=None; break
            except Exception as exc:
                error=str(exc)[:1000]; kind='429' if '429' in error else '403' if '403' in error else type(exc).__name__
                async with lock:
                    with EVENTS.open('a',encoding='utf-8') as f: f.write(json.dumps({'task_id':tid,'model':model,'repeat':repeat,'attempt':attempts,'kind':kind,'error':error,'timestamp':datetime.now(timezone.utc).isoformat()})+'\n')
                if kind=='403' or attempts==3: break
                await asyncio.sleep((20 if kind=='429' else 2**attempts)+random.random())
        row={'task_id':tid,'split':'development_train','primary_capability':task['primary_capability'],'source_dataset':task['source_dataset'],
             'model':model,'repeat':repeat,'answer':answer,'success':error is None,'error':error,'attempts':attempts,'usage':usage,
             'cost_usd':cost_usd(cfg,model,usage) if usage else 0.0,'latency_ms':round((time.perf_counter()-started)*1000,2),'timestamp':datetime.now(timezone.utc).isoformat()}
        async with lock:
            with OUT.open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n'); f.flush(); os.fsync(f.fileno())
            stats['success' if error is None else 'failed']+=1; stats[model]+=1
            done=stats['success']+stats['failed']
            if done%20==0 or done==len(jobs): print(json.dumps({'new_completed':done,'success':stats['success'],'failed':stats['failed'],'calls_by_model':{m:stats[m] for m in MODELS}}),flush=True)
    await asyncio.gather(*(one(x) for x in jobs))

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--max-new',type=int); args=ap.parse_args(); asyncio.run(main(args.max_new))
