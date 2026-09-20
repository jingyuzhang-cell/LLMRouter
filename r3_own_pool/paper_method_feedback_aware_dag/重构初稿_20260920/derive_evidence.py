"""Read-only paper audit: recompute summaries; never calls a model or modifies experiment files."""
from pathlib import Path
import json, hashlib
from collections import defaultdict,Counter
import numpy as np
ROOT=Path('/root/r3_own_pool'); B=ROOT/'static_dag_v0'; OUT=Path(__file__).parent
sources={}
def path(f):
 p=B/f;sources[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest();return p
def read(f):return json.loads(path(f).read_text())
def ci_cluster(diff,task,ratio=True):
 ids=np.unique(task); sums=np.array([diff[task==u].sum()for u in ids]);ns=np.array([(task==u).sum()for u in ids]);rng=np.random.default_rng(20260920);idx=rng.integers(0,len(ids),(10000,len(ids)));z=sums[idx].sum(1)/ns[idx].sum(1);return np.quantile(z,[.025,.975]).tolist()
a=dict(np.load(path('fresh_static_confirmation/SCORED_MATRIX_EXEC.npz'),allow_pickle=False));nodes=read('fresh_static_confirmation/NODES.json');dev=read('tool_aware_v1/node_benchmark/NODE_GAP_AUDIT.json');pool=['medium','large','coder'];idx=np.flatnonzero(a['main']);Q=a['Q'][idx];task=a['task_of'][idx];types=np.array([nodes[i]['node_type']for i in idx]);tp=np.array([pool.index(dev['by_type'][t]['best_fixed_model'])for t in types]);picks={k:a[k][idx].astype(int)for k in ['AlwaysLarge','QueryRouter','FrozenNodeRouter']};picks['TypePrior']=tp;picks['NodeOracle']=Q.argmax(1)
qs={k:Q[np.arange(len(idx)),v]for k,v in picks.items()}
r={'audit_seed':20260920,'bootstrap_replicates':10000,'note':'New descriptive aggregations of existing outputs only; ratio-of-sums cluster bootstrap aligns with node-weighted Q. Post-hoc audit, not new preregistered experiment.'}
r['routing']={'n_tasks':len(np.unique(task)),'n_nodes':len(idx),'Q':{k:float(v.mean())for k,v in qs.items()},'diff_ci95':{x+'-'+y:ci_cluster(qs[x]-qs[y],task)for x,y in [('FrozenNodeRouter','QueryRouter'),('FrozenNodeRouter','TypePrior'),('TypePrior','QueryRouter')]},'types':{t:{'n':int(sum(types==t)),'Q':dict(zip(pool,Q[types==t].mean(0).tolist())),'oracle':float(Q[types==t].max(1).mean())}for t in np.unique(types)},'dev_type_prior':{t:pool[int(tp[np.flatnonzero(types==t)[0]])]for t in np.unique(types)}}
c=read('complexity_stratification.json');r['complexity']={}
for dom in sorted({x['domain']for x in c})+['ALL']:
 for name,fn in [('1-2',lambda x:x['n_ops']<=2),('3',lambda x:x['n_ops']==3),('4+',lambda x:x['n_ops']>=4)]:
  z=[x for x in c if(dom=='ALL'or x['domain']==dom)and fn(x)];r['complexity'][dom+':'+name]={'n':len(z),'mono_correct':sum(x['mono']for x in z),'dag_correct':sum(x['dag']for x in z)}
d=read('dynamic_v2_test/TEST_ANALYSIS.json')['detail'];diff=np.array([x['success']-x['static_success']for x in d]);r['dynamic_v2']={'n':len(d),'latency_mean':float(np.mean([x['lat']for x in d])),'realloc_count':sum(x['realloc']for x in d),'dQ_ci95':ci_cluster(diff,np.arange(len(d))),'help':int(sum(diff==1)),'harm':int(sum(diff==-1))}
r['faults']={};pairs=defaultdict(dict)
for x in read('controlled_fault_propagation/RAW_RESULTS.json')['results']:pairs[(x['uid'],x['fault'])][x['arm']]=x
for ft in ['C0','T1','T2','T3']:
 z=[(v['static'],v['dynamic'])for (u,f),v in pairs.items()if f==ft and len(v)==2];r['faults'][ft]={'n':len(z),'static_correct':sum(s['success']for s,d in z),'dynamic_correct':sum(d['success']for s,d in z),'help':sum(not s['success']and d['success']for s,d in z),'harm':sum(s['success']and not d['success']for s,d in z),'dC':float(np.mean([d['used']-s['used']for s,d in z])),'dL':float(np.mean([d['lat']-s['lat']for s,d in z]))}
orig=read('recovery_matrix_v2/full_4983983/ORIG_CORRECTNESS.json');clean={x['nid']:x for x in orig if not x['orig_correct']};full=read('recovery_matrix_v2/full_4983983/FULL_RESULTS.json')['results'];rows=[x for x in full if x['node_id']in clean];r['recovery']={'n':len(rows),'unique_tasks':len(set(x['task_uid']for x in rows)),'already_correct':len(orig)-len(rows),'actions':{}}
for act in ['retry_same','switch_model','evidence_retrieval','local_decompose']:
 r['recovery']['actions'][act]={'successes':sum(x['actions'][act]['success']for x in rows),'tokens':float(np.mean([x['actions'][act]['tokens']for x in rows])),'latency':float(np.mean([x['actions'][act]['dt_s']for x in rows]))}
r['source_sha256']=sources
(OUT/'DERIVED_EVIDENCE.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in r.items()if k!='source_sha256'},ensure_ascii=False,indent=2))
