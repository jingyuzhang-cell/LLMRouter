#!/usr/bin/env python3
"""Frozen E3.0 objective contribution and routability geometry audit."""
import hashlib, json, math
from collections import Counter
from pathlib import Path
import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

ROOT=Path(__file__).resolve().parent; EXP=ROOT/"target_support_expansion_v1"; OUT=ROOT/"phase_e3_0"
PROTOCOL=OUT/"E3_0_PROTOCOL.json"; SEED=20260902
MODELS=("deepseek-chat","glm-5.2","qwen-plus","qwen-turbo","gemini-2.5-flash")
WEIGHTS={"Q":[1,0,0,0],"Q+C":[.7,.3,0,0],"Q+T":[.7,0,.3,0],"Q+R":[.7,0,0,.3],"Q+C+T":[.6,.2,.2,0],"Q+C+R":[.6,.2,0,.2],"Q+T+R":[.6,0,.2,.2],"Q+C+T+R":[.45,.2,.15,.2]}

def rows(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def render(t):
    table="\n".join(" | ".join(map(str,r)) for r in t.get("table",[]) if isinstance(r,list))
    return f"[QUESTION] {t.get('question','')}\n[CONTEXT] {t.get('context','')}\n[TABLE] {table}"
def entropy(labels):
    p=np.array(list(Counter(labels).values()),dtype=float); p/=p.sum()
    return float(-(p*np.log(p)).sum())
def boot(delta,rng):
    idx=rng.integers(0,len(delta),(10000,len(delta))); b=delta[idx].mean(1)
    return [float(np.quantile(b,.025)),float(np.quantile(b,.975))],float(np.mean(b>0))

tasks={r["id"]:r for r in rows(EXP/"combined_509_tasks_frozen.jsonl")}
old=json.loads((ROOT/"target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text()); new=json.loads((EXP/"EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
ids=sorted(set(old["train_task_ids"]+old["validation_task_ids"]+new["train_task_ids"])); assert len(ids)==419 and not set(ids)&set(new["validation_task_ids"])
rr=rows(ROOT/"five_model_routability_audit/five_model_training_repeats_frozen.jsonl")+rows(EXP/"expanded_five_model_repeats_frozen.jsonl")
look={(x["task_id"],x["model"],int(x["repeat"])):x for x in rr if x["task_id"] in ids}; assert all((t,m,r) in look for t in ids for m in MODELS for r in range(3))
raw=np.zeros((len(ids),5,3,4))
for i,t in enumerate(ids):
 for j,m in enumerate(MODELS):
  for r in range(3):
   x=look[t,m,r]; raw[i,j,r]=[float(x["quality"]),float(x["cost_usd"]),float(x["latency_ms"]),float(x["reliability"])]
comp=raw.copy(); comp[...,1]=1-np.minimum(raw[...,1]/.02,1); comp[...,2]=1-np.minimum(raw[...,2]/10000,1); mean=comp.mean(2)
texts=[render(tasks[t]) for t in ids]; pred=np.full_like(mean,np.nan); folds=np.full(len(ids),-1); train_static={k:np.full(len(ids),-1) for k in WEIGHTS}
for f,(tr,va) in enumerate(KFold(5,shuffle=True,random_state=SEED).split(ids)):
    wv=TfidfVectorizer(ngram_range=(1,2),min_df=3,max_features=12000,sublinear_tf=True); cv=TfidfVectorizer(analyzer="char_wb",ngram_range=(3,5),min_df=3,max_features=8000,sublinear_tf=True)
    xtr=hstack([wv.fit_transform([texts[i] for i in tr]),cv.fit_transform([texts[i] for i in tr])],format="csr"); xva=hstack([wv.transform([texts[i] for i in va]),cv.transform([texts[i] for i in va])],format="csr")
    pred[va]=np.clip(Ridge(alpha=20).fit(xtr,mean[tr].reshape(len(tr),-1)).predict(xva),0,1).reshape(len(va),5,4); folds[va]=f
    for name,w in WEIGHTS.items(): train_static[name][va]=int(np.argmax((mean[tr]@np.asarray(w)).mean(0)))
assert np.isfinite(pred).all() and np.all(folds>=0)
rng=np.random.default_rng(SEED); pos=np.arange(len(ids)); results={}
for name,w0 in WEIGHTS.items():
    w=np.asarray(w0); observed=mean@w; predicted=pred@w; static=train_static[name]; dynamic=predicted.argmax(1); oracle=observed.argmax(1)
    sv=observed[pos,static]; dv=observed[pos,dynamic]; ov=observed[pos,oracle]; margin=np.sort(observed,axis=1)[:,-1]-np.sort(observed,axis=1)[:,-2]
    repeat_winners=(comp@w).argmax(1); stable=np.all(repeat_winners==repeat_winners[:,[0]],axis=1)
    delta_ci,p=boot(dv-sv,rng); head_ci,hp=boot(ov-sv,rng); counts=Counter(MODELS[x] for x in oracle)
    results[name]={"weights":w0,"static_score":float(sv.mean()),"dynamic_score":float(dv.mean()),"dynamic_minus_static":float((dv-sv).mean()),"dynamic_delta_ci95":delta_ci,"p_dynamic_positive":p,"oracle_score":float(ov.mean()),"oracle_headroom":float((ov-sv).mean()),"oracle_headroom_ci95":head_ci,"p_headroom_positive":hp,"gap_recovery":float((dv.mean()-sv.mean())/max(ov.mean()-sv.mean(),1e-12)),"oracle_winner_counts":dict(counts),"oracle_winner_entropy":entropy([MODELS[x] for x in oracle]),"largest_winner_share":max(counts.values())/len(ids),"median_top1_top2_margin":float(np.median(margin)),"tie_rate_at_0_01":float(np.mean(margin<.01)),"stable_winner_rate":float(np.mean(stable)),"query_crossover_rate":float(np.mean(oracle!=static)),"dynamic_selection_counts":dict(Counter(MODELS[x] for x in dynamic))}
report={"status":"E3_0_COMPLETE","integrity":{"tasks":len(ids),"models":5,"repeats":3,"external_api_calls":0,"reserved_v3_access":False,"protocol_sha256":hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()},"results":results}
(OUT/"E3_0_RESULTS.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
(OUT/"E3_0_SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT)}\n" for p in (PROTOCOL,Path(__file__),OUT/"E3_0_RESULTS.json")))
print(json.dumps(report,ensure_ascii=False,indent=2))
