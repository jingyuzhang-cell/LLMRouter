"""Train fixed OOF request-only policies and freeze real-execution assignments."""
import hashlib,json,sys,time
from collections import defaultdict
from pathlib import Path
ROOT=Path('/root');sys.path.insert(0,str(ROOT));OUT=ROOT/'phase_e5_unified'
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold
from threadpoolctl import threadpool_limits
from phase_e5_unified.common import MODELS,NODES,WEIGHTS,components,vector
from phase_e5_unified.execute import rows,atomic

def build_data():
 tasks={r['task_id']:r for r in rows(OUT/'DEVELOPMENT_TASKS.jsonl')}
 whole={r['key']:r for r in rows(OUT/'WHOLE_QUERY_RECORDS.jsonl')}
 labels=rows(OUT/'WHOLE_QUERY_LABELS.jsonl')
 assert len(whole)==len(labels)==160 and len({r['key'] for r in labels})==160
 assert all(r['Q'] is not None for r in labels),'Missing whole-query labels'
 data=[]
 for lab in labels:
  r=whole[lab['key']]
  data.append({'task_id':r['task_id'],'domain':'whole','node':'N4','model':r['model'],'components':components(lab['Q'],r['cost_usd'],r['latency_ms'],lab['R']).tolist()})
 # Actual observed exploration returns; no causal-node-value claim and no sequence splicing.
 labels={r['trajectory_id']:r for r in rows(ROOT/'phase_e4_1/E4_PHASE_A_FINAL_LABELS.jsonl')}
 rtg=rows(ROOT/'phase_e4_1/E4_PHASE_C_RTG.jsonl')
 plans=rows(ROOT/'phase_e4_0_v2/E4_0_B_V2_EXPLORATION_PLAN.jsonl')
 events=defaultdict(list)
 for r in rows(ROOT/'phase_e4_0_v2/E4_0_B_V2_EXPLORATION_EVENTS.jsonl'):events[r['trajectory_id']].append(r)
 assert len(labels)==160 and len(rtg)==640
 for p in plans:
  lab=labels[p['trajectory_id']]; assert lab['Q_delivered'] is not None
  ev=events[p['trajectory_id']]
  c=sum(float(r.get('cost_usd') or 0) for r in ev)
  t=sum(float(r.get('provider_latency_ms') or 0)+float(r.get('retry_backoff_ms') or 0) for r in ev)
  y=components(lab['Q_delivered'],c,t,lab['workflow_valid']).tolist()
  for n in NODES:data.append({'task_id':p['task_id'],'domain':'dag','node':n,'model':p['assignment'][n],'components':y})
 return tasks,data

def main():
 tasks,data=build_data();ids=sorted(tasks);groups=np.array([tasks[t]['leakage_group_id'] for t in ids]);fields=sorted(tasks[ids[0]]['observable_features'])
 assert all(sorted(t['observable_features'])==fields for t in tasks.values())
 pars=json.loads((OUT/'EXECUTION_PROTOCOL.json').read_text())['training']['parameters']
 assignments={};fold_manifest=[]
 with threadpool_limits(limits=1):
  for fold,(tr,te) in enumerate(GroupKFold(5).split(ids,groups=groups)):
   train={ids[i] for i in tr};test=[ids[i] for i in te]
   assert not set(groups[tr])&set(groups[te])
   fold_manifest.append({'fold':fold,'train_task_ids':sorted(train),'test_task_ids':test})
   for tid in test:
    for obj in WEIGHTS:assignments[tid,obj]={'task_id':tid,'objective':obj,'fold':fold,'Static':{},'Dynamic':{},'DAG':{},'routing_overhead_ms':{'whole':0.,'dag':0.}}
   for domain,node in [('whole','N4')]+[('dag',n) for n in NODES]:
    samples=[r for r in data if r['domain']==domain and r['node']==node and r['task_id'] in train]
    X=np.array([vector(tasks[r['task_id']],r['model'],node,fields) for r in samples]);Y=np.array([r['components'] for r in samples])
    XX=np.array([vector(tasks[t],m,node,fields) for t in test for m in MODELS])
    fitted=[HistGradientBoostingRegressor(**pars).fit(X,Y[:,c]) for c in range(4)]
    predictions=[];overheads=[]
    for i,tid in enumerate(test):
     started=time.perf_counter()
     xx=np.array([vector(tasks[tid],m,node,fields) for m in MODELS])
     predictions.append(np.clip(np.stack([m.predict(xx) for m in fitted],axis=1),0,1))
     overheads.append((time.perf_counter()-started)*1000)
    predictions=np.array(predictions)
    for obj,weights in WEIGHTS.items():
     choices=(predictions@np.array(weights)).argmax(axis=1)
     if domain=='whole':
      scores=[np.mean([np.dot(r['components'],weights) for r in samples if r['model']==m]) for m in MODELS]
      static=MODELS[int(np.argmax(scores))]
     for i,tid in enumerate(test):
      a=assignments[tid,obj]
      a['routing_overhead_ms'][domain]+=overheads[i]
      if domain=='whole':a['Static']={'model':static};a['Dynamic']={'model':MODELS[int(choices[i])]}
      else:a['DAG'][node]=MODELS[int(choices[i])]
   print(json.dumps({'fold_complete':fold}),flush=True)
 manifest=[]
 for (tid,obj),a in sorted(assignments.items()):
  for regime in ('Static','Dynamic','DAG'):
   sequence=a[regime] if regime=='DAG' else {'N4':a[regime]['model']}
   canonical=json.dumps({'task_id':tid,'sequence':sequence,'prompt_family':'dag' if regime=='DAG' else 'whole'},sort_keys=True)
   manifest.append({'task_id':tid,'objective':obj,'regime':regime,'fold':a['fold'],'assignment':sequence,'execution_key':hashlib.sha256(canonical.encode()).hexdigest()[:24],'routing_overhead_ms':0. if regime=='Static' else a['routing_overhead_ms']['dag' if regime=='DAG' else 'whole']})
 inputs=['WHOLE_QUERY_RECORDS.jsonl','WHOLE_QUERY_LABELS.jsonl','EXECUTION_PROTOCOL.json','train_policies.py']
 atomic(OUT/'POLICY_BANK_FROZEN.json',{'status':'FROZEN_OOF_DEVELOPMENT_POLICIES','methods':['Static','Dynamic','DAG_RequestOnly'],'no_state_features':True,'no_OPE_policy_value_claim':True,'folds':fold_manifest,'assignments':list(assignments.values()),'input_sha256':{p:hashlib.sha256((OUT/p).read_bytes()).hexdigest() for p in inputs},'DAG_training_limitation':'Exploration actions have coupled upstream/downstream assignments; node predictors are associational. Actual policy execution is the evaluation.'})
 (OUT/'PAIRED_EXECUTION_MANIFEST.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in manifest))
 atomic(OUT/'POLICY_TRAINING_STATUS.json',{'status':'COMPLETE','policy_task_objective_regime_rows':len(manifest),'unique_executions':len({r['execution_key'] for r in manifest}),'unique_whole':len({r['execution_key'] for r in manifest if r['regime']!='DAG'}),'unique_dag':len({r['execution_key'] for r in manifest if r['regime']=='DAG'}),'further_api_calls':0,'note':'Shared execution across identical policies removes duplicate billing but does not create independent repeats.'})
if __name__=='__main__':main()
