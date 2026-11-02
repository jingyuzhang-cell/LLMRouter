"""Single development batch. Default preflight is read-only; live requires receipts.
No new scheduling algorithm. Reuses frozen choose(), Execution, citation validator.
"""
import argparse, ast, copy, hashlib, json, os, sys, time, re
from dataclasses import asdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,'/root/.worktrees/codex-dd-v51-six-arm/dynamic_pi_binding_20261030')
import binding as B
from paid_transport import Transport, Guard, units, write
import reference_policy
from collab_scheduler_v1.typed_dag_v1.protocol import Output
SOURCE=Path('/root/.worktrees/planner/r3_own_pool/planner_execution_workpackage_20261028_v1/window2_core.py')
ns={'bridge':B.bridge,'re':re}
tree=ast.parse(SOURCE.read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='make_validator')
retrieve=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='retrieve_chunks')
exec(compile(ast.Module(body=[node,retrieve],type_ignores=[]),str(SOURCE),'exec'),ns)

CONTRACT_HINTS={
 'capital.extract.v1':{'claims':[{'id':'<node_id>:c1','statement':'原文支持的事实','citations':['source:page:start']}]},
 'capital.timeline.v1':{'findings':[{'id':'<node_id>:f1','statement':'时间关系','status':'CONFIRMED or UNKNOWN','citations':['上游claimID']}]},
 'capital.relations.v1':{'findings':[{'id':'<node_id>:f1','statement':'事实关系','status':'CONFIRMED or UNKNOWN','citations':['上游claimID']}]},
 'capital.verify.v1':{'findings':[{'id':'<node_id>:v1','statement':'证据核验结论','status':'CONFIRMED or UNKNOWN or CONTRADICTED','citations':['上游claimID或source:page:start']}]},
 'capital.report.v1':{'report':{'text':'完整回答调查问题','unknown':['仍不能确认的事项'],'citations':['上游findingID']}}}


def load(role):
 task=json.loads((ROOT/role/'TASK.json').read_text());g=B.bridge.Graph.from_json((ROOT/role/'DAG.json').read_text());catalog={}
 for doc in task['source_index']:
  for page in sorted((ROOT/role/'sources'/doc['id']).glob('p*.txt')):
   text=page.read_text();sha=hashlib.sha256(text.encode()).hexdigest()
   for start in range(0,len(text),768):
    cid=f'{doc["id"]}:{int(page.stem[1:])}:{start}'
    catalog[cid]=dict(id=cid,source=doc['id'],page=int(page.stem[1:]),start=start,end=min(start+768,len(text)),page_sha256=sha,text=text[start:start+768])
 return task,g,catalog


def preflight():
 c=json.loads((ROOT/'EXPERIMENT_CONFIG.json').read_text());issues=[]
 frozen=json.loads((ROOT/'RUNNER_LOCK.json').read_text())
 for rel,sha in frozen['files'].items():
  if not (ROOT/rel).is_file() or hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()!=sha:issues.append('CHANGED:'+rel)
 for src,sha in frozen['dependencies'].items():
  if not Path(src).is_file() or hashlib.sha256(Path(src).read_bytes()).hexdigest()!=sha:issues.append('DEPENDENCY_CHANGED:'+src)
 checks={}
 for name in ('AUTHORIZATION.json','REFERENCE_DECISIONS.json'):
  path=ROOT/name
  if not path.exists():issues.append('MISSING:'+name);continue
  checks[name]=json.loads(path.read_text())
 a=checks.get('AUTHORIZATION.json',{})
 if not a.get('approved_by') or not a.get('authorization_source') or not a.get('date') or a.get('approved') is not True or a.get('lock_sha256')!=hashlib.sha256((ROOT/'RUNNER_LOCK.json').read_bytes()).hexdigest() or a.get('max_requests')!=40 or a.get('estimate_stop_CNY')!=1 or a.get('estimate_stop_USD')!=.5 or not a.get('accept_non_hard_cash_cap') or not a.get('accept_unpinned_deepseek_version') or not a.get('accept_token_reservation_uncertainty') or not a.get('account_configuration_verified'):
  issues.append('NO_MATCHING_BATCH_AUTHORIZATION')
 ref=checks.get('REFERENCE_DECISIONS.json',{})
 try:reference_policy.validate(ROOT,ref)
 except ValueError as exc:issues.append(str(exc))
 for env in ('DYNAMIC_PI_QWEN_KEY','DYNAMIC_PI_DEEPSEEK_KEY'):
  if not os.environ.get(env):issues.append('ACCOUNT_KEY_NOT_SET:'+env)
 return c,issues


def caps(n):return dict(requests=n,input_tokens=n*16384,output_tokens=n*3072,total_tokens=n*19456,micro_cny=1000000,micro_usd=500000)


def execute(config,out,*,send=None):
 """Internal offline send injection never enters command-line live flow."""
 out=Path(out);out.mkdir(exist_ok=False,parents=True)
 write(out/'RUN_CONTEXT.json',dict(config=config,origin='OFFLINE_FIXTURE' if send else 'LIVE_DEVELOPMENT',lock_sha256=hashlib.sha256((ROOT/'RUNNER_LOCK.json').read_bytes()).hexdigest(),reference_decisions_sha256=hashlib.sha256((ROOT/'REFERENCE_DECISIONS.json').read_bytes()).hexdigest() if (ROOT/'REFERENCE_DECISIONS.json').exists() else None))
 if (ROOT/'REFERENCE_DECISIONS.json').exists():write(out/'REFERENCE_SCOPE.json',json.loads((ROOT/'REFERENCE_DECISIONS.json').read_text()))
 models=[m['request_model'] for m in config['models']];specs={m['request_model']:m for m in config['models']}
 cells={f'cal_{i}':caps(5) for i in range(2)}
 for i in range(1,4):
  cells[f'P{i}_prefix']=caps(2)
  for arm in ('Static-Pi','Dynamic-Pi'):cells[f'P{i}_{arm}']=caps(4)
 guard=Guard(out/'ledger.sqlite',{'batch_id':out.name,'global':caps(40),'models':{m:caps(35) for m in models},'cells':cells})
 transport=Transport(config,guard,out/'requests',enabled=send is None,send=send)
 starts=time.monotonic();profiles={};records=[];pairs=[]
 def stopped():return guard.snapshot()['stopped'] or time.monotonic()-starts>=5400
 def run(role,graph,task,pi,cell,*,cache=None,deadline=600):
  _,_,catalog=load(role);base_validator=ns['make_validator'](catalog)
  def validator(n,inputs,output):
   # Resolve cross-branch ambiguity: model IDs must be globally namespaced.
   for port in ('claims','findings'):
    if isinstance(output,dict) and isinstance(output.get(port),list):
     if any(not isinstance(it,dict) or not isinstance(it.get('id'),str) or not it['id'].startswith(n.node_id+':') for it in output[port]):
      return dict(K=False,E=False,Q=None,safe_to_consume=False)
   try:return base_validator(n,inputs,output)
   except (TypeError,KeyError,ValueError):return dict(K=False,E=False,Q=None,safe_to_consume=False)
  def handler(n,m,data,timeout):
   if stopped():raise RuntimeError('BATCH_STOP')
   if n.output_contract=='capital.retrieve.v1':
    allowed={'retrieve_notice':['NINGBO_NOTICE'],'retrieve_result':['NINGBO_RESULT'],'retrieve_1':['SUPCON_CAPITAL','SUPCON_ANNUAL']}[n.node_id]
    evidence=copy.deepcopy(ns['retrieve_chunks'](catalog,data['question'],allowed,k=6,max_chars=6000))
    return {'output':{'evidence':evidence},'usage':{'tokens':0,'cash':{'CNY':0,'USD':0}}}
   prompt=('根据给定输入完成此节点，不能读取其他资料或猜测缺失事实。只输出一个JSON对象，不使用Markdown。'
           '引用必须指向给定片段或上游项目ID，不计算字符偏移。每个新项目id必须以本node_id加冒号开头。'
           '事实不确定时明确UNKNOWN，不把计划写成已完成。Schema示例中的说明不是事实。\n'+
           json.dumps(dict(node_id=n.node_id,contract=n.output_contract,schema=CONTRACT_HINTS[n.output_contract],input=data),ensure_ascii=False))
   return transport.call(cell,n.node_id,m,prompt,timeout)
  resources=dict(slots={m:1 for m in models},global_slots=2,tokens=19456*6,cash={'CNY':1,'USD':.5},deadline_s=max(.001,min(deadline,5400-(time.monotonic()-starts))),reservation={})
  for n in graph.nodes:
   for m in models:
    u=units(16384,3072,specs[m]) if n.output_contract!='capital.retrieve.v1' else dict(total_tokens=0,micro_cny=0,micro_usd=0)
    resources['reservation'][n.node_id,m]={'tokens':u['total_tokens'],'cash':{'CNY':u['micro_cny']/1e6,'USD':u['micro_usd']/1e6}}
  result=B.Execution(graph,task,pi,{c:handler for c in B.bridge.CONTRACTS},validator,resources,cache=cache,origin='OFFLINE_FIXTURE' if send else 'LIVE_DEVELOPMENT_EXPLORATION').execute()
  write(out/(cell+'.RAW.json'),result)
  if result['system_stop']:guard.halt('RUNTIME_SYSTEM_STOP')
  return result
 try:
  task,g,_=load('calibration')
  for j,m in enumerate(models):
   if stopped():break
   raw=run('calibration',g,task,{n.node_id:m for n in g.nodes},f'cal_{j}')
   for tr in raw['trace']:
    contract=next(n.output_contract for n in g.nodes if n.node_id==tr['node'])
    if contract=='capital.retrieve.v1' or 'wall_s' not in tr:continue
    profiles[contract,m]=dict(latency=tr['wall_s'],Q=None,E_grounding=tr['verdict'].get('E'),K=tr['verdict'].get('K'),committed=tr['commit'],source=f'cal_{j}.RAW.json',usage=tr['usage'],reliability=None)
  write(out/'CALIBRATION.json',{f'{c}|{m}':p for (c,m),p in profiles.items()})
  task,g,_=load('evaluation');llm=[n for n in g.nodes if n.output_contract!='capital.retrieve.v1']
  usable=[m for m in models if all((n.output_contract,m) in profiles for n in llm)]
  if len(usable)!=2:
   pairs=[dict(pair_id=f'P{i}',status='PROFILE_INCOMPLETE_REFUSAL',arms=[dict(arm=a,Q=None,status='REFUSED_NO_PROFILE',task_complete=False) for a in ('Static-Pi','Dynamic-Pi')]) for i in range(1,4)]
  else:
   ep={}
   for n in llm:
    for m in models:
     u=units(16384,3072,specs[m]);ep[n.node_id,m]=B.engine.Profile(profiles[n.output_contract,m]['latency'],19456,u['micro_cny'],u['micro_usd'],quality=None,reliability=None,evidence='ISOLATED_CALIBRATION_CONTRACT_TRANSFER')
   nodes=[B.engine.Node(n.node_id,tuple(d for d in n.dependencies if d in {x.node_id for x in llm}),tuple(models)) for n in llm]
   limits=B.engine.Limits({m:1 for m in models},600,180,6,6*19456,1000000,500000)
   t=time.monotonic();initial,audit=B.engine.choose(nodes,ep,limits,{})
   initial_planning=time.monotonic()-t
   write(out/'INITIAL_DECISION.json',dict(pi=initial,audit=audit,planning_s=initial_planning))
   for i,order in enumerate((('Static-Pi','Dynamic-Pi'),('Dynamic-Pi','Static-Pi'),('Static-Pi','Dynamic-Pi')),1):
    row=dict(pair_id=f'P{i}',arms=[]);pairs.append(row)
    if stopped() or initial is None:
     row['status']='NOT_STARTED_SYSTEM_STOP' if stopped() else 'INITIAL_REFUSED'
     row['arms']=[dict(arm=a,status=row['status'],Q=None,task_complete=False) for a in order];continue
    pi={n.node_id:initial.get(n.node_id,models[0]) for n in g.nodes}
    prefix=copy.deepcopy(g);prefix.nodes=[n for n in prefix.nodes if n.node_id in ('retrieve_notice','retrieve_result','extract_notice','extract_result')]
    prefix.final_outputs=[Output('prefix_notice','extract_notice','claims'),Output('prefix_result','extract_result','claims')]
    ptask=copy.deepcopy(task);ptask['required_outputs']={'prefix_notice':'claims','prefix_result':'claims'}
    pre=run('evaluation',prefix,ptask,{n.node_id:pi[n.node_id] for n in prefix.nodes},f'P{i}_prefix')
    row['prefix_wall_s']=pre['wall_s'];row['prefix_cost']=pre['cash_estimate_or_pending_reservation']
    if stopped() or any(v not in ('COMMITTED','REUSED') for v in pre['states'].values()):
     row['status']='PREFIX_FAILED';row['arms']=[dict(arm=a,status='PREFIX_FAILED',Q=None,task_complete=False) for a in order];continue
    scale={}
    for tr in pre['trace']:
     if tr['node'].startswith('extract'):
      m=tr['model'];ratio=tr['wall_s']/max(profiles['capital.extract.v1',m]['latency'],1e-9)
      scale[m]=max(scale.get(m,0),ratio)
    healthy=set(pre['cache']);remaining=[n for n in llm if n.node_id not in healthy]
    remtime=max(0,600-initial_planning-pre['wall_s'])
    remcash={c:max(0,cap-pre['cash_estimate_or_pending_reservation'][c]) for c,cap in [('CNY',1),('USD',.5)]}
    lim=B.engine.Limits({m:1 for m in models},remtime,180,4,4*19456,int(remcash['CNY']*1e6),int(remcash['USD']*1e6))
    snap=B.snapshot(g,task,{n.node_id:pre['states'].get(n.node_id,'PENDING') for n in g.nodes},pre['cache'],pi,{'latency_scale':scale},lim,B.digest(task['source_index']))
    B.restore(snap);write(out/f'P{i}.SNAPSHOT.json',snap)
    common=B.digest(dict(snapshot=snap['sha256'],profiles={f'{n}:{m}':asdict(p) for (n,m),p in ep.items()},limits=asdict(lim)))
    nd=[B.engine.Node(n.node_id,tuple(d for d in n.dependencies if d not in healthy),tuple(models)) for n in remaining]
    row['status']='PAIR_ATTEMPTED'
    for arm in order:
     ar=dict(arm=arm,snapshot_sha256=snap['sha256'],decision_inputs_sha256=common,Q=None,E=None,K=None,actual_cash_settlement=None);row['arms'].append(ar)
     if stopped():ar['status']='NOT_STARTED_SYSTEM_STOP';continue
     t=time.monotonic();chosen,aud=B.engine.choose(nd,ep,lim,copy.deepcopy(scale),fixed={n.node_id:pi[n.node_id] for n in remaining} if arm=='Static-Pi' else None)
     planning=time.monotonic()-t;ar.update(decision=aud,pi=chosen,planning_s=planning)
     if chosen is None or remtime<=planning:ar.update(status='REFUSED',task_complete=False);continue
     arm_pi=dict(pi);arm_pi.update(chosen)
     raw=run('evaluation',g,task,arm_pi,f'P{i}_{arm}',cache=copy.deepcopy(pre['cache']),deadline=remtime-planning)
     ar.update(status='SYSTEM_STOP' if raw['system_stop'] else 'EXECUTED_AWAITING_BLIND_SCORE',task_complete=bool(raw['outputs']) and all(s in ('COMMITTED','REUSED') for s in raw['states'].values()),full_output_file=f'P{i}_{arm}.RAW.json',wall_s_components=initial_planning+pre['wall_s']+planning+raw['wall_s'],continuation_cost=raw['cash_estimate_or_pending_reservation'],scoring_status='PENDING_OUTPUT_REVIEW_WITH_DECLARED_PROVENANCE')
     ar['deadline_met']=ar['task_complete'] and ar['wall_s_components']<=600
 finally:
  for i in range(1,4):
   if not any(p['pair_id']==f'P{i}' for p in pairs):pairs.append(dict(pair_id=f'P{i}',status='NOT_STARTED_SYSTEM_STOP',arms=[dict(arm=a,Q=None,status='NOT_STARTED_SYSTEM_STOP') for a in ('Static-Pi','Dynamic-Pi')]))
  write(out/'LEDGER.json',guard.snapshot())
  write(out/'RESULT.json',dict(pairs=pairs,planned_arms=6,independent_events=1,terminal_quality_status='PENDING_OUTPUT_REVIEW_WITH_DECLARED_PROVENANCE',actual_cash_settlement=None,origin='OFFLINE_FIXTURE' if send else 'LIVE_DEVELOPMENT',algorithm_benefit='NOT_YET_IDENTIFIED',batch_wall_s=time.monotonic()-starts))
 return pairs


def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--output');a=p.parse_args()
 config,issues=preflight()
 if not a.execute:print(json.dumps({'status':'HOLD' if issues else 'READY_FOR_AUTHORIZED_EXECUTION','issues':issues,'model_calls':0},ensure_ascii=False,indent=2));return
 if issues:raise SystemExit('HOLD: '+'; '.join(issues))
 if not a.output:raise SystemExit('--output required')
 # One physical paid run per frozen package, including abnormal termination.
 with (ROOT/'RUN_ONCE.lock').open('x') as f:f.write('authorized dispatch claimed\n')
 execute(config,a.output)

if __name__=='__main__':main()
