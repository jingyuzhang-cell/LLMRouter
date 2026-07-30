#!/usr/bin/env python3
import argparse, json, sys
from pathlib import Path
import torch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"scripts")]
from kqapro_e4_generate import DEFAULT_DATASET, MODELS, file_sha256, query_row, read_json, read_jsonl, run_resumable_model, sampled_indices, value_sha256, write_json, write_jsonl
from llmrouter.utils.embeddings import get_longformer_embedding

def prepare(out,size,seed):
    out.mkdir(parents=True,exist_ok=True)
    val=read_json(DEFAULT_DATASET/"val.json")
    e4=read_json(ROOT/"data/kqapro/e4/partition_manifest.json")
    e6=read_json(ROOT/"data/kqapro/e6_final3/partition_manifest.json")
    excluded=set(e4["dev_indices"])|set(e4["final_indices"])|set(e6["final3_indices"])
    indices=sampled_indices(len(val),size,seed,excluded)
    manifest={"version":1,"purpose":"cost_policy_development_only","size":size,"seed":seed,"source_count":len(val),"excluded_prior_eval_count":len(excluded),"overlap_with_prior_eval":len(set(indices)&excluded),"indices":indices,"indices_sha256":value_sha256(indices),"val_source_sha256":e4["val_source_sha256"]}
    write_json(out/"partition_manifest.json",manifest)
    prereg={"experiment_id":"kqapro_cost_dev_v1","created_utc":"2026-07-18","development_only":True,"final3_forbidden":True,"sample_size":size,"sample_seed":seed,"operating_points":{"quality_first":{"epsilon_accuracy":0.0025,"min_coverage":0.10,"max_harm_rate":0.025},"balanced":{"epsilon_accuracy":0.005,"min_coverage":0.20,"max_harm_rate":0.04},"cost_first":{"epsilon_accuracy":0.01,"min_coverage":0.40,"max_harm_rate":0.06}},"selection":"maximize parameter-size saving among feasible candidates; paired bootstrap lower CI must be >= -epsilon","bootstrap":{"replicates":5000,"seed":20260718},"confirmation":"freeze one selected operating point, then evaluate once on a new disjoint sealed set"}
    write_json(out/"PREREGISTRATION.json",prereg)
    (out/"PREREGISTRATION.sha256").write_text(file_sha256(out/"PREREGISTRATION.json")+"  PREREGISTRATION.json\n")
    return val,indices

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output-dir",type=Path,default=ROOT/"data/kqapro/cost_dev_v1");ap.add_argument("--size",type=int,default=1500);ap.add_argument("--seed",type=int,default=20260718);ap.add_argument("--batch-size",type=int,default=16);ap.add_argument("--prepare-only",action="store_true");a=ap.parse_args()
    val,idx=prepare(a.output_dir,a.size,a.seed)
    if a.prepare_only: print("prepared",len(idx));return
    samples=[(i,val[i]) for i in idx]; parts={"train":samples,"final":[]}
    for key,repo,size in MODELS: run_resumable_model(key,repo,size,parts,a.output_dir,a.batch_size,0.05)
    queries=[query_row(x,"cost_dev",i) for i,x in samples];write_jsonl(a.output_dir/"query_cost_dev.jsonl",queries)
    ep=a.output_dir/"query_embeddings_longformer.pt"
    if not ep.exists():
        emb={}
        for start in range(0,len(queries),32):
            vec=get_longformer_embedding([r["query"] for r in queries[start:start+32]])
            emb.update({start+j:v for j,v in enumerate(vec)});print("embeddings",min(start+32,len(queries)),len(queries))
        torch.save(emb,ep)
    emb=torch.load(ep,map_location="cpu"); qid={r["query"]:i for i,r in enumerate(queries)}; routing=[]
    for key,_,_ in MODELS:
        rows=read_jsonl(a.output_dir/"partial/train"/f"{key}.jsonl")
        if len(rows)!=len(queries): raise ValueError((key,len(rows)))
        for r in rows:r["embedding_id"]=qid[r["query"]];r["task_id"]=r["task_id"].replace("-train-","-cost_dev-")
        routing.extend(rows)
    write_jsonl(a.output_dir/"routing_cost_dev.jsonl",routing)
    write_json(a.output_dir/"llm_candidates.json",read_json(ROOT/"data/kqapro/e4/llm_candidates.json"))
    write_json(a.output_dir/"development_seal.json",{"routing_sha256":file_sha256(a.output_dir/"routing_cost_dev.jsonl"),"query_sha256":file_sha256(a.output_dir/"query_cost_dev.jsonl"),"development_metrics_may_be_read":True})
    print("cost development data complete")
if __name__=="__main__":main()
