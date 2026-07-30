#!/usr/bin/env python3
"""Nested-CV cascade verifier using real 0.5B first-token confidence."""
import json,sys
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
D=ROOT/"data/kqapro/cost_dev_v1";C=ROOT/"run_logs/kqapro/cascade_v2/confidence.jsonl";O=ROOT/"run_logs/kqapro/cascade_v2"
def fit(x,y):
 base=make_pipeline(StandardScaler(),LogisticRegression(C=.1,class_weight="balanced",max_iter=2000))
 return CalibratedClassifierCV(base,method="sigmoid",cv=3).fit(x,y)
def lower(delta,b=3000,seed=1):
 n=len(delta);cnt=np.array([(delta==-1).sum(),(delta==0).sum(),(delta==1).sum()]);d=np.random.default_rng(seed).multinomial(n,cnt/n,size=b);return float(np.quantile((d[:,2]-d[:,0])/n,.025))
def met(acc,pred,correct):
 n=len(acc);strong=2;r=np.arange(n);harm=acc&(correct[:,0]==0)&(correct[:,strong]==1);sel=np.where(acc,0,strong);delta=correct[r,sel]-correct[:,strong];cost=.5+(~acc)*3
 return {"acceptance":float(acc.mean()),"accepted":int(acc.sum()),"harms":int(harm.sum()),"harm_rate":float(harm.mean()),"harm_ci95_upper":wilson_upper(int(harm.sum()),n),"accuracy_delta":float(delta.mean()),"accuracy_delta_ci95_lower":lower(delta,seed=20260724),"avg_compute_size_b":float(cost.mean()),"compute_saving_fraction":float(1-cost.mean()/3)}
def choose(p,correct):
 rows=[]
 for t in np.linspace(.01,.99,99):
  m=met(p>=t,None,correct);m["threshold"]=float(t);rows.append(m)
 f=[x for x in rows if x["acceptance"]>=1/6 and x["compute_saving_fraction"]>0 and x["harm_ci95_upper"]<.025 and x["accuracy_delta_ci95_lower"]>=-.0025]
 return max(f,key=lambda x:(x["compute_saving_fraction"],x["accuracy_delta"])) if f else None
def main():
 O.mkdir(parents=True,exist_ok=True);frame=load_routing(D/"routing_cost_dev.jsonl");emb=torch.load(D/"query_embeddings_longformer.pt",map_location="cpu");names=list(json.loads((D/"llm_candidates.json").read_text()));queries,raw,correct,perf,_=build_matrices(frame,emb,names);cf=pd.read_json(C,lines=True).set_index("query").loc[queries];safe=frame[["query","choices","embedding_id"]];base=np.concatenate([raw.astype(np.float32),structural_features(queries),extra_features(queries,safe)],1);letters=np.asarray([[r[chr(65+i)] for i in range(10)] for r in cf["letter_probabilities"]],dtype=np.float32);conf=cf[["top1_probability","margin","entropy","letter_probability_mass","format_valid","top1_matches_stored","stability"]].astype(float).to_numpy();x=np.concatenate([base,letters,conf],1);y=correct[:,0].astype(int);strat=correct[:,2].astype(int)*2+y;splits=list(StratifiedKFold(5,shuffle=True,random_state=20260724).split(x,strat));accept=np.zeros(len(x),bool);folds=[]
 for fold,(tr,va) in enumerate(splits):
  inner=StratifiedKFold(3,shuffle=True,random_state=800+fold);ip=np.zeros(len(tr))
  for ft,iv in inner.split(x[tr],strat[tr]):ip[iv]=fit(x[tr][ft],y[tr][ft]).predict_proba(x[tr][iv])[:,1]
  pol=choose(ip,correct[tr])
  if pol is None:pol={"threshold":1.1,"feasible":False}
  else:pol["feasible"]=True
  pv=fit(x[tr],y[tr]).predict_proba(x[va])[:,1];accept[va]=pv>=pol["threshold"];folds.append({"fold":fold,**pol})
 final=met(accept,None,correct);gate=final["acceptance"]>=1/6 and final["compute_saving_fraction"]>0 and final["harm_ci95_upper"]<.025 and final["accuracy_delta_ci95_lower"]>=-.0025
 summary={"format_valid_rate":float(cf["format_valid"].mean()),"top1_matches_stored_rate":float(cf["top1_matches_stored"].mean()),"mean_stability":float(cf["stability"].mean()),"mean_margin":float(cf["margin"].mean()),"mean_entropy":float(cf["entropy"].mean()),"mean_letter_probability_mass":float(cf["letter_probability_mass"].mean())}
 report={"experiment_id":"cascade_v2_confidence","scope":"cost_dev_only","confirmation_sets_read":False,"confidence_summary":summary,"nested_cv":{"fold_policies":folds,"combined_oof":final},"gates":{"acceptance_at_least_16_7pct":final["acceptance"]>=1/6,"positive_compute_saving":final["compute_saving_fraction"]>0,"harm_ci_upper_below_2_5pct":final["harm_ci95_upper"]<.025,"noninferiority_ci_lower_at_least_minus_0_25pp":final["accuracy_delta_ci95_lower"]>=-.0025,"passed":gate},"eligible_for_sealed_confirmation":gate}
 (O/"REPORT.json").write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=="__main__":main()
