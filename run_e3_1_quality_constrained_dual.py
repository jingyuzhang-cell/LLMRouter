#!/usr/bin/env python3
"""Frozen E3.1 quality-constrained and Pareto/Tchebycheff dual routing."""
import hashlib,json
from collections import Counter
from pathlib import Path
import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
ROOT=Path(__file__).resolve().parent; EXP=ROOT/"target_support_expansion_v1"; OUT=ROOT/"phase_e3_1"; PROTOCOL=OUT/"E3_1_PROTOCOL.json"; SEED=20260902
MODELS=("deepseek-chat","glm-5.2","qwen-plus","qwen-turbo","gemini-2.5-flash"); TAUS=(0,.02,.05,.10)
def rows(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def render(t): return f"[QUESTION] {t.get('question','')}\n[CONTEXT] {t.get('context','')}\n[TABLE] "+"\n".join(" | ".join(map(str,r)) for r in t.get("table",[]) if isinstance(r,list))
def boot(x,rng):
 idx=rng.integers(0,len(x),(10000,len(x))); b=x[idx].mean(1); return [float(np.quantile(b,.025)),float(np.quantile(b,.975))],float(np.mean(b>0))
def pareto(q,c):
 return np.array([not any(q[j]>=q[i] and c[j]>=c[i] and (q[j]>q[i] or c[j]>c[i]) for j in range(len(q))) for i in range(len(q))])
tasks={r['id']:r for r in rows(EXP/'combined_509_tasks_frozen.jsonl')}; old=json.loads((ROOT/'target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json').read_text()); new=json.loads((EXP/'EXPANSION_DEV_VALIDATION_SPLIT.json').read_text()); ids=sorted(set(old['train_task_ids']+old['validation_task_ids']+new['train_task_ids'])); assert len(ids)==419 and not set(ids)&set(new['validation_task_ids'])
rr=rows(ROOT/'five_model_routability_audit/five_model_training_repeats_frozen.jsonl')+rows(EXP/'expanded_five_model_repeats_frozen.jsonl'); look={(x['task_id'],x['model'],int(x['repeat'])):x for x in rr if x['task_id'] in ids}; assert all((t,m,r) in look for t in ids for m in MODELS for r in range(3))
raw=np.zeros((len(ids),5,3,4))
for i,t in enumerate(ids):
 for j,m in enumerate(MODELS):
  for r in range(3):
   x=look[t,m,r]; raw[i,j,r]=[float(x['quality']),float(x['cost_usd']),float(x['latency_ms']),float(x['reliability'])]
mean=raw.mean(2); target=np.stack([mean[...,0],1-np.minimum(mean[...,1]/.02,1)],-1); pred=np.full_like(target,np.nan); static=np.full(len(ids),-1); texts=[render(tasks[t]) for t in ids]
for f,(tr,va) in enumerate(KFold(5,shuffle=True,random_state=SEED).split(ids)):
 w=TfidfVectorizer(ngram_range=(1,2),min_df=3,max_features=12000,sublinear_tf=True); c=TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),min_df=3,max_features=8000,sublinear_tf=True); xtr=hstack([w.fit_transform([texts[i] for i in tr]),c.fit_transform([texts[i] for i in tr])]); xva=hstack([w.transform([texts[i] for i in va]),c.transform([texts[i] for i in va])]); pred[va]=np.clip(Ridge(alpha=20).fit(xtr,target[tr].reshape(len(tr),-1)).predict(xva),0,1).reshape(len(va),5,2); static[va]=int(np.argmax((target[tr]@np.array([.7,.3])).mean(0)))
assert np.isfinite(pred).all(); pos=np.arange(len(ids)); selections={'static_ws':static,'dynamic_ws':(pred@np.array([.7,.3])).argmax(1)}
for tau in TAUS:
 s=[]
 for i in pos:
  eligible=np.where(pred[i,:,0]>=pred[i,:,0].max()-tau-1e-12)[0]; s.append(int(eligible[np.argmax(pred[i,eligible,1])]))
 selections[f'quality_constrained_tau_{tau:.2f}']=np.array(s)
tch=[]
for i in pos:
 mask=pareto(pred[i,:,0],pred[i,:,1]); cand=np.where(mask)[0]; vals=pred[i,cand]; span=np.maximum(vals.max(0)-vals.min(0),1e-12); short=(vals.max(0)-vals)/span; score=np.maximum(.7*short[:,0],.3*short[:,1]); tch.append(int(cand[np.argmin(score)]))
selections['pareto_tchebycheff']=np.array(tch)
base=static; bq=mean[pos,base,0]; bc=mean[pos,base,1]; obs_u=target@np.array([.7,.3]); oracle_u=obs_u.max(1); rng=np.random.default_rng(SEED); results={}
actual_pareto=np.array([pareto(target[i,:,0],target[i,:,1]) for i in pos])
for name,s in selections.items():
 q=mean[pos,s,0]; cost=mean[pos,s,1]; util=obs_u[pos,s]; qd=q-bq; saving=(bc-cost)/np.maximum(bc,1e-12); qci,qp=boot(qd,rng); sci,sp=boot(saving,rng)
 results[name]={'quality':float(q.mean()),'cost_usd':float(cost.mean()),'quality_delta_vs_static':float(qd.mean()),'quality_delta_ci95':qci,'p_quality_delta_positive':qp,'cost_saving_vs_static':float(saving.mean()),'cost_saving_ci95':sci,'p_cost_saving_positive':sp,'weighted_sum_utility':float(util.mean()),'actual_pareto_selection_rate':float(np.mean(actual_pareto[pos,s])),'normalized_weighted_sum_regret':float(np.mean((oracle_u-util)/np.maximum(oracle_u,1e-12))),'selection_counts':dict(Counter(MODELS[x] for x in s))}
oracle={}
for tau in TAUS:
 s=[]
 for i in pos:
  eligible=np.where(mean[i,:,0]>=mean[i,:,0].max()-tau-1e-12)[0]; s.append(int(eligible[np.argmin(mean[i,eligible,1])]))
 s=np.array(s); oracle[f'tau_{tau:.2f}']={'quality':float(mean[pos,s,0].mean()),'cost_usd':float(mean[pos,s,1].mean()),'cost_saving_vs_static':float(np.mean((bc-mean[pos,s,1])/np.maximum(bc,1e-12)))}
passing=[n for n,v in results.items() if n.startswith('quality_constrained') and v['quality_delta_vs_static']>=0 and v['cost_saving_vs_static']>=.05]
report={'status':'E3_1_COMPLETE','integrity':{'tasks':len(ids),'external_api_calls':0,'reserved_v3_access':False,'protocol_sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()},'results':results,'oracle_quality_constrained':oracle,'stop_gate':{'passing_quality_constrained_points':passing,'stop_dual_method_expansion':not bool(passing)}}
(OUT/'E3_1_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); (OUT/'E3_1_SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT)}\n' for p in (PROTOCOL,Path(__file__),OUT/'E3_1_RESULTS.json'))); print(json.dumps(report,ensure_ascii=False,indent=2))
