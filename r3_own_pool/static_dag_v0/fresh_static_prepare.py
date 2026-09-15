"""Dev-only export and source-exposure audit before any fresh collection."""
import hashlib,json,re,time
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge
from . import core,node_router_compare as old

OUT=core.ROOT/'static_dag_v0/fresh_static_confirmation'
DATA=Path('/root/phase_c9_0/external/MultiHiertt-data/multihiertt_data')

def export():
 OUT.mkdir(exist_ok=True)
 if (OUT/'DEV_FROZEN.json').exists():raise FileExistsError('Preserve frozen dev export')
 data=old.build_dataset();emb=np.array([d['emb'] for d in data]);typ=np.array([[float(d['node_type']==t) for t in old.TYPES] for d in data]);length=np.log1p(np.array([len(d['question']) for d in data]))[:,None]
 features={'QueryRouter':emb,'NodeRouter':np.hstack([emb,typ,length])};Y=np.array([[d['Q_'+s] for s in old.POOL] for d in data]);C=np.array([[d['C_'+s] for s in old.POOL] for d in data],dtype=float);L=np.array([[d['L_'+s] for s in old.POOL] for d in data],dtype=float)
 assert np.isfinite(Y).all() and np.isfinite(C).all() and np.isfinite(L).all()
 # Fail on dev transport omissions instead of silently accepting imputed zero cells.
 nodeids={d['node_id'] for d in data}
 for slot in old.POOL:
  rr=core.lines(old.OUT/(slot+'_RESPONSES.jsonl'));mapping={nid:r for r in rr for nid in r['node_ids']}
  assert nodeids<=mapping.keys() and all(mapping[n]['status']=='delivered' and mapping[n].get('answer') and mapping[n].get('usage') for n in nodeids)
 historical=json.loads((old.OUT/'ROUTER_COMPARISON.json').read_text());picks={a:np.zeros(len(data),int) for a in ['AlwaysLarge','StaticCapability','QueryRouter','NodeRouter']}
 for fold in range(3):
  tr=np.array([d['fold']!=fold for d in data]);te=~tr;cost=C[tr].mean(0);lat=L[tr].mean(0)
  picks['AlwaysLarge'][te]=old.POOL.index('large');picks['StaticCapability'][te]=np.argmax(old.utility(Y[tr].mean(0),cost,lat))
  for arm,x in features.items():
   # Separate heads exactly as the original implementation.
   pred=np.column_stack([Ridge(alpha=1.0).fit(x[tr],Y[tr,j]).predict(x[te]) for j in range(3)])
   picks[arm][te]=np.argmax(old.utility(pred,cost,lat),axis=1)
 reproduction={}
 for arm,p in picks.items():
  q=Y[np.arange(len(data)),p].mean();u=old.utility(Y[np.arange(len(data)),p],C[np.arange(len(data)),p],L[np.arange(len(data)),p]).mean()
  counts={s:int(sum(p==j)) for j,s in enumerate(old.POOL)}
  assert abs(q-historical['arms'][arm]['Q'])<1e-12 and abs(u-historical['arms'][arm]['utility'])<1e-10 and counts==historical['arms'][arm]['selection_counts']
  reproduction[arm]=dict(Q=float(q),utility=float(u),selection_counts=counts)
 arrays={'mean_C':C.mean(0),'mean_L':L.mean(0),'mean_Q':Y.mean(0)}
 for arm,x in features.items():
  heads=[Ridge(alpha=1.0).fit(x,Y[:,j]) for j in range(3)];arrays[arm+'_coef']=np.stack([h.coef_ for h in heads]);arrays[arm+'_intercept']=np.array([h.intercept_ for h in heads])
 np.savez_compressed(OUT/'DEV_MODELS.npz',**arrays)
 files=[Path(old.__file__),Path(__file__),old.OUT/'NODES.json',old.OUT/'QUESTION_EMBEDDINGS.npz',old.OUT/'ROUTER_COMPARISON.json',core.ROOT/'static_dag_v0/node_gap_audit_full.py',core.ROOT/'static_dag_v0/node_benchmark_build.py',core.ROOT/'static_dag_v0/node_benchmark_collect.py',core.ROOT/'static_dag_v0/tool_aware_v1.py']+[old.OUT/(s+'_RESPONSES.jsonl') for s in old.POOL]
 core.write(OUT/'DEV_FROZEN.json',dict(created_unix=time.time(),role='Dev-only full-development refit/export, before fresh sampling or generation. Old CV script did not serialize heads.',pool=old.POOL,types=old.TYPES,ridge_alpha=1.0,features='Unchanged question GTE + 4type onehot + log1p(question character length); NOT node context length',static_capability='Unchanged global dev quality/mean resource profile, NOT per-type profile',encoder=old.GTE,embedding_normalize=True,utility=dict(alpha=1,beta=old.ALPHA_C,gamma=old.ALPHA_L),dev_tasks=len({d['task_uid'] for d in data}),dev_nodes=len(data),historical_cv_reproduced=reproduction,models_sha256=core.sha(OUT/'DEV_MODELS.npz'),bindings={str(p):core.sha(p) for p in files}))
 print('Dev models exported; original CV metrics and selections exactly reproduced')

def exposure():
 OUT.mkdir(exist_ok=True)
 source={split:json.loads((DATA/(split+'.json')).read_text()) for split in ['train','dev','test']}
 ids={r['uid'] for rows in source.values() for r in rows};used=set();evidence=[];scanned=0;skipped=[]
 canonical={str(DATA/(s+'.json')) for s in source}
 for root in [core.ROOT,Path('/root/phase_c9_0')]:
  for p in root.rglob('*'):
   if not p.is_file() or p.suffix not in ['.json','.jsonl','.md','.py','.log'] or str(p) in canonical or OUT in p.parents:continue
   if '.git' in p.parts or '__pycache__' in p.parts:continue
   if p.stat().st_size>200_000_000:skipped.append(str(p));continue
   try:b=p.read_bytes()
   except OSError:skipped.append(str(p));continue
   scanned+=1;hits={m.decode() for m in re.findall(rb'(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])',b)}&ids
   if hits:used.update(hits);evidence.append(dict(path=str(p),sha256=hashlib.sha256(b).hexdigest(),uids=sorted(hits)))
 devnodes=json.loads((old.OUT/'NODES.json').read_text());prior=json.loads((core.ROOT/'static_dag_v0/tool_aware_v1/fresh/TASKS.json').read_text())
 norm=lambda x:re.sub(r'\s+',' ',x).strip().lower()
 used_questions={norm(n['question']) for n in devnodes+prior}
 available={s:[r['uid'] for r in rows if r['uid'] not in used and norm(r['qa']['question']) not in used_questions] for s,rows in source.items()}
 report=dict(created_unix=time.time(),scope='UID mentions in text artifacts under r3_own_pool and phase_c9_0; canonical dataset files excluded. Conservative mention=exposed, not proof of no pretraining exposure or use outside audited roots.',scanned_files=scanned,skipped=skipped,source_hashes={s:core.sha(DATA/(s+'.json')) for s in source},total={s:len(rows) for s,rows in source.items()},labelled={s:sum('answer' in r['qa'] and 'program' in r['qa'] for r in rows) for s,rows in source.items()},used_uid_count=len(used),candidate_uid_counts={s:len(x) for s,x in available.items()},used_uids=sorted(used),candidate_uids=available,evidence=evidence)
 core.write(OUT/'EXPOSURE_AUDIT.json',report)
 core.write(OUT/'STATUS.json',dict(phase='AWAITING_LABELLED_FRESH_SOURCE_DECISION',reason='Official test has questions only; no gold program/answer for unchanged conditional nodes or scoring',generation_requests=0,dev_models_frozen=(OUT/'DEV_FROZEN.json').exists()))
 print(json.dumps({k:report[k] for k in ['scanned_files','skipped','total','labelled','candidate_uid_counts']}))

if __name__=='__main__':
 import sys
 globals()[sys.argv[1]]()
