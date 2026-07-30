#!/usr/bin/env python3
"""Development-only two-stage cascade with probe cost fully accounted."""
import json,math,sys
from pathlib import Path
import numpy as np,pandas as pd,torch
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"scripts")]
from train_safe_graphrouter import build_matrices,load_routing
from train_safe_graphrouter_cv import structural_features
from train_cost_router_v2 import extra_features,wilson_upper
D=ROOT/"data/kqapro/cost_dev_v1";O=ROOT/"run_logs/kqapro/cascade_v1"
def onehot(values):
 out=np.zeros((len(values),11),dtype=np.float32)
 for i,v in enumerate(values):
  j=ord(str(v)[0])-65 if isinstance(v,str) and v else 10
  out[i,j if 0<=j<10 else 10]=1
 return out
def fit(x,y):
 base=make_pipeline(StandardScaler(),LogisticRegression(C=.1,class_weight="balanced",max_iter=2000))
 return CalibratedClassifierCV(base,method="sigmoid",cv=3).fit(x,y)
def metrics(accept,choice,correct,strong,probe_cost,sizes):
 n=len(accept);r=np.arange(n);selected=np.where(accept,choice,strong);harm=accept&(correct[r,choice]==0)&(correct[:,strong]==1);rescue=accept&(correct[r,choice]==1)&(correct[:,strong]==0);total=probe_cost+(~accept)*sizes[strong]
 return {"acceptance":float(accept.mean()),"accepted":int(accept.sum()),"harms":int(harm.sum()),"harm_rate":float(harm.mean()),"harm_ci95_upper":wilson_upper(int(harm.sum()),n),"rescues":int(rescue.sum()),"accuracy_delta":float((correct[r,selected]-correct[:,strong]).mean()),"avg_compute_size_b":float(total.mean()),"compute_saving_fraction":float(1-total.mean()/sizes[strong])}
def choose(p,choice,correct,strong,probe,sizes):
 rows=[]
 for t in np.linspace(.3,.99,70):
  m=metrics(p>=t,choice,correct,strong,probe,sizes);m["threshold"]=float(t);rows.append(m)
 feasible=[x for x in rows if x["harm_ci95_upper"]<.025 and x["compute_saving_fraction"]>0]
 return max(feasible,key=lambda x:(x["compute_saving_fraction"],x["accuracy_delta"])) if feasible else None
def evaluate_variant(name,x,label,choice,correct,strong,probe,sizes,splits):
 pred_accept=np.zeros(len(x),bool);policies=[]
 for fold,(tr,va) in enumerate(splits):
  inner=StratifiedKFold(3,shuffle=True,random_state=700+fold);ip=np.zeros(len(tr))
  for ft,iv in inner.split(x[tr],label[tr]):
   ip[iv]=fit(x[tr][ft],label[tr][ft]).predict_proba(x[tr][iv])[:,1]
  pol=choose(ip,choice[tr],correct[tr],strong,probe,sizes)
  if pol is None:pol={"threshold":1.1,"feasible":False}
  else:pol["feasible"]=True
  model=fit(x[tr],label[tr]);pv=model.predict_proba(x[va])[:,1];pred_accept[va]=pv>=pol["threshold"];policies.append({"fold":fold,**pol})
 m=metrics(pred_accept,choice,correct,strong,probe,sizes);gate=m["harm_ci95_upper"]<.025 and m["compute_saving_fraction"]>0 and m["acceptance"]>=.10
 return {"variant":name,"fold_policies":policies,"nested_oof":m,"deployment_gate":gate}
def main():
 O.mkdir(parents=True,exist_ok=True);f=load_routing(D/"routing_cost_dev.jsonl");emb=torch.load(D/"query_embeddings_longformer.pt",map_location="cpu");names=list(json.loads((D/"llm_candidates.json").read_text()));queries,raw,correct,perf,_=build_matrices(f,emb,names);safe=f[["query","choices","embedding_id"]];qfeat=np.concatenate([raw.astype(np.float32),structural_features(queries),extra_features(queries,safe)],1)
 piv=f.pivot(index="query",columns="model_name",values="predicted_label").reindex(queries);a0=piv[names[0]].tolist();a1=piv[names[1]].tolist();x0=np.concatenate([qfeat,onehot(a0)],1);xdual=np.concatenate([qfeat,onehot(a0),onehot(a1),np.asarray([[float(x==y)] for x,y in zip(a0,a1)])],1);label0=correct[:,0].astype(int);label1=correct[:,1].astype(int);strat=correct[:,2].astype(int)*4+label0*2+label1;counts=np.bincount(strat);strat=np.where(np.array([counts[z] for z in strat])>=5,strat,correct[:,2].astype(int));splits=list(StratifiedKFold(5,shuffle=True,random_state=20260722).split(qfeat,strat));sizes=np.array([.5,1.5,3.])
 results=[evaluate_variant("0.5b_probe",x0,label0,np.zeros(len(x0),int),correct,2,.5,sizes,splits),evaluate_variant("0.5b_plus_1.5b_probe",xdual,label1,np.ones(len(x0),int),correct,2,2.0,sizes,splits)]
 report={"experiment_id":"kqapro_two_stage_cascade_v1","scope":"cost_dev_only","confirmation_sets_read":False,"inference_contract":{"stage1":"call cheap probe model(s)","stage2_features":["query","choices","query_embedding","probe_predicted_label","probe_agreement"],"forbidden":["ground_truth","correct","performance"],"fallback":"call 3B strong when verifier abstains"},"cost_accounting":"probe compute is always charged; rejected queries charge probe plus 3B","results":results,"eligible_for_confirmation":any(x["deployment_gate"] for x in results)}
 (O/"REPORT.json").write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=="__main__":main()
