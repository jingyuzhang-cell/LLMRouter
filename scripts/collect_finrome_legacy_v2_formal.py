#!/usr/bin/env python3
"""Budgeted, resumable formal collector for legacy_v2 confirmation."""
import argparse,asyncio,json,os,time
from collections import defaultdict
from pathlib import Path
from openclaw_router.config import OpenClawConfig
from openclaw_router.server import LLMBackend
from openclaw_router.judge_utils import extract_message_text,parse_judge_payload
from scripts.run_finance_model_evaluation import build_prompt,answer_from_result,usage_from_result,cost_usd
from scripts.collect_finrome_300_judges import prompt as judge_prompt,judges
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data/finance_router/finrome_legacy_v2_confirmatory';CONFIG=ROOT/'configs/openclaw_multi_provider.yaml';MODELS=('deepseek-chat','qwen-plus','qwen-turbo','glm-5.2')
def rows(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
def append(p,x):
 with p.open('a',encoding='utf-8') as h:h.write(json.dumps(x,ensure_ascii=False)+'\n');h.flush();os.fsync(h.fileno())
def valid_answer(x):return bool(x.get('success') and str(x.get('answer') or '').strip())
def transient(e):return str(e or '').startswith(('429','500','502','503','504')) or any(z in str(e or '').lower() for z in ('timeout','temporar','connection','disconnect'))
def fatal(e):return any(z in str(e or '').lower() for z in ('arrearage','overdue-payment','authentication','invalid api key','unauthorized','permission'))
def provider(model):return 'zhipu' if model=='glm-5.2' else 'deepseek' if model=='deepseek-chat' else 'qwen_combined'
def costs(data):
 out=defaultdict(float)
 for p in (data/'responses.jsonl',data/'judges.jsonl'):
  for x in rows(p):out[provider(x.get('model',x.get('judge_model')))]+=float(x.get('cost_usd') or 0)
 return out
def budget_check(data,seal):
 c=costs(data);total=sum(c.values());caps=seal['budget_caps_usd']
 if total>=caps['overall']:raise SystemExit(f'BUDGET_HARD_STOP overall {total:.4f}/{caps["overall"]}')
 for k,v in c.items():
  if v>=caps[k]:raise SystemExit(f'BUDGET_HARD_STOP {k} {v:.4f}/{caps[k]}')
 return {'overall':total,**c}
def quality_check(data):
 latest={}
 for x in rows(data/'responses.jsonl'):latest[(x['task_id'],x['model'],x['repeat'])]=x
 glm=[x for x in latest.values() if x['model']=='glm-5.2'];empty=[x for x in glm if x.get('success') and not str(x.get('answer') or '').strip()]
 if len(glm)>=50 and len(empty)/len(glm)>.02:raise SystemExit(f'QUALITY_HARD_STOP glm_empty_rate={len(empty)/len(glm):.4f}')
 combined=list(latest.values());jlatest={}
 for x in rows(data/'judges.jsonl'):jlatest[(x['task_id'],x['candidate_model'],x['repeat'],x['judge_model'])]=x
 combined+=list(jlatest.values())
 for p in ('zhipu','deepseek','qwen_combined'):
  values=[x for x in combined if provider(x.get('model',x.get('judge_model')))==p];bad=[x for x in values if x.get('error') and not transient(x.get('error'))]
  if len(values)>=100 and len(bad)/len(values)>.01:raise SystemExit(f'QUALITY_HARD_STOP {p}_nontransient_rate={len(bad)/len(values):.4f}')
async def call_retry(fn,retries=2):
 last=None
 for attempt in range(retries+1):
  try:
   value=await fn();return value,None,attempt+1
  except Exception as e:
   last=str(e)[:500]
   if fatal(last) or not transient(last) or attempt==retries:break
   await asyncio.sleep(min(20,2**(attempt+1)))
 return None,last,attempt+1
async def main(a):
 data=a.data_dir.resolve();seal=json.loads((data/'EXECUTION_SEAL.json').read_text());tasks=rows(data/'tasks.jsonl');tmap={x['id']:x for x in tasks};cfg=OpenClawConfig.from_yaml(str(CONFIG));backend=LLMBackend(cfg);budget=budget_check(data,seal);quality_check(data)
 ans_path=data/'responses.jsonl';judge_path=data/'judges.jsonl';latest={}
 for x in rows(ans_path):latest[(x['task_id'],x['model'],x['repeat'])]=x
 answer_done={k for k,x in latest.items() if valid_answer(x)};answer_jobs=[(t,m,r) for t in tasks for m in MODELS for r in range(3) if (t['id'],m,r) not in answer_done]
 judge_tasks=[t for t in tasks if t.get('task_type')=='financial_audit_compliance_qa'];jlatest={}
 for x in rows(judge_path):jlatest[(x['task_id'],x['candidate_model'],x['repeat'],x['judge_model'])]=x
 judge_done={k for k,x in jlatest.items() if x.get('parsed')};required_judges=len(judge_tasks)*4*3*2
 if a.dry_run:
  print(json.dumps({'phase':'answers' if answer_jobs else 'judges' if len(judge_done)<required_judges else 'complete','answers':{'required':len(tasks)*12,'completed':len(answer_done),'pending':len(answer_jobs)},'judges':{'required':required_judges,'completed':len(judge_done),'pending':required_judges-len(judge_done)},'cost_usd':budget},ensure_ascii=False));return
 missing=[x for x in ('DEEPSEEK_API_KEY','QWEN_API_KEY','ZHIPU_API_KEY') if not os.getenv(x)]
 if missing:raise SystemExit('Missing required API credentials: '+', '.join(missing))
 sem=asyncio.Semaphore(seal['concurrency']['global']);per={k:asyncio.Semaphore(seal['concurrency']['per_provider']) for k in ('zhipu','deepseek','qwen_combined')};lock=asyncio.Lock();errors=[]
 if answer_jobs:
  batch=answer_jobs[:a.batch_size]
  async def one(job):
   t,m,r=job;limit=4096 if m=='glm-5.2' else 512;started=time.perf_counter()
   async with sem,per[provider(m)]:
    attempts=0;raw=None;err=None;text='';usage={}
    while True:
     async def invoke():return await backend.call(m,[{'role':'user','content':build_prompt(t)}],max_tokens=limit,temperature=.2,stream=False)
     raw,err,n=await call_retry(invoke);attempts+=n
     if raw is not None:
      text=answer_from_result(raw);usage=usage_from_result(raw,build_prompt(t),text);err=None if text.strip() else f'empty_response_at_{limit}'
     if not err or m!='glm-5.2' or not err.startswith('empty_response') or limit>=16384:break
     limit*=2
    rec={'task_id':t['id'],'dataset':t['dataset'],'task_type':t.get('task_type'),'risk_level':t['risk_level'],'model':m,'repeat':r,'answer':text,'success':not err,'error':err,'attempts':attempts,'max_tokens_used':limit,'usage':usage,'cost_usd':cost_usd(cfg,m,usage) if usage else 0.,'latency_ms':round((time.perf_counter()-started)*1000,2)}
   async with lock:append(ans_path,rec);errors.append(err) if err else None
  await asyncio.gather(*(one(x) for x in batch))
 else:
  jobs=[]
  for t in judge_tasks:
   for m in MODELS:
    for r in range(3):
     response=latest[(t['id'],m,r)]
     for j in judges(m):
      if (t['id'],m,r,j) not in judge_done:jobs.append((t,response,j))
  batch=jobs[:a.batch_size]
  async def onej(job):
   t,r,j=job;started=time.perf_counter();jp=judge_prompt(t,r['answer'])
   async with sem,per[provider(j)]:
    async def invoke():return await backend.call(j,[{'role':'user','content':jp}],max_tokens=2048 if j=='glm-5.2' else 512,temperature=0,stream=False)
    raw,err,attempts=await call_retry(invoke);text=extract_message_text(raw) if raw else '';payload=parse_judge_payload(text);err=err or (None if payload else 'judge_json_parse_failed');usage=usage_from_result(raw,jp,text) if raw else {}
    rec={'task_id':t['id'],'dataset':t['dataset'],'risk_level':t['risk_level'],'candidate_model':r['model'],'repeat':r['repeat'],'judge_model':j,'parsed':bool(payload),'score':payload.get('score') if payload else None,'dimensions':payload.get('dimensions') if payload else {},'reason':payload.get('reason') if payload else '','error':err,'attempts':attempts,'usage':usage,'cost_usd':cost_usd(cfg,j,usage) if usage else 0.,'latency_ms':round((time.perf_counter()-started)*1000,2)}
   async with lock:append(judge_path,rec);errors.append(err) if err else None
  await asyncio.gather(*(onej(x) for x in batch))
 if any(fatal(x) for x in errors if x):raise SystemExit('FATAL_PROVIDER_STOP: '+next(x for x in errors if x and fatal(x)))
 budget_check(data,seal);print(json.dumps({'processed_batch':len(batch),'errors':sum(bool(x) for x in errors)},ensure_ascii=False));await main(argparse.Namespace(data_dir=data,batch_size=a.batch_size,dry_run=True))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,default=DATA);p.add_argument('--batch-size',type=int,default=60);p.add_argument('--dry-run',action='store_true');asyncio.run(main(p.parse_args()))
