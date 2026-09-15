"""Live tool nodes and post-freeze outcome analysis (no model generation)."""
import argparse, ast, json, math, operator, re, time
from pathlib import Path
from fractions import Fraction
import numpy as np
from . import core,tool_aware_v1 as v
OUT=v.OUT/'fresh'

def live_tools():
 v.verify()
 if (OUT/'TOOL_NODES.jsonl').exists():raise RuntimeError('tool output already exists')
 facts={};finished=set();start=time.time()
 while time.time()-start<1800:
  file=OUT/'routed_RESPONSES.jsonl'
  rows=core.lines(file) if file.exists() else []
  for r in rows:
   if r['node_id']=='extraction':
    try:facts[r['task_id']]=v.parse_facts(r['answer'])
    except Exception:pass
   if r['node_id']!='semantic' or r['task_id'] in finished:continue
   begin=time.time();record=dict(task_id=r['task_id'],started_unix=begin)
   try:
    expr=v.decode(r['answer'])['expression'];value=v.calculate(expr,facts[r['task_id']]);record.update(expression=expr,value=value,status='valid',arithmetic_executed=True,verification_accept=True)
   except Exception as e:record.update(value=None,status='rejected',error=type(e).__name__,arithmetic_executed=False,verification_accept=False)
   record.update(ended_unix=time.time(),wall_seconds=time.time()-begin);v.append(OUT/'TOOL_NODES.jsonl',record);finished.add(r['task_id'])
  status=OUT/'routed_STATUS.json'
  if status.exists() and json.loads(status.read_text())['phase']=='COMPLETE':
   ids={t['task_id'] for t in json.loads((OUT/'TASKS.json').read_text())}
   for tid in sorted(ids-finished):v.append(OUT/'TOOL_NODES.jsonl',dict(task_id=tid,status='blocked',value=None,arithmetic_executed=False,verification_accept=False,started_unix=time.time(),ended_unix=time.time(),wall_seconds=0.))
   core.write(OUT/'TOOLS_COMPLETE.json',dict(tasks=len(ids),executed=len(finished),unix_time=time.time()));print('live tools complete');return
  time.sleep(.25)
 raise TimeoutError('routed execution did not complete')

def operands(program):
 vals=[]
 for args in re.findall(r'\(([^()]*)\)',program):
  for x in args.split(','):
   x=x.strip()
   if x.startswith(('#','const_')):continue
   try:vals.append(float(x))
   except ValueError:pass
 return vals

def close(a,b):return a is not None and abs(a-b)<=max(.0001,.0001*abs(b))
def extraction_metric(answer,program):
 try:
  f=v.parse_facts(answer);wanted=operands(program);got=[x['value'] for x in f['facts']]
  return bool(wanted) and all(any(close(g,w) for g in got) for w in wanted)
 except Exception:return False

def independent_calc(expression,facts):
 funcs={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv}
 tree=ast.parse(expression,mode='eval')
 def walk(n):
  if isinstance(n,ast.Expression):return walk(n.body)
  if isinstance(n,ast.Constant) and type(n.value) in [int,float] and n.value in [0,1,100]:return Fraction(str(n.value))
  if isinstance(n,ast.Name) and re.fullmatch('v[0-9]+',n.id):return Fraction(str(facts['facts'][int(n.id[1:])]['value']))
  if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.USub,ast.UAdd)):return walk(n.operand)*(-1 if isinstance(n.op,ast.USub) else 1)
  if isinstance(n,ast.BinOp) and type(n.op) in funcs:return funcs[type(n.op)](walk(n.left),walk(n.right))
  raise ValueError('not allowed')
 return float(walk(tree))

def evaluate():
 v.verify();tasks=json.loads((OUT/'TASKS.json').read_text());labels={t['task_id']:t for t in json.loads((OUT/'EVAL_ONLY.json').read_text())};plans=json.loads((OUT/'PLANS.json').read_text());rows=core.lines(OUT/'routed_RESPONSES.jsonl');lookup={(r['task_id'],r['node_id']):r for r in rows};tools={r['task_id']:r for r in core.lines(OUT/'TOOL_NODES.jsonl')};per=[];facts={};toolchecks=[]
 entry=min(r['end_unix']-r['stage_sojourn_seconds'] for r in rows)
 for t in tasks:
  tid=t['task_id'];r=tools[tid];e=lookup.get((tid,'extraction'));s=lookup.get((tid,'semantic'));gold=labels[tid];value=r['value'];q=close(value,gold['answer']);actual=[x for x in [e,s] if x];coverage=all(x.get('usage') for x in actual)
  try:facts[tid]=v.parse_facts(e['answer'])
  except Exception:pass
  if r['arithmetic_executed']:
   independent=independent_calc(r['expression'],facts[tid]);assert close(independent,r['value']);toolchecks.append(True)
  per.append(dict(task_id=tid,answer=value,reference=gold['answer'],quality=float(q),success=q,tool_status=r['status'],extraction_operand_recall_pass=extraction_metric(e.get('answer') if e else None,gold['program']),semantic_answer_equivalence_pass=q,tokens=sum(x['usage']['total_tokens'] for x in actual) if coverage else None,known_tokens=sum((x.get('usage') or {}).get('total_tokens',0) for x in actual),infrastructure_missing=any(x['status']=='infrastructure_failure' for x in actual),end_to_end_batch_seconds=r['ended_unix']-entry,llm_calls=len(actual)))
 diagnostics=[]
 shadow=set(json.loads((OUT/'SHADOW_IDS.json').read_text()))
 for slot in ['small','medium','large','reasoning','coder']:
  file=OUT/(slot+'_RESPONSES.jsonl')
  if not file.exists():diagnostics.append(dict(model=slot,available=False,reason='Checkpoint unavailable / no run',nodes=0));continue
  rr=core.lines(file)
  for nid in ['extraction','semantic']:
   subset=[r for r in rr if r['node_id']==nid];available=[r for r in subset if r['status']=='delivered'];correct=[]
   for r in available:
    if nid=='extraction':ok=extraction_metric(r['answer'],labels[r['task_id']]['program'])
    else:
     try:ok=close(v.calculate(v.decode(r['answer'])['expression'],facts[r['task_id']]),labels[r['task_id']]['answer'])
     except Exception:ok=False
    correct.append(ok)
   diagnostics.append(dict(model=slot,node_type=nid,available=True,requested=len(subset),delivered=len(available),correct=sum(correct),accuracy_delivered=sum(correct)/len(correct) if correct else None,mean_actual_tokens=np.mean([r['usage']['total_tokens'] for r in available if r.get('usage')]).item() if any(r.get('usage') for r in available) else None,mean_actual_latency_s=np.mean([r['latency_s'] for r in available]).item() if available else None))
 audit=[]
 for p in plans:
  for n in p['nodes']:
   rr={r['model']:r for r in diagnostics if r.get('node_type')==n['node_id']}
   candidates=n['candidates'];top=candidates[n['selected_model']]
   for slot,c in candidates.items():
    actual=None;fp=OUT/(slot+'_RESPONSES.jsonl')
    if fp.exists():actual=next((r for r in core.lines(fp) if r['task_id']==p['task_id'] and r['node_id']==n['node_id']),None)
    node_ok=None
    if actual and actual['status']=='delivered':
     if n['node_id']=='extraction':node_ok=extraction_metric(actual['answer'],labels[p['task_id']]['program'])
     else:
      try:node_ok=close(v.calculate(v.decode(actual['answer'])['expression'],facts[p['task_id']]),labels[p['task_id']]['answer'])
      except Exception:node_ok=False
    audit.append(dict(actual_shadow_node_accuracy=node_ok,task_id=p['task_id'],node_type=n['node_id'],candidate=slot,selected=slot==n['selected_model'],**c,actual_shadow_tokens=(actual.get('usage') or {}).get('total_tokens') if actual else None,actual_shadow_latency_s=actual.get('latency_s') if actual else None,actual_status=actual.get('status') if actual else 'not_sampled_or_unavailable',score_margin_to_selected=top['score']-c['score'] if c.get('score') is not None else None))
 counts={nid:{slot:sum(n['node_id']==nid and n['selected_model']==slot for p in plans for n in p['nodes']) for slot in ['small','medium','large','reasoning','coder']} for nid in ['extraction','semantic']}
 success=sum(r['success'] for r in per);llmacc=sum(r['extraction_operand_recall_pass']+int(r['semantic_answer_equivalence_pass']) for r in per)/80
 # bool + bool in Python uses integer addition; values are normalized explicitly below.
 llmacc=sum(int(r['extraction_operand_recall_pass'])+int(r['semantic_answer_equivalence_pass']) for r in per)/80
 result=dict(tasks=40,task_success_rate=success/40,mean_quality=success/40,total_tokens=sum(r['known_tokens'] for r in per),token_coverage_tasks=sum(r['tokens'] is not None for r in per),inference_cost=None,cost_basis='tokens measured; local GPU monetary bill unavailable',mean_end_to_end_batch_seconds=sum(r['end_to_end_batch_seconds'] for r in per)/40,latency_scope='Observed batch arrival through model queues, model loads, semantic stage, live tool/verification completion. Shared single GPU, not isolated per-task online latency.',tool_node_accuracy=1. if toolchecks else None,tool_accuracy_denominator=len(toolchecks),tool_valid_execution_tasks=len(toolchecks),verification_rejected_or_blocked=40-len(toolchecks),llm_node_accuracy_proxy=llmacc,extraction_accuracy=sum(r['extraction_operand_recall_pass'] for r in per)/40,semantic_accuracy=sum(r['semantic_answer_equivalence_pass'] for r in per)/40,selection=counts,shadow_diagnostics=diagnostics,small_unavailable=True,router_changed=False,success_gate_applicable='Controlled 20-task ablation only. No Static/Repair results on these natural tasks; cannot claim a paired gain here.')
 core.write(OUT/'PER_TASK.json',per);core.write(OUT/'RESULTS.json',result);core.write(OUT/'CANDIDATE_AUDIT.json',audit)
 with (OUT/'CANDIDATE_AUDIT.csv').open('w') as f:
  import csv
  keys=['task_id','node_type','candidate','selected','eligible','Q','C_tokens','L_seconds','score','actual_shadow_tokens','actual_shadow_latency_s','actual_shadow_node_accuracy','actual_status','score_margin_to_selected'];w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');w.writeheader();w.writerows(audit)
 text=['# Tool-aware v1：40题真实多步金融确认','',f"来源：MultiHiertt dev，UID哈希冻结40题，完整报告上下文、至少两步参考算术。未向模型发送答案、参考程序或标注证据。仅声明本DAG实验新题，不能证明整个工作区及预训练未见。",'',f"任务成功 {success}/40（{success/40:.1%}），平均质量 {success/40:.3f}；模型tokens {result['total_tokens']}；平均实测批任务端到端 {result['mean_end_to_end_batch_seconds']:.2f}s，包含模型加载、排队和live工具收尾。",f"Tool Node Accuracy（独立解释器核对已执行算术）={result['tool_node_accuracy']}，分母{len(toolchecks)}；{40-len(toolchecks)}题被表达式/前驱有效性检查拒绝或阻断。工具算对不等于模型选对数字或表达式。",f"Extraction accuracy（参考操作数召回诊断）={result['extraction_accuracy']:.1%}；Semantic accuracy（实际前驱下的最终数值等价代理）={result['semantic_accuracy']:.1%}；LLM Node Accuracy代理均值={llmacc:.1%}。这些是不同诊断定义，不是同一种通用节点准确率。",'', '| Node Type | #Planned nodes | Small | Medium | Large | R1 | Tool | Accuracy |','|---|---:|---:|---:|---:|---:|---:|---|']
 for nid,display,acc in [('extraction','Extraction',result['extraction_accuracy']),('semantic','Semantic reasoning',result['semantic_accuracy'])]:
  c=counts[nid];text.append(f"| {display} | 40 | {c['small']} | {c['medium']} | {c['large']} | {c['reasoning']} | 0 | {acc:.1%}（诊断定义见上） |")
 text+= [f"| Arithmetic | 40 | 0 | 0 | 0 | 0 | 40 | 已执行{len(toolchecks)}题，解释器核对100% |",'| Constraint check | 0 | 0 | 0 | 0 | 0 | 0 | N/A：此自然题图无采购预算约束 |',f"| Verification | 40 | 0 | 0 | 0 | 0 | 40 | 语法/范围契约；接受{len(toolchecks)}，拒绝/阻断{40-len(toolchecks)}，不是答案正确率 |",'', '## 候选模型诊断','', '| Model | Node | Delivered/Requested | Node diagnostic accuracy | Mean tokens | Mean latency s |','|---|---|---:|---:|---:|---:|']
 for d in diagnostics:
  if not d['available']:text.append('| small (Qwen2.5-3B) | unavailable weights/profile | 0/0 | N/A | N/A | N/A |');continue
  text.append(f"| {d['model']} | {d['node_type']} | {d['delivered']}/{d['requested']} | {d['accuracy_delivered']} | {d['mean_actual_tokens']} | {d['mean_actual_latency_s']} |")
 text+=['','候选Q/C/L、加权分数、选择、实际tokens/耗时和缺失原因逐节点保存于CANDIDATE_AUDIT.json/csv。旁路仅冻结的10题；语义节点统一使用实际路由抽取结果，因此不能当作各模型独立端到端效果。','', '## 路由解释与结论边界','', '- 沿用原候选池 medium/large/coder，公式 Q−0.05*C_tokens/1000−0.05*L_seconds/10。Small原3B检查点缺失且无本协议可比画像；R1只做旁路诊断，不悄悄加入候选池。','- Q仍为各模型全局均值，没有query条件；C/L只有长度缩放。因此短提示偏large，长提示的耗时惩罚可能令medium获选。这是长度触发的权衡，不是已验证的语义能力路由。','- R1画像来自远程服务，延迟与本地硬件不可直接当作纯模型能力差。tokens是资源用量，不等于跨模型货币成本。','- 本自然任务确认只执行Tool-aware，不存在同题Static/Repair对照，不能把旧采购15%/20%与本结果配对。受控三组比较在controlled目录。','- 不根据旁路结果重选模型，不调Router，不加Local Repair，不启动Dynamic DAG，不推GitHub。']
 (OUT/'REPORT.md').write_text('\n'.join(text)+'\n');core.write(OUT/'STATUS.json',dict(phase='COMPLETE',small_diagnostic='unavailable',next_experiment_started=False));print(json.dumps({k:v for k,v in result.items() if k!='shadow_diagnostics'}))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['live_tools','evaluate']);args=p.parse_args();globals()[args.action]()
