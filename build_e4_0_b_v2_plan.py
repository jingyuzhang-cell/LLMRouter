#!/usr/bin/env python3
"""Build outcome-blind four-model E4.0-B v2 with exact transition balance."""
import hashlib,json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parent; OLD=ROOT/'phase_e4_0'; OUT=ROOT/'phase_e4_0_v2'; OUT.mkdir(exist_ok=True)
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo'); NODES=('N1','N2','N3','N4')
split=json.loads((OLD/'E4_0_B_SPLIT.json').read_text()); task_ids=split['exploration_train_task_ids']; assert len(task_ids)==40
v2split={**split,'version':'E4.0-B-v2-four-model-split-v1','parent_split':'phase_e4_0/E4_0_B_SPLIT.json','task_ids_unchanged':True}
(OUT/'E4_0_B_V2_SPLIT.json').write_text(json.dumps(v2split,ensure_ascii=False,indent=2)+'\n')
plans=[]
for task_rank,task_id in enumerate(task_ids):
 shifts=(task_rank%4,task_rank%4,(task_rank*3)%4)
 for trajectory in range(4):
  indices=[trajectory]
  for shift in shifts:indices.append((indices[-1]+shift)%4)
  assignment={node:MODELS[indices[i]] for i,node in enumerate(NODES)}
  plans.append({'task_id':task_id,'trajectory_id':f'{task_id}:V2T{trajectory+1}','assignment':assignment,'behavior_probability':.25,'action_depends_on_state':False,'randomization_seed':f'E4.0-B-v2|20260902|{task_id}','ready_queue_priority_seed':hashlib.sha256(f'E4.0-B-v2-ready|{task_id}|{trajectory}'.encode()).hexdigest()})
path=OUT/'E4_0_B_V2_EXPLORATION_PLAN.jsonl'; path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in plans))
node_counts={n:Counter(p['assignment'][n] for p in plans) for n in NODES}; transitions={}
for a,b in zip(NODES,NODES[1:]):transitions[f'{a}->{b}']=Counter(f"{p['assignment'][a]}->{p['assignment'][b]}" for p in plans)
assert len(plans)==160 and all(set(c.values())=={40} for c in node_counts.values())
assert all(len(c)==16 and set(c.values())=={10} for c in transitions.values())
report={'status':'READY_FOR_LONG_CONTEXT_PREFLIGHT','tasks':40,'trajectories':160,'expected_outcomes':640,'behavior_probability':.25,'node_model_counts':{n:dict(c) for n,c in node_counts.items()},'transition_counts':{k:dict(v) for k,v in transitions.items()},'each_task_node_uses_every_model_once':True,'external_api_calls':0,'semantic_outcomes_accessed':False,'plan_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'split_sha256':hashlib.sha256((OUT/'E4_0_B_V2_SPLIT.json').read_bytes()).hexdigest()}
(OUT/'E4_0_B_V2_PLAN_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
