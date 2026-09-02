#!/usr/bin/env python3
"""Outcome-blind split and balanced E4.0-B exploration assignment."""
import hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent; OUT=ROOT/'phase_e4_0'; MANIFEST=OUT/'E4_0_DAG_MANIFEST.jsonl'; RESERVED=ROOT/'c10_prep/C10_REMAINING_60.jsonl'; PROTOCOL=OUT/'E4_0_B_PROTOCOL.json'
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash'); NODES=('N1','N2','N3','N4'); SEED='E4.0-B0|20260902|'
def rows(p): return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
manifest=rows(MANIFEST); reserved={x['task_id'] for x in rows(RESERVED)}; assert len(manifest)==60 and not {x['task_id'] for x in manifest}&reserved
ranked=sorted(manifest,key=lambda x:hashlib.sha256((SEED+x['task_id']).encode()).hexdigest()); train=ranked[:40]; holdout=ranked[40:]
split={'version':'E4.0-B0-split-v1','seed':SEED,'method':'SHA256(seed+task_id), ascending','exploration_train_task_ids':[x['task_id'] for x in train],'internal_holdout_task_ids':[x['task_id'] for x in holdout],'counts':{'exploration_train':40,'internal_holdout':20},'outcome_inputs_used':False,'reserved_holdout_accessed':False}
(OUT/'E4_0_B_SPLIT.json').write_text(json.dumps(split,ensure_ascii=False,indent=2)+'\n')
plans=[]
for task in train:
 perms={}
 for node in NODES:
  seed=int(hashlib.sha256(f"E4.0-B1|20260902|{task['task_id']}|{node}".encode()).hexdigest()[:16],16); rng=np.random.default_rng(seed); perms[node]=list(rng.permutation(MODELS))
 for trajectory in range(5):
  assignment={node:perms[node][trajectory] for node in NODES}; priority_seed=hashlib.sha256(f"E4.0-B-ready-priority|{task['task_id']}|{trajectory}".encode()).hexdigest()
  plans.append({'task_id':task['task_id'],'trajectory_id':f"{task['task_id']}:T{trajectory+1}",'assignment':assignment,'behavior_probability':0.2,'action_depends_on_state':False,'randomization_seed':f"E4.0-B1|20260902|{task['task_id']}",'ready_queue_priority_seed':priority_seed})
plan_path=OUT/'E4_0_B_EXPLORATION_PLAN.jsonl'; plan_path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in plans))
report={'status':'E4_0_B_READY_FOR_EXPLORATION','train_tasks':40,'internal_holdout_tasks':20,'trajectories':len(plans),'planned_node_calls':len(plans)*4,'balanced_checks':{},'reserved_holdout_accessed':False,'external_api_calls':0}
for node in NODES:
 counts={m:0 for m in MODELS}
 for p in plans: counts[p['assignment'][node]]+=1
 report['balanced_checks'][node]={'global_counts':counts,'each_task_uses_all_models_once':all(sorted(p['assignment'][node] for p in plans if p['task_id']==t['task_id'])==sorted(MODELS) for t in train)}
assert all(x['each_task_uses_all_models_once'] for x in report['balanced_checks'].values())
report.update({'protocol_sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),'split_sha256':hashlib.sha256((OUT/'E4_0_B_SPLIT.json').read_bytes()).hexdigest(),'plan_sha256':hashlib.sha256(plan_path.read_bytes()).hexdigest()})
(OUT/'E4_0_B_PREFLIGHT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
