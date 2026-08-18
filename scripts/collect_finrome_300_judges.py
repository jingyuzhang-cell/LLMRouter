#!/usr/bin/env python3
"""Resumable dual cross-judge collection for compliance responses."""
import argparse,asyncio,json,os,random,time
from pathlib import Path
from openclaw_router.config import OpenClawConfig
from openclaw_router.server import LLMBackend
from openclaw_router.judge_utils import extract_message_text,parse_judge_payload
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data/finance_router/finrome_300';CONFIG=ROOT/'configs/openclaw_multi_provider.yaml'
def read(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
def latest_responses():
 d={}
 for x in read(DATA/'responses.jsonl'):d[(x['task_id'],x['model'],x['repeat'])]=x
 return d
def judges(candidate):
 if candidate=='deepseek-chat':return ('qwen-plus','glm-5.2')
 if candidate in {'qwen-plus','qwen-turbo'}:return ('deepseek-chat','glm-5.2')
 return ('deepseek-chat','qwen-plus')
def prompt(task,response):
 return f'''你是独立金融合规回答评审员。只评估候选回答，不要重新回答问题。依据参考答案和给定上下文，评估准确性、完整性、推理、清晰度和安全性。严格输出一个JSON对象：{{"score":0到1,"dimensions":{{"accuracy":0到1,"completeness":0到1,"reasoning":0到1,"clarity":0到1,"safety":0到1}},"reason":"简短理由"}}。
问题：{task.get("question","")}
参考答案：{task.get("gold_answer","")}
上下文：{str(task.get("context", ""))[:12000]}
候选回答：{response}'''
def transient(e):return str(e or '').startswith(('429','500','502','503','504')) or any(x in str(e or '').lower() for x in ('timeout','temporar','connection','disconnect'))
async def main(a):
 data=a.data_dir.resolve();tasks={x['id']:x for x in read(data/'tasks.jsonl')};responses={};
 for x in read(data/'responses.jsonl'):responses[(x['task_id'],x['model'],x['repeat'])]=x
 jobs=[]
 for key,r in responses.items():
  if not r.get('success') or tasks[key[0]].get('task_type')!='financial_audit_compliance_qa':continue
  for judge in judges(key[1]):jobs.append((key,r,judge))
 existing=read(a.output);done={(x['task_id'],x['candidate_model'],x['repeat'],x['judge_model']) for x in existing if x.get('parsed')};pending=[x for x in jobs if (x[0][0],x[0][1],x[0][2],x[2]) not in done]
 if a.dry_run:
  print(json.dumps({'data_dir':str(data),'required':len(jobs),'completed':len(done),'pending':len(pending)},ensure_ascii=False));return
 if not pending:
  print(json.dumps({'required':len(jobs),'previously_done':len(done),'this_run':0,'ok':0,'failed':0,'retried':0},ensure_ascii=False));return
 providers={'deepseek-chat':'DEEPSEEK_API_KEY','qwen-plus':'QWEN_API_KEY','glm-5.2':'ZHIPU_API_KEY'};missing=sorted({providers[x[2]] for x in pending if not os.getenv(providers[x[2]])})
 if missing:raise SystemExit('Missing required API credentials: '+', '.join(missing))
 cfg=OpenClawConfig.from_yaml(str(CONFIG));backend=LLMBackend(cfg);sem=asyncio.Semaphore(a.workers);per={m:asyncio.Semaphore(2) for m in ('deepseek-chat','qwen-plus','glm-5.2')};lock=asyncio.Lock();stat={'ok':0,'failed':0,'retried':0};start=time.perf_counter()
 async def one(job):
  key,r,j=job;task=tasks[key[0]];attempt=0;error=None;payload=None;raw=''
  async with sem,per[j]:
   while attempt<=a.retries:
    try:
     
     token_limit=2048 if j=='glm-5.2' else 512
     result=await backend.call(j,[{'role':'user','content':prompt(task,r.get('answer',''))}],max_tokens=token_limit,temperature=0,stream=False);raw=extract_message_text(result);payload=parse_judge_payload(raw);error=None if payload else 'judge_json_parse_failed'
    except Exception as e:error=str(e)[:500]
    if payload or not transient(error):break
    attempt+=1;stat['retried']+=1
    if attempt<=a.retries:await asyncio.sleep(min(30,2**attempt+random.random()))
  rec={'task_id':key[0],'candidate_model':key[1],'repeat':key[2],'judge_model':j,'parsed':bool(payload),'score':payload.get('score') if payload else None,'dimensions':payload.get('dimensions') if payload else {},'reason':payload.get('reason') if payload else '','error':error,'attempts':attempt+1};stat['ok' if payload else 'failed']+=1
  async with lock:
   with a.output.open('a',encoding='utf-8') as h:h.write(json.dumps(rec,ensure_ascii=False)+'\n');h.flush();os.fsync(h.fileno())
   n=stat['ok']+stat['failed']
   if n%20==0:print(json.dumps({'completed':n,'pending_start':len(pending),**stat,'elapsed_s':round(time.perf_counter()-start,1)},ensure_ascii=False),flush=True)
 await asyncio.gather(*(one(x) for x in pending));print(json.dumps({'required':len(jobs),'previously_done':len(done),'this_run':sum(stat[k] for k in ('ok','failed')),**stat},ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,default=DATA);p.add_argument('--output',type=Path,default=None);p.add_argument('--workers',type=int,default=6);p.add_argument('--dry-run',action='store_true');p.add_argument('--retries',type=int,default=3);a=p.parse_args();a.output=a.output or a.data_dir/'judges.jsonl';a.output.parent.mkdir(parents=True,exist_ok=True);asyncio.run(main(a))
