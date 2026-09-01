#!/usr/bin/env python3
"""Resume C9 Wave 1 with frozen per-attempt cost and service-latency accounting."""
import asyncio, json, os, random, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path('/root'); PROJECT=ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main'; DATA=ROOT/'phase_c9_0'
TASKS=DATA/'C9_DEV_TASKS.jsonl'; OUT=DATA/'C9_TRAIN_RESPONSES.jsonl'; EVENTS=DATA/'C9_TRAIN_RESPONSE_EVENTS.jsonl'; CONFIG=PROJECT/'configs/openclaw_multi_provider.yaml'
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

async def main():
    gate=json.loads((DATA/'C9_0_PREFLIGHT_GATE.json').read_text()); protocol=json.loads((DATA/'C9_1_RESPONSE_HANDLING_PROTOCOL.json').read_text())
    if gate.get('status')!='C9_0_PREFLIGHT_PASS' or not gate.get('api_authorized'): raise SystemExit('C9 preflight is not authorized')
    if protocol['max_attempts_per_key']!=3: raise SystemExit('response protocol mismatch')
    tasks=[x for x in read(TASKS) if x['split']=='development_train']; assert len(tasks)==480
    byid={x['task_id']:x for x in tasks}; expected={(tid,m,r) for tid in byid for m in MODELS for r in range(3)}; assert len(expected)==7200
    previous=read(OUT); attempted={(x['task_id'],x['model'],int(x['repeat'])) for x in previous}; jobs=sorted(expected-attempted)
    print(json.dumps({'wave':1,'expected':7200,'already_final':len(attempted),'pending':len(jobs),'accounting_schema':'per_attempt_v2'}),flush=True)
    cfg=OpenClawConfig.from_yaml(str(CONFIG)); backend=LLMBackend(cfg); global_sem=asyncio.Semaphore(4); per={m:asyncio.Semaphore(2) for m in MODELS}; lock=asyncio.Lock(); stats=Counter()
    async def one(key):
        tid,model,repeat=key; task=byid[tid]; prompt=build_prompt(task); answer=''; error=None; attempt_rows=[]
        for attempt in range(1,4):
            started=time.perf_counter(); result=None; usage={}; attempt_error=None
            try:
                async with global_sem,per[model]: result=await backend.call(model,[{'role':'user','content':prompt}],max_tokens=512,temperature=0,stream=False)
                answer=answer_from_result(result); usage=usage_from_result(result,prompt,answer)
                if not answer.strip(): raise RuntimeError('empty answer')
            except Exception as exc:
                attempt_error=str(exc)[:1000]
                if result is not None and not usage: usage=usage_from_result(result,prompt,answer)
            service_ms=round((time.perf_counter()-started)*1000,2); billed=cost_usd(cfg,model,usage) if usage else 0.0
            attempt_row={'attempt':attempt,'success':attempt_error is None,'error':attempt_error,'service_latency_ms':service_ms,'usage':usage,
                         'billed_cost_usd':billed,'billing_observable':bool(usage),'timestamp':datetime.now(timezone.utc).isoformat()}
            attempt_rows.append(attempt_row)
            async with lock:
                with EVENTS.open('a',encoding='utf-8') as f: f.write(json.dumps({'task_id':tid,'model':model,'repeat':repeat,**attempt_row},ensure_ascii=False)+'\n')
            if attempt_error is None: error=None; break
            error=attempt_error; kind='429' if '429' in error else '403' if '403' in error else '503' if '503' in error else 'other'
            if kind=='403' or attempt==3: break
            await asyncio.sleep((20 if kind=='429' else 2**attempt)+random.random())
        final_latency=attempt_rows[-1]['service_latency_ms']; total_latency=round(sum(x['service_latency_ms'] for x in attempt_rows),2); total_cost=round(sum(x['billed_cost_usd'] for x in attempt_rows),10)
        row={'accounting_schema':'per_attempt_v2','task_id':tid,'split':'development_train','primary_capability':task['primary_capability'],'source_dataset':task['source_dataset'],
             'model':model,'repeat':repeat,'answer':answer,'success':error is None,'error':error,'attempts':len(attempt_rows),'attempt_records':attempt_rows,
             'usage':attempt_rows[-1]['usage'],'cost_usd':total_cost,'total_billed_cost_usd':total_cost,'final_response_latency_ms':final_latency,
             'total_attempt_latency_ms':total_latency,'latency_ms':total_latency,'timestamp':datetime.now(timezone.utc).isoformat()}
        async with lock:
            with OUT.open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n'); f.flush(); os.fsync(f.fileno())
            stats['success' if error is None else 'failed']+=1; stats[model]+=1; done=stats['success']+stats['failed']
            if done%20==0 or done==len(jobs): print(json.dumps({'new_final':done,'success':stats['success'],'failed':stats['failed'],'calls_by_model':{m:stats[m] for m in MODELS}}),flush=True)
    await asyncio.gather(*(one(x) for x in jobs))

if __name__=='__main__': asyncio.run(main())
