"""Replay artifact validation only: no model calls and no new experiment."""
import hashlib
import json
from pathlib import Path
import numpy as np
from . import core,repair

def main():
 p=repair.verify();out=repair.OUT;tasks=json.loads((out/'TASKS.json').read_text());plans=json.loads((out/'PLANS.json').read_text());nodes=core.lines(out/'NODES.jsonl');requests=core.lines(out/'REQUESTS.jsonl');responses=core.lines(out/'RESPONSES.jsonl');per=json.loads((out/'PER_TASK.json').read_text());result=json.loads((out/'RESULTS.json').read_text());tools=json.loads((out/'TOOL_ONLY.json').read_text())
 assert len(tasks)==len(per)==len(tools)==20
 records={(r['arm'],r['task_id'],r['node_id']):r for r in nodes};rq={r['request_id']:r for r in requests};rr={r['request_id']:r for r in responses}
 assert len(records)==len(nodes)==160
 assert len(rq)==len(requests)==len(rr)==len(responses)<=240 and rq.keys()==rr.keys()
 assert all(r['unix_time']>=p['created_unix'] for r in requests)
 assert all(hashlib.sha256(r['prompt'].encode()).hexdigest()==r['request_id'] for r in requests)
 for r in responses:
  assert r['status']=='delivered' and r['usage']['total_tokens']==r['usage']['prompt_tokens']+r['usage']['completion_tokens']
  assert r['provider_model']== 'Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8'
 logical={a:0 for a in repair.ARMS};tokens={a:0 for a in repair.ARMS};used=set()
 for task,plan,metric in zip(tasks,plans,per):
  tid=task['task_id'];assert tid==plan['task_id']==metric['task_id']
  for arm in repair.ARMS:
   state={};calls=0;total=0
   for layer in plan['layers']:
    for nid in layer:
     node=next(n for n in plan['nodes'] if n['id']==nid);record=records[arm,tid,nid];attempts=record['attempts']
     assert record['model']==node['model']=='large'
     assert len(attempts)<= (1 if arm=='static' else 2)
     if any(d not in state for d in node['deps']):
      assert record['status']=='blocked_dependency' and not attempts and record['parsed'] is None;continue
     text=core.prompt(task,node,state);key=hashlib.sha256(text.encode()).hexdigest()
     assert attempts[0]==dict(request_id=key,kind='initial') and rq[key]['prompt']==text
     first=repair.inspect_output(task,node,state,rr[key]);saved=record['initial_audit']
     assert all(first[k]==saved[k] for k in ['parsed','passed','error_fields'])
     need=arm=='local_repair' and not first['passed'];assert len(attempts)==1+int(need)
     chosen=first['parsed']
     if need:
      text=repair.feedback_prompt(text,rr[key].get('answer'),first['error_fields']);key=hashlib.sha256(text.encode()).hexdigest();assert attempts[1]==dict(request_id=key,kind='repair') and rq[key]['prompt']==text
      second=repair.inspect_output(task,node,state,rr[key]);assert all(second[k]==record['repair_audit'][k] for k in ['parsed','passed','error_fields'])
      chosen=second['parsed'] if second['passed'] else first['parsed'] if first['parsed'] is not None else second['parsed']
      assert record['repaired']==second['passed']
     assert record['parsed']==chosen
     if chosen is not None:state[nid]=chosen
     for a in attempts:used.add(a['request_id']);total+=rr[a['request_id']]['usage']['total_tokens'];calls+=1
   logical[arm]+=calls;tokens[arm]+=total;assert calls==metric['arms'][arm]['logical_calls'] and total==metric['arms'][arm]['tokens']
  # Independent final-task reference, not the online local checker implementation.
  x=task['input'];units=sum(x['departments'])-x['stock']+x['reserve'];eligible=[]
  for s in x['suppliers']:
   amount=units*(s['unit_cents']-s['discount_cents'])+s['freight_cents']+s['handling_cents']
   if units<=s['capacity'] and s['days']<=x['deadline_days'] and amount<=x['budget_cents']:eligible.append((amount,s['vendor']))
  amount,vendor=min(eligible) if eligible else (0,'NONE');expected={'vendor':vendor,'total_cents':amount};assert metric['expected']==expected
  for arm in repair.ARMS+['tool_only']:
   a=metric['arms'][arm]['answer'];quality=sum(a.get(k)==v for k,v in expected.items())/2 if a else 0
   assert metric['arms'][arm]['quality']==quality and metric['arms'][arm]['success']==(a==expected)
 assert used==rq.keys()
 assert logical['static']<=80 and logical['local_repair']<=160
 for arm in repair.ARMS:assert result['arms'][arm]['tokens']==tokens[arm] and result['arms'][arm]['logical_calls']==logical[arm]
 indices=np.random.default_rng(20260916).integers(0,20,(10000,20))
 for field in ['success','quality']:
  d=np.array([float(r['arms']['local_repair'][field])-float(r['arms']['static'][field]) for r in per]);v=result['paired_repair_minus_static'][field]
  assert v['delta']==float(d.mean()) and np.allclose(v['ci95'],np.quantile(d[indices].mean(axis=1),[.025,.975]))
 assert result['physical_tokens']==sum(r['usage']['total_tokens'] for r in responses)
 checks=['Pre-generation input/code freeze verified','20 fresh task inputs, 160 unique logical nodes, <=240 unique physical requests','Replay confirms initial prompts use only actual arm predecessors','Every repair triggered by failed local contract, <=1 per node, deterministic acceptance rule','All generated responses used; logical and physical cost budgets reconcile','Independent final integer reference matches both LLM arms and tool outputs','Paired task bootstrap reproduced']
 old=json.loads((core.OUT/'TASKS.json').read_text());assert not ({json.dumps(t['input'],sort_keys=True) for t in tasks}&{json.dumps(t['input'],sort_keys=True) for t in old})
 core.write(out/'VALIDATION.json',dict(passed=True,checks=checks,validator_sha256=core.sha(Path(__file__))))
 core.write(out/'ARTIFACT_MANIFEST.json',{f.name:core.sha(f) for f in out.iterdir() if f.is_file() and f.name not in ['ARTIFACT_MANIFEST.json','MODEL_SERVER.log','EXECUTION.log']})
 print(json.dumps(dict(passed=True,physical_requests=len(requests),logical_requests=logical)))
if __name__=='__main__':main()
