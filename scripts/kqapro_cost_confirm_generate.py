#!/usr/bin/env python3
import argparse,json,sys
from pathlib import Path
import torch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"scripts")]
from kqapro_e4_generate import DEFAULT_DATASET,MODELS,file_sha256,query_row,read_json,read_jsonl,run_resumable_model,sampled_indices,value_sha256,write_json,write_jsonl
from llmrouter.utils.embeddings import get_longformer_embedding
def prepare(out,size,seed):
 out.mkdir(parents=True,exist_ok=True); val=read_json(DEFAULT_DATASET/"val.json");e4=read_json(ROOT/"data/kqapro/e4/partition_manifest.json");e6=read_json(ROOT/"data/kqapro/e6_final3/partition_manifest.json");dev=read_json(ROOT/"data/kqapro/cost_dev_v1/partition_manifest.json")
 excluded=set(e4["dev_indices"])|set(e4["final_indices"])|set(e6["final3_indices"])|set(dev["indices"]);idx=sampled_indices(len(val),size,seed,excluded)
 manifest={"version":1,"purpose":"cost_policy_sealed_confirmation","size":size,"seed":seed,"excluded_count":len(excluded),"overlap_with_all_prior_splits":len(set(idx)&excluded),"indices":idx,"indices_sha256":value_sha256(idx),"val_source_sha256":e4["val_source_sha256"]};write_json(out/"partition_manifest.json",manifest)
 frozen=ROOT/"run_logs/kqapro/cost_dev_v1/FROZEN_COST_POLICY.json"
 prereg={"experiment_id":"kqapro_cost_confirm_v1","created_utc":"2026-07-18","confirmatory":True,"sample_size":size,"sample_seed":seed,"frozen_policy_sha256":file_sha256(frozen),"beta":2.0,"margin":0.08,"success_criteria":{"minimum_coverage":0.10,"minimum_size_saving_fraction":0.08,"minimum_accuracy_delta_ci95_lower":-0.0025,"maximum_harm_rate":0.025},"bootstrap":{"replicates":10000,"seed":20260719},"evaluation_rule":"seal all outputs, then evaluate frozen policy exactly once; no parameter changes"};write_json(out/"PREREGISTRATION.json",prereg);(out/"PREREGISTRATION.sha256").write_text(file_sha256(out/"PREREGISTRATION.json")+"  PREREGISTRATION.json\n");return val,idx
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--output-dir",type=Path,default=ROOT/"data/kqapro/cost_confirm_v1");ap.add_argument("--size",type=int,default=2000);ap.add_argument("--seed",type=int,default=20260719);ap.add_argument("--batch-size",type=int,default=16);ap.add_argument("--prepare-only",action="store_true");a=ap.parse_args();val,idx=prepare(a.output_dir,a.size,a.seed)
 if a.prepare_only:print("prepared",len(idx));return
 samples=[(i,val[i]) for i in idx];parts={"train":samples,"final":[]}
 for key,repo,size in MODELS:run_resumable_model(key,repo,size,parts,a.output_dir,a.batch_size,0.05)
 qs=[query_row(x,"cost_confirm",i) for i,x in samples];write_jsonl(a.output_dir/"query_cost_confirm.jsonl",qs);ep=a.output_dir/"query_embeddings_longformer.pt"
 if not ep.exists():
  emb={}
  for st in range(0,len(qs),32):
   vs=get_longformer_embedding([r["query"] for r in qs[st:st+32]]);emb.update({st+j:v for j,v in enumerate(vs)});print("embeddings",min(st+32,len(qs)),len(qs))
  torch.save(emb,ep)
 qid={r["query"]:i for i,r in enumerate(qs)};routing=[]
 for key,_,_ in MODELS:
  rows=read_jsonl(a.output_dir/"partial/train"/f"{key}.jsonl")
  if len(rows)!=len(qs):raise ValueError((key,len(rows)))
  for r in rows:r["embedding_id"]=qid[r["query"]];r["task_id"]=r["task_id"].replace("-train-","-cost_confirm-")
  routing.extend(rows)
 write_jsonl(a.output_dir/"routing_cost_confirm.jsonl",routing);write_json(a.output_dir/"llm_candidates.json",read_json(ROOT/"data/kqapro/e4/llm_candidates.json"));write_json(a.output_dir/"CONFIRMATION_SEAL.json",{"routing_sha256":file_sha256(a.output_dir/"routing_cost_confirm.jsonl"),"query_sha256":file_sha256(a.output_dir/"query_cost_confirm.jsonl"),"embeddings_sha256":file_sha256(ep),"evaluated":False});print("sealed")
if __name__=="__main__":main()
