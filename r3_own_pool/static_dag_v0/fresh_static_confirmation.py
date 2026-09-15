"""Inference-only fresh holdout confirmation of the frozen dev Node Router."""
import argparse,fcntl,hashlib,json,math,os,re,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import numpy as np
from . import core,node_benchmark_build as build,node_benchmark_collect as collect
from . import node_router_compare as old,run as engine,tool_aware_v1 as v
from .fresh_static_prepare import OUT,DATA

POOL=['medium','large','coder']

def check_dev():
 d=json.loads((OUT/'DEV_FROZEN.json').read_text())
 assert core.sha(OUT/'DEV_MODELS.npz')==d['models_sha256']
 for p,h in d['bindings'].items():assert core.sha(p)==h, p
 return d

def nodes_for(t):
 ops=build.operand_values(t['program']);uid=t['uid'];nodes=[]
 for k,val in enumerate(ops[:2]):nodes.append(dict(node_id=f'{uid}:ex{k}',task_uid=uid,node_type='extraction',question=t['question'],program=t['program'],answer=t['answer'],gold_operand=val,shares_model_call=f'{uid}:extraction'))
 nodes.append(dict(node_id=f'{uid}:rs',task_uid=uid,node_type='reasoning',question=t['question'],program=t['program'],answer=t['answer'],gold_facts=dict(facts=[dict(value=val,evidence='gold') for val in ops])))
 for variant in (['pos','neg'] if ops else []):
  facts=[dict(value=val,evidence='gold') for val in ops]
  if variant=='neg':
   idx=int(build.uid_hash(uid,build.SEED+':n')[:8],16)%len(facts);facts[idx]['value']=facts[idx]['value']*3+7
  nodes.append(dict(node_id=f'{uid}:vf{variant}',task_uid=uid,node_type='verification',question=t['question'],program=t['program'],answer=t['answer'],gold_facts=dict(facts=facts),expect_accept=variant=='pos'))
 # Same natural transformation construction as original dev builder.
 env={};made=0
 def resolve(tok):
  if tok.startswith('#'):return env.get(int(tok[1:]))
  if re.fullmatch(r'-?\d+(\.\d+)?',tok):return float(tok)
  return None
 for si,(op,args) in enumerate(re.findall(r'(add|subtract|multiply|divide)\(([^()]*)\)',t['program'])):
  parts=[p.strip() for p in args.split(',')] if args.count(',')==1 else None
  if parts is None:break
  a,b=resolve(parts[0]),resolve(parts[1])
  if a is not None and b is not None:
   try:env[si]={'add':lambda:a+b,'subtract':lambda:a-b,'multiply':lambda:a*b,'divide':lambda:a/b}[op]()
   except ZeroDivisionError:break
  if op not in ['multiply','divide'] or made>=2:continue
  const=[p for p in parts if p in ['const_100','const_1000','const_1000000']]
  if not const:continue
  vt=[p for p in parts if p!=const[0]];x=resolve(vt[0]) if vt else None
  if x is None:continue
  scale={'const_100':100,'const_1000':1000,'const_1000000':1000000}[const[0]];unit={100:'percent',1000:'thousands',1000000:'millions'}[scale];gold=x*scale if op=='multiply' else x/scale
  instruction=f'Express the value {x:g} in {unit} by multiplying by {scale}.' if op=='multiply' else f'Convert the value {x:g} from {unit} by dividing by {scale}.'
  made+=1;nodes.append(dict(node_id=f'{uid}:tr{made}',task_uid=uid,node_type='transformation',question=t['question'],raw_value=x,direction=unit,instruction=instruction,gold_value=gold))
 return nodes

def freeze():
 check_dev()
 if (OUT/'PROTOCOL.json').exists():raise FileExistsError('Already frozen')
 from transformers import AutoTokenizer
 audit=json.loads((OUT/'EXPOSURE_AUDIT.json').read_text());assert not audit['skipped']
 for split,h in audit['source_hashes'].items():assert core.sha(DATA/(split+'.json'))==h
 used=set(audit['used_uids']);norm=lambda q:re.sub(r'\s+',' ',q).strip().lower();allrows=[r for s in ['train','dev','test'] for r in json.loads((DATA/(s+'.json')).read_text())]
 used_q={norm(r['qa']['question']) for r in allrows if r['uid'] in used};allow=set(audit['candidate_uids']['train'])
 tok=AutoTokenizer.from_pretrained(engine.MODELS['medium']['path'],local_files_only=True)
 selected=[];nodes=[];calls=[];excluded={'exposure_or_duplicate':0,'ineligible':0,'unconstructable':0,'over_context':0};seen=set();train=json.loads((DATA/'train.json').read_text())
 for r in sorted(train,key=lambda x:build.uid_hash(x['uid'],'20260915:fresh')):
  uid=r['uid'];qa=r['qa'];question=norm(qa['question'])
  if uid not in allow or question in used_q or question in seen:excluded['exposure_or_duplicate']+=1;continue
  prog=qa.get('program','')
  if qa.get('question_type')!='arithmetic' or prog.count('(')<2 or any(op not in build.ALLOWED_OPS for op in re.findall(r'([a-z_]+)\(',prog)) or not build.operand_values(prog):excluded['ineligible']+=1;continue
  try:answer=float(qa['answer'])
  except (ValueError,TypeError):excluded['ineligible']+=1;continue
  if not math.isfinite(answer):continue
  task=dict(uid=uid,question=qa['question'],program=prog,answer=answer,context=v.context(r));nn=nodes_for(task);cc=collect.build_calls(nn,{uid:task['context']})
  if {n['node_id'] for n in nn}!={nid for c in cc for nid in c['node_ids']}:excluded['unconstructable']+=1;continue
  sizes=[len(tok.apply_chat_template([dict(role='user',content=c['prompt'])],tokenize=True,add_generation_prompt=True)) for c in cc]
  if max(sizes)+512>8192:excluded['over_context']+=1;continue
  for c,size in zip(cc,sizes):c['preflight_input_tokens']=size
  selected.append(task);nodes.extend(nn);calls.extend(cc);seen.add(question)
  if len(selected)==100:break
 assert len(selected)==100,'Not enough audited eligible tasks'
 core.write(OUT/'TASKS.json',selected);core.write(OUT/'NODES.json',nodes);core.write(OUT/'CALLS.json',calls)
 # Matches original definitions on all previously built dev nodes, including exploratory transformations.
 devnodes=json.loads((old.OUT/'NODES.json').read_text());source_dev={r['uid']:r for r in json.loads((DATA/'dev.json').read_text())};rebuilt={}
 for uid in {n['task_uid'] for n in devnodes}:
  r=source_dev[uid];qa=r['qa'];t=dict(uid=uid,question=qa['question'],program=qa['program'],answer=float(qa['answer']))
  rebuilt.update({n['node_id']:n for n in nodes_for(t)})
 assert all(rebuilt[n['node_id']]==n for n in devnodes),'Node construction drift'
 bind=[OUT/x for x in ['DEV_FROZEN.json','DEV_MODELS.npz','ANALYSIS_PLAN.json','EXPOSURE_AUDIT.json','TASKS.json','NODES.json','CALLS.json']]+[Path(__file__),Path(collect.__file__),Path(build.__file__),Path(v.__file__),core.ROOT/'static_dag_v0/node_gap_audit_full.py']
 core.write(OUT/'PROTOCOL.json',dict(created_unix=time.time(),source='Audited unused MultiHiertt train, explicitly authorized by user as fresh holdout; not official test',tasks=100,nodes=len(nodes),counts={t:sum(n['node_type']==t for n in nodes) for t in old.TYPES},calls_per_model=len(calls),total_request_cap=3*len(calls),pool=POOL,retries=0,max_tokens=512,temperature=0,concurrency=4,seed=20260915,selection='UID SHA256 order salt20260915:fresh; audit unused UID and normalized-question exclusion; unchanged supported node construction; full prompt fits8192 with512 output; no outcomes used.',selection_exclusions=excluded,dev_construction_exact_match=True,source_labels='Only used for inherited conditional node inputs and held-out scoring; never features or fitting.',train_forbidden_on_fresh=True,conditional_benchmark=True,models='Same local checkpoints and serve configuration as dev',bindings={str(p):core.sha(p) for p in bind}))
 core.write(OUT/'STATUS.json',dict(phase='TASKS_FROZEN',calls_per_model=len(calls),fresh_generation_requests=0));print(json.dumps(dict(tasks=100,nodes=len(nodes),counts={t:sum(n['node_type']==t for n in nodes) for t in old.TYPES},calls_per_model=len(calls))))

def verify():
 d=check_dev();p=json.loads((OUT/'PROTOCOL.json').read_text())
 for path,h in p['bindings'].items():assert core.sha(path)==h,path
 return p

def encode_predict():
 verify()
 if (OUT/'PREDICTIONS_FROZEN.json').exists():raise RuntimeError('Already frozen predictions')
 from sentence_transformers import SentenceTransformer
 import torch
 with (core.ROOT/'collect/logs/local_gpu.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  tasks=json.loads((OUT/'TASKS.json').read_text());questions=sorted({t['question'] for t in tasks});model=SentenceTransformer(old.GTE)
  oldemb=np.load(old.OUT/'QUESTION_EMBEDDINGS.npz');anchors=oldemb['questions'][:3].tolist();a=model.encode(anchors,batch_size=8,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
  error=float(np.max(np.abs(a-oldemb['emb'][:3])));assert error<.001,'Encoder differs from dev cache'
  em=model.encode(questions,batch_size=8,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
  np.savez_compressed(OUT/'QUESTION_EMBEDDINGS.npz',questions=np.array(questions),emb=em)
  del model;torch.cuda.empty_cache()
 emb={q:e for q,e in zip(questions,em)};nodes=json.loads((OUT/'NODES.json').read_text());weights=np.load(OUT/'DEV_MODELS.npz');pred=[]
 for n in nodes:
  xq=emb[n['question']];xn=np.concatenate([xq,[float(n['node_type']==t) for t in old.TYPES],[np.log1p(len(n['question']))]])
  result=dict(node_id=n['node_id'],task_uid=n['task_uid'],node_type=n['node_type'],arms={},candidates={})
  for arm,x in [('QueryRouter',xq),('NodeRouter',xn)]:
   q=weights[arm+'_coef']@x+weights[arm+'_intercept'];u=old.utility(q,weights['mean_C'],weights['mean_L']);name='FrozenNodeRouter' if arm=='NodeRouter' else arm;result['arms'][name]=POOL[int(np.argmax(u))]
   result['candidates'][name]={s:dict(Q=float(q[j]),C=float(weights['mean_C'][j]),L=float(weights['mean_L'][j]),utility=float(u[j])) for j,s in enumerate(POOL)}
  result['arms']['AlwaysLarge']='large';result['arms']['StaticCapability']=POOL[int(np.argmax(old.utility(weights['mean_Q'],weights['mean_C'],weights['mean_L'])))];pred.append(result)
 core.write(OUT/'PREDICTIONS.json',pred);core.write(OUT/'PREDICTIONS_FROZEN.json',dict(created_unix=time.time(),anchor_max_abs_error=error,encoder=old.GTE,models_sha256=core.sha(OUT/'DEV_MODELS.npz'),embeddings_sha256=core.sha(OUT/'QUESTION_EMBEDDINGS.npz'),predictions_sha256=core.sha(OUT/'PREDICTIONS.json'),protocol_sha256=core.sha(OUT/'PROTOCOL.json')))
 core.write(OUT/'STATUS.json',dict(phase='PREDICTIONS_FROZEN',fresh_generation_requests=0));print('Frozen fresh predictions; encoder anchor error',error)

def collect_slot(slot):
 p=verify();f=json.loads((OUT/'PREDICTIONS_FROZEN.json').read_text());assert f['predictions_sha256']==core.sha(OUT/'PREDICTIONS.json')
 ledger=OUT/(slot+'_REQUESTS.jsonl');file=OUT/(slot+'_RESPONSES.jsonl')
 if ledger.exists():raise RuntimeError('No automatic generation replay')
 calls=json.loads((OUT/'CALLS.json').read_text());assert len(calls)==p['calls_per_model'];engine.OUT=OUT
 with (core.ROOT/'collect/logs/local_gpu.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);proc=log=None;start=time.time()
  try:
   proc,log,startup=engine.start_model(slot);done=0;missing=0
   with ThreadPoolExecutor(max_workers=4) as pool,ledger.open('x') as intents,file.open('x') as out:
    futures={}
    for c in calls:
     intents.write(json.dumps(dict(call_key=c['call_key'],model=slot,prompt_sha256=hashlib.sha256(c['prompt'].encode()).hexdigest(),unix_time=time.time()))+'\n');intents.flush();futures[pool.submit(engine.call_model,slot,c['prompt'])]=c
    os.fsync(intents.fileno())
    for future in as_completed(futures):
     c=futures[future];raw=future.result();row=dict(**raw,call_key=c['call_key'],task_uid=c['task_uid'],node_type=c['node_type'],node_ids=c['node_ids'],model=slot);out.write(json.dumps(row,ensure_ascii=False)+'\n');out.flush();done+=1;missing+=int(raw['status']!='delivered' or not raw.get('answer') or not raw.get('usage'))
     if done%20==0:core.write(OUT/(slot+'_STATUS.json'),dict(phase='COLLECTING',done=done,total=len(calls),missing=missing))
    os.fsync(out.fileno())
   core.write(OUT/(slot+'_STATUS.json'),dict(phase='COMPLETE',done=done,total=len(calls),missing=missing,startup_seconds=startup,total_seconds=time.time()-start));print(slot,'complete',done,'missing',missing)
  finally:
   if proc is not None:engine.stop_model(proc,log)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('stage',choices=['freeze','encode_predict']+POOL);a=p.parse_args()
 if a.stage in POOL:collect_slot(a.stage)
 else:globals()[a.stage]()
