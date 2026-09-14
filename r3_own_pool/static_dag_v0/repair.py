"""Frozen local-repair pilot, with shared exact-request controls and tool baseline."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import time
from . import core
from . import run as engine

OUT=core.ROOT/'static_dag_v0/local_repair/run_v1'
ARMS=['static','local_repair']

def panel():
 rng=random.Random(20260916);rows=[]
 for i in range(20):
  departments=[rng.randint(10,55) for _ in range(4)];stock=rng.randint(5,30);reserve=rng.randint(3,12);units=sum(departments)-stock+reserve;deadline=rng.randint(3,8)
  suppliers=[dict(vendor=chr(65+j),unit_cents=rng.randint(180,460),discount_cents=rng.choice([0,10,20,30]),freight_cents=rng.randint(1,9)*100,handling_cents=rng.randint(0,4)*50,capacity=units+rng.choice([-15,0,25,50]),days=rng.randint(2,10)) for j in range(3)]
  budget=units*rng.randint(220,450)+500
  if i%5==0:deadline=1
  if i%5==1:
   suppliers[0].update(capacity=units,days=deadline);budget=units*(suppliers[0]['unit_cents']-suppliers[0]['discount_cents'])+suppliers[0]['freight_cents']+suppliers[0]['handling_cents']
  if i%5==2:
   suppliers[1]={**suppliers[0],'vendor':'B'}
   for j in [0,1]:suppliers[j].update(capacity=units,days=deadline)
  rows.append(dict(task_id=f'repair_new_{i:03d}',family='constrained_procurement',input=dict(departments=departments,stock=stock,reserve=reserve,suppliers=suppliers,budget_cents=budget,deadline_days=deadline)))
 return rows

def local_expected(task,node,predecessors):
 """Public node contract, never final task labels. Also used by the tool arm."""
 x=task['input'];nid=node['id']
 if nid=='demand':return dict(units=sum(x['departments'])-x['stock']+x['reserve'])
 if nid=='quotes':return dict(quotes=[dict(vendor=q['vendor'],unit_cents=q['unit_cents']-q['discount_cents'],shipping_cents=q['freight_cents']+q['handling_cents'],capacity=q['capacity'],days=q['days']) for q in x['suppliers']])
 if nid=='feasibility':
  units=predecessors['demand']['units'];options=[]
  for q in predecessors['quotes']['quotes']:
   total=units*q['unit_cents']+q['shipping_cents'];options.append(dict(vendor=q['vendor'],total_cents=total,eligible=units<=q['capacity'] and q['days']<=x['deadline_days'] and total<=x['budget_cents']))
  return dict(options=options)
 rows=sorted((q for q in predecessors['feasibility']['options'] if q['eligible']),key=lambda r:(r['total_cents'],r['vendor']))
 return dict(vendor=rows[0]['vendor'],total_cents=rows[0]['total_cents']) if rows else dict(vendor='NONE',total_cents=0)

def inspect_output(task,node,predecessors,raw):
 t=time.perf_counter();nid=node['id'];parsed=None;errors=[]
 if raw['status']=='infrastructure_failure':errors=['infrastructure_failure']
 else:
  try:parsed=core.parse(raw['answer'],nid)
  except (ValueError,KeyError,TypeError,IndexError):errors=['invalid_JSON_or_schema']
 if parsed is not None:
  target=local_expected(task,node,predecessors)
  if nid in ['demand','decision']:errors=[k for k in target if parsed[k]!=target[k]]
  else:
   key='quotes' if nid=='quotes' else 'options';actual={r['vendor']:r for r in parsed[key]}
   errors=[r['vendor']+'.'+k for r in target[key] for k in r if actual[r['vendor']][k]!=r[k]]
 return dict(parsed=parsed,passed=not errors,error_fields=errors,validation_seconds=time.perf_counter()-t)

def feedback_prompt(original,answer,error_fields):
 return original+'\nPrevious output:\n'+(answer or '(no output)')+'\nNode contract check failed for these fields: '+json.dumps(error_fields)+'. Recompute from this node input and predecessor outputs, check each arithmetic operation and boundary condition, and return one corrected JSON object. Write evaluated numbers, not arithmetic expressions. This is the only repair attempt.'

def prepare():
 if OUT.exists():raise FileExistsError('Refusing overwrite')
 OUT.mkdir(parents=True)
 rows=panel();old=json.loads((core.OUT/'TASKS.json').read_text());assert not ({json.dumps(r['input'],sort_keys=True) for r in rows}&{json.dumps(r['input'],sort_keys=True) for r in old})
 profiles=json.loads((core.OUT/'PROFILES.json').read_text());plans=[]
 for task in rows:
  nodes=[]
  for n in core.NODES:
   text=core.prompt(task,n,{d:{'upstream_output':'pending'} for d in n['deps']});n_in=(len(text)+3)//4+80*len(n['deps']);slot,preds=core.route(profiles,n_in)
   nodes.append(dict(**n,model=slot,predictions=preds))
  plans.append(dict(task_id=task['task_id'],nodes=nodes,layers=core.topology(nodes)))
 assert {n['model'] for p in plans for n in p['nodes']}=={'large'},'This bounded pilot requires the existing single selected server'
 core.write(OUT/'TASKS.json',rows);core.write(OUT/'PLANS.json',plans)
 bind=[Path(__file__),Path(core.__file__),Path(engine.__file__),OUT/'TASKS.json',OUT/'PLANS.json',core.OUT/'PROFILES.json',core.OUT/'TASKS.json']
 core.write(OUT/'PROTOCOL.json',dict(role='fresh_within_template_local_repair_pilot',seed=20260916,tasks=20,arms=['static','local_repair','tool_only'],initial_model='large',max_physical_requests=240,max_logical_static_requests=80,max_logical_repair_requests=160,repair_limit_per_node=1,temperature=0,max_tokens=512,concurrency=4,transport_retries=0,repair_trigger='Invalid schema or node-local arithmetic/constraint violation; infrastructure failure aborts experiment.',acceptance='Use repair if its contract passes; otherwise retain schema-valid original, or schema-valid repair if original unparseable; otherwise block descendants.',graph='Unchanged demand/quotes -> feasibility -> decision. No ancestor retries, model switching or replanning.',sharing='Exact identical initial requests shared across arms. Counterfactual logical token/service costs include shared work in each arm. Not independent repeated end-to-end runs.',feedback='Only error field names from executable public local contracts; no hidden answer, correct value or final task label sent.',tool_baseline='Execute same public contracts directly; demonstrates that this task family is deterministically solvable. Not a router method.',success='Final vendor and exact integer total both correct; quality 0.5 per field.',statistics='Paired task bootstrap 10000 resamples, seed20260916. Primary difference repair-static success rate; quality secondary. Conditional on this one new template sample and one response per unique prompt; no independent method-level runs.',cost='Actual usage tokens. Full logical costs charged per arm, including failed repairs; physical unique tokens separately. No dollar billing.',latency='Logical sum of request service times plus validator overhead per task; not measured isolated arm end-to-end latency. Shared batched experiment wall time separately.',stop='No new router, prompt search, model selection, new task families, Dynamic DAG or GitHub push after this run.',bindings={str(p):core.sha(p) for p in bind},created_unix=time.time()))
 core.write(OUT/'STATUS.json',dict(phase='PREPARED'));print('Prepared 20 fresh tasks, <=240 local requests')

def verify():
 p=json.loads((OUT/'PROTOCOL.json').read_text())
 for path,h in p['bindings'].items():
  if core.sha(path)!=h:raise ValueError('Frozen input changed: '+path)
 return p

def execute():
 verify()
 if (OUT/'STARTED.json').exists():raise RuntimeError('No automatic generation replay')
 def append(name,row):
  with (OUT/name).open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
 with (core.ROOT/'collect/logs/local_gpu.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);core.write(OUT/'STARTED.json',dict(unix_time=time.time(),protocol_sha256=core.sha(OUT/'PROTOCOL.json')))
  start=time.monotonic();engine.OUT=OUT;proc=log=None;cache={};physical=0
  rows=json.loads((OUT/'TASKS.json').read_text());plans=json.loads((OUT/'PLANS.json').read_text());state={(a,t['task_id']):{} for a in ARMS for t in rows};records=[]
  def batch(texts):
   nonlocal physical
   wanted={hashlib.sha256(text.encode()).hexdigest():text for text in texts}
   with ThreadPoolExecutor(max_workers=4) as pool:
    futures={}
    for key,text in wanted.items():
     if key in cache:continue
     if physical>=240:raise RuntimeError('Physical budget exhausted')
     physical+=1;append('REQUESTS.jsonl',dict(request_id=key,prompt=text,model='large',unix_time=time.time()))
     futures[pool.submit(engine.call_model,'large',text)]=key
    for f in as_completed(futures):
     key=futures[f];raw=f.result();cache[key]=raw;append('RESPONSES.jsonl',dict(request_id=key,**raw))
     if raw['status']=='infrastructure_failure':raise RuntimeError('Infrastructure failure; no inference from incomplete panel')
   return {text:(hashlib.sha256(text.encode()).hexdigest(),cache[hashlib.sha256(text.encode()).hexdigest()]) for text in texts}
  try:
   proc,log,startup=engine.start_model('large')
   for layer in range(3):
    jobs=[]
    for arm in ARMS:
     for task,p in zip(rows,plans):
      for node in p['nodes']:
       if node['id'] not in p['layers'][layer]:continue
       pred=state[arm,task['task_id']]
       base=dict(arm=arm,task_id=task['task_id'],node_id=node['id'],model=node['model'],attempts=[],validation_seconds=0.)
       if any(d not in pred for d in node['deps']):
        r=dict(**base,status='blocked_dependency',parsed=None);records.append(r);append('NODES.jsonl',r);continue
       text=core.prompt(task,node,pred);jobs.append((task,node,pred,text,base))
    first=batch([j[3] for j in jobs]);pending=[];ready=[]
    for task,node,pred,text,base in jobs:
     key,raw=first[text];audit=inspect_output(task,node,pred,raw)
     base.update(initial_audit=audit,validation_seconds=audit['validation_seconds'] if base['arm']=='local_repair' else 0.,attempts=[dict(request_id=key,kind='initial')])
     if base['arm']=='local_repair' and not audit['passed']:
      pending.append((task,node,pred,feedback_prompt(text,raw.get('answer'),audit['error_fields']),base))
     else:ready.append(dict(**base,parsed=audit['parsed'],status='accepted' if audit['parsed'] is not None else 'schema_invalid',repaired=False))
    repaired=batch([j[3] for j in pending])
    for task,node,pred,text,base in pending:
     key,raw=repaired[text];audit=inspect_output(task,node,pred,raw);base['attempts'].append(dict(request_id=key,kind='repair'));base['validation_seconds']+=audit['validation_seconds'];original=base['initial_audit']['parsed']
     accepted=audit['parsed'] if audit['passed'] else original if original is not None else audit['parsed']
     ready.append(dict(**base,parsed=accepted,repair_audit=audit,status='repaired' if audit['passed'] else 'unresolved' if accepted is not None else 'schema_invalid',repaired=audit['passed']))
    for r in ready:
     if r['parsed'] is not None:state[r['arm'],r['task_id']][r['node_id']]=r['parsed']
     records.append(r);append('NODES.jsonl',r)
    core.write(OUT/'STATUS.json',dict(phase='EXECUTING',completed_layers=layer+1,physical_requests=physical,logical_nodes=len(records)))
   tools=[]
   for task in rows:
    t0=time.perf_counter();pred={}
    for node in core.NODES:pred[node['id']]=local_expected(task,node,pred)
    tools.append(dict(task_id=task['task_id'],outputs=pred,wall_seconds=time.perf_counter()-t0))
   core.write(OUT/'TOOL_ONLY.json',tools);core.write(OUT/'EXECUTION_COMPLETE.json',dict(physical_requests=physical,wall_seconds=time.monotonic()-start,model_startup_seconds=startup,unix_time=time.time()))
  except BaseException as e:
   core.write(OUT/'STATUS.json',dict(phase='FAILED',error=type(e).__name__+': '+str(e),physical_requests=physical));raise
  finally:
   if proc is not None:engine.stop_model(proc,log)
 evaluate()

def evaluate():
 import numpy as np
 verify();rows=json.loads((OUT/'TASKS.json').read_text());nodes=core.lines(OUT/'NODES.jsonl');raws={r['request_id']:r for r in core.lines(OUT/'RESPONSES.jsonl')};tool={t['task_id']:t for t in json.loads((OUT/'TOOL_ONLY.json').read_text())};records={(r['arm'],r['task_id'],r['node_id']):r for r in nodes};assert len(records)==len(nodes)==160
 per=[]
 for task in rows:
  target=core.truth(task)['decision'];row=dict(task_id=task['task_id'],expected=target,arms={})
  for arm in ARMS:
   nr=[records[arm,task['task_id'],n['id']] for n in core.NODES];answer=nr[-1]['parsed'];attempts=[a for r in nr for a in r['attempts']];selected=[raws[a['request_id']] for a in attempts]
   assert all(r.get('usage') for r in selected)
   row['arms'][arm]=dict(answer=answer,quality=sum(answer.get(k)==v for k,v in target.items())/2 if answer else 0.,success=answer==target,tokens=sum(r['usage']['total_tokens'] for r in selected),logical_calls=len(attempts),repair_calls=sum(a['kind']=='repair' for a in attempts),request_service_seconds=sum(r['latency_s'] for r in selected),validator_seconds=sum(r['validation_seconds'] for r in nr),repair_tokens=sum(raws[a['request_id']]['usage']['total_tokens'] for a in attempts if a['kind']=='repair'))
  ans=tool[task['task_id']]['outputs']['decision'];row['arms']['tool_only']=dict(answer=ans,quality=sum(ans[k]==v for k,v in target.items())/2,success=ans==target,tokens=0,logical_calls=0,repair_calls=0,wall_seconds=tool[task['task_id']]['wall_seconds'])
  per.append(row)
 summary={}
 for arm in ARMS+['tool_only']:
  rs=[r['arms'][arm] for r in per];summary[arm]=dict(quality=float(np.mean([r['quality'] for r in rs])),success_rate=float(np.mean([r['success'] for r in rs])),tokens=sum(r['tokens'] for r in rs),logical_calls=sum(r['logical_calls'] for r in rs),repair_calls=sum(r['repair_calls'] for r in rs))
  if arm!='tool_only':summary[arm].update(mean_request_service_seconds=float(np.mean([r['request_service_seconds'] for r in rs])),mean_validator_seconds=float(np.mean([r['validator_seconds'] for r in rs])),repair_tokens=sum(r['repair_tokens'] for r in rs))
  else:summary[arm]['mean_wall_seconds']=float(np.mean([r['wall_seconds'] for r in rs]))
 rng=np.random.default_rng(20260916);indices=rng.integers(0,20,(10000,20));comparisons={}
 for metric in ['success','quality']:
  d=np.array([float(r['arms']['local_repair'][metric])-float(r['arms']['static'][metric]) for r in per]);comparisons[metric]=dict(delta=float(d.mean()),ci95=np.quantile(d[indices].mean(axis=1),[.025,.975]).tolist())
 failed=[r for r in per if not r['arms']['static']['success']];recovered=sum(r['arms']['local_repair']['success'] for r in failed);regressed=sum(r['arms']['static']['success'] and not r['arms']['local_repair']['success'] for r in per)
 repairs=[r for r in nodes if r['arm']=='local_repair' and len(r['attempts'])==2]
 result=dict(arms=summary,paired_repair_minus_static=comparisons,task_recovery=dict(recovered=recovered,baseline_failed=len(failed),rate=recovered/len(failed) if failed else None,regressed=regressed),node_repair=dict(attempted=len(repairs),contract_passed=sum(r['repaired'] for r in repairs)),physical_requests=len(raws),physical_tokens=sum(r['usage']['total_tokens'] for r in raws.values()),execution=json.loads((OUT/'EXECUTION_COMPLETE.json').read_text()),limitations=['Fresh tasks within an already inspected constructed family, not untouched external benchmark.','Executable verifier completely solves this arithmetic family; tool baseline is essential.','Repair receives more compute than static; no attribution to specific feedback versus retry budget alone.','Shared exact requests couple the arms; logical latency is service accounting, not isolated end-to-end measurement.','All assignments large: no evidence of model routing gain, dynamic planning gain or Pareto optimality.'])
 core.write(OUT/'PER_TASK.json',per);core.write(OUT/'RESULTS.json',result)
 report=['# Static DAG + Local Repair：一次受控验证','', '20 个新生成且在调用前冻结的同模板任务；旧20题仅用于定位问题。模型、图、初始分配保持原样，每个失败节点最多修复一次。','', '| 方法 | 最终质量 | 完全成功率 | 逻辑 tokens | 逻辑调用 | 修复调用 |','|---|---:|---:|---:|---:|---:|']
 for arm,s in summary.items():report.append(f"| {arm} | {s['quality']:.3f} | {s['success_rate']:.1%} | {s['tokens']} | {s['logical_calls']} | {s['repair_calls']} |")
 c=comparisons['success'];q=comparisons['quality'];report+=['',f"修复−静态：成功率差 {100*c['delta']:+.1f} pp，95% task-paired bootstrap CI [{100*c['ci95'][0]:.1f}, {100*c['ci95'][1]:.1f}] pp。质量差 {q['delta']:+.3f}，CI {q['ci95']}。",f"原静态失败 {len(failed)} 题，修复后恢复 {recovered} 题，原成功退化 {regressed} 题。触发节点修复 {len(repairs)} 次，通过当前节点契约 {sum(r['repaired'] for r in repairs)} 次。",'', '## 实际执行与计量','',f"实际唯一请求 {len(raws)} 次，消耗 {result['physical_tokens']} tokens；各方法表格按独立执行应承担的全部调用收费式计量，包含共享初次请求及失败修复。成本是 tokens，不是账单。"]
 for arm in ARMS:report.append(f"{arm} 每题累计请求服务时长 {summary[arm]['mean_request_service_seconds']:.3f}s，检查开销 {summary[arm]['mean_validator_seconds']:.6f}s。它们不是独立部署的端到端延迟；本批物理执行耗时 {result['execution']['wall_seconds']:.2f}s 含模型启动与排队。")
 report+=['', '## 解释边界','', '- 反馈由公开节点输入的算术/约束契约生成，只回传不一致字段名，未传正确数值或评测答案。但该验证器本质上已能计算此任务，因此不能把提升宣传为通用自修复或路由创新。','- tool_only 是真实确定性执行，0 模型 tokens；计入其 CPU 时间。这不是 Oracle 标签替代回答，而是直接执行公开业务规则。','- 修复增加算力；没有等预算重试对照，不能单独归因于反馈内容。','- 任务级 CI 仅刻画20题重采样不确定性，不包括模型重复、任务族迁移或独立执行方差。','- 不调提示/模型/阈值，不重跑选最好结果，不自动上 Dynamic DAG 或扩展数据。']
 if summary['tool_only']['success_rate']>=summary['local_repair']['success_rate']:
  report+=['','下一步建议：将可精确计算的节点显式路由给确定性工具，随后在需要语义提取/非确定推理的自然复杂任务上建立静态基线。当前证据不足以推进 Graph Forest；不要继续用模型反复做整数运算证明动态方法。']
 (OUT/'REPORT.md').write_text('\n'.join(report)+'\n');core.write(OUT/'STATUS.json',dict(phase='COMPLETE',next_experiment_started=False));print(json.dumps(result))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','execute','evaluate']);a=p.parse_args();globals()[a.action]()
