"""Bounded transport, disabled unless batch authorization was validated by caller.
Ledger SETTLED means usage-known estimate, never a paid account settlement.
"""
import json, math, os, subprocess, sys, threading, time
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
sys.path.insert(0,'/root/.worktrees/codex-dd-v51-six-arm/batch_budget_guard_20261029')
from budget import Guard

WORKER = r'''
import json,sys,urllib.request,urllib.error
x=json.load(sys.stdin)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**kw): raise RuntimeError('REDIRECT_FORBIDDEN')
op=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
r=urllib.request.Request(x['endpoint'],data=json.dumps(x['body'],ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+x['key'],'Content-Type':'application/json'},method='POST')
try:
 with op.open(r,timeout=x['timeout']) as response:
  sys.stdout.buffer.write(response.read())
except urllib.error.HTTPError as e:
 sys.stdout.buffer.write(e.read());sys.exit(2)
'''

def write(path,value):
 with Path(path).open('x') as f: json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)

def units(tokens_in,tokens_out,model):
 def cost():return int((Decimal(tokens_in)*Decimal(str(model['input_per_million']))+Decimal(tokens_out)*Decimal(str(model['output_per_million']))).to_integral_value(rounding=ROUND_CEILING))
 return dict(requests=1,input_tokens=tokens_in,output_tokens=tokens_out,total_tokens=tokens_in+tokens_out,micro_cny=cost() if model['currency']=='CNY' else 0,micro_usd=cost() if model['currency']=='USD' else 0)

class Transport:
 def __init__(self,config,guard,out,*,enabled=False,send=None):
  self.config=config;self.guard=guard;self.out=Path(out);self.out.mkdir(exist_ok=False)
  self.models={m['request_model']:m for m in config['models']}
  self.enabled=enabled;self.send=send;self.start=time.monotonic();self.lock=threading.Lock()
 def call(self,cell,node,model,body,timeout):
  if not self.enabled and self.send is None:raise RuntimeError('NO_PAID_AUTHORIZATION')
  spec=self.models[model]
  body=json.loads(json.dumps(body))
  if body.get('model')!=model or body.get('max_tokens')!=3072:raise ValueError('REQUEST_CONFIG_MISMATCH')
  if model.startswith('qwen'):body['enable_thinking']=False
  elif model=='deepseek-flash':body['thinking']={'type':'disabled'}
  else:raise ValueError('UNBOUND_MODEL')
  # Conservative local payload cap, NOT a certified provider token count.
  if len(json.dumps(body,ensure_ascii=False).encode())>131072:
   self.guard.halt('REQUEST_PAYLOAD_OVER_LOCAL_BYTE_CAP');raise ValueError('INPUT_TOO_LARGE_NO_TRUNCATION')
  remaining=min(float(timeout),180,self.config['batch_wall_s']-(time.monotonic()-self.start))
  if not math.isfinite(remaining) or remaining<=0:
   self.guard.halt('DEADLINE');raise TimeoutError('DEADLINE')
  rid=cell+'__'+node
  reqdir=self.out/rid;reqdir.mkdir(exist_ok=False)
  write(reqdir/'REQUEST.json',body)
  reserve=units(65536,3072,spec)
  self.guard.reserve(rid,model,cell,reserve)
  self.guard.mark_dispatched(rid)
  began=time.monotonic();known=False
  try:
   if self.send is not None:
    reply=self.send(body,remaining);raw=json.dumps(reply,ensure_ascii=False).encode()
   else:
    envname='DYNAMIC_PI_QWEN_KEY' if model.startswith('qwen') else 'DYNAMIC_PI_DEEPSEEK_KEY'
    key=os.environ[envname]
    # Credentials only in a private pipe, never command line, saved request or log.
    proc=subprocess.Popen([sys.executable,'-B','-c',WORKER],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
     raw,err=proc.communicate(json.dumps(dict(endpoint=spec['endpoint'],key=key,body=body,timeout=remaining)).encode(),timeout=remaining)
    except subprocess.TimeoutExpired:
     proc.kill();raw,err=proc.communicate()
     (reqdir/'PARTIAL_RESPONSE.bin').write_bytes(raw)
     raise TimeoutError('IN_FLIGHT_BILLING_UNKNOWN')
    (reqdir/'RESPONSE.bin').write_bytes(raw)
    if proc.returncode:raise RuntimeError('HTTP_OR_TRANSPORT_ERROR')
    reply=json.loads(raw)
   if not (reqdir/'RESPONSE.bin').exists():(reqdir/'RESPONSE.bin').write_bytes(raw)
   usage=reply.get('usage',{})
   ti,to,tt=usage.get('prompt_tokens'),usage.get('completion_tokens'),usage.get('total_tokens')
   if any(type(v) is not int or v<0 for v in (ti,to,tt)) or ti+to!=tt:raise ValueError('USAGE_UNKNOWN')
   measured=units(ti,to,spec);self.guard.settle(rid,measured);known=True
   write(reqdir/'ACCOUNTING.json',dict(usage=usage,public_price_estimate=measured,actual_cash_settlement=None,wall_s=time.monotonic()-began,reported_model=reply.get('model'),response_id=reply.get('id')))
   if self.guard.snapshot()['stopped']:raise RuntimeError('BUDGET_OVERRUN_STOP')
   choice=reply['choices'][0];content=choice['message'].get('content')
   # Ordinary malformed/truncated model content remains a MODEL_FAILED output.
   try:payload=json.loads(content) if choice.get('finish_reason')=='stop' and isinstance(content,str) else None
   except (json.JSONDecodeError,TypeError):payload=None
   return {'output':payload,'usage':{'tokens':tt,'cash':{'CNY':measured['micro_cny']/1e6,'USD':measured['micro_usd']/1e6}}}
  except BaseException as e:
   if not known:self.guard.mark_unknown(rid,type(e).__name__)
   self.guard.halt(type(e).__name__)
   write(reqdir/'ERROR.json',{'type':type(e).__name__,'usage_known':known,'actual_cash_settlement':None,'wall_s':time.monotonic()-began})
   raise
