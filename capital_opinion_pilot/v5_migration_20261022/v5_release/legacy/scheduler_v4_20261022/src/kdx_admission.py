"""Offline final gate helpers. No real service implementation is provided."""
import copy,fcntl,json,time
from contextlib import contextmanager
from pathlib import Path
from kdx_execution_adapter import sha

class Lineage:
 def __init__(self,corpus):self.corpus=corpus;self.facts={}
 def register(self,fact):
  if not isinstance(fact,dict) or not fact.get('fact_id') or not fact.get('content') or not fact.get('applicable_time') or not fact.get('origins'):raise ValueError('FACT_LINEAGE_REQUIRED')
  for origin in fact['origins']:
   c=next((c for c in self.corpus.chunks if c['fragment_id']==origin.get('chunk_id')),None)
   if not c or any(origin.get(k)!=c[v] for k,v in [('document_id','document_id'),('source_hash','source_hash'),('start','start'),('end','end')]):raise ValueError('BROKEN_LINEAGE')
   if not origin.get('quote') or origin['quote'] not in c['text']:raise ValueError('QUOTE_NOT_LOCATED')
  old=self.facts.get(fact['fact_id'])
  if old and old!=fact:raise ValueError('FACT_ID_REDEFINED')
  self.facts[fact['fact_id']]=copy.deepcopy(fact)
  return copy.deepcopy(fact)
 def consume(self,ids,propagated,required=()):
  if set(required)-set(ids):raise ValueError('NECESSARY_FACT_MISSING')
  for ident in ids:
   if ident not in self.facts or propagated.get(ident)!=self.facts[ident]:raise ValueError('LINEAGE_OR_UNCERTAINTY_LOST')
  return [copy.deepcopy(self.facts[i]) for i in ids]

class TokenBoundary:
 """Requires a trusted deployment-specific full-request counter, not arbitrary text count."""
 def __init__(self,model_id,tokenizer_id,counter,evidence,output_cap_verified=False):
  self.model_id=model_id;self.tokenizer_id=tokenizer_id;self.counter=counter;self.evidence=evidence;self.output_cap_verified=output_cap_verified
 def bound(self,request):
  if request.get('model')!=self.model_id:raise ValueError('MODEL_ID_MISMATCH')
  if not self.counter or not self.evidence or not self.output_cap_verified:raise ValueError('TRUSTED_TOKEN_BOUND_UNAVAILABLE')
  # counter must include service-side formatting/system/chat wrappers and all billable input.
  count=self.counter(request)
  if type(count)!=int or count<0:raise ValueError('INVALID_TOKEN_COUNT')
  return count,self.evidence

class Lifecycle:
 """Own-resource-only service hook, tested with Mock; no subprocess/model loading here."""
 def __init__(self,lock_path,run_path,seconds,clock=time.monotonic):
  self.lock_path=Path(lock_path);self.run_path=Path(run_path);self.seconds=seconds;self.clock=clock;self.events=[]
 @contextmanager
 def own_service(self,service,load_budget,cleanup_budget):
  start=self.clock();lock=self.lock_path.open('a+');owned=False;primary=None
  try:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   # Atomic run directory is a permanent duplicate-start marker, including failures.
   self.run_path.mkdir(exist_ok=False)
   if self.seconds<load_budget+cleanup_budget:raise ValueError('WALLCLOCK_LOAD_REJECTED')
   owned=True;service.start();self.events.append({'event':'STARTED','elapsed':self.clock()-start})
   if not service.identity_ok():raise ValueError('SERVICE_IDENTITY_MISMATCH')
   def admit(timeout):
    if self.clock()-start+timeout+cleanup_budget>self.seconds:raise ValueError('WALLCLOCK_REQUEST_REJECTED')
   yield admit
  except BaseException as e:primary=type(e).__name__;raise
  finally:
   if owned:
    try:service.cancel();service.stop();self.events.append({'event':'CLEANED'})
    except BaseException as e:self.events.append({'event':'CLEANUP_FAILED','error':type(e).__name__})
   self.events.append({'event':'END','primary_error':primary,'elapsed':self.clock()-start,'hard_deadline_exceeded':self.clock()-start>self.seconds})
   if self.run_path.exists() and owned:(self.run_path/'LIFECYCLE.json').write_text(json.dumps(self.events))
   lock.close()
 # Hook timing cannot prove hard deadline unless start/cancel/stop themselves have enforced bounds.

class FinalNodeGate:
 """Opt-in protected KDX node dispatch; no DAG runner and no real-service default."""
 def __init__(self,adapter,boundary,lineage,deadline_admit):
  from kdx_execution_adapter import KDXNodeAdapter
  if type(adapter) is not KDXNodeAdapter:raise ValueError('LEGACY_ENTRY_FORBIDDEN')
  self.adapter=adapter;self.boundary=boundary;self.lineage=lineage;self.deadline_admit=deadline_admit
 def dispatch(self,node_id,upstream,question,fragments,*,fact_ids,propagated,required,alias,max_output,timeout_s=60):
  from pilot_common import MODELS
  _,_,payload=self.adapter.prepare(node_id,upstream,question,fragments)
  self.lineage.consume(fact_ids,propagated,required)
  self.deadline_admit(timeout_s)
  system='Produce JSON with exactly the registered output ports; citations must point to supplied source fragments. Do not adjudicate contradictory sources.'
  request={'model':MODELS[alias],'max_tokens':max_output,'thinking':{'type':'disabled'},'system':system,'messages':[{'role':'user','content':json.dumps(payload,ensure_ascii=False,sort_keys=True)}]}
  upper,evidence=self.boundary.bound(request)
  return self.adapter.dispatch_node(node_id,upstream,question,fragments,alias=alias,input_upper=upper,bound_evidence=evidence,max_output=max_output,timeout_s=timeout_s)
