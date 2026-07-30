#!/usr/bin/env python3
import json,sys
from pathlib import Path
import joblib,numpy as np,torch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"scripts")]
from train_safe_graphrouter import build_matrices,load_routing
from train_safe_graphrouter_cv import enhanced_features
from train_e5_multitask_router import ensemble_predictions,route_with_bounds,routing_metrics
D=ROOT/"data/kqapro/cost_dev_v1";O=ROOT/"run_logs/kqapro/cost_dev_v1"

def ci(delta,rng,b=5000):
    # A paired bootstrap draw depends only on win/tie/loss counts.
    # Multinomial resampling is exactly equivalent to resampling query indices.
    n=len(delta)
    counts=np.array([(delta == -1).sum(), (delta == 0).sum(), (delta == 1).sum()])
    draws=rng.multinomial(n, counts / n, size=b)
    values=(draws[:, 2] - draws[:, 0]) / n
    return [float(x) for x in np.quantile(values,[.025,.975])]

def main():
    O.mkdir(parents=True,exist_ok=True)
    prereg=json.loads((D/"PREREGISTRATION.json").read_text()); art=joblib.load(ROOT/"run_logs/kqapro/e5/multitask_ensemble.joblib")
    frame=load_routing(D/"routing_cost_dev.jsonl");emb=torch.load(D/"query_embeddings_longformer.pt",map_location="cpu")
    names=art["model_names"];q,raw,correct,perf,_=build_matrices(frame,emb,names);features=enhanced_features(q,raw)
    seedmeans=[]
    for seed in art["seeds"]: seedmeans.append(ensemble_predictions(art["models"][seed],features)[0])
    mean=np.mean(seedmeans,axis=0);unc=np.std(seedmeans,axis=0);strong=art["strong_idx"];sizes=art["sizes"];base=correct[:,strong];rng=np.random.default_rng(prereg["bootstrap"]["seed"]);rows=[];n=len(q)
    for beta in np.arange(0,2.01,.25):
      for margin in np.arange(-.50,.301,.01):
        pred=route_with_bounds(mean,unc,float(beta),float(margin),strong,sizes);m=routing_metrics(pred,correct,perf,sizes,strong);chosen=correct[np.arange(n),pred];delta=chosen-base;m.update({"beta":float(beta),"margin":float(margin),"coverage":m["downgrade_count"]/n,"harm_rate":m["harmful_downgrades"]/n,"size_saving_fraction":1-m["avg_size_b"]/sizes[strong],"accuracy_delta":float(delta.mean()),"accuracy_delta_ci95":ci(delta,rng)});rows.append(m)
    selected={}
    for name,c in prereg["operating_points"].items():
      feasible=[r for r in rows if r["coverage"]>=c["min_coverage"] and r["harm_rate"]<=c["max_harm_rate"] and r["accuracy_delta_ci95"][0]>=-c["epsilon_accuracy"]]
      selected[name]=max(feasible,key=lambda r:(r["size_saving_fraction"],r["accuracy_delta"])) if feasible else {"feasible":False,"constraints":c}
      if feasible:selected[name]["feasible"]=True
    frontier=sorted(rows,key=lambda r:r["size_saving_fraction"])
    report={"experiment_id":"kqapro_cost_dev_v1","queries":n,"final3_read":False,"candidate_count":len(rows),"operating_points":selected,"all_constraints_preregistered":True}
    (O/"pareto_candidates.json").write_text(json.dumps(frontier,indent=2));(O/"operating_points.json").write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=="__main__":main()
