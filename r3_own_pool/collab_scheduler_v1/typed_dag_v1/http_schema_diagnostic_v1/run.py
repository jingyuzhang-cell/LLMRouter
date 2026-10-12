"""Explicitly authorized two-call HTTP diagnosis; NEVER executes DAG nodes."""
import json,time,signal,hashlib,fcntl,tempfile,subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib import request,error
from collab_scheduler_v1.typed_dag_v1.ab_interleaved import check
from collab_scheduler_v1.typed_dag_v1.generation import InitialDAGGenerator
from collab_scheduler_v1.typed_dag_v1.protocol import Limits,canonical,validate
from collab_scheduler_v1.typed_dag_v1.service_schema import full_validate,to_service_schema,backend_precheck,classify_http
from collab_scheduler_v1.typed_dag_v1.goal_ir import compile_goal_ir
from collab_scheduler_v1.typed_dag_v1.producer_plan import compile_producer_plan,verify_producer_bindings
from collab_scheduler_v1.typed_dag_v1.semantic_ids import assemble_semantic
from collab_scheduler_v1.typed_dag_v1.heterogeneous_models import audit_pool,SerialModelService
from collab_scheduler_v1.typed_dag_v1.resource_envelope import request_deadline
from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget,StopRun,append
from static_dag_v0 import run as engine

ROOT=Path(__file__).resolve().parent;OUT=ROOT/'run01';PACKET=ROOT.parent/'ab_preparation_v2';OUT.mkdir(exist_ok=False)
started=time.monotonic();service=None;rows=[];budgets=[];abort=None
TASK=dict(task_id='stage3-http-only-label-diagnostic-20261011',domain='financial_arithmetic',context=dict(question='How many labels remain after setting aside the listed labels?',ctx_table='The diagnostic workshop has 6 packs containing 7 labels in each pack.',ctx_text='The workshop sets aside 5 labels; there are no other additions or removals.'),required_outputs={'answer':'Remaining label count after the stated reservation'})
(OUT/'PUBLIC_INPUT.json').write_text(json.dumps(TASK,indent=2)+'\n')
def deadline():
 if time.monotonic()-started>=1170:raise StopRun('1200s global wall: cleanup reserved')
def snapshot():
 (OUT/'RESULTS.json').write_text(json.dumps(dict(rows=rows,abort=abort,wall_s=time.monotonic()-started,attempts=sum(b.attempts for b in budgets),known_tokens=sum(b.actual_tokens for b in budgets),charged_tokens=sum(b.charged for b in budgets),pending_by_arm={arm:dict(b.pending) for arm,b in zip(('A','B'),budgets)},service_stopped=service is None or service.active is None,node_execution=False,scoring=False),indent=2)+'\n')
with (engine.ROOT/'collect/logs/local_gpu.lock').open('a+') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 oldhandler=signal.getsignal(signal.SIGALRM)
 def stop(s,f):raise StopRun('Global hard wall cleanup reserve')
 signal.signal(signal.SIGALRM,stop);signal.setitimer(signal.ITIMER_REAL,1170)
 try:
  (OUT/'PRECHECK.json').write_text(json.dumps(check(PACKET),indent=2)+'\n')
  pool=audit_pool(engine.MODELS,engine.ROOT/'router_v2/label_repair_experiment/raw',verify_weights=True)
  (OUT/'MODEL_POOL.json').write_text(json.dumps(pool,indent=2)+'\n')
  from transformers import AutoTokenizer
  tokenizer=AutoTokenizer.from_pretrained(engine.MODELS['medium']['path'],local_files_only=True)
  prompts={}
  for arm,mode in (('A','semantic'),('B','goal_ir')):
   folder=OUT/arm;folder.mkdir();caps=dict(new_request_attempts=1,new_total_tokens=5000,request_token_reservation=5000,max_output_tokens=768,wall_seconds=1200,logical_calls_per_task_config_state=1)
   b=Budget(folder,caps);b.start=started;budgets.append(b)
   with tempfile.TemporaryDirectory() as temp:
    class Capture:
     bindings={'medium':'medium'};directory=Path(temp);budget=SimpleNamespace(attempts=0,actual_tokens=0,charged=0,pending={})
     def begin_cell(self,*a):pass
     def call(self,key,model,prompt):self.prompt=prompt;raise StopRun('No HTTP during capture')
    cap=Capture()
    try:InitialDAGGenerator(cap,'medium',limits=Limits(max_nodes=5,max_depth=5,max_llm_calls=5),strict_planning_schema=True,planning_mode=mode).generate(**TASK)
    except StopRun:pass
   body=json.loads(cap.prompt);schema=body['plan_json_schema'];transport,audit=to_service_schema(schema);backend_precheck(transport)
   n=len(tokenizer.apply_chat_template([dict(role='user',content=cap.prompt)],tokenize=True,add_generation_prompt=True));reservation=n+768
   if reservation>5000:raise StopRun('Per-arm 5000 token diagnostic cap')
   (folder/'PROMPT.json').write_text(cap.prompt+'\n');(folder/'SCHEMA.json').write_text(json.dumps(audit,indent=2)+'\n');prompts[arm]=(cap.prompt,schema,transport,reservation)
  if sum(p[3] for p in prompts.values())>10000:raise StopRun('Global Token preflight')
  if time.monotonic()-started>790:raise StopRun('Cannot reserve model loading + 2 requests + cleanup')
  service=SerialModelService(engine.MODELS,pool,OUT,deadline,max_activations=1);service.activate('medium')
  for arm,mode,b in zip(('A','B'),('semantic','goal_ir'),budgets):
   deadline();prompt,full,transport,reservation=prompts[arm];b.caps['request_token_reservation']=reservation
   if time.monotonic()-started>1110:raise StopRun('Insufficient request and cleanup wall')
   row=dict(arm=arm,mode=mode,http_status=None,finish_reason=None,json_complete=False,full_schema_pass=False,legal_dag=False,errors=[],token_usage='UNKNOWN',request_schema_sha256=hashlib.sha256(canonical(transport).encode()).hexdigest(),full_schema_sha256=hashlib.sha256(canonical(full).encode()).hexdigest());rows.append(row)
   def dispatch(model,text):
    payload=dict(model=engine.MODELS['medium']['served'],messages=[dict(role='user',content=text)],temperature=0,top_p=1,max_tokens=768,stream=False,response_format=dict(type='json_schema',json_schema=dict(name='diagnostic_plan',strict=True,schema=transport)))
    (OUT/arm/'HTTP_INPUT.json').write_text(json.dumps(payload,indent=2)+'\n')
    req=request.Request('http://127.0.0.1:8128/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    try:
     with request_deadline(30):
      with service.opener.open(req,timeout=30) as response:row['http_status']=response.status;raw=response.read().decode();data=json.loads(raw)
    except error.HTTPError as exc:
     row['http_status']=exc.code;raw=exc.read().decode(errors='replace');(OUT/arm/'HTTP_ERROR.txt').write_text(raw);row['errors'].append(dict(code=classify_http(exc.code,raw),body=raw));raise
    (OUT/arm/'HTTP_RESPONSE.json').write_text(raw);row['response_bytes_sha256']=hashlib.sha256(raw.encode()).hexdigest();service.check_provider('medium',data.get('model'))
    choice=data['choices'][0];row['finish_reason']=choice.get('finish_reason');row['token_usage']=data['usage'];row['actual_model']=data['model']
    return dict(status='delivered',answer=choice['message']['content'],usage=data['usage'],finish_reason=choice.get('finish_reason'),provider_model=data['model'])
   ex=MeteredExecutor(OUT/arm,b,dispatch,service.activate,{'medium':engine.MODELS['medium']['served']});ex.begin_cell('http-schema-diagnostic-'+arm,TASK['task_id']);ts=time.monotonic()
   rec=ex.call('typed:generate:v1:generate:0:'+TASK['task_id'],'medium',prompt);text=rec['response']['answer'];(OUT/arm/'RAW_CANDIDATE.txt').write_text(text)
   try:
    candidate=json.loads(text);row['json_complete']=True
    if row['finish_reason']=='length':raise ValueError('GENERATION_TRUNCATED even if JSON parsable')
    full_validate(candidate,full);row['full_schema_pass']=True
    rawplan=candidate
    if mode=='goal_ir':rawplan,ir_evidence=compile_goal_ir(candidate,limits=Limits(max_nodes=5,max_depth=5,max_llm_calls=5))
    plan,evidence=compile_producer_plan(rawplan);g=assemble_semantic(plan,TASK['task_id'],TASK['context'],TASK['required_outputs'],limits=Limits(max_nodes=5,max_depth=5,max_llm_calls=5));verify_producer_bindings(g,evidence);validate(g,TASK['required_outputs'],Limits(max_nodes=5,max_depth=5,max_llm_calls=5))
    (OUT/arm/'GRAPH.json').write_text(g.to_json());row['legal_dag']=True;row['nodes']=len(g.nodes)
   except Exception as exc:row['errors'].append(getattr(exc,'feedback',dict(code='JSON_OR_PLAN_INVALID',message=str(exc))))
   row['request_wall_s']=time.monotonic()-ts;row['charged_tokens']=b.charged;snapshot()
 except BaseException as exc:abort=repr(exc);append(OUT/'STOP.jsonl',dict(reason=abort));snapshot()
 finally:
  if service:service.close()
  signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,oldhandler);snapshot()
print((OUT/'RESULTS.json').read_text())
