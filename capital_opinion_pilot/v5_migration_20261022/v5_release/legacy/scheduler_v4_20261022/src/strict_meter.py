"""Opt-in fail-closed meter sharing the existing real HTTP transport.
No character-ratio estimate is accepted as a certified token bound.
"""
import fcntl,hashlib,json,os,time
from pathlib import Path
from pilot_common import Meter,BudgetExceeded

def append_sync(path,row):
 with path.open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())

class StrictMeter(Meter):
 def __init__(self,*a,**kw):
  super().__init__(*a,**kw);self.journal=self.ledger.with_name(self.ledger.stem+'_reservations.jsonl');self.lock_path=self.ledger.with_suffix('.lock')
 def call(self,alias,system,user,max_tokens=512,purpose='unspecified',timeout_s=60,*,input_upper=None,bound_evidence=None):
  self.ledger.parent.mkdir(parents=True,exist_ok=True)
  with self.lock_path.open('a+') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   events=[json.loads(l) for l in self.journal.read_text().splitlines() if l.strip()] if self.journal.exists() else []
   if self.ledger.exists() and self.ledger.stat().st_size and not events:raise BudgetExceeded('LEGACY_LEDGER_WITHOUT_RESERVATIONS')
   reservations={e['request_id']:e for e in events if e['event']=='RESERVE'};settled={e['request_id']:e for e in events if e['event']=='SETTLE'}
   key=hashlib.sha256((alias+'\0'+system+'\0'+user).encode()).hexdigest()
   for rid,res in reservations.items():
    if res['identity']==key:
     if rid not in settled:raise BudgetExceeded('UNKNOWN_PRIOR_ATTEMPT_NO_RETRY')
     e=settled[rid]
     if e['status']!='COMPLETE':raise BudgetExceeded('PRIOR_FAILED_ATTEMPT_NO_RETRY')
     return e['record'],e['text']
   if any(e['status']=='BOUND_VIOLATION' for e in settled.values()):raise BudgetExceeded('PROVIDER_BOUND_VIOLATION_STOP')
   actual=sum(e['actual_tokens'] for e in settled.values());pending=sum(e['tokens'] for rid,e in reservations.items() if rid not in settled)
   if len(reservations)>=self.max_calls:raise BudgetExceeded('REQUEST_CAP')
   if type(input_upper)!=int or input_upper<0 or not bound_evidence:raise BudgetExceeded('CERTIFIED_INPUT_BOUND_REQUIRED')
   if type(max_tokens)!=int or max_tokens<1:raise BudgetExceeded('OUTPUT_BOUND_REQUIRED')
   amount=input_upper+max_tokens
   if actual+pending+amount>self.max_guaranteed_actual:raise BudgetExceeded('TOKEN_CAP_PRE_DISPATCH')
   rid=str(len(reservations)+1)
   append_sync(self.journal,dict(event='RESERVE',request_id=rid,identity=key,tokens=amount,input_upper=input_upper,max_tokens=max_tokens,bound_evidence=bound_evidence,model_alias=alias,timeout_s=timeout_s,ts=time.time()))
   # Any transport exception/crash leaves the entire durable reservation outstanding.
   r=self._transport(alias,system,user,max_tokens,timeout_s)
   usage=r.get('usage',{})
   if any(type(usage.get(k))!=int or usage[k]<0 for k in ('input_tokens','output_tokens')):raise BudgetExceeded('UNKNOWN_USAGE_RESERVATION_RETAINED')
   used=usage['input_tokens']+usage['output_tokens']
   violation=usage['input_tokens']>input_upper or usage['output_tokens']>max_tokens or actual+pending+used>self.max_guaranteed_actual
   status='BOUND_VIOLATION' if violation else 'TRUNCATED' if r.get('stop_reason')=='max_tokens' else 'COMPLETE'
   rec=dict(call_id=len(reservations)+1,model_alias=alias,purpose=purpose,prompt_sha256=hashlib.sha256((system+'\0'+user).encode()).hexdigest(),max_tokens=max_tokens,usage=usage,stop_reason=r.get('stop_reason'),latency_s=r['latency_s'],status=status)
   # This record contains raw response and settlement atomically; resume never retransmits.
   append_sync(self.journal,dict(event='SETTLE',request_id=rid,actual_tokens=used,status=status,record=rec,text=r['text'],ts=time.time()))
   append_sync(self.ledger,rec);append_sync(self.responses_path,dict(call_id=rec['call_id'],text=r['text'],usage=usage,stop_reason=r.get('stop_reason')))
   if status!='COMPLETE':raise BudgetExceeded(status)
   return rec,r['text']

 def summary(self):
  rows=[json.loads(l) for l in self.journal.read_text().splitlines() if l.strip()] if self.journal.exists() else []
  reserves={e['request_id']:e for e in rows if e['event']=='RESERVE'};settles={e['request_id']:e for e in rows if e['event']=='SETTLE'}
  actual=sum(e['actual_tokens'] for e in settles.values());pending=sum(e['tokens'] for r,e in reserves.items() if r not in settles)
  return {'requests':len(reserves),'actual_tokens':actual,'pending_reserve':pending,'charged_tokens':actual+pending,'budget_cap':self.max_guaranteed_actual,'unknown_attempts':[r for r in reserves if r not in settles]}
