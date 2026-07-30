#!/usr/bin/env python3
import hashlib,json,sys
from pathlib import Path
import joblib,numpy as np,torch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"scripts")]
from train_safe_graphrouter import build_matrices,load_routing
from train_safe_graphrouter_cv import enhanced_features
from train_e5_multitask_router import ensemble_predictions,route_with_bounds,routing_metrics
D=ROOT/"data/kqapro/cost_confirm_v1";O=ROOT/"run_logs/kqapro/cost_confirm_v1"
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 O.mkdir(parents=True,exist_ok=True);marker=O/"EVALUATED_ONCE"
 result_path=O/"CONFIRMATORY_RESULT.json"
 if marker.exists() and result_path.exists():raise RuntimeError("sealed confirmation was already evaluated")
 recovery=marker.exists()

 pre=json.loads((D/"PREREGISTRATION.json").read_text());frozen=ROOT/"run_logs/kqapro/cost_dev_v1/FROZEN_COST_POLICY.json";assert sha(frozen)==pre["frozen_policy_sha256"];seal=json.loads((D/"CONFIRMATION_SEAL.json").read_text());assert sha(D/"routing_cost_confirm.jsonl")==seal["routing_sha256"];assert sha(D/"query_cost_confirm.jsonl")==seal["query_sha256"];assert sha(D/"query_embeddings_longformer.pt")==seal["embeddings_sha256"]
 marker.write_text("metrics read exactly once\n")
 art=joblib.load(ROOT/"run_logs/kqapro/e5/multitask_ensemble.joblib");frame=load_routing(D/"routing_cost_confirm.jsonl");emb=torch.load(D/"query_embeddings_longformer.pt",map_location="cpu");names=art["model_names"];q,raw,correct,perf,_=build_matrices(frame,emb,names);features=enhanced_features(q,raw);means=[ensemble_predictions(art["models"][s],features)[0] for s in art["seeds"]];mean=np.mean(means,0);unc=np.std(means,0);strong=art["strong_idx"];sizes=art["sizes"];pred=route_with_bounds(mean,unc,pre["beta"],pre["margin"],strong,sizes);m=routing_metrics(pred,correct,perf,sizes,strong);n=len(q);delta=correct[np.arange(n),pred]-correct[:,strong];counts=np.array([(delta==-1).sum(),(delta==0).sum(),(delta==1).sum()]);rng=np.random.default_rng(pre["bootstrap"]["seed"]);draw=rng.multinomial(n,counts/n,size=pre["bootstrap"]["replicates"]);vals=(draw[:,2]-draw[:,0])/n;ci=[float(x) for x in np.quantile(vals,[.025,.975])];metrics={"coverage":m["downgrade_count"]/n,"size_saving_fraction":1-m["avg_size_b"]/sizes[strong],"accuracy_delta":float(delta.mean()),"accuracy_delta_ci95":ci,"harm_rate":m["harmful_downgrades"]/n,**m};c=pre["success_criteria"];checks={"coverage":metrics["coverage"]>=c["minimum_coverage"],"size_saving":metrics["size_saving_fraction"]>=c["minimum_size_saving_fraction"],"accuracy_ci":ci[0]>=c["minimum_accuracy_delta_ci95_lower"],"harm_rate":metrics["harm_rate"]<=c["maximum_harm_rate"]};report={"experiment_id":pre["experiment_id"],"queries":n,"evaluated_once":True,"serialization_recovery":recovery,"policy_or_threshold_changed_during_recovery":False,"frozen_beta":pre["beta"],"frozen_margin":pre["margin"],"metrics":metrics,"success_checks":checks,"primary_success":all(checks.values()),"predicted_models":{names[i]:int((pred==i).sum()) for i in range(len(names))}};(O/"CONFIRMATORY_RESULT.json").write_text(json.dumps(report,indent=2,default=lambda x:x.item()));print(json.dumps(report,indent=2,default=lambda x:x.item()))
if __name__=="__main__":main()
