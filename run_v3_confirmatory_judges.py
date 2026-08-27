#!/usr/bin/env python3
"""Strict-cap dual judging of successful v3 Gemini compliance responses."""
import asyncio,json,os,sys,time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
PROJECT=Path('/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main');DATA=Path('/root/v3_confirmatory');TASKS=DATA/'V3_CONFIRMATORY_TASKS.jsonl';RESP=DATA/'V3_NEW_RESPONSES.jsonl';OUT=DATA/'V3_GEMINI_COMPLIANCE_JUDGES.jsonl';EVENTS=DATA/'V3_JUDGE_FAILURES.jsonl';CONFIG=PROJECT/'configs/openclaw_multi_provider.yaml';JUDGES=('deepseek-chat','qwen-plus')
def read(p):return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()] if Path(p).exists() else []
for line in Path('/root/.env').read_text().splitlines():
 line=line.strip()
 if line and not line.startswith('#') and '=' in line:
  k,v=line.split('=',1);os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
def prompt(t,a):return f'''你是独立金融合规回答评审员。只评估候选回答，不要重新回答问题。依据参考答案和给定上下文，评估准确性、完整性、推理、清晰度和安全性。严格输出一个JSON对象：{{"score":0到1,"dimensions":{{"accuracy":0到1,"completeness":0到1,"reasoning":0到1,"clarity":0到1,"safety":0到1}},"reason":"简短理由"}}。\n问题：{t.get("question","")}\n参考答案：{t.get("gold_answer","")}\n上下文：{str(t.get("context",""))[:12000]}\n候选回答：{a}'''
async def main():
 sys.path.insert(0,str(PROJECT));from openclaw_router.config import OpenClawConfig;from openclaw_router.judge_utils import extract_message_text,parse_judge_payload;from openclaw_router.server import LLMBackend;from scripts.run_finance_model_evaluation import usage_from_result,cost_usd
 tasks={x['id']:x for x in read(TASKS) if x['dataset']=='ObliQA'};responses={(x['task_id'],int(x['repeat'])):x for x in read(RESP) if x['task_id'] in tasks and x['model']=='gemini-2.5-flash' and x['success'] and str(x.get('answer') or '').strip()};expected={(t,r,j) for t,r in responses for j in JUDGES};assert len(expected)<=240
 previous=read(OUT);attempted={(x['task_id'],int(x['repeat']),x['judge_model']) for x in previous};jobs=sorted(expected-attempted);assert len(previous)+len(jobs)<=240;print(json.dumps({'full_expected':240,'valid_response_keys':len(responses),'judge_keys_now':len(expected),'already_attempted':len(attempted),'pending':len(jobs)}),flush=True)
 cfg=OpenClawConfig.from_yaml(str(CONFIG));backend=LLMBackend(cfg);sem=asyncio.Semaphore(4);per={j:asyncio.Semaphore(2) for j in JUDGES};lock=asyncio.Lock();stats={'parsed':0,'failed':0};calls=Counter()
 async def one(key):
  tid,repeat,j=key;t=tasks[tid];pr=prompt(t,responses[(tid,repeat)]['answer']);payload=None;usage={};error=None;started=time.perf_counter()
  try:
   async with sem,per[j]:result=await backend.call(j,[{'role':'user','content':pr}],max_tokens=1024 if j=='qwen-plus' else 512,temperature=0,stream=False)
   raw=extract_message_text(result);payload=parse_judge_payload(raw);usage=usage_from_result(result,pr,raw);error=None if payload else 'judge_json_parse_failed'
  except Exception as exc:error=str(exc)[:1000]
  row={'task_id':tid,'candidate_model':'gemini-2.5-flash','repeat':repeat,'judge_model':j,'parsed':bool(payload),'score':payload.get('score') if payload else None,'dimensions':payload.get('dimensions') if payload else {},'reason':payload.get('reason') if payload else '','error':error,'attempts':1,'usage':usage,'cost_usd':cost_usd(cfg,j,usage) if usage else 0.0,'latency_ms':round((time.perf_counter()-started)*1000,2),'timestamp':datetime.now(timezone.utc).isoformat()}
  async with lock:
   with OUT.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
   calls[j]+=1;stats['parsed' if payload else 'failed']+=1
   if not payload:
    with EVENTS.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
   done=stats['parsed']+stats['failed']
   if done%20==0:print(json.dumps({'completed':done,**stats,'calls':dict(calls)}),flush=True)
 await asyncio.gather(*(one(x) for x in jobs));print(json.dumps({'new_calls':len(jobs),**stats,'calls':dict(calls)}),flush=True)
if __name__=='__main__':asyncio.run(main())
