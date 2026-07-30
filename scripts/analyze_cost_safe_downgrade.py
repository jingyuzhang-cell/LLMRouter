#!/usr/bin/env python3
"""Cost-dev-only learnability and task-conditional abstention audit."""
import json,math,sys,re
from pathlib import Path
import numpy as np,torch
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"scripts")]
from train_safe_graphrouter import build_matrices,load_routing
from train_safe_graphrouter_cv import structural_features
from train_cost_router_v2 import extra_features,wilson_upper
D=ROOT/"data/kqapro/cost_dev_v1";O=ROOT/"run_logs/kqapro/cost_learnability"
TYPES=["count","comparison","verification","temporal","set_operation","relation","multi_hop","other"]
def qtype(q):
 l=q.lower()
 checks=[("count",["how many","number of","count"]),("comparison",["more","less","largest","smallest","same","earlier","later"]),("verification",["is ","are ","was ","were ","did ","does "]),("temporal",["year","date","before","after","during"]),("set_operation",[" both "," either "," or "," and ","not ","all the"]),("relation",["whose","which has","that has","related","belongs to","located in","part of"]),("multi_hop",["whose","which has","that has","of the"])]
 for name,terms in checks:
  if any(x in (" "+l) for x in terms):return name
 return "other"
def fit(x,y):
 if len(np.unique(y))<2:return float(y[0])
 base=make_pipeline(StandardScaler(),LogisticRegression(C=.1,class_weight="balanced",max_iter=2000))
 return CalibratedClassifierCV(base,method="sigmoid",cv=3).fit(x,y)
def pp(m,x):return np.full(len(x),m) if isinstance(m,float) else m.predict_proba(x)[:,1]
def ece(y,p,bins=10):
 out=0.
 for lo,hi in zip(np.linspace(0,1,bins+1)[:-1],np.linspace(0,1,bins+1)[1:]):
  m=(p>=lo)&(p<(hi if hi<1 else hi+1e-9))
  if m.any():out+=m.mean()*abs(y[m].mean()-p[m].mean())
 return float(out)
def feature_sets(queries,raw,frame):
 safe=frame[["query","choices","embedding_id"]].copy();structure=np.concatenate([structural_features(queries),extra_features(queries,safe)],1)
 return {"embedding_only":raw.astype(np.float32),"structure_only":structure,"embedding_plus_structure":np.concatenate([raw.astype(np.float32),structure],1)}
def main():
 O.mkdir(parents=True,exist_ok=True);frame=load_routing(D/"routing_cost_dev.jsonl");emb=torch.load(D/"query_embeddings_longformer.pt",map_location="cpu");names=list(json.loads((D/"llm_candidates.json").read_text()));queries,raw,correct,perf,_=build_matrices(frame,emb,names);types=np.array([qtype(q) for q in queries]);strong=2;small=[0,1];n=len(queries)
 descriptive=[]
 for typ in TYPES:
  mask=types==typ
  for j in small:
   win=mask&(correct[:,j]==1)&(correct[:,strong]==0);harm=mask&(correct[:,j]==0)&(correct[:,strong]==1);tie=mask&~win&~harm
   descriptive.append({"type":typ,"model":names[j],"n":int(mask.sum()),"wins":int(win.sum()),"harms":int(harm.sum()),"ties":int(tie.sum()),"harm_rate":float(harm.sum()/max(mask.sum(),1)),"harm_ci95_upper":wilson_upper(int(harm.sum()),int(mask.sum())) if mask.sum() else 1.0})
 labels=((correct[:,strong,None]==1)&(correct[:,small]==0)).astype(int);strat=labels.max(1);outer=StratifiedKFold(5,shuffle=True,random_state=20260721);ablations={}
 splits=list(outer.split(raw,strat))
 for fname,x in feature_sets(queries,raw,frame).items():
  probs=np.zeros((n,2));foldstats=[]
  for fold,(tr,va) in enumerate(splits):
   for pos in range(2):probs[va,pos]=pp(fit(x[tr],labels[tr,pos]),x[va])
   foldstats.append({"fold":fold,"n":len(va),"mean_predicted_harm":float(probs[va].mean()),"observed_harm":float(labels[va].mean())})
  per=[]
  for pos,j in enumerate(small):
   y=labels[:,pos];p=probs[:,pos];per.append({"model":names[j],"brier":float(brier_score_loss(y,p)),"ece10":ece(y,p),"roc_auc":float(roc_auc_score(y,p))})
  ablations[fname]={"per_model":per,"fold_drift":foldstats}
 # Honest task-conditional OOF: subgroup decisions use outer-train outcomes only.
 pred=np.full(n,strong);fold_policies=[]
 for fold,(tr,va) in enumerate(splits):
  policy={}
  for typ in TYPES:
   tm=types[tr]==typ
   if tm.sum()<100:continue
   candidates=[]
   for j in small:
    harm=((correct[tr,j]==0)&(correct[tr,strong]==1)&tm);k=int(harm.sum());upper=wilson_upper(k,int(tm.sum()))
    wins=int(((correct[tr,j]==1)&(correct[tr,strong]==0)&tm).sum())
    if upper<.025:candidates.append((wins-k,-j,j,upper,k,int(tm.sum())))
   if candidates:
    best=max(candidates);policy[typ]={"model_idx":best[2],"model":names[best[2]],"train_n":best[5],"train_harms":best[4],"train_harm_ci_upper":best[3]}
  for typ,item in policy.items():pred[va[types[va]==typ]]=item["model_idx"]
  fold_policies.append({"fold":fold,"safe_types":policy})
 down=pred!=strong;harm=down&(correct[np.arange(n),pred]==0)&(correct[:,strong]==1);win=down&(correct[np.arange(n),pred]==1)&(correct[:,strong]==0);sizes=np.array([.5,1.5,3.])
 task_oof={"coverage":float(down.mean()),"downgrades":int(down.sum()),"harms":int(harm.sum()),"harm_rate":float(harm.mean()),"harm_ci95_upper":wilson_upper(int(harm.sum()),n),"wins":int(win.sum()),"accuracy_delta":float((correct[np.arange(n),pred]-correct[:,strong]).mean()),"size_saving_fraction":float(1-sizes[pred].mean()/3)}
 gate=task_oof["coverage"]>=.10 and task_oof["harm_ci95_upper"]<.025
 report={"experiment_id":"cost_safe_downgrade_learnability","data_scope":"cost_dev_v1_only","confirmation_sets_read":False,"descriptive_by_type":descriptive,"feature_ablation":ablations,"task_conditional_nested_oof":{"fold_policies":fold_policies,"metrics":task_oof},"next_confirmation_gate":{"coverage_at_least_10pct":task_oof["coverage"]>=.10,"harm_ci95_upper_below_2_5pct":task_oof["harm_ci95_upper"]<.025,"passed":gate},"claim":("eligible_for_preregistered_confirmation" if gate else "high_precision_selective_downgrade_only")}
 (O/"REPORT.json").write_text(json.dumps(report,indent=2));print(json.dumps({"task_conditional_nested_oof":report["task_conditional_nested_oof"],"next_confirmation_gate":report["next_confirmation_gate"],"claim":report["claim"],"feature_ablation":ablations},indent=2))
if __name__=="__main__":main()
