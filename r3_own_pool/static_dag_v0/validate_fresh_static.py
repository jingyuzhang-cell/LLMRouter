"""Independent frozen-input, inference, scoring and accounting audit."""
import hashlib,json,re,time
from pathlib import Path
import numpy as np
from . import core,node_router_compare as old,node_benchmark_collect as collector
from . import fresh_static_confirmation as fresh
from .fresh_static_evaluate import dedup_cost,bootstrap_quality,ci
from .node_gap_audit_full import score
OUT=fresh.OUT

def main():
 p=fresh.verify();legacy=json.loads((core.ROOT/'static_dag_v0/run_v0/PROTOCOL.json').read_text());engine_path=str(core.ROOT/'static_dag_v0/run.py');assert core.sha(engine_path)==legacy['code_and_inputs'][engine_path]
 evalfreeze=json.loads((OUT/'EVALUATOR_FROZEN.json').read_text())
 for path,h in evalfreeze['bindings'].items():assert core.sha(path)==h
 audit=json.loads((OUT/'EXPOSURE_AUDIT.json').read_text());sources={s:json.loads((fresh.DATA/(s+'.json')).read_text()) for s in ['train','dev','test']}
 for s,h in audit['source_hashes'].items():assert core.sha(fresh.DATA/(s+'.json'))==h
 tasks=json.loads((OUT/'TASKS.json').read_text());nodes=json.loads((OUT/'NODES.json').read_text());calls=json.loads((OUT/'CALLS.json').read_text());pred=json.loads((OUT/'PREDICTIONS.json').read_text());weights=np.load(OUT/'DEV_MODELS.npz');pf=json.loads((OUT/'PREDICTIONS_FROZEN.json').read_text());em=np.load(OUT/'QUESTION_EMBEDDINGS.npz');emb=dict(zip(em['questions'],em['emb']));used=set(audit['used_uids']);norm=lambda x:re.sub(r'\s+',' ',x).strip().lower();usedq={norm(r['qa']['question']) for rows in sources.values() for r in rows if r['uid'] in used};train={r['uid']:r for r in sources['train']}
 assert len(tasks)==len({t['uid'] for t in tasks})==100
 assert not({t['uid'] for t in tasks}&used) and not({norm(t['question']) for t in tasks}&usedq)
 for t in tasks:
  source=train[t['uid']];assert t['question']==source['qa']['question'] and t['program']==source['qa']['program'] and t['answer']==float(source['qa']['answer'])
 assert nodes==[n for t in tasks for n in fresh.nodes_for(t)]
 reconstructed=collector.build_calls(nodes,{t['uid']:t['context'] for t in tasks})
 assert len(reconstructed)==len(calls)==p['calls_per_model']
 for a,b in zip(reconstructed,calls):assert all(a[k]==b[k] for k in a)
 assert pf['models_sha256']==core.sha(OUT/'DEV_MODELS.npz') and pf['predictions_sha256']==core.sha(OUT/'PREDICTIONS.json') and pf['embeddings_sha256']==core.sha(OUT/'QUESTION_EMBEDDINGS.npz')
 assert pf['created_unix']<json.loads((OUT/'EVALUATION_STARTED.json').read_text())['unix_time']
 for n,r in zip(nodes,pred):
  assert n['node_id']==r['node_id'];q=emb[n['question']];x=np.r_[q,[float(n['node_type']==t) for t in old.TYPES],np.log1p(len(n['question']))]
  for arm,tag,feat in [('QueryRouter','QueryRouter',q),('FrozenNodeRouter','NodeRouter',x)]:
   qp=weights[tag+'_coef']@feat+weights[tag+'_intercept'];u=qp-old.ALPHA_C*weights['mean_C']-old.ALPHA_L*weights['mean_L'];assert r['arms'][arm]==fresh.POOL[int(np.argmax(u))]
   np.testing.assert_allclose(qp,[r['candidates'][arm][s]['Q'] for s in fresh.POOL],rtol=1e-12,atol=1e-12)
 callmap={c['call_key']:c for c in calls};lookup={};requests={};minimum=time.time();missing=[]
 for slot in fresh.POOL:
  rq=core.lines(OUT/(slot+'_REQUESTS.jsonl'));rr=core.lines(OUT/(slot+'_RESPONSES.jsonl'));assert len(rq)==len(rr)==len(calls)
  assert {r['call_key'] for r in rq}=={r['call_key'] for r in rr}==callmap.keys();assert len({r['call_key'] for r in rr})==len(rr)
  minimum=min(minimum,min(r['unix_time'] for r in rq));lookup[slot]={nid:r for r in rr for nid in r['node_ids']};requests[slot]=len(rq)
  for r in rq:assert r['prompt_sha256']==hashlib.sha256(callmap[r['call_key']]['prompt'].encode()).hexdigest() and r['model']==slot
  for r in rr:
   assert r['node_ids']==callmap[r['call_key']]['node_ids'] and r['model']==slot
   if r['status']!='delivered' or not r.get('usage') or not r.get('answer'):missing.append((slot,r['call_key']));continue
   u=r['usage'];assert u['total_tokens']==u['prompt_tokens']+u['completion_tokens'] and r['latency_s']>=0
   from .run import MODELS
   assert r['provider_model']==MODELS[slot]['served']
 assert minimum>pf['created_unix'] and minimum>evalfreeze['created_unix']
 if missing:
  result=json.loads((OUT/'RESULTS.json').read_text());assert result['phase']=='INCONCLUSIVE_MISSING';core.write(OUT/'VALIDATION.json',dict(passed=True,complete_panel=False,missing=missing,requests=requests));(OUT/'REPORT.md').write_text('# Fresh confirmation incomplete\n\nMissing transport/usage records prevent frozen F1–F3 evaluation. No missing values were scored as zero; no automatic retry or tuning occurred. See RESULTS.json.\n');return
 matrix=np.load(OUT/'SCORED_MATRIX.npz');Q=np.array([[score(n,lookup[s][n['node_id']]['answer']) for s in fresh.POOL] for n in nodes]);np.testing.assert_array_equal(Q,matrix['Q']);np.testing.assert_array_equal(matrix['C'],np.array([[lookup[s][n['node_id']]['usage']['total_tokens'] for s in fresh.POOL] for n in nodes]));np.testing.assert_allclose(matrix['L'],np.array([[lookup[s][n['node_id']]['latency_s'] for s in fresh.POOL] for n in nodes]));mainmask=np.array([n['node_type']!='transformation' for n in nodes]);np.testing.assert_array_equal(mainmask,matrix['main']);taskids=sorted({n['task_uid'] for n in nodes});task_index={t:i for i,t in enumerate(taskids)};task_of=np.array([task_index[n['task_uid']] for n in nodes]);boot=np.random.default_rng(20260915).integers(0,len(taskids),(10000,len(taskids)));result=json.loads((OUT/'RESULTS.json').read_text());picks={a:matrix[a] for a in result['arms']};samples,best=bootstrap_quality(Q,picks,mainmask,task_of,boot)
 for arm,choice in picks.items():
  actual=Q[np.arange(len(Q)),choice];assert result['arms'][arm]['Q']==actual[mainmask].mean()
  c,l,count=dedup_cost(nodes,np.flatnonzero(mainmask),choice,lookup,task_index);assert result['arms'][arm]['tokens_total']==c.sum() and result['arms'][arm]['deduplicated_calls']==count.sum()
  if arm!='NodeOracle':assert [fresh.POOL[j] for j in choice]==[r['arms'][arm] for r in pred]
  else:
   assert np.all(actual==Q.max(1))
   utility=old.utility(Q,matrix['C'],matrix['L'])
   assert all(choice[i]==max(range(3),key=lambda j:(Q[i,j],utility[i,j],-j)) for i in range(len(nodes)))
 for baseline in ['QueryRouter','AlwaysLarge','StaticCapability']:
  np.testing.assert_allclose(result['contrasts']['FrozenNodeRouter_minus_'+baseline]['Q_ci95'],ci(samples['FrozenNodeRouter']-samples[baseline]))
 globalbest=Q[mainmask].mean(0).max();gap=Q[mainmask].max(1).mean()-globalbest;rec=(result['arms']['FrozenNodeRouter']['Q']-globalbest)/gap if gap>0 else None;assert result['quality_recovery']['recovery']==rec
 checks=['Dev CV exactly reproduced and full-dev heads sealed before sample outcomes','100 train UIDs and normalized questions excluded from audited usage','Node definitions/prompts/scoring match dev; no fresh fitting','All predictions reproduced from fixed coefficients and question embeddings','3 x 404 unique model requests; no retries; before/after hash chain intact','Quality oracle and primary/exploratory separation verified','Shared calls deduplicated for cost; cluster-bootstrap estimand verified']
 core.write(OUT/'VALIDATION.json',dict(passed=True,complete_panel=True,checks=checks,requests=requests,gates=result['gates'],validator_sha256=core.sha(Path(__file__))))
 core.write(OUT/'ARTIFACT_MANIFEST.json',{f.name:core.sha(f) for f in OUT.iterdir() if f.is_file() and f.suffix!='.log' and f.name!='ARTIFACT_MANIFEST.json'})
 print(json.dumps(dict(passed=True,requests=requests,gates=result['gates'])))
if __name__=='__main__':main()
