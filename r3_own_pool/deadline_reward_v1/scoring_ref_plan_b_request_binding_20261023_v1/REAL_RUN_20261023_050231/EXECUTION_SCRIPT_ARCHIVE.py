"""One authorized Plan B batch. No retries, no resume, no policy experiment."""
from pathlib import Path
import json,hashlib,os,re,time,multiprocessing as mp,datetime
from decimal import Decimal as D
import requests
B=Path('/root/r3_own_pool/deadline_reward_v1/scoring_ref_plan_b_request_binding_20261023_v1')
F=Path('/root/r3_own_pool/deadline_reward_v1/scoring_ref_plan_b_freeze_20261023_v1')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
bodybytes=lambda obj:json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode()
config=json.loads((B/'CONFIG_AND_BUDGET.json').read_text());queue=json.loads((B/'REQUESTS_NOT_AUTHORIZED.json').read_text());freeze=json.loads((F/'SCORING_REF_FREEZE.json').read_text())
for n,h in json.loads((B/'MANIFEST.json').read_text())['files'].items():assert sha(B/n)==h, n
for n,h in config['source_sha256'].items():assert sha(n)==h,n
for n,h in freeze['source_file_sha256'].items():assert sha(n)==h,n
for n,h in freeze['algorithm_sha256'].items():assert sha(n)==h,n
assert len(queue)==20 and all(sum(r['family']==k for r in queue)==10 for k in ['deepseek','qwen'])
allowed={'deepseek':('deepseek-flash','https://api.deepseek.com/chat/completions'),'qwen':('qwen-plus','https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions')}
for r in queue:
 assert (r['body']['model'],r['endpoint'])==allowed[r['family']]
 assert hashlib.sha256(bodybytes(r['body'])).hexdigest()==r['body_sha256']
 assert r['body']['max_tokens']==8192 and r['body']['stream'] is False
 if r['family']=='deepseek':assert r['body']['thinking']=={'type':'disabled'}
 else:assert r['body']['enable_thinking'] is False

def get_key(name):
 value=os.environ.get(name)
 if value:return value
 for f in [Path('/root/.env.modelpool'),Path('/root/.env')]:
  if not f.exists():continue
  for line in f.read_text().splitlines():
   m=re.fullmatch(r'\s*(?:export\s+)?'+re.escape(name)+r'\s*=\s*(.*?)\s*',line)
   if m:
    val=m[1]
    if len(val)>=2 and val[0]==val[-1] and val[0] in "\"'":val=val[1:-1]
    if val:return val
 raise RuntimeError('REQUIRED_CREDENTIAL_UNAVAILABLE_'+name)
keys={'deepseek':get_key('DEEPSEEK_API_KEY'),'qwen':get_key('DASHSCOPE_API_KEY')}
# Credential values remain in process memory, used only as authentication headers.
fd=os.open(B/'EXECUTION_CLAIM.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
run=B/('REAL_RUN_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S'));run.mkdir(mode=0o700)
os.write(fd,json.dumps({'run':str(run),'authorization':'接受上述探索性费用信封及非现金硬上限风险，按本批固定20请求执行','requests_max':20,'native_estimate_stops':{'CNY':'1','USD':'0.40'},'no_retry':True},ensure_ascii=False).encode());os.fsync(fd);os.close(fd)
def dump(name,obj):
 p=run/name;tmp=run/(name+'.tmp')
 with tmp.open('w') as out:json.dump(obj,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
 os.replace(tmp,p)
def event(kind,**kw):
 with (run/'EVENTS.jsonl').open('a') as f:
  f.write(json.dumps({'kind':kind,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),**kw},ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
def worker(conn,endpoint,raw,key):
 try:
  sess=requests.Session();sess.trust_env=False
  sess.mount('https://',requests.adapters.HTTPAdapter(max_retries=0))
  r=sess.post(endpoint,data=raw,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},timeout=(15,165),allow_redirects=False)
  content=r.content
  if key.encode() in content:content=content.replace(key.encode(),b'[REDACTED_AUTH_REFLECTION]')
  conn.send({'http_status':r.status_code,'body':content,'headers':{k:v for k,v in r.headers.items() if k.lower() in ['date','content-type','x-request-id','request-id']}})
 except Exception as ex:conn.send({'error_type':type(ex).__name__})
 finally:conn.close()
prices={'deepseek':('USD',D('.3'),D('1.2')),'qwen':('CNY',D('.8'),D('2'))};limits={'CNY':D('1'),'USD':D('.40')};spent={k:D(0) for k in limits}
records=[];started=time.monotonic();tokens={'prompt':0,'completion':0};halt=None
accepted={'deepseek':{'deepseek-flash','deepseek-v4.1-flash','deepseek-v4.1-flash-1017'},'qwen':{'qwen-plus','qwen-plus-2025-12-01'}}
dump('AUTHORIZATION.json',{'user_scope':'20 fixed requests; DeepSeek/Qwen each10; output<=8192 per request; no retry/append','budget_risk_acceptance':'Exploratory estimate thresholds are not cash hard limits; input upper uncertified accepted explicitly','native_estimate_stops':{k:str(v) for k,v in limits.items()},'source_scope':str(F/'SCOPE_DECISION_16.json'),'input_reservation_per_call':65536,'output_limit_per_call':8192,'input_total_monitor':1310720,'output_total_limit':163840,'request_wall_s':180,'batch_wall_s':5400,'actual_bill':None,'credentials':'memory-only authentication; no key values persisted','configuration_sha256':sha(B/'CONFIG_AND_BUDGET.json'),'request_matrix_sha256':sha(B/'REQUESTS_NOT_AUTHORIZED.json'),'script_sha256':sha(Path(__file__))})
print(json.dumps({'run':str(run),'state':'STARTED','requests_limit':20}),flush=True)
try:
 for index,r in enumerate(queue):
  rid=r['request_id'];cur,ip,op=prices[r['family']];reservation=(D(65536)*ip+D(8192)*op)/D(1000000)
  if time.monotonic()-started>=5400:halt='BATCH_WALL_LIMIT';break
  if spent[cur]+reservation>limits[cur]:halt='PRE_SEND_FEE_RESERVATION';break
  if tokens['prompt']+65536>1310720 or tokens['completion']+8192>163840:halt='PRE_SEND_TOKEN_RESERVATION';break
  for p,h in config['source_sha256'].items():
   if sha(p)!=h:raise RuntimeError('SOURCE_IDENTITY_DRIFT')
  raw=bodybytes(r['body']);assert hashlib.sha256(raw).hexdigest()==r['body_sha256']
  dump(rid+'_REQUEST.json',r['body']);begin=time.monotonic()
  record={'request_id':rid,'task_id':r['task_id'],'family':r['family'],'model_requested':r['body']['model'],'endpoint':r['endpoint'],'body_sha256':r['body_sha256'],'messages_sha256':r['messages_sha256'],'input_reservation':65536,'output_limit':8192,'currency':cur,'reserved_estimate':str(reservation),'actual_bill':None,'start_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'state':'DISPATCHED'}
  records.append(record);dump('REQUEST_LEDGER.json',records);event('DISPATCH',request_id=rid,index=index+1)
  context=mp.get_context('fork');parent,child=context.Pipe(False);proc=context.Process(target=worker,args=(child,r['endpoint'],raw,keys[r['family']]));proc.start();child.close();result=None
  while time.monotonic()-begin<180 and time.monotonic()-started<5400:
   if parent.poll(min(1,max(.01,180-(time.monotonic()-begin)))):
    result=parent.recv();break
   if not proc.is_alive():break
  if result is None:
   if proc.is_alive():proc.terminate()
   proc.join(timeout=3);record.update(state='REMOTE_COMPLETION_OR_USAGE_UNKNOWN',client_wall_s=time.monotonic()-begin);halt='UNKNOWN_REMOTE_COMPLETION';dump(rid+'_RESULT.json',record);break
  proc.join(timeout=3)
  if proc.is_alive():proc.terminate();proc.join(timeout=3)
  record['client_wall_s']=time.monotonic()-begin
  if 'error_type' in result:record.update(state='TRANSPORT_FAILED_USAGE_UNKNOWN',error_type=result['error_type']);halt='UNKNOWN_USAGE_AFTER_TRANSPORT_FAILURE';dump(rid+'_RESULT.json',record);break
  (run/(rid+'_HTTP_RESPONSE.bin')).write_bytes(result['body']);record.update(http_status=result['http_status'],response_headers=result['headers'])
  try:response=json.loads(result['body'])
  except ValueError:record['state']='HTTP_NOT_JSON_USAGE_UNKNOWN';halt='UNKNOWN_USAGE';dump(rid+'_RESULT.json',record);break
  if result['http_status']!=200:record['state']='HTTP_FAILURE_USAGE_UNKNOWN';halt='HTTP_FAILURE_NO_RETRY';dump(rid+'_RESULT.json',record);break
  usage=response.get('usage',{});identity=response.get('model');record.update(usage=usage,model_returned=identity,response_id=response.get('id'),system_fingerprint=response.get('system_fingerprint'))
  fields=[usage.get(k) for k in ['prompt_tokens','completion_tokens','total_tokens']]
  if not all(type(x) is int and x>=0 for x in fields) or fields[0]+fields[1]!=fields[2]:record['state']='USAGE_UNKNOWN';halt='UNKNOWN_USAGE';dump(rid+'_RESULT.json',record);break
  charge=(D(fields[0])*ip+D(fields[1])*op)/D(1000000);spent[cur]+=charge;tokens['prompt']+=fields[0];tokens['completion']+=fields[1];record['cold_miss_peak_estimate']=str(charge)
  choices=response.get('choices',[])
  if not choices:record['state']='NO_RESPONSE_CHOICE';halt='RESPONSE_CONTRACT_FAILED';dump(rid+'_RESULT.json',record);break
  text=choices[0].get('message',{}).get('content');record['finish_reason']=choices[0].get('finish_reason')
  if not isinstance(text,str):text='';record['content_missing']=True
  (run/(rid+'_MODEL_OUTPUT.txt')).write_text(text)
  native=False;parse_mode='NONE';parsed=None
  try:parsed=json.loads(text);native=True;parse_mode='NATIVE_JSON'
  except ValueError:
   match=re.fullmatch(r'\s*```(?:json)?\s*([\s\S]*?)\s*```\s*',text)
   if match:
    try:parsed=json.loads(match[1]);parse_mode='FENCE_CONTAINER_ONLY_NO_CONTENT_REPAIR'
    except ValueError:pass
  shape=isinstance(parsed,dict) and parsed.get('task_id')==r['task_id'] and all(isinstance(parsed.get(k),list) for k in ['key_facts','conflict_reviews','unverifiable_claims','necessary_answer_points','scope_limitations'])
  if parsed is not None:dump(rid+'_PARSED.json',parsed)
  record.update(state='MODEL_RESPONSE_SAVED',native_json=native,parse_mode=parse_mode,review_container_pass=shape,output_chars=len(text))
  if identity not in accepted[r['family']]:halt='MODEL_IDENTITY_DRIFT'
  elif fields[0]>65536 or fields[1]>8192:halt='TOKEN_MONITOR_EXCEEDED'
  elif spent[cur]>limits[cur]:halt='POST_SETTLEMENT_ESTIMATE_EXCEEDED'
  dump(rid+'_RESULT.json',record);dump('REQUEST_LEDGER.json',records);event('SETTLED',request_id=rid,native_json=native,review_container_pass=shape)
  print(json.dumps({'request':rid,'index':index+1,'wall_s':round(record['client_wall_s'],3),'native_json':native,'review_container_pass':shape,'estimated_native':{k:str(v) for k,v in spent.items()}}),flush=True)
  if halt:break
except Exception as ex:
 halt='LOCAL_EXCEPTION_'+type(ex).__name__;event('STOP',reason=halt)
finally:
 dump('REQUEST_LEDGER.json',records)
 intact=all(sha(p)==h for p,h in config['source_sha256'].items()) and all(sha(p)==h for p,h in freeze['algorithm_sha256'].items())
 summary={'status':'COMPLETED' if len(records)==20 and not halt else 'STOPPED_INCOMPLETE','stop_reason':halt,'requests_dispatched':len(records),'saved_responses':sum(r.get('state')=='MODEL_RESPONSE_SAVED' for r in records),'native_json_pass':sum(r.get('native_json',False) for r in records),'review_container_pass':sum(r.get('review_container_pass',False) for r in records),'tokens':tokens,'estimated_native':{k:str(v) for k,v in spent.items()},'actual_cash':None,'bill_status':'PENDING_BILL_VERIFICATION','wall_s':time.monotonic()-started,'source_and_algorithm_identity_unchanged':intact,'automatic_retries':0,'additional_requests_allowed':False,'candidate_gold_status':'NOT_YET_SOURCE_CHECKED_MACHINE_ASSISTED_ONLY'}
 dump('SUMMARY.json',summary);print(json.dumps({'final_summary':summary,'run':str(run)}),flush=True)
 dump('RESULT_MANIFEST.json',{'files':{p.name:sha(p) for p in run.iterdir() if p.is_file() and p.name!='RESULT_MANIFEST.json'},'source_sha256':config['source_sha256'],'algorithm_sha256':freeze['algorithm_sha256']})
