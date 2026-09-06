"""Resume-safe E5 collection and scoring, global $10 accounting incl. uncertain calls."""
import argparse,asyncio,fcntl,hashlib,json,os,sys,time
from pathlib import Path
ROOT=Path('/root');sys.path.insert(0,str(ROOT));OUT=ROOT/'phase_e5_unified'
from phase_e5_unified.common import MODELS,LADDERS,whole_prompt,delivery
from run_e4_0_b_exploration import load_env,PROJECT,CONFIG
from phase_e4_0.execution_controls import generation_ceiling_binding
from phase_e4_1.deterministic_extractor import score_deterministic
from phase_e4_1.judge_format_normalization import parse_scores
load_env();sys.path.insert(0,str(PROJECT))
from openclaw_router.config import OpenClawConfig
from openclaw_router.server import LLMBackend
from scripts.run_finance_model_evaluation import answer_from_result,cost_usd

def rows(p):return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
def append(p,r):
 with p.open('a') as h:h.write(json.dumps(r,ensure_ascii=False)+'\n');h.flush();os.fsync(h.fileno())
def atomic(p,r):
 t=p.with_suffix('.tmp');t.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');t.replace(p)
class BudgetExceeded(RuntimeError):pass
class Engine:
 def __init__(self):
  self.cfg=OpenClawConfig.from_yaml(str(CONFIG));self.backend=LLMBackend(self.cfg)
  self.lock=asyncio.Lock();self.provider_locks={}
  self.budgetpath=OUT/'BUDGET.json'
  self.budget=json.loads(self.budgetpath.read_text()) if self.budgetpath.exists() else {'cap_usd':10.,'reservations':{}}
  self.events=OUT/'CALL_EVENTS.jsonl'
 def charged(self):return sum(r.get('charged_usd',r['bound_usd']) for r in self.budget['reservations'].values())
 async def call(self,key,model,prompt,ceiling,timeout,retry_backoff_ms=0.):
  cached=[r for r in rows(self.events) if r["call_key"]==key]
  if cached:return cached[-1]
  provider=self.cfg.llms[model].provider
  async with self.provider_locks.setdefault(provider,asyncio.Lock()):
   llm=self.cfg.llms[model]
   # Full configured context plus output is a conservative configured-price upper bound.
   if llm.input_price<=0 or llm.output_price<=0:raise RuntimeError('Unknown model pricing')
   bound=(llm.context_limit*llm.input_price+ceiling*llm.output_price)/1e6
   async with self.lock:
    if key in self.budget['reservations']:raise RuntimeError('Unresolved previous call; inspect call ledger before retry')
    if self.charged()+bound>10:raise BudgetExceeded('Budget reservation would exceed $10')
    self.budget['reservations'][key]={'bound_usd':bound,'model':model,'status':'RESERVED'};atomic(self.budgetpath,self.budget)
   start=time.perf_counter();result={};error=None
   try:result=await asyncio.wait_for(self.backend.call(model,[{'role':'user','content':prompt}],max_tokens=ceiling,temperature=0,stream=False,timeout=timeout),timeout+5)
   except Exception as exc:error=type(exc).__name__
   elapsed=(time.perf_counter()-start)*1000
   usage=result.get('usage') or {};known=isinstance(usage,dict) and 'prompt_tokens' in usage and 'completion_tokens' in usage
   charged=cost_usd(self.cfg,model,usage) if known else bound
   row={'call_key':key,'model':model,'provider':provider,'requested_model_id':llm.model_id,'returned_model':result.get('model'),'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'requested_ceiling':ceiling,'timeout_seconds':timeout,'latency_ms':elapsed,'retry_backoff_ms':retry_backoff_ms,'usage':usage,'configured_price_cost_usd':charged if known else None,'accounted_upper_bound_usd':charged,'billing_known':known,'error_type':error,'raw_response':result}
   append(self.events,row)
   async with self.lock:
    self.budget['reservations'][key].update(status='SETTLED' if known else 'UNKNOWN_BILLING_BOUND_RETAINED',charged_usd=charged)
    atomic(self.budgetpath,self.budget)
   if charged>bound or self.charged()>10:raise BudgetExceeded('Observed accounting exceeds reserved configured-price bound')
   return row
 async def generate(self,key,task,model):
  path=OUT/'WHOLE_QUERY_RECORDS.jsonl'
  if key in {r['key'] for r in rows(path)}:return
  prompt=whole_prompt(task);history=[r for r in rows(self.events) if r['call_key'].startswith(key+'|')]
  raw='';result={};binding=False;success=False;backoff=0.;error_count=sum(bool(r['error_type']) for r in history)
  level=0
  if history:
   # A completed response without a saved final record is recovered without another API call.
   last=history[-1];result=last.get('raw_response',{});raw=answer_from_result(result) if result else ''
   reason=(result.get('choices') or [{}])[0].get('finish_reason')
   binding=generation_ceiling_binding(reason,last.get('usage'),last['requested_ceiling'],empty_output=not raw.strip())
   success=last['error_type'] is None and bool(raw.strip())
   if binding:level=next((i for i,v in enumerate(LADDERS['N4']) if v>last['requested_ceiling']),4)
  while not (success and not binding) and error_count<3 and level<4:
   delay=0
   if history and not binding:
    delay=(30,120)[min(error_count-1,1)];await asyncio.sleep(delay);backoff+=delay*1000
   item=await self.call(f'{key}|{len(history)+1}',model,prompt,LADDERS['N4'][level],120,retry_backoff_ms=delay*1000)
   history.append(item);result=item['raw_response'];raw=answer_from_result(result) if result else ''
   reason=(result.get('choices') or [{}])[0].get('finish_reason')
   binding=generation_ceiling_binding(reason,item['usage'],item['requested_ceiling'],empty_output=not raw.strip())
   success=item['error_type'] is None and bool(raw.strip())
   if binding:level+=1
   elif not success:error_count+=1
  valid,obj=delivery(raw,success,binding)
  record={'key':key,'task_id':task['task_id'],'model':model,'raw_output':raw,'parsed_output':obj,'provider_success':success,'generation_ceiling_binding':binding,'workflow_valid':valid,'attempts':len(history),'cost_usd':sum(r['accounted_upper_bound_usd'] for r in history),'cost_is_upper_bound':any(not r['billing_known'] for r in history),'provider_latency_ms':sum(r['latency_ms'] for r in history),'retry_backoff_ms':sum(r.get('retry_backoff_ms',0) for r in history),'latency_ms':sum(r['latency_ms']+r.get('retry_backoff_ms',0) for r in history)}
  append(path,record);print(json.dumps({'collected':key,'valid':valid,'budget_accounted':self.charged()}),flush=True)

def judge_prompt(task,answer):
 # Reuse the exact frozen atomic prompt without importing its data-loading module.
 import ast
 source=(ROOT/'phase_e4_1/run_phase_a_final_scoring.py').read_text();tree=ast.parse(source)
 fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='atomic_prompt')
 ns={'json':json};exec(compile(ast.Module(body=[fn],type_ignores=[]),'<frozen atomic prompt>','exec'),ns)
 return ns['atomic_prompt'](task,answer)

async def run(stage):
 protocol=json.loads((OUT/'EXECUTION_PROTOCOL.json').read_text())
 for rel,digest in protocol['artifact_sha256'].items():
  if hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()!=digest:raise RuntimeError('Frozen file changed: '+rel)
 engine=Engine();tasks={r['task_id']:r for r in rows(OUT/'DEVELOPMENT_TASKS.jsonl')}
 if stage=='preflight':
  print(json.dumps({'tasks':len(tasks),'calls':len(tasks)*4,'known_pricing':{m:engine.cfg.llms[m].input_price>0 and engine.cfg.llms[m].output_price>0 for m in (*MODELS,'qwen-max')},'accounted_usd':engine.charged(),'cap_usd':10.},indent=2));return
 if stage=='collect':
  # At most four in flight; provider locks ensure one call/provider.
  jobs=[(f"dev|{t}|{m}",tasks[t],m) for t in sorted(tasks) for m in MODELS]
  for i in range(0,len(jobs),4):
   result=await asyncio.gather(*(engine.generate(*j) for j in jobs[i:i+4]),return_exceptions=True)
   failures=[str(r) for r in result if isinstance(r,Exception)]
   if failures:raise RuntimeError('; '.join(failures))
 elif stage=='score':
  records=rows(OUT/'WHOLE_QUERY_RECORDS.jsonl');assert len(records)==160 and len({r['key'] for r in records})==160
  assert not any(r['generation_ceiling_binding'] for r in records),'Engineering ceiling binding blocks scoring'
  contracts={r['task_id']:r for r in json.loads((ROOT/'phase_e4_1/E4_1_NUMERIC_UNIT_CONTRACT_FROZEN.json').read_text())['tasks']}
  path=OUT/'WHOLE_QUERY_LABELS.jsonl';done={r['key'] for r in rows(path)}
  for rec in records:
   if rec['key'] in done:continue
   tid=rec['task_id'];q=None;layer='delivery_failure';details={}
   if not rec['workflow_valid']:q=0.
   elif tid in contracts:
    details=score_deterministic(rec['parsed_output']['answer'],contracts[tid]);q=details['score'];layer='deterministic'
   else:
    layer='machine_qwen_only';prompt=judge_prompt(tasks[tid],rec['parsed_output']['answer'])
    for attempt in range(3):
     call=await engine.call(f"judge|{rec['key']}|{attempt}",'qwen-max',prompt,1500,90)
     try:q=parse_scores(answer_from_result(call['raw_response']),['A'])['A']/4.;break
     except (ValueError,TypeError,KeyError):pass
   append(path,{'key':rec['key'],'task_id':tid,'model':rec['model'],'Q':q,'R':float(rec['workflow_valid']),'scoring_layer':layer,'details':details})
   print(json.dumps({'scored':rec['key'],'missing':q is None,'budget_accounted':engine.charged()}),flush=True)
  assert len(rows(path))==160 and all(r['Q'] is not None for r in rows(path)), 'Missing evaluator labels block training'
 atomic(OUT/f'{stage.upper()}_STATUS.json',{'status':'COMPLETE','accounted_usd':engine.charged()})
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['preflight','collect','score']);args=parser.parse_args()
 with (OUT/'RUN.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:asyncio.run(run(args.stage))
  except Exception as exc:
   atomic(OUT/f'{args.stage.upper()}_STATUS.json',{'status':'STOPPED','reason':str(exc)});raise
