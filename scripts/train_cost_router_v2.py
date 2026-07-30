#!/usr/bin/env python3
"""Cost-router v2: query-only nested-CV harm-controlled routing."""
import json,math,sys
from pathlib import Path
import joblib,numpy as np,pandas as pd,torch
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"scripts")]
from train_safe_graphrouter import build_matrices,load_routing
from train_safe_graphrouter_cv import structural_features
D=ROOT/"data/kqapro/cost_dev_v1";O=ROOT/"run_logs/kqapro/cost_router_v2"
ALLOWED=["query","choices","query_embedding"];FORBIDDEN=["ground_truth","response","predicted_label","correct","performance","response_time"]
def extra_features(queries,frame):
 rows=[]
 for q in queries:
  row=frame[frame["query"]==q].iloc[0];choices=row["choices"];texts=choices.get("text",[]) if isinstance(choices,dict) else []
  toks=q.split(); lower=q.lower()
  rows.append([len(texts),np.mean([len(str(x).split()) for x in texts]) if texts else 0,max([len(str(x).split()) for x in texts] or [0]),sum(t[:1].isupper() for t in toks),q.count('"')//2,q.count("'")//2,sum(lower.count(x) for x in ["which","whose","that","of the","and","or"]),int(any(x in lower for x in ["how many","number of","count"])),int(any(x in lower for x in ["before","after","during","year","date"])),int(any(x in lower for x in ["more","less","largest","smallest","same"]))])
 return np.asarray(rows,dtype=np.float32)
def features(frame,emb,names):
 queries,raw,correct,perf,_=build_matrices(frame,emb,names)
 safe_frame=frame[["query","choices","embedding_id"]].copy()
 # Only this explicitly reduced frame reaches handcrafted inference features.
 return queries,np.concatenate([raw.astype(np.float32),structural_features(queries),extra_features(queries,safe_frame)],1),correct,perf
def fit(x,y):
 base=make_pipeline(StandardScaler(),LogisticRegression(C=.1,class_weight="balanced",max_iter=2000))
 if len(np.unique(y))<2:return float(y[0])
 return CalibratedClassifierCV(base,method="sigmoid",cv=3).fit(x,y)
def prob(model,x):
 return np.full(len(x),model) if isinstance(model,float) else model.predict_proba(x)[:,1]
def train_models(x,correct,strong,small):
 out=[]
 for j in small:
  harm=((correct[:,strong]==1)&(correct[:,j]==0)).astype(int);success=correct[:,j].astype(int)
  out.append((fit(x,harm),fit(x,success)))
 return out
def predict(models,x):
 return np.column_stack([prob(m[0],x) for m in models]),np.column_stack([prob(m[1],x) for m in models])
def wilson_upper(k,n,z=1.96):
 if n==0:return 1.
 p=k/n;d=1+z*z/n;return (p+z*z/(2*n)+z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/d
def route(h,s,ht,st,strong,small):
 pred=np.full(len(h),strong);eligible=(h<=ht)&(s>=st)
 for pos,j in enumerate(small):
  take=eligible[:,pos]&(pred==strong);pred[take]=j
 return pred
def metrics(pred,correct,sizes,strong):
 n=len(pred);r=np.arange(n);down=pred!=strong;harm=down&(correct[:,strong]==1)&(correct[r,pred]==0);rescue=down&(correct[:,strong]==0)&(correct[r,pred]==1)
 return {"coverage":float(down.mean()),"harmful":int(harm.sum()),"harm_rate":float(harm.mean()),"harm_ci95_upper":wilson_upper(int(harm.sum()),n),"accuracy":float(correct[r,pred].mean()),"accuracy_delta":float((correct[r,pred]-correct[:,strong]).mean()),"size_saving_fraction":float(1-sizes[pred].mean()/sizes[strong]),"rescues":int(rescue.sum())}
def choose(h,s,correct,sizes,strong,small):
 rows=[]
 for ht in np.linspace(.01,.30,30):
  for st in np.linspace(.3,.9,25):
   m=metrics(route(h,s,ht,st,strong,small),correct,sizes,strong);m.update({"harm_threshold":float(ht),"success_threshold":float(st)});rows.append(m)
 feasible=[x for x in rows if x["coverage"]>=.10 and x["harm_ci95_upper"]<.025]
 return (max(feasible,key=lambda x:(x["size_saving_fraction"],x["accuracy_delta"])) if feasible else None),rows
def main():
 O.mkdir(parents=True,exist_ok=True);frame=load_routing(D/"routing_cost_dev.jsonl");emb=torch.load(D/"query_embeddings_longformer.pt",map_location="cpu");llm=json.loads((D/"llm_candidates.json").read_text());names=list(llm);sizes=np.array([.5,1.5,3.]);strong=2;small=[0,1];queries,x,correct,perf=features(frame,emb,names)
 labels=((correct[:,strong]==1)&(correct[:,small].min(1)==0)).astype(int);outer=StratifiedKFold(5,shuffle=True,random_state=20260720);oof=np.full(len(x),strong);folds=[]
 for fold,(tr,va) in enumerate(outer.split(x,labels)):
  inner=StratifiedKFold(3,shuffle=True,random_state=300+fold);ih=np.zeros((len(tr),2));isu=np.zeros((len(tr),2))
  for fitidx,validx in inner.split(x[tr],labels[tr]):
   ms=train_models(x[tr][fitidx],correct[tr][fitidx],strong,small);ih[validx],isu[validx]=predict(ms,x[tr][validx])
  policy,_=choose(ih,isu,correct[tr],sizes,strong,small)
  if policy is None: policy={"harm_threshold":0.0,"success_threshold":1.0}
  ms=train_models(x[tr],correct[tr],strong,small);h,s=predict(ms,x[va]);oof[va]=route(h,s,policy["harm_threshold"],policy["success_threshold"],strong,small);folds.append(policy)
 combined=metrics(oof,correct,sizes,strong);deployable=combined["coverage"]>=.10 and combined["harm_ci95_upper"]<.025
 final_models=train_models(x,correct,strong,small) if deployable else None
 report={"experiment_id":"cost_router_v2","feature_contract":{"allowed_at_inference":ALLOWED,"forbidden":FORBIDDEN,"uses_model_outputs_at_inference":False,"uses_ground_truth_at_inference":False},"nested_cv":{"outer_folds":5,"inner_folds":3,"fold_policies":folds,"combined_oof":combined},"deployment_gate":{"coverage_at_least_10pct":combined["coverage"]>=.10,"harm_ci95_upper_below_2_5pct":combined["harm_ci95_upper"]<.025,"passed":deployable},"confirmation_set_read":False}
 (O/"REPORT.json").write_text(json.dumps(report,indent=2));joblib.dump({"models":final_models,"fold_policies":folds,"feature_contract":report["feature_contract"]},O/"artifact.joblib");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
