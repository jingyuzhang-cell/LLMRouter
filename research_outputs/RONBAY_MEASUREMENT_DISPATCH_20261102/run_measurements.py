"""Single authorized 60-cell RQ1 batch. No stage2, fallback, retry or network preflight."""
import json,sys,os,shlex,time,hashlib,math
from pathlib import Path
from decimal import Decimal
from transport import Transport,Guard,write,units
P=Path(__file__).resolve().parent
BASE=Path('/root/research_outputs/RONBAY_FINAL_ADMISSION_20261102')
KEYS={'ZHIPUAI_API_KEY':'RQ1_GLM_KEY','DEEPSEEK_API_KEY':'DYNAMIC_PI_DEEPSEEK_KEY','DASHSCOPE_API_KEY':'DYNAMIC_PI_QWEN_KEY'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def authorization(a):
 if a.get('authorized') is not True or a.get('max_requests')!=60 or a.get('max_calls_per_model')!=15 or a.get('stage2_authorized') is not False:raise ValueError('AUTHORIZATION_REQUIRED_EXACT_60')
 cap=a.get('CNY_equivalent_estimate_stop')
 if type(cap) not in (int,float) or not math.isfinite(cap) or cap<=0:raise ValueError('NEW_BATCH_BUDGET_REQUIRED')
 if a.get('USD_to_CNY')!=8 or a.get('accept_non_absolute_bill_cap') is not True or a.get('accept_input_reservation_error') is not True:raise ValueError('RISK_AUTHORIZATION_REQUIRED')
 frozen={m['key']:m for m in json.loads((BASE/'MODEL_BINDINGS.json').read_text())['models']}
 if set(a['models'])!=set(frozen):raise ValueError('EXACT_FOUR_MODELS_REQUIRED')
 for k,m in a['models'].items():
  if any(m[x]!=frozen[k][x] for x in ('model_id','endpoint')):raise ValueError('MODEL_SUBSTITUTION_FORBIDDEN')
  if m['currency']!=frozen[k]['price']['currency']:raise ValueError('CURRENCY_MISMATCH')
  if m.get('account_confirmed') is not True or not m.get('account_evidence'):raise ValueError('ACCOUNT_CONFIRMATION_REQUIRED')
  if m.get('completion_usage_includes_all_billed_thinking') is not True or not m.get('usage_basis_evidence'):raise ValueError('USAGE_BASIS_REQUIRED')
  for x in ('input_per_million','output_per_million'):
   if type(m[x]) not in (int,float) or not math.isfinite(m[x]) or m[x]<0:raise ValueError('INVALID_PRICE')
  if not isinstance(m.get('returned_aliases'),list) or not m['returned_aliases'] or any(not isinstance(v,str) or not v for v in m['returned_aliases']):raise ValueError('ALIAS_BINDING_REQUIRED')
 return int(Decimal(str(cap))*1000000)
class Combined:
 def __init__(self,g,cap):self.g=g;self.cap=cap
 def __getattr__(self,k):return getattr(self.g,k)
 def reserve(self,r,m,c,v):
  u=self.g.snapshot()['global_usage_and_reservations']
  if u['micro_cny']+v['micro_cny']+8*(u['micro_usd']+v['micro_usd'])>self.cap:self.g.halt('COMBINED_BUDGET');raise RuntimeError('COMBINED_BUDGET')
  self.g.reserve(r,m,c,v)
 def settle(self,r,v):
  self.g.settle(r,v);u=self.g.snapshot()['global_usage_and_reservations']
  if u['micro_cny']+8*u['micro_usd']>self.cap:self.g.halt('COMBINED_BUDGET')
def run(authpath):
 a=json.loads(Path(authpath).read_text());cap=authorization(a)
 for manifest,root in [(P/'FREEZE.json',P),(BASE/'FREEZE.json',BASE)]:
  for f,h in json.loads(manifest.read_text()).items():
   if sha(root/f)!=h:raise RuntimeError('FROZEN_FILE_CHANGED')
 schedule=json.loads((BASE/'SCHEDULE_60.json').read_text())['schedule']
 assert len(schedule)==60 and len({(s['node'],s['repeat'],s['model_key']) for s in schedule})==60
 for line in Path('/root/.env.modelpool').read_text().splitlines():
  for t in shlex.split(line,comments=True):
   if '=' in t:
    k,v=t.split('=',1)
    if k in KEYS:os.environ[KEYS[k]]=v
 if not all(os.environ.get(v) for v in KEYS.values()):raise RuntimeError('LOCAL_CREDENTIAL_MISSING')
 def limits(n):return dict(requests=n,input_tokens=n*65536,output_tokens=n*3072,total_tokens=n*68608,micro_cny=cap,micro_usd=cap//8)
 cells={f'cell{i:02d}':limits(1) for i in range(60)}
 config={'batch_wall_s':18000,'models':[dict(m,request_model=m['model_id']) for m in a['models'].values()]}
 gc={'batch_id':P.name,'global':limits(60),'models':{m['model_id']:limits(15) for m in a['models'].values()},'cells':cells}
 # Validate all frozen bodies before first dispatch, no re-design or new fixture generation.
 bodies=[]
 for s in schedule:
  body=json.loads((BASE/'requests'/f"{s['node']}__{s['model_key']}.json").read_text())
  if body['model']!=a['models'][s['model_key']]['model_id']:raise ValueError('MODEL_MISMATCH')
  if len(json.dumps(body,ensure_ascii=False).encode())>131072:raise ValueError('PAYLOAD_LIMIT')
  bodies.append(body)
 (P/'RUN_ONCE.lock').open('x').close();out=P/'run';out.mkdir(exist_ok=False)
 write(out/'AUTHORIZATION_USED.json',a);g=Combined(Guard(out/'ledger.sqlite',gc),cap);tr=Transport(config,g,out/'requests',enabled=True)
 records=[];status='RUNNING';start=time.monotonic()
 try:
  for i,(s,body) in enumerate(zip(schedule,bodies)):
   model=a['models'][s['model_key']];cell=f'cell{i:02d}'
   r=tr.call(cell,s['node'],model['model_id'],body,180)
   folder=out/'requests'/(cell+'__'+s['node']);acct=json.loads((folder/'ACCOUNTING.json').read_text());raw=json.loads((folder/'RESPONSE.bin').read_bytes())
   reported=acct.get('reported_model')
   # Preserve response and usage before halting unexpected routing/version identity.
   rec={'index':i,**s,'requested_model':model['model_id'],'reported_model':reported,'wall_s':acct['wall_s'],'usage':acct['usage'],'public_or_confirmed_price_estimate':acct['public_price_estimate'],'actual_bill':None,'Q':None,'E_semantic':None,'K':'PENDING_FROZEN_CONTRACT_REVIEW','parse_status':'JSON_OBJECT' if isinstance(r['output'],dict) else 'MODEL_OUTPUT_FAILED','finish_reason':raw['choices'][0].get('finish_reason'),'semantic_review_required':True}
   write(folder/'MEASUREMENT.json',rec);records.append(rec)
   print(json.dumps({'index':i,'model':model['model_id'],'node':s['node'],'parse':rec['parse_status'],'wall_s':rec['wall_s']}),flush=True)
   if reported not in model['returned_aliases']:raise RuntimeError('UNEXPECTED_REPORTED_MODEL')
  status='COMPLETED_60_AWAITING_SILVER_REVIEW'
 except BaseException as e:
  status='INCOMPLETE_STOP';g.halt(type(e).__name__);write(out/'STOP.json',{'type':type(e).__name__,'no_retry':True})
 finally:
  write(out/'RESULTS.json',{'status':status,'measurements':records,'attempted_ledger':g.snapshot(),'wall_s':time.monotonic()-start,'stage2_started':False,'full_Q':None,'actual_bill':None})
  write(out/'CLOSED.json',{'status':status,'remaining_authorization_reusable':False,'stage2_started':False})
if __name__=='__main__':
 if len(sys.argv)!=2:raise SystemExit('Usage: run_measurements.py AUTHORIZATION.json')
 run(sys.argv[1])
