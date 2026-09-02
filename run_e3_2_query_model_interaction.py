#!/usr/bin/env python3
"""Frozen E3.2 query-model interaction ablation."""
import hashlib,json,re
from collections import Counter
from pathlib import Path
import numpy as np
from scipy.sparse import hstack
from scipy.stats import spearmanr
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler
ROOT=Path(__file__).resolve().parent; EXP=ROOT/'target_support_expansion_v1'; OUT=ROOT/'phase_e3_2'; PROTOCOL=OUT/'E3_2_PROTOCOL.json'; SEED=20260902
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash'); METHODS=('F0','F1','F2','F3','F4'); OBJECTIVES={'Q+C+T+R':np.array([.45,.2,.15,.2]),'Q+T':np.array([.7,0,.3,0]),'Q':np.array([1,0,0,0])}
def rows(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def render(t): return f"[QUESTION] {t.get('question','')}\n[CONTEXT] {t.get('context','')}\n[TABLE] "+'\n'.join(' | '.join(map(str,r)) for r in t.get('table',[]) if isinstance(r,list))
def structural(t):
 q=str(t.get('question','')); c=str(t.get('context','')); tab=t.get('table',[]) or []; s=q+' '+c; low=s.lower(); nums=re.findall(r'[-+]?\d[\d,.]*%?',s)
 return np.array([len(q),len(c),len(s.split()),len(tab),max([len(r) for r in tab if isinstance(r,list)]+[0]),len(nums),sum('%' in x for x in nums),sum(x in s for x in '$€£¥'),len(set(re.findall(r'\b(?:19|20)\d{2}\b',s))),sum(k in low for k in ('calculate','difference','change','ratio','percent','average','sum')),sum(k in low for k in ('compare','versus','higher','lower','increase','decrease')),float(len(c)>8000),float(bool(tab) and bool(c)),q.count('?')+q.count(' and ')+1],float)
def comps(raw):
 x=raw.copy(); x[...,1]=1-np.minimum(raw[...,1]/.02,1); x[...,2]=1-np.minimum(raw[...,2]/10000,1); return x
def transformed(rawmean): return np.stack([rawmean[...,0],np.log1p(rawmean[...,2]),rawmean[...,3],np.log1p(rawmean[...,1]*1e6)],-1)
def inverse(y):
 x=np.empty_like(y); x[...,0]=np.clip(y[...,0],0,1); x[...,1]=1-np.minimum(np.maximum(np.expm1(y[...,3]),0)/1e6/.02,1); x[...,2]=1-np.minimum(np.maximum(np.expm1(y[...,1]),0)/10000,1); x[...,3]=np.clip(y[...,2],0,1); return x
def ci(d,rng):
 idx=rng.integers(0,len(d),(10000,len(d))); b=d[idx].mean(1); return [float(np.quantile(b,.025)),float(np.quantile(b,.975))],float(np.mean(b>0))
tasks={r['id']:r for r in rows(EXP/'combined_509_tasks_frozen.jsonl')}; old=json.loads((ROOT/'target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json').read_text()); new=json.loads((EXP/'EXPANSION_DEV_VALIDATION_SPLIT.json').read_text()); ids=sorted(set(old['train_task_ids']+old['validation_task_ids']+new['train_task_ids'])); assert len(ids)==419 and not set(ids)&set(new['validation_task_ids'])
rr=rows(ROOT/'five_model_routability_audit/five_model_training_repeats_frozen.jsonl')+rows(EXP/'expanded_five_model_repeats_frozen.jsonl'); look={(x['task_id'],x['model'],int(x['repeat'])):x for x in rr if x['task_id'] in ids}; assert all((t,m,r) in look for t in ids for m in MODELS for r in range(3))
raw=np.zeros((len(ids),5,3,4))
for i,t in enumerate(ids):
 for j,m in enumerate(MODELS):
  for r in range(3):
   x=look[t,m,r]; raw[i,j,r]=[float(x['quality']),float(x['cost_usd']),float(x['latency_ms']),float(x['reliability'])]
mean=raw.mean(2); target=transformed(mean); observed=comps(raw).mean(2); texts=[render(tasks[t]) for t in ids]; S=np.stack([structural(tasks[t]) for t in ids]); pred={m:np.full_like(target,np.nan) for m in METHODS}; static={o:np.full(len(ids),-1) for o in OBJECTIVES}; folds=KFold(5,shuffle=True,random_state=SEED)
for f,(tr,va) in enumerate(folds.split(ids)):
 word=TfidfVectorizer(ngram_range=(1,2),min_df=3,max_features=12000,sublinear_tf=True); char=TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),min_df=3,max_features=8000,sublinear_tf=True); xtr=hstack([word.fit_transform([texts[i] for i in tr]),char.fit_transform([texts[i] for i in tr])],format='csr'); xva=hstack([word.transform([texts[i] for i in va]),char.transform([texts[i] for i in va])],format='csr')
 # F0 exactly preserves E3.0 component prediction semantics.
 f0=np.clip(Ridge(alpha=20).fit(xtr,observed[tr].reshape(len(tr),-1)).predict(xva),0,1).reshape(len(va),5,4); pred['F0'][va]=np.stack([f0[...,0],np.log1p((1-f0[...,2])*10000),f0[...,3],np.log1p((1-f0[...,1])*.02*1e6)],-1)
 scaler=StandardScaler().fit(S[tr]); str_tr=scaler.transform(S[tr]); str_va=scaler.transform(S[va]); svd=TruncatedSVD(n_components=64,random_state=SEED+f).fit(xtr); emb_tr=svd.transform(xtr); emb_va=svd.transform(xva)
 for name,a,b in [('F1',str_tr,str_va),('F2',emb_tr,emb_va),('F3',np.c_[emb_tr,str_tr],np.c_[emb_va,str_va])]: pred[name][va]=Ridge(alpha=20).fit(a,target[tr].reshape(len(tr),-1)).predict(b).reshape(len(va),5,4)
 profile=np.c_[mean[tr].mean((0,2)),np.quantile(raw[tr,:,:,2],.9,axis=(0,2))] if False else None
 # Fold-training model profiles: mean Q/cost/latency/reliability plus latency p90.
 prof=np.stack([np.r_[mean[tr,j].mean(0),np.quantile(raw[tr,j,:,2],.9)] for j in range(5)])
 def f4mat(base,idx):
  out=[]
  for row,ti in zip(base,idx):
   for j in range(5):
    one=np.eye(5)[j]; inter=np.outer(row[-14:],prof[j,[0,2,3,4]]).ravel(); out.append(np.r_[row,one,prof[j],inter])
  return np.asarray(out)
 a=np.c_[emb_tr,str_tr]; b=np.c_[emb_va,str_va]; A=f4mat(a,tr); B=f4mat(b,va); Y=target[tr].reshape(-1,4); yh=np.zeros((len(B),4))
 for k in range(4): yh[:,k]=HistGradientBoostingRegressor(max_iter=150,max_leaf_nodes=15,l2_regularization=2,random_state=SEED+f+k).fit(A,Y[:,k]).predict(B)
 pred['F4'][va]=yh.reshape(len(va),5,4)
 for o,w in OBJECTIVES.items(): static[o][va]=int(np.argmax((observed[tr]@w).mean(0)))
assert all(np.isfinite(v).all() for v in pred.values())
pc={m:inverse(y) for m,y in pred.items()}; prediction={}
labels=(raw[...,3].reshape(-1)>0.5).astype(int)
for m in METHODS:
 y=pred[m]; qhat=y[...,0]; lhat=y[...,1]; rhat=np.clip(y[...,2],0,1); chat=np.maximum(np.expm1(y[...,3]),0)/1e6
 rep_r=np.repeat(rhat[:,:,None],3,axis=2).reshape(-1); auc=float(roc_auc_score(labels,rep_r)) if len(np.unique(labels))>1 else None
 prediction[m]={'quality_mae':float(np.mean(np.abs(qhat-mean[...,0]))),'quality_spearman':float(spearmanr(qhat.ravel(),mean[...,0].ravel()).statistic),'latency_log_mae':float(np.mean(np.abs(lhat-np.log1p(mean[...,2])))),'latency_spearman':float(spearmanr(lhat.ravel(),mean[...,2].ravel()).statistic),'reliability_brier':float(np.mean((rep_r-labels)**2)),'reliability_auc':auc,'cost_mae':float(np.mean(np.abs(chat-mean[...,1]))),'cost_relative_error':float(np.mean(np.abs(chat-mean[...,1])/np.maximum(mean[...,1],1e-9)))}
rng=np.random.default_rng(SEED); pos=np.arange(len(ids)); routing={}
for o,w in OBJECTIVES.items():
 obs=observed@w; sta=static[o]; sv=obs[pos,sta]; oracle=obs.argmax(1); ov=obs[pos,oracle]; routing[o]={'static':{'score':float(sv.mean())},'oracle':{'score':float(ov.mean()),'headroom':float((ov-sv).mean())}}
 f0sel=(pc['F0']@w).argmax(1); f0v=obs[pos,f0sel]
 for m in METHODS:
  sel=(pc[m]@w).argmax(1); val=obs[pos,sel]; d=val-sv; inc=val-f0v; dci,dp=ci(d,rng); ici,ip=ci(inc,rng); chosen=mean[pos,sel]
  harmful=(val<sv-1e-12)&(sel!=sta)
  routing[o][m]={'score':float(val.mean()),'delta_vs_static':float(d.mean()),'delta_vs_static_ci95':dci,'p_delta_positive':dp,'delta_vs_F0':float(inc.mean()),'delta_vs_F0_ci95':ici,'p_increment_positive':ip,'gap_recovery':float((val.mean()-sv.mean())/max(ov.mean()-sv.mean(),1e-12)),'quality':float(chosen[:,0].mean()),'cost_usd':float(chosen[:,1].mean()),'latency_ms':float(chosen[:,2].mean()),'reliability':float(chosen[:,3].mean()),'selection_counts':dict(Counter(MODELS[x] for x in sel)),'switch_coverage':float(np.mean(sel!=sta)),'harmful_switch_rate':float(np.mean(harmful))}
main=routing['Q+C+T+R']; gate=main['F4']['delta_vs_F0']>=.003 and main['F4']['delta_vs_F0_ci95'][0]>0 and main['F4']['gap_recovery']>main['F0']['gap_recovery']
report={'status':'E3_2_COMPLETE','integrity':{'tasks':len(ids),'models':5,'repeats':3,'external_api_calls':0,'reserved_v3_access':False,'protocol_sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()},'prediction':prediction,'routing':routing,'incremental_gate':{'strong_continue':gate,'decision':'FREEZE_INTERACTION_ROUTER_THEN_E3_3' if gate else 'STOP_ROUTER_ARCHITECTURE_EXPANSION'}}
(OUT/'E3_2_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); (OUT/'E3_2_SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT)}\n' for p in (PROTOCOL,Path(__file__),OUT/'E3_2_RESULTS.json'))); print(json.dumps(report,ensure_ascii=False,indent=2))
