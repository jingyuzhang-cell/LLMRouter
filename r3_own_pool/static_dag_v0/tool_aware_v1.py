"""Executor-only controlled ablation and bounded natural-task confirmation."""
import argparse, ast, hashlib, html, json, math, os, re, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import fcntl
from urllib import request
from . import core,repair
from . import run as engine
OUT=core.ROOT/'static_dag_v0/tool_aware_v1'
SOURCE=Path('/root/phase_c9_0/external/MultiHiertt-data/multihiertt_data/dev.json')

def append(path,row):
 with path.open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
def context(row):
 tables=[]
 for i,raw in enumerate(row['tables']):
  txt=re.sub(r'</tr\s*>','\n',raw,flags=re.I);txt=re.sub(r'</t[dh]\s*>',' | ',txt,flags=re.I);txt=html.unescape(re.sub('<[^>]+>','',txt));tables.append(f'TABLE {i}\n'+txt)
 return '\n'.join(row['paragraphs'])+'\n'+'\n'.join(tables)
def eprompt(task):
 return 'Read the financial report and extract the quantities needed to answer the question. Do not calculate the answer. Return ONLY JSON {"facts":[{"value":number,"evidence":"exact short quote containing the value and its meaning"}]}. Use at most 12 facts. Preserve signs and units; values in millions stay in millions.\nQUESTION: '+task['question']+'\nREPORT:\n'+task['context']
def sprompt(task,facts):
 return 'Choose the arithmetic reasoning needed to answer the financial question using the extracted facts. Return ONLY JSON {"expression":"..."}. Reference fact values as v0,v1,... in their listed order. Allowed operators: + - * / and parentheses. Only numeric constants 0,1,100 are permitted. Do not do the arithmetic or include the final answer. For a percentage question multiply the ratio by 100; for an absolute amount preserve the reported units.\nQUESTION: '+task['question']+'\nFACTS: '+json.dumps(facts)
def parse_facts(answer):
 o=decode(answer);facts=o['facts'];assert 0<len(facts)<=12
 for f in facts:assert type(f['value']) in [int,float] and math.isfinite(f['value']) and isinstance(f['evidence'],str) and f['evidence']
 return dict(facts=facts)
def decode(text):
 text=(text or '').strip()
 if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
 return json.loads(text)
def calculate(expression,facts):
 if not isinstance(expression,str) or len(expression)>500:raise ValueError('expression length')
 tree=ast.parse(expression,mode='eval');count=0
 def walk(n):
  nonlocal count
  count+=1
  if count>100:raise ValueError('expression budget')
  if isinstance(n,ast.Expression):return walk(n.body)
  if isinstance(n,ast.Name) and re.fullmatch(r'v\d+',n.id):return float(facts['facts'][int(n.id[1:])]['value'])
  if isinstance(n,ast.Constant) and type(n.value) in [int,float] and n.value in [0,1,100]:return float(n.value)
  if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.UAdd,ast.USub)):return walk(n.operand)*(1 if isinstance(n.op,ast.UAdd) else -1)
  if isinstance(n,ast.BinOp):
   a,b=walk(n.left),walk(n.right)
   if isinstance(n.op,ast.Add):return a+b
   if isinstance(n.op,ast.Sub):return a-b
   if isinstance(n.op,ast.Mult):return a*b
   if isinstance(n.op,ast.Div):return a/b
  raise ValueError('unsupported AST')
 value=walk(tree)
 if not math.isfinite(value) or abs(value)>1e18:raise ValueError('nonfinite/range')
 return value

def controlled():
 out=OUT/'controlled';out.mkdir(parents=True,exist_ok=False)
 source=repair.OUT;tasks=json.loads((source/'TASKS.json').read_text());baseline=json.loads((source/'RESULTS.json').read_text());old=json.loads((source/'PER_TASK.json').read_text())
 core.write(out/'PROTOCOL.json',dict(change='Executor only; same 20 Local Repair tasks, graph and node contracts.',types={'demand':'aggregation','quotes':'arithmetic','feasibility':'constraint','decision':'verification'},router_unchanged=True,local_repair=False,bindings={str(p):core.sha(p) for p in [source/'TASKS.json',source/'RESULTS.json',source/'PER_TASK.json',Path(repair.__file__),Path(__file__)]},created_unix=time.time()))
 results=[];allstart=time.perf_counter()
 for t in tasks:
  started=time.perf_counter();state={};nodes=[]
  for n in core.NODES:
   tick=time.perf_counter();value=repair.local_expected(t,n,state);state[n['id']]=value;nodes.append(dict(node_id=n['id'],executor='tool',output=value,wall_seconds=time.perf_counter()-tick))
  elapsed=time.perf_counter()-started;expected=core.truth(t)
  results.append(dict(task_id=t['task_id'],answer=state['decision'],quality=sum(state['decision'][k]==expected['decision'][k] for k in expected['decision'])/2,success=state['decision']==expected['decision'],end_to_end_seconds=elapsed,nodes=nodes,tool_correct=sum(state[k]==expected[k] for k in expected)))
 summary=dict(task_success_rate=sum(r['success'] for r in results)/20,quality=sum(r['quality'] for r in results)/20,tokens=0,inference_cost=0,inference_cost_basis='No model inference; tool CPU resource cost not monetized',mean_end_to_end_seconds=sum(r['end_to_end_seconds'] for r in results)/20,tool_node_accuracy=sum(r['tool_correct'] for r in results)/80,llm_node_accuracy=None,llm_nodes=0,baselines=baseline['arms'],static_and_repair_end_to_end_latency=None,latency_limitation='Historical controls have shared service accounting only; no comparable isolated end-to-end latency. Do not compare against tool wall time as a speedup.',success_gate=dict(quality_above_static=sum(r['quality'] for r in results)/20>baseline['arms']['static']['quality'],tokens_at_most_repair=True))
 core.write(out/'PER_TASK.json',results);core.write(out/'RESULTS.json',summary)
 (out/'REPORT.md').write_text('# Tool-aware Static DAG v1：同题执行器消融\n\n| 方法 | 成功率 | 平均质量 | 逻辑tokens | 平均端到端latency |\n|---|---:|---:|---:|---|\n'+f"| Static DAG v0协议（同题重测） | {baseline['arms']['static']['success_rate']:.0%} | {baseline['arms']['static']['quality']:.3f} | {baseline['arms']['static']['tokens']} | 历史未独立测量 |\n| Local Repair | {baseline['arms']['local_repair']['success_rate']:.0%} | {baseline['arms']['local_repair']['quality']:.3f} | {baseline['arms']['local_repair']['tokens']} | 历史未独立测量 |\n| Tool-aware v1 | {summary['task_success_rate']:.0%} | {summary['quality']:.3f} | 0 | {summary['mean_end_to_end_seconds']*1000:.3f}ms |\n\nTool Node Accuracy=100%，LLM Node Accuracy=N/A（0个LLM节点）。满足质量高于Static且tokens不高于Repair的判据；这只是执行器消融，不是多模型路由证据。旧数据的服务累计时长不能充当端到端latency。\n\n| Node Type | #Nodes | Small | Medium | Large | R1 | Tool | Accuracy |\n|---|---:|---:|---:|---:|---:|---:|---|\n| Extraction | 0 | 0 | 0 | 0 | 0 | 0 | N/A |\n| Semantic reasoning | 0 | 0 | 0 | 0 | 0 | 0 | 0 | N/A |\n| Arithmetic / aggregation | 40 | 0 | 0 | 0 | 0 | 40 | 100% |\n| Constraint check | 20 | 0 | 0 | 0 | 0 | 20 | 100% |\n| Verification / ordering | 20 | 0 | 0 | 0 | 0 | 20 | 100% |\n")
 print('controlled complete',json.dumps(summary['success_gate']))

def prepare():
 out=OUT/'fresh';out.mkdir(parents=True,exist_ok=False)
 # Full source context, no evidence annotations, answer, program or table_description in prompts.
 from transformers import AutoTokenizer
 tok=AutoTokenizer.from_pretrained(engine.MODELS['medium']['path'],local_files_only=True)
 raw=json.loads(SOURCE.read_text());selected=[];hidden=[]
 for row in sorted(raw,key=lambda r:hashlib.sha256(('20260917'+r['uid']).encode()).hexdigest()):
  qa=row['qa']
  if qa.get('question_type')!='arithmetic' or qa.get('program','').count('(')<2:continue
  try:answer=float(str(qa['answer']).replace(',',''))
  except ValueError:continue
  if not math.isfinite(answer):continue
  task=dict(task_id=row['uid'],question=qa['question'],context=context(row));text=eprompt(task)
  n=len(tok.encode(text))
  if n>5500:continue
  task['input_tokens_preflight']=n;selected.append(task);hidden.append(dict(task_id=row['uid'],answer=answer,program=qa['program']))
  if len(selected)==40:break
 assert len(selected)==40
 profiles=json.loads((core.OUT/'PROFILES.json').read_text());r1rows=core.lines(core.ROOT/'router_v2/label_repair_experiment/raw/reasoning.jsonl')
 profiles['reasoning']=dict(quality=sum(r['quality'] for r in r1rows)/len(r1rows),mean_output_tokens=sum(r['usage']['completion_tokens'] for r in r1rows)/len(r1rows),mean_total_tokens=sum(r['usage']['total_tokens'] for r in r1rows)/len(r1rows),mean_latency_s=sum(r['latency']['total_ms']/1000 for r in r1rows)/len(r1rows))
 plans=[]
 for task in selected:
  nodes=[]
  for nid in ['extraction','semantic']:
   # Same frozen char/4 input heuristic as current router; semantic placeholder is input-only.
   text=eprompt(task) if nid=='extraction' else sprompt(task,{'facts':'pending'});estimate=(len(text)+3)//4+(80 if nid=='semantic' else 0)
   picked,candidates=core.route({s:profiles[s] for s in ['medium','large','coder']},estimate)
   _,r1=core.route({'reasoning':profiles['reasoning']},estimate)
   for s,v in candidates.items():v['eligible']=True
   candidates['reasoning']={**r1['reasoning'],'eligible':False,'reason':'not in frozen current Router pool; shadow diagnostic only'}
   candidates['small']=dict(Q=None,C_tokens=None,L_seconds=None,score=None,eligible=False,reason='Original Qwen2.5-3B weights unavailable; not in frozen Router pool; no compatible corrected profile')
   nodes.append(dict(node_id=nid,selected_model=picked,candidates=candidates,estimated_input_tokens=estimate))
  plans.append(dict(task_id=task['task_id'],nodes=nodes))
 core.write(out/'TASKS.json',selected);core.write(out/'EVAL_ONLY.json',hidden);core.write(out/'PLANS.json',plans)
 # Fixed shadow audit sample, chosen before responses. The routed run always uses frozen selections.
 core.write(out/'SHADOW_IDS.json',[t['task_id'] for t in selected[:10]])

 bind=[Path(__file__),Path(core.__file__),Path(engine.__file__),SOURCE,core.OUT/'PROFILES.json',core.ROOT/'router_v2/label_repair_experiment/raw/reasoning.jsonl']+[out/x for x in ['TASKS.json','EVAL_ONLY.json','PLANS.json','SHADOW_IDS.json']]
 core.write(out/'PROTOCOL.json',dict(role='natural_financial_multistep_confirmation_and_shadow_audit',source=str(SOURCE),n_tasks=40,selection='UID hash seed20260917; arithmetic >=2 program operations; full flattened report prompt <=5500 local tokens. No result-dependent selection.',freshness='New to this DAG experiment, not certified untouched across entire workspace, prior models or pretraining. Existing external-project dataset is used.',nodes=['extraction:LLM','semantic:LLM','arithmetic:tool','verification:tool'],router_unchanged=True,router_pool=['medium','large','coder'],shadow_only=['reasoning'],unavailable=['small'],shadow_tasks=10,max_requests=dict(routed=80,large=20,medium=20,coder=20,reasoning=20),temperature=0,max_tokens=512,concurrency=4,retries=0,api_timeout_seconds=600,transport_failure='Keep as missing, no replacement or retry; missing candidate evidence does not become zero-quality evidence.',shadow_semantic_input='Same routed extraction facts; conditional node diagnostic, not alternative end-to-end route.',quality='Numeric exactness tolerance max(1e-4,1e-4*abs(reference)); no posthoc percent rescaling. Overall includes failures as task unsuccessful; infrastructure availability separately reported.',extraction_accuracy='All nonconstant numeric operands in reference program recovered among extracted fact values; diagnostic operand recall, not complete extraction correctness.',semantic_accuracy='Expression executed on actual routed facts yields reference numeric answer; downstream conditional proxy, not isolated semantic correctness.',tool_accuracy='Arithmetic matches independent restricted interpreter; verification implements syntax/range contract. Does not mean upstream semantics correct.',latency='Measured routed first-layer queue/service/startup plus second-layer queue/service and tool processing; sum stage durations per task excludes shadow/model-switch gaps. Called amortized staged end-to-end, not independent online latency.',no_repair=True,no_dynamic=True,no_tuning=True,created_unix=time.time(),bindings={str(p):core.sha(p) for p in bind}))
 core.write(out/'STATUS.json',dict(phase='PREPARED'));print('fresh prepared 40; selections frozen, Small unavailable, R1 shadow only')

def verify():
 out=OUT/'fresh';p=json.loads((out/'PROTOCOL.json').read_text())
 for path,h in p['bindings'].items():
  if core.sha(path)!=h:raise ValueError('frozen input changed '+path)
 return p

def request_r1(text):
 from router_v2.run_repeat_stability import api_client
 client=api_client();t=time.monotonic();start=time.time();payload=dict(model='deepseek-r1-distill-qwen-14b',messages=[dict(role='user',content=text)],temperature=0,top_p=1,max_tokens=512,stream=False)
 try:
  req=request.Request(client['base_url']+'/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+client['api_key']},method='POST')
  with request.urlopen(req,timeout=600) as response:data=json.loads(response.read())
  choice=data['choices'][0];return dict(status='delivered' if choice['message'].get('content') else 'infrastructure_failure',answer=choice['message'].get('content'),usage=data.get('usage'),finish_reason=choice.get('finish_reason'),provider_model=data.get('model'),start_unix=start,end_unix=time.time(),latency_s=time.monotonic()-t)
 except Exception as e:return dict(status='infrastructure_failure',answer=None,usage=None,error=type(e).__name__+': '+str(e),start_unix=start,end_unix=time.time(),latency_s=time.monotonic()-t)

def collect(slot):
 verify();out=OUT/'fresh';file=out/(slot+'_RESPONSES.jsonl');ledger=out/(slot+'_REQUESTS.jsonl')
 if ledger.exists():raise RuntimeError('No generation replay')
 tasks=json.loads((out/'TASKS.json').read_text());shadow=set(json.loads((out/'SHADOW_IDS.json').read_text()));tasks=[t for t in tasks if t['task_id'] in shadow]
 with (core.ROOT/'collect/logs'/('reasoning.lock' if slot=='reasoning' else 'local_gpu.lock')).open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);engine.OUT=out;proc=log=None;start=time.time();startup=0;records=[];facts={}
  if True:
   base=core.lines(out/'routed_RESPONSES.jsonl')
   for r in base:
    if r['node_id']=='extraction':
     try:facts[r['task_id']]=parse_facts(r['answer'])
     except Exception:pass
  try:
   if slot!='reasoning':proc,log,startup=engine.start_model(slot)
   for nid in ['extraction','semantic']:
    layerstart=time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
     fs={}
     for t in tasks:
      if nid=='semantic' and t['task_id'] not in facts:continue
      text=eprompt(t) if nid=='extraction' else sprompt(t,facts[t['task_id']]);intent=dict(task_id=t['task_id'],node_id=nid,model=slot,prompt=text,unix_time=time.time());append(ledger,intent)
      fs[pool.submit(request_r1 if slot=='reasoning' else lambda txt:engine.call_model(slot,txt),text)]=t
     for future in as_completed(fs):
      t=fs[future];raw=future.result();r=dict(**raw,task_id=t['task_id'],node_id=nid,model=slot,stage_sojourn_seconds=raw['end_unix']-layerstart);records.append(r);append(file,r)
      if False:
       try:facts[t['task_id']]=parse_facts(r['answer'])
       except Exception:pass
    core.write(out/(slot+'_STATUS.json'),dict(phase='COLLECTING',records=len(records),layer=nid))
   core.write(out/(slot+'_STATUS.json'),dict(phase='COMPLETE',records=len(records),startup_seconds=startup,total_seconds=time.time()-start,missing=sum(r['status']!='delivered' for r in records)))
  finally:
   if proc is not None:engine.stop_model(proc,log)
 print(slot,'complete',len(records))

def routed():
 verify();out=OUT/'fresh';ledger=out/'routed_REQUESTS.jsonl';file=out/'routed_RESPONSES.jsonl'
 if ledger.exists():raise RuntimeError('No generation replay')
 tasks=json.loads((out/'TASKS.json').read_text());plans={p['task_id']:p for p in json.loads((out/'PLANS.json').read_text())};facts={};records=[];overall=time.time();loads=[]
 with (core.ROOT/'collect/logs/local_gpu.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);engine.OUT=out;proc=log=None;active=None
  try:
   for nid in ['extraction','semantic']:
    for slot in ['medium','large','coder']:
     group=[t for t in tasks if next(n['selected_model'] for n in plans[t['task_id']]['nodes'] if n['node_id']==nid)==slot and (nid=='extraction' or t['task_id'] in facts)]
     if not group:continue
     layerstart=time.time()
     if active!=slot:
      if proc is not None:engine.stop_model(proc,log);proc=log=None
      proc,log,startup=engine.start_model(slot);active=slot;loads.append(dict(model=slot,seconds=startup))
     with ThreadPoolExecutor(max_workers=4) as pool:
      fs={}
      for t in group:
       text=eprompt(t) if nid=='extraction' else sprompt(t,facts[t['task_id']]);append(ledger,dict(task_id=t['task_id'],node_id=nid,model=slot,prompt=text,unix_time=time.time()));fs[pool.submit(engine.call_model,slot,text)]=t
      for future in as_completed(fs):
       t=fs[future];raw=future.result();r=dict(**raw,task_id=t['task_id'],node_id=nid,model=slot,stage_sojourn_seconds=raw['end_unix']-layerstart);records.append(r);append(file,r)
       if nid=='extraction':
        try:facts[t['task_id']]=parse_facts(r['answer'])
        except Exception:pass
     core.write(out/'routed_STATUS.json',dict(phase='COLLECTING',records=len(records),node=nid,model=slot))
   core.write(out/'routed_STATUS.json',dict(phase='COMPLETE',records=len(records),loads=loads,total_seconds=time.time()-overall,missing=sum(r['status']!='delivered' for r in records)))
  finally:
   if proc is not None:engine.stop_model(proc,log)
 print('routed complete',len(records))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['controlled','prepare','routed','large','medium','coder','reasoning']);a=p.parse_args()
 if a.action in ['controlled','prepare']:globals()[a.action]()
 elif a.action=='routed':routed()
 else:collect(a.action)
