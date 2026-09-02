#!/usr/bin/env python3
"""Frozen static/dynamic/DAG and 1/2/multi-objective empirical replay."""
import hashlib, json
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

ROOT = Path(__file__).resolve().parent
EXP = ROOT / "target_support_expansion_v1"
OUT = ROOT / "routing_regime_objective_results"
PROTOCOL = ROOT / "ROUTING_REGIME_OBJECTIVE_PROTOCOL.json"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
SEED = 20260902

def rows(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]

def text(task):
    table = "\n".join(" | ".join(map(str, r)) for r in task.get("table", []) if isinstance(r, list))
    return f"[QUESTION] {task.get('question','')}\n[CONTEXT] {task.get('context','')}\n[TABLE] {table}"

def norm_components(raw):
    out = raw.copy()
    out[..., 1] = 1-np.minimum(raw[..., 1]/.02, 1)
    out[..., 2] = 1-np.minimum(raw[..., 2]/10000, 1)
    return out

def ci(delta, rng, n=10000):
    idx = rng.integers(0, len(delta), (n, len(delta)))
    boot = delta[idx].mean(1)
    return [float(np.quantile(boot,.025)), float(np.quantile(boot,.975))], float(np.mean(boot>0))

tasks = {r["id"]: r for r in rows(EXP / "combined_509_tasks_frozen.jsonl")}
old = json.loads((ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text())
new = json.loads((EXP / "EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
ids = sorted(set(old["train_task_ids"] + old["validation_task_ids"] + new["train_task_ids"]))
assert len(ids) == 419 and not set(ids) & set(new["validation_task_ids"])
rep = rows(ROOT / "five_model_routability_audit/five_model_training_repeats_frozen.jsonl")
rep += rows(EXP / "expanded_five_model_repeats_frozen.jsonl")
look = {(r["task_id"],r["model"],int(r["repeat"])):r for r in rep if r["task_id"] in ids}
assert all((t,m,r) in look for t in ids for m in MODELS for r in range(3))

raw = np.zeros((len(ids),len(MODELS),3,4))
for i,t in enumerate(ids):
  for j,m in enumerate(MODELS):
    for r in range(3):
      x=look[t,m,r]; raw[i,j,r]=[float(x["quality"]),float(x["cost_usd"]),float(x["latency_ms"]),float(x["reliability"])]
comp = norm_components(raw)
assert comp.shape == (len(ids), len(MODELS), 3, 4)
weights={"single":[1,0,0,0],"dual":[.7,.3,0,0],"multi":[.45,.20,.15,.20]}
means=comp.mean(2)
texts=[text(tasks[t]) for t in ids]
pred=np.full_like(means,np.nan); fold_of=np.full(len(ids),-1); static={k:np.full(len(ids),-1) for k in weights}
for fold,(tr,va) in enumerate(KFold(5,shuffle=True,random_state=SEED).split(ids)):
    word=TfidfVectorizer(ngram_range=(1,2),min_df=3,max_features=12000,sublinear_tf=True)
    char=TfidfVectorizer(analyzer="char_wb",ngram_range=(3,5),min_df=3,max_features=8000,sublinear_tf=True)
    xtr=hstack([word.fit_transform([texts[i] for i in tr]),char.fit_transform([texts[i] for i in tr])],format="csr")
    xva=hstack([word.transform([texts[i] for i in va]),char.transform([texts[i] for i in va])],format="csr")
    pred[va]=np.clip(Ridge(alpha=20).fit(xtr,means[tr].reshape(len(tr),-1)).predict(xva),0,1).reshape(len(va),len(MODELS),4)
    fold_of[va]=fold
    for name,w in weights.items(): static[name][va]=int(np.argmax((means[tr]@np.asarray(w)).mean(0)))
assert np.isfinite(pred).all() and np.all(fold_of>=0)

rng=np.random.default_rng(SEED); pos=np.arange(len(ids)); result={}
selections={}
for name,w0 in weights.items():
    w=np.asarray(w0); observed=means@w; forecast=pred@w
    dyn=forecast.argmax(1); sta=static[name]; oracle=observed.argmax(1); selections[name]=(sta,dyn,oracle)
    sv=observed[pos,sta]; dv=observed[pos,dyn]; ov=observed[pos,oracle]
    dci,dp=ci(dv-sv,rng); hci,hp=ci(ov-sv,rng)
    result[name]={
      "static":{"score":float(sv.mean()),"models":dict(Counter(MODELS[x] for x in sta))},
      "dynamic":{"score":float(dv.mean()),"models":dict(Counter(MODELS[x] for x in dyn)),"delta_vs_static":float((dv-sv).mean()),"ci95":dci,"p_delta_positive":dp},
      "oracle":{"score":float(ov.mean()),"headroom_vs_static":float((ov-sv).mean()),"ci95":hci,"p_headroom_positive":hp},
      "headroom_recovered":float((dv.mean()-sv.mean())/max(ov.mean()-sv.mean(),1e-12))}

# Diamond DAG empirical-node replay. Groups never cross folds.
dag={}
for name,w0 in weights.items():
    w=np.asarray(w0); sta,dyn,_=selections[name]; workflows=[]
    for fold in range(5):
      pool=np.where(fold_of==fold)[0]
      for start in range(0,len(pool)-3,4):
        nodes=pool[start:start+4]
        rec={"static":[],"dynamic":[],"adaptive":[]}
        for node in nodes:
          repeat=int(hashlib.sha256(f"{ids[node]}:{SEED}".encode()).hexdigest()[:8],16)%3
          for regime,choice in (("static",sta[node]),("dynamic",dyn[node])):
            c=comp[node,choice,repeat]; rec[regime].append((c,raw[node,choice,repeat,1],raw[node,choice,repeat,2],False))
          ranking=np.argsort(-(pred[node]@w)); first=int(ranking[0]); c=comp[node,first,repeat]
          failed=bool(raw[node,first,repeat,3]<1 or raw[node,first,repeat,0]<.6)
          cost=float(raw[node,first,repeat,1]); lat=float(raw[node,first,repeat,2]); retried=False
          if failed:
            second=int(ranking[1]); c2=comp[node,second,repeat]; cost+=float(raw[node,second,repeat,1]); lat+=float(raw[node,second,repeat,2]); c=c2; retried=True
          rec["adaptive"].append((c,cost,lat,retried))
        out={}
        for regime,vals in rec.items():
          ok=np.array([v[0][3]>=1 and v[0][0]>=.6 for v in vals])
          # critical path n0 -> max(n1,n2) -> n3
          latency=vals[0][2]+max(vals[1][2],vals[2][2])+vals[3][2]
          cost=float(sum(v[1] for v in vals))
          workflow_components=np.array([np.mean([v[0][0] for v in vals]),1-min((cost/4)/.02,1),1-min((latency/3)/10000,1),np.mean([v[0][3] for v in vals])])
          out[regime]={"score":float(workflow_components@w),"success":bool(ok.all()),"cost":cost,"critical_latency":float(latency),"retries":sum(v[3] for v in vals)}
        workflows.append(out)
    dag[name]={"workflows":len(workflows)}
    for regime in ("static","dynamic","adaptive"):
      dag[name][regime]={k:float(np.mean([x[regime][k] for x in workflows])) for k in ("score","success","cost","critical_latency","retries")}
    for regime in ("dynamic","adaptive"):
      dag[name][regime]["delta_score_vs_static"]=dag[name][regime]["score"]-dag[name]["static"]["score"]
      dag[name][regime]["delta_success_vs_static"]=dag[name][regime]["success"]-dag[name]["static"]["success"]
      score_delta=np.array([x[regime]["score"]-x["static"]["score"] for x in workflows])
      success_delta=np.array([float(x[regime]["success"])-float(x["static"]["success"]) for x in workflows])
      dag[name][regime]["score_delta_ci95"],dag[name][regime]["p_score_delta_positive"]=ci(score_delta,rng)
      dag[name][regime]["success_delta_ci95"],dag[name][regime]["p_success_delta_positive"]=ci(success_delta,rng)

report={"status":"COMPLETE","integrity":{"tasks":len(ids),"models":len(MODELS),"repeats":3,"external_calls":0,"reserved_v3_access":False,"protocol_sha256":hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()},"request_routing":result,"dag_replay":dag,"claim_boundary":"DAG results are empirical-node mechanism replay, not end-to-end semantic decomposition evidence."}
OUT.mkdir(exist_ok=True)
(OUT/"RESULTS.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
print(json.dumps(report,ensure_ascii=False,indent=2))
