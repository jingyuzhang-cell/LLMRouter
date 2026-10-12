"""Frozen diagnostic, offline by default; generation+review, NEVER node execution."""
import argparse,fcntl,hashlib,json,signal,time
from pathlib import Path
from urllib import request,error
from .ab_diagnostic import DiagnosticArm,request_packet
from .http_diagnostic import decode_response
from .generation import InitialDAGGenerator
from .protocol import Limits
from .service_schema import full_validate,classify_http
from .heterogeneous_models import SerialModelService,audit_pool
from .resource_envelope import request_deadline
from .run_cleanup import finish
from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget,StopRun

def verify(packet):
 p=json.loads((packet/'PROTOCOL.json').read_text())
 for f,h in p['source_sha256'].items():
  if hashlib.sha256(Path(f).read_bytes()).hexdigest()!=h:raise ValueError('Source hash changed: '+f)
 for f,h in p['file_sha256'].items():
  if hashlib.sha256((packet/f).read_bytes()).hexdigest()!=h:raise ValueError('Frozen file changed: '+f)
 if p.get('required_files'):
  from .freeze_integrity import check
  from static_dag_v0 import run as engine
  check(packet,p,engine.MODELS)
  cell_specs(packet,p)
 return p

STATES={'NOT_STARTED','GENERATION_FAILED','STRUCTURE_REJECTED','CONTRACT_REJECTED',
 'SOURCE_REJECTED','REVIEW_REJECTED','ACCEPTED','RESOURCE_STOP','INFRASTRUCTURE_ERROR'}

def cell_specs(packet,p):
 if 'cells' not in p:
  return [dict(run_id=a,arm=a,mode=m,role=r,task=json.loads((packet/'PUBLIC_INPUT.json').read_text()),required=json.loads((packet/'REQUIRED_SOURCE_DATA.json').read_text()),budget=p['arms'][a]) for a,m,r in [('A','semantic','flat'),('B','goal_ir','roles')]]
 by_id={f"T{x['task']}_{x['arm']}":x for x in p['cells']}
 if set(p['order'])!=set(by_id) or len(p['order'])!=len(by_id):raise ValueError('Invalid cell order')
 if sum(x['requests_upper'] for x in by_id.values())!=p['requests'] or sum(x['tokens_upper'] for x in by_id.values())!=p['total_tokens']:raise ValueError('Global/cell envelope mismatch')
 result=[]
 for rid in p['order']:
  x=by_id[rid];arm=x['arm'];prompt=json.loads((packet/(rid+'_PROMPT.json')).read_text())
  from .protocol import canonical
  bp=dict(total_tokens_upper=x['tokens_upper'],generation_input_tokens=x['input_tokens'],generation_prompt_sha256=hashlib.sha256(canonical(prompt).encode()).hexdigest())
  result.append(dict(run_id=rid,arm=arm,mode='semantic' if arm=='A' else 'goal_ir',role='flat' if arm=='A' else 'roles',task=json.loads((packet/f"TASK_{x['task']}.json").read_text()),required=json.loads((packet/f"REQUIRED_SOURCES_{x['task']}.json").read_text()),budget=bp,wire_protocol=p.get('wire_protocol','legacy')))
 return result

def classify_result(result):
 if result.status=='GENERATED':return 'ACCEPTED'
 rejected=[e for e in result.events if e.get('status')=='REJECTED']
 if not rejected:return 'GENERATION_FAILED'
 text=json.dumps(rejected).upper()
 if 'SEMANTIC_REVIEW' in text or 'COVERAGE_REVIEW' in text:return 'REVIEW_REJECTED'
 if 'REQUIRED_SOURCE' in text:return 'SOURCE_REJECTED'
 if any(k in text for k in ('TYPE_MISMATCH','OPERATION_INPUT','CONTRACT','ROLE','PORT')):return 'CONTRACT_REJECTED'
 return 'STRUCTURE_REJECTED'

def run_cell(ex,spec,row,folder):
 row.update(state='NOT_STARTED',run_id=spec['run_id'],uid=spec['task']['task_id'],review='NOT_RUN',admitted_nonfallback=False)
 try:
  result=InitialDAGGenerator(ex,'medium',max_repairs=0,fallbacks={},limits=Limits(max_nodes=5,max_depth=5,max_llm_calls=5),strict_planning_schema=True,planning_mode=spec['mode'],goal_input_mode=spec['role'],wire_protocol=spec.get('wire_protocol','legacy')).generate(**spec['task'],required_source_data=spec['required'])
  row.update(state=classify_result(result),generation_status=result.status,events=result.events,semantic_status=result.semantic_status,review='CALLED' if ex.counts['semantic_review'] else 'NOT_RUN_NO_ADMISSIBLE_CANDIDATE',admitted_nonfallback=result.status=='GENERATED',accounting=result.accounting)
  if result.graph is not None:(folder/'GRAPH.json').write_text(result.graph.to_json())
 except StopRun as exc:row.update(state='INFRASTRUCTURE_ERROR' if 'Infrastructure' in str(exc) else 'RESOURCE_STOP',error=repr(exc))
 except (error.HTTPError,error.URLError,TimeoutError,OSError) as exc:row.update(state='INFRASTRUCTURE_ERROR',error=repr(exc))
 except (ValueError,TypeError,KeyError) as exc:row.update(state='GENERATION_FAILED',error=repr(exc))
 finally:
  row['layers']=dict(structure='PASS' if any(e.get('phase')=='structural_validation' and e.get('status')=='PASS' for e in row.get('events',[])) else 'NOT_ESTABLISHED',source=[e.get('status') for e in row.get('events',[]) if e.get('phase')=='source_coverage'],semantic_review=row.get('semantic_status','NOT_TESTED'),nonfallback=row.get('admitted_nonfallback',False),raw_validation_events=[e for e in row.get('events',[]) if e.get('phase')=='validation'])
  row['ledger_accounting']=dict(attempts=ex.budget.attempts,known_tokens=ex.budget.actual_tokens,charged_tokens=ex.budget.charged,pending=dict(ex.budget.pending))
 return row

def request_wall_gate(elapsed,p):
 if p['wall_seconds']-elapsed < p['request_timeout_s']+p['cleanup_reserve_s']:
  raise StopRun('Global wall insufficient for request and cleanup')

def global_gate(row):
 if row['state']=='INFRASTRUCTURE_ERROR':raise StopRun('Global infrastructure failure: '+row.get('error',''))
 if row['state']=='RESOURCE_STOP' and any(k in row.get('error','') for k in ('Global wall','Request wall timeout')):
  raise StopRun('Global wall stop')

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--packet',required=True);ap.add_argument('--execute',action='store_true');a=ap.parse_args();packet=Path(a.packet).resolve();p=verify(packet)
 if not a.execute:print('PREPARED_NOT_AUTHORIZED: hashes PASS, no HTTP/model');return
 from static_dag_v0 import run as engine
 out=packet/'execution';out.mkdir(exist_ok=False);start=time.monotonic();service=None;rows=[];budgets=[];abort=None;cleanup=None;start_unix=time.time()
 def deadline():
  if time.monotonic()-start>=p['wall_seconds']-p['cleanup_reserve_s']:raise StopRun('Global wall; cleanup reserved')
 def snapshot():
  (out/'RESULTS.json').write_text(json.dumps(dict(rows=rows,abort=abort,cleanup=cleanup,start_unix_s=start_unix,start_monotonic_s=start,requests=sum(b.attempts for b in budgets),known_tokens=sum(b.actual_tokens for b in budgets),charged_tokens=sum(b.charged for b in budgets),pending=[dict(b.pending) for b in budgets],wall_s=time.monotonic()-start,service_stopped=service is None or service.active is None,node_execution=False,scoring=False),indent=2)+'\n')
 old=signal.getsignal(signal.SIGALRM)
 def stop(*a):raise StopRun('Global wall deadline')
 with (engine.ROOT/'collect/logs/local_gpu.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);signal.signal(signal.SIGALRM,stop);signal.setitimer(signal.ITIMER_REAL,p['wall_seconds']-p['cleanup_reserve_s'])
  try:
   from transformers import AutoTokenizer
   with request_deadline(p['cpu_preflight_cap_s']):
    pool=audit_pool(engine.MODELS,engine.ROOT/'router_v2/label_repair_experiment/raw',verify_weights=True)
    tok=AutoTokenizer.from_pretrained(engine.MODELS['medium']['path'],local_files_only=True)
   (out/'MODEL_POOL.json').write_text(json.dumps(pool,indent=2)+'\n')
   frozen_pool=json.loads((packet/'MODEL_POOL_OFFLINE.json').read_text())
   if pool['medium']['weights_identity_sha256']!=frozen_pool['medium']['weights_identity_sha256']:raise StopRun('Frozen model weights identity changed')
   needed=p['model_load_cap_s']+p['requests']*p['request_timeout_s']+p['cleanup_reserve_s']
   if p['wall_seconds']-(time.monotonic()-start)<needed:raise StopRun('Remaining load/request/cleanup envelope insufficient')
   service=SerialModelService(engine.MODELS,pool,out,deadline,max_activations=1,load_cap_s=p['model_load_cap_s'],request_id_headers=p.get('request_tracing',False));service.activate('medium')
   for spec in cell_specs(packet,p):
    arm=spec['arm'];mode=spec['mode'];role=spec['role']
    deadline();folder=out/spec['run_id'];folder.mkdir();bp=spec['budget'];b=Budget(folder,dict(new_request_attempts=2,new_total_tokens=bp['total_tokens_upper'],request_token_reservation=0,max_output_tokens=768,wall_seconds=p['wall_seconds']-p['cleanup_reserve_s'],logical_calls_per_task_config_state=2));b.start=start;budgets.append(b)
    calls=[];row=dict(arm=arm,calls=calls,review='NOT_RUN',admitted_nonfallback=False);rows.append(row)
    def dispatch(model,text):
     deadline();request_wall_gate(time.monotonic()-start,p);phase,payload,audit=request_packet(engine.MODELS['medium']['served'],text);item=dict(phase=phase,http_status=None,schema=audit);calls.append(item)
     (folder/(phase+'_PROMPT.json')).write_text(text+'\n');(folder/(phase+'_HTTP_INPUT.json')).write_text(json.dumps(payload,indent=2)+'\n')
     from .request_trace import new_id,mark,exchange
     rid=new_id();trace=folder/'REQUEST_TRACE.jsonl';item['request_id']=rid
     if p.get('request_tracing'):mark(trace,rid,'constructed',phase=phase)
     req=request.Request('http://127.0.0.1:8128/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json',**({'X-Request-Id':rid} if p.get('request_tracing') else {})})
     try:
      if p.get('request_tracing'):
       item['http_status'],raw=exchange(service.opener,req,p['request_timeout_s'],trace,rid)
      else:
       with request_deadline(p['request_timeout_s']):
        with service.opener.open(req,timeout=p['request_timeout_s']) as r:item['http_status']=r.status;raw=r.read().decode()
     except error.HTTPError as exc:
      raw=exc.read().decode(errors='replace');item.update(http_status=exc.code,error=classify_http(exc.code,raw));(folder/(phase+'_HTTP_ERROR.txt')).write_text(raw);raise
     (folder/(phase+'_HTTP_RESPONSE.json')).write_text(raw);data=None
     try:
      data=json.loads(raw);service.check_provider('medium',data.get('model'));rec=decode_response(data,engine.MODELS['medium']['served'])
     except (ValueError,TypeError,KeyError) as exc:raise StopRun('Infrastructure response invalid; reservation retained: '+str(exc))
     item.update(finish_reason=rec['finish_reason'],usage=rec['usage'],json_complete=False,full_schema=False)
     try:
      candidate=json.loads(rec['answer']);item['json_complete']=True;full_validate(candidate,audit['full_schema']);item['full_schema']=True
     except (ValueError,TypeError) as exc:item['validation_error']=str(exc)
     if rec['finish_reason']=='length':raise ValueError('Diagnostic response truncated; no review admission')
     if item.get('validation_error'):raise ValueError('Strict diagnostic response validation failed: '+item['validation_error'])
     return rec
    inner=MeteredExecutor(folder,b,dispatch,service.activate,{'medium':engine.MODELS['medium']['served']});ex=DiagnosticArm(inner,tok,engine.MODELS['medium']['served'],bp['generation_input_tokens'],bp['generation_prompt_sha256'])
    run_cell(ex,spec,row,folder)
    snapshot()
    global_gate(row)
  except BaseException as exc:abort=repr(exc);snapshot()
  finally:
   # Cleanup gets its own reserved interval; old alarm must not interrupt it.
   signal.setitimer(signal.ITIMER_REAL,0)
   try:
    cleanup=finish(service,out,start,[c.get('request_id') for row in rows for c in row.get('calls',[])])
   finally:
    signal.signal(signal.SIGALRM,old)
    snapshot()
 print((out/'RESULTS.json').read_text())
 if abort is not None or (cleanup and cleanup['errors']):raise SystemExit(2)
if __name__=='__main__':main()
