"""Bounded local-only Static DAG v0: prepare -> execute -> evaluate."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib import request
from .core import ROOT, OUT, NODES, tasks, topology, truth, prompt, parse, route, sha, write, lines

MODELS={
 'medium':dict(path='/root/autodl-tmp/models/Qwen2.5-7B-Instruct',served='Qwen/Qwen2.5-7B-Instruct'),
 'large':dict(path='/root/autodl-tmp/models/Qwen2.5-14B-Instruct-GPTQ-Int8',served='Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8'),
 'coder':dict(path='/root/autodl-tmp/models/Qwen2.5-Coder-7B-Instruct',served='Qwen/Qwen2.5-Coder-7B-Instruct'),
}

def prepare():
 if OUT.exists():raise FileExistsError('Preserve frozen run; refusing overwrite')
 OUT.mkdir()
 source=ROOT/'router_v2/label_repair_experiment';profile={};sources={}
 for slot in MODELS:
  p=source/'raw'/f'{slot}.jsonl';rows=lines(p)
  assert len(rows)==1030 and all(r['quality'] is not None for r in rows)
  profile[slot]=dict(quality=sum(r['quality'] for r in rows)/len(rows),mean_output_tokens=sum(r['usage']['completion_tokens'] for r in rows)/len(rows),mean_total_tokens=sum(r['usage']['total_tokens'] for r in rows)/len(rows),mean_latency_s=sum(r['latency']['total_ms']/1000 for r in rows)/len(rows),n_queries=len({r['query_id'] for r in rows}),n_responses=len(rows))
  sources[str(p)]=sha(p)
  provenance=source/'raw'/f'{slot}_MODEL_PROVENANCE.json';sources[str(provenance)]=sha(provenance)
 profile=dict(sorted(profile.items()));panel=tasks();plans=[]
 for task in panel:
  nodes=[]
  for n in NODES:
   # Input-only heuristic. Placeholder length budget is frozen before node execution.
   base=prompt(task,n,{d:{'upstream_output':'pending'} for d in n['deps']})
   estimate=(len(base)+3)//4+80*len(n['deps'])
   selected,candidates=route(profile,estimate)
   nodes.append(dict(**n,model=selected,predictions=candidates,estimated_input_tokens=estimate))
  plans.append(dict(task_id=task['task_id'],nodes=nodes,layers=topology(nodes)))
 write(OUT/'TASKS.json',panel);write(OUT/'PROFILES.json',profile);write(OUT/'PLANS.json',plans)
 bindings={str(p):sha(p) for p in [Path(__file__),Path(__file__).with_name('core.py'),OUT/'TASKS.json',OUT/'PROFILES.json',OUT/'PLANS.json']}
 write(OUT/'PROTOCOL.json',dict(version='static_dag_v0',role='synthetic_business_workflow_pilot',n_tasks=20,n_nodes_per_task=4,max_requests=80,models=MODELS,seed=20260915,temperature=0,top_p=1,max_tokens=512,timeout_seconds=180,concurrency=4,retries=0,local_repair=False,dynamic_replanning=False,decomposition='deterministic domain template; not learned decomposition',routing='Q - 0.05*C_tokens/1000 - 0.05*L_seconds/10; fixed input-only initial assignments',profile_limitations='Uncalibrated global priors from actively selected MMLU queries, transferred to procurement nodes; not GTE or a newly trained router.',cost_basis='Measured token usage, not money or actual GPU billing. Resource wall time separately recorded.',latency_basis='Observed per-task batch sojourn includes model startup/queueing. Service critical path is a diagnostic, not observed parallel latency.',quality='Final vendor and exact total each 0.5; task success requires both. Infrastructure missing is not semantic zero. No evaluator truth used during execution.',scope='20 one-family constructed tasks test mechanics, not generalization, superiority, or Pareto claims.',code_and_inputs=bindings,profile_sources=sources,created_unix=time.time()))
 write(OUT/'STATUS.json',dict(phase='PREPARED',requests=0,next_experiment_started=False))
 print(json.dumps(dict(prepared=True,tasks=20,nodes=80,selection={s:sum(n['model']==s for p in plans for n in p['nodes']) for s in MODELS})))

def verify():
 p=json.loads((OUT/'PROTOCOL.json').read_text())
 for path,h in {**p['code_and_inputs'],**p['profile_sources']}.items():
  if sha(path)!=h:raise ValueError('Frozen input changed: '+path)
 return p

def start_model(slot):
 cfg=MODELS[slot]
 gpu=subprocess.run(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],capture_output=True,text=True)
 if gpu.returncode or gpu.stdout.strip():raise RuntimeError('GPU busy; refusing to interrupt another job')
 with socket.socket() as s:
  if s.connect_ex(('127.0.0.1',8128))==0:raise RuntimeError('Port occupied')
 provenance=json.loads((ROOT/'router_v2/label_repair_experiment/raw'/f'{slot}_MODEL_PROVENANCE.json').read_text())
 for name,h in {**provenance['config_sha256'],**provenance['weight_sha256']}.items():
  if sha(Path(cfg['path'])/name)!=h:raise ValueError('Checkpoint changed')
 log=(OUT/'MODEL_SERVER.log').open('a');t=time.monotonic()
 proc=subprocess.Popen(['/root/autodl-tmp/r3_venv/bin/vllm','serve',cfg['path'],'--served-model-name',cfg['served'],'--port','8128','--max-model-len','8192','--max-num-seqs','4','--gpu-memory-utilization','.92','--dtype','auto','--generation-config','vllm'],stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
 opener=request.build_opener(request.ProxyHandler({}))
 try:
  deadline=time.monotonic()+300
  while time.monotonic()<deadline:
   if proc.poll() is not None:raise RuntimeError('Model server exited')
   try:
    with opener.open('http://127.0.0.1:8128/health',timeout=2) as response:
     if response.status==200:return proc,log,time.monotonic()-t
   except Exception:time.sleep(1)
  raise TimeoutError('Model startup timeout')
 except BaseException:
  stop_model(proc,log);raise

def stop_model(proc,log):
 proc.terminate()
 try:proc.wait(timeout=30)
 except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=10)
 log.close()

def call_model(slot,text):
 t=time.monotonic();start=time.time()
 payload=dict(model=MODELS[slot]['served'],messages=[dict(role='user',content=text)],temperature=0,top_p=1,max_tokens=512,stream=False)
 try:
  req=request.Request('http://127.0.0.1:8128/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
  with request.build_opener(request.ProxyHandler({})).open(req,timeout=180) as r:data=json.loads(r.read())
  choice=data['choices'][0];answer=choice['message'].get('content') or ''
  return dict(status='delivered' if answer else 'infrastructure_failure',answer=answer,usage=data.get('usage'),finish_reason=choice.get('finish_reason'),provider_model=data.get('model'),provider_id=data.get('id'),start_unix=start,end_unix=time.time(),latency_s=time.monotonic()-t)
 except Exception as e:return dict(status='infrastructure_failure',error=type(e).__name__+': '+str(e),answer=None,usage=None,start_unix=start,end_unix=time.time(),latency_s=time.monotonic()-t)

def execute():
 verify()
 if (OUT/'EXECUTION_STARTED.json').exists():raise RuntimeError('Already started; no implicit replay of generation')
 with (ROOT/'collect/logs/local_gpu.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  write(OUT/'EXECUTION_STARTED.json',dict(unix_time=time.time(),protocol_sha256=sha(OUT/'PROTOCOL.json')))
  begin=time.monotonic();panel={t['task_id']:t for t in json.loads((OUT/'TASKS.json').read_text())};plans=json.loads((OUT/'PLANS.json').read_text());outputs={k:{} for k in panel};records={};proc=log=None;current=None;loads=[];count=0
  def append(path,obj):
   with path.open('a') as f:f.write(json.dumps(obj,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
  try:
   for layer in range(3):
    jobs={s:[] for s in MODELS}
    for p in plans:
     for n in p['nodes']:
      if n['id'] not in p['layers'][layer]:continue
      tid=p['task_id'];key=(tid,n['id'])
      if any(d not in outputs[tid] for d in n['deps']):
       r=dict(task_id=tid,node_id=n['id'],model=n['model'],status='blocked_dependency',latency_s=0,usage=None,end_unix=time.time());records[key]=r;append(OUT/'NODES.jsonl',r);continue
      jobs[n['model']].append((tid,n,prompt(panel[tid],n,outputs[tid])))
    for slot in sorted(jobs):
     if not jobs[slot]:continue
     if current!=slot:
      if proc is not None:stop_model(proc,log);proc=log=None
      proc,log,seconds=start_model(slot);current=slot;loads.append(dict(model=slot,startup_seconds=seconds))
     with ThreadPoolExecutor(max_workers=4) as pool:
      futures={}
      for tid,n,text in jobs[slot]:
       if count>=80:raise RuntimeError('Request budget exceeded')
       intent=dict(task_id=tid,node_id=n['id'],model=slot,prompt=text,prompt_sha256=__import__('hashlib').sha256(text.encode()).hexdigest(),unix_time=time.time());append(OUT/'REQUESTS.jsonl',intent);count+=1
       futures[pool.submit(call_model,slot,text)]=(tid,n)
      for f in as_completed(futures):
       tid,n=futures[f];r=dict(**f.result(),task_id=tid,node_id=n['id'],model=slot)
       if r['status']=='delivered':
        try:r['parsed']=parse(r['answer'],n['id']);outputs[tid][n['id']]=r['parsed'];r['status']='schema_valid'
        except (ValueError,TypeError,KeyError,IndexError) as e:r['status']='schema_invalid';r['parse_error']=str(e)
       records[(tid,n['id'])]=r;append(OUT/'NODES.jsonl',r)
       write(OUT/'STATUS.json',dict(phase='EXECUTING',recorded_nodes=len(records),submitted_requests=count,active_model=slot))
   write(OUT/'EXECUTION_COMPLETE.json',dict(wall_seconds=time.monotonic()-begin,model_loads=loads,requests=count,recorded_nodes=len(records),unix_time=time.time()))
  finally:
   if proc is not None:stop_model(proc,log)
 evaluate()

def evaluate():
 verify();panel=json.loads((OUT/'TASKS.json').read_text());records=lines(OUT/'NODES.jsonl');index={(r['task_id'],r['node_id']):r for r in records};plans=json.loads((OUT/'PLANS.json').read_text());meta=json.loads((OUT/'EXECUTION_COMPLETE.json').read_text());start=json.loads((OUT/'EXECUTION_STARTED.json').read_text())['unix_time']
 assert len(index)==len(records)==80
 results=[]
 for t,p in zip(panel,plans):
  tid=t['task_id'];expected=truth(t);rs={n['id']:index[(tid,n['id'])] for n in p['nodes']};final=rs['decision'];infra=any(r['status']=='infrastructure_failure' for r in rs.values());got=final.get('parsed')
  q=None if infra else (sum(got.get(k)==expected['decision'][k] for k in ['vendor','total_cents'])/2 if got else 0.)
  tokens=sum((r.get('usage') or {}).get('total_tokens',0) for r in rs.values());coverage=all(r.get('usage') is not None for r in rs.values() if r['status']!='blocked_dependency')
  path={}
  for layer in p['layers']:
   for nid in layer:
    deps=next(n['deps'] for n in p['nodes'] if n['id']==nid);path[nid]=max([path[d] for d in deps] or [0])+rs[nid]['latency_s']
  results.append(dict(task_id=tid,quality=q,task_success=q==1,final=got,expected=expected['decision'],node_exact={nid:r.get('parsed')==expected[nid] for nid,r in rs.items()},node_status={nid:r['status'] for nid,r in rs.items()},cost_tokens=tokens if coverage else None,known_tokens=tokens,batch_sojourn_seconds=max(r['end_unix'] for r in rs.values())-start,service_critical_path_seconds=path['decision']))
 valid=[r['quality'] for r in results if r['quality'] is not None];selection={s:sum(n['model']==s for p in plans for n in p['nodes']) for s in MODELS}
 summary=dict(role='workflow_pilot_not_method_comparison',tasks=20,quality_mean=sum(valid)/len(valid) if valid else None,quality_denominator=len(valid),task_success_rate=sum(r['task_success'] for r in results)/20,total_known_tokens=sum(r['known_tokens'] for r in results),token_coverage_tasks=sum(r['cost_tokens'] is not None for r in results),mean_batch_sojourn_seconds=sum(r['batch_sojourn_seconds'] for r in results)/20,mean_service_critical_path_seconds=sum(r['service_critical_path_seconds'] for r in results)/20,execution=meta,planned_selection=selection,node_exact_counts={nid:sum(r['node_exact'][nid] for r in results) for nid in expected},node_status_counts={s:sum(r['status']==s for r in records) for s in sorted({r['status'] for r in records})},failure_recovery_rate=None,replanning_cost=None,pareto_hypervolume=None,metrics_not_applicable='No repair/replanning/comparators implemented in v0; no hypervolume computed.')
 write(OUT/'RESULTS.json',summary);write(OUT/'PER_TASK.json',results)
 report=['# Static DAG v0 — 20-task workflow pilot','', '复杂任务 → 显式模板分解 → 固定 DAG → 节点静态分配 → 真实本地模型执行 → 独立 Q/C/L 统计已执行。','',f"- 任务：20 个构造的采购约束任务；单一任务族，不能据此声称通用复杂任务效果。",f"- 最终质量：{summary['quality_mean']}（可评分 {len(valid)}/20）；完全成功率：{summary['task_success_rate']:.1%}。",f"- 成本：已记录 {summary['total_known_tokens']} tokens，完整计量 {summary['token_coverage_tasks']}/20 题；这不是美元费用。",f"- 平均观测批处理逗留时间：{summary['mean_batch_sojourn_seconds']:.2f}s；含队列、模型启动与其他任务等待。",f"- 平均服务时长关键路径：{summary['mean_service_critical_path_seconds']:.2f}s；只是诊断，不能当实际并行端到端延迟。",f"- 节点分配：{selection}；不为了展示多模型而强制分散。",f"- 节点状态：{summary['node_status_counts']}。",'', '## 冻结设置与边界','', '- 图：demand 与 quotes 为独立根节点；共同输入 feasibility；decision 依赖 feasibility。同层跨任务并发 4，同一 GPU 按模型分批执行。','- 初始画像来自历史103题补采的模型平均质量、tokens、请求耗时；是未经采购任务校准的先验，不是新训练的 Router，也没有宣称 GTE 对节点有效。','- 选择规则冻结为 Q − 0.05·tokens/1000 − 0.05·seconds/10，不用本次任务答案或执行反馈改分配。','- JSON 结构错误阻断后继；数值错误只在执行结束后评分，不触发重试、换模型或重规划。','- 分解是可检查的领域模板，尚未实现自由文本自动分解；采购任务本身为程序构造，LLM 回答为真实调用。','- v0 只验证执行闭环，未比较 BestSingle / Router Only / Local Repair / Dynamic DAG，不报告方法优越性或 Pareto hypervolume。','- 未扩展1000题画像数据，未启动 Graph Forest、Local Repair 或新 GAP 实验，未推 GitHub。','', '## 后续接口','', 'NODES.jsonl 的状态、原始输出、解析输出、usage 和耗时是 Execution Feedback 的接口。PLANS.json 已冻结输入画像和全部候选分数；Local Repair 与 Dynamic Replanning 后续应独立增加，不能混入本次静态结果。','']
 (OUT/'REPORT.md').write_text('\n'.join(report));write(OUT/'STATUS.json',dict(phase='COMPLETE',next_experiment_started=False,requests=meta['requests']))
 print(json.dumps(summary))

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','execute','evaluate']);args=ap.parse_args();globals()[args.action]()
