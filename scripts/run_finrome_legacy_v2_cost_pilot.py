#!/usr/bin/env python3
"""Twelve-task priced pilot; outputs are forbidden for policy tuning."""
import argparse,asyncio,hashlib,json,os,random,time
from collections import Counter,defaultdict
from pathlib import Path
from openclaw_router.config import OpenClawConfig
from openclaw_router.server import LLMBackend
from openclaw_router.judge_utils import extract_message_text,parse_judge_payload
from scripts.run_finance_model_evaluation import build_prompt,answer_from_result,usage_from_result,cost_usd
from scripts.collect_finrome_300_judges import prompt as judge_prompt,judges

ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT/'data/finance_router/finrome_legacy_v2_confirmatory';OUT=ROOT/'run_logs/finrome_legacy_v2_cost_pilot';CONFIG=ROOT/'configs/openclaw_multi_provider.yaml';MODELS=('deepseek-chat','qwen-plus','qwen-turbo','glm-5.2');SEED=20260823
def rows(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def append(p,x):
 with p.open('a',encoding='utf-8') as h:h.write(json.dumps(x,ensure_ascii=False)+'\n');h.flush();os.fsync(h.fileno())
def prepare():
 OUT.mkdir(parents=True,exist_ok=True);p=OUT/'tasks.jsonl'
 if p.exists():return rows(p)
 by=defaultdict(list)
 for x in rows(SOURCE/'tasks.jsonl'):by[x['dataset']].append(x)
 chosen=[]
 for i,name in enumerate(sorted(by)):chosen+=random.Random(SEED+i).sample(sorted(by[name],key=lambda x:x['id']),3)
 random.Random(SEED).shuffle(chosen);p.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in chosen));manifest={'status':'COST_ONLY_NO_POLICY_TUNING','seed':SEED,'tasks':12,'dataset_counts':dict(Counter(x['dataset'] for x in chosen)),'risk_counts':dict(Counter(x['risk_level'] for x in chosen)),'answer_calls':144,'dual_judge_calls':288,'formal_policy_use_prohibited':True,'task_sha256':sha(p)};(OUT/'PILOT_CONTRACT.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');return chosen
async def run(a):
 tasks=prepare();cfg=OpenClawConfig.from_yaml(str(CONFIG));backend=LLMBackend(cfg);ans=OUT/'responses.jsonl';jout=OUT/'judges.jsonl';done={(x['task_id'],x['model'],x['repeat']) for x in rows(ans) if x.get('success') and str(x.get('answer') or '').strip()};jobs=[(t,m,r) for t in tasks for m in MODELS for r in range(3) if (t['id'],m,r) not in done]
 if a.dry_run:print(json.dumps({'answers_required':144,'answers_done':len(done),'answers_pending':len(jobs),'judges_required':288},ensure_ascii=False));return
 need={'DEEPSEEK_API_KEY','QWEN_API_KEY','ZHIPU_API_KEY'};missing=sorted(x for x in need if not os.getenv(x));
 if missing:raise SystemExit('Missing required API credentials: '+', '.join(missing))
 sem=asyncio.Semaphore(6);lock=asyncio.Lock()
 async def answer(job):
  t,m,r=job;limit=4096 if m=='glm-5.2' else 512;started=time.perf_counter();error=None;result=None
  async with sem:
   for attempt in range(3):
    try:
     raw=await backend.call(m,[{'role':'user','content':build_prompt(t)}],max_tokens=limit,temperature=.2,stream=False);text=answer_from_result(raw);usage=usage_from_result(raw,build_prompt(t),text);error=None if text.strip() else f'empty_response_at_{limit}'
    except Exception as e:text='';usage={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0};error=str(e)[:500]
    if not error:break
    if m=='glm-5.2' and error.startswith('empty_response') and limit<16384:limit*=2
   result={'task_id':t['id'],'dataset':t['dataset'],'risk_level':t['risk_level'],'model':m,'repeat':r,'answer':text,'success':not error,'error':error,'attempts':attempt+1,'max_tokens_used':limit,'usage':usage,'cost_usd':cost_usd(cfg,m,usage),'latency_ms':round((time.perf_counter()-started)*1000,2)}
  async with lock:append(ans,result)
 await asyncio.gather(*(answer(x) for x in jobs))
 latest={(x['task_id'],x['model'],x['repeat']):x for x in rows(ans)}
 if len([x for x in latest.values() if x.get('success') and str(x.get('answer') or '').strip()])<144:raise SystemExit('Answer pilot incomplete; rerun to resume.')
 tmap={x['id']:x for x in tasks};jdone={(x['task_id'],x['candidate_model'],x['repeat'],x['judge_model']) for x in rows(jout) if x.get('parsed')};jj=[]
 for key,r in latest.items():
  for j in judges(key[1]):
   if (key[0],key[1],key[2],j) not in jdone:jj.append((key,r,j))
 async def judge(job):
  key,r,j=job;t=tmap[key[0]];started=time.perf_counter();error=None;payload=None;usage={};rawtext=''
  async with sem:
   try:
    raw=await backend.call(j,[{'role':'user','content':judge_prompt(t,r['answer'])}],max_tokens=2048 if j=='glm-5.2' else 512,temperature=0,stream=False);rawtext=extract_message_text(raw);payload=parse_judge_payload(rawtext);usage=usage_from_result(raw,judge_prompt(t,r['answer']),rawtext);error=None if payload else 'judge_json_parse_failed'
   except Exception as e:error=str(e)[:500]
  rec={'task_id':key[0],'dataset':t['dataset'],'risk_level':t['risk_level'],'candidate_model':key[1],'repeat':key[2],'judge_model':j,'parsed':bool(payload),'score':payload.get('score') if payload else None,'error':error,'usage':usage,'cost_usd':cost_usd(cfg,j,usage) if usage else 0.,'latency_ms':round((time.perf_counter()-started)*1000,2)}
  async with lock:append(jout,rec)
 await asyncio.gather(*(judge(x) for x in jj));summarize(cfg)
def summarize(cfg):
 ans=rows(OUT/'responses.jsonl');jud=rows(OUT/'judges.jsonl');la={};lj={}
 for x in ans:la[(x['task_id'],x['model'],x['repeat'])]=x
 for x in jud:lj[(x['task_id'],x['candidate_model'],x['repeat'],x['judge_model'])]=x
 def agg(values,key):
  g=defaultdict(list)
  for x in values:g[x[key]].append(x)
  return {k:{'calls':len(v),'success_rate':sum(bool(x.get('success',x.get('parsed'))) for x in v)/len(v),'mean_prompt_tokens':sum((x.get('usage') or {}).get('prompt_tokens',0) for x in v)/len(v),'mean_completion_tokens':sum((x.get('usage') or {}).get('completion_tokens',0) for x in v)/len(v),'cost_usd':sum(x.get('cost_usd',0) for x in v),'mean_latency_ms':sum(x.get('latency_ms',0) for x in v)/len(v)} for k,v in sorted(g.items())}
 empty=[x for x in la.values() if not str(x.get('answer') or '').strip()];glm=[x for x in la.values() if x['model']=='glm-5.2'];formal_answer=sum(x.get('cost_usd',0) for x in la.values())/len(la)*9600;formal_judge=sum(x.get('cost_usd',0) for x in lj.values())/len(lj)*12600;report={'status':'PILOT_COMPLETE' if len(la)==144 and len(lj)==288 else 'INCOMPLETE','contract':'cost estimation only; prohibited for policy tuning or efficacy claims','answers':agg(la.values(),'model'),'judges':agg(lj.values(),'judge_model'),'glm_truncation':{'calls':len(glm),'empty_final':sum(not str(x.get('answer') or '').strip() for x in glm),'escalated_above_4096':sum(x.get('max_tokens_used',4096)>4096 for x in glm)},'observed_cost_usd':sum(x.get('cost_usd',0) for x in la.values())+sum(x.get('cost_usd',0) for x in lj.values()),'projected_formal':{'answer_calls':9600,'judge_calls':12600,'total_calls':22200,'answer_cost_usd':formal_answer,'judge_cost_usd':formal_judge,'total_cost_usd':formal_answer+formal_judge},'elapsed_estimate_hours_serial_equivalent':(sum(x.get('latency_ms',0) for x in la.values())/144*9600+sum(x.get('latency_ms',0) for x in lj.values())/288*12600)/3.6e6,'human_review':'PENDING'};(OUT/'PILOT_REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--dry-run',action='store_true');asyncio.run(run(p.parse_args()))
