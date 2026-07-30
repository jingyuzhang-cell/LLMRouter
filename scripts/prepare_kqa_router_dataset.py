#!/usr/bin/env python3
"""Aggregate per-model KQAPro data and deterministically split by task_id."""
import argparse,csv,hashlib,json
from pathlib import Path
from kqa_routing_utils import MODEL_SPECS, load_jsonl, normalized_status, validate_file
ROOT=Path(__file__).resolve().parents[1]; DEFAULT=ROOT/"data/kqapro/router_data"
def split_ids(ids,seed):
    ordered=sorted(ids,key=lambda x:hashlib.sha256(f"{seed}:{x}".encode()).hexdigest()); n=len(ordered); ntrain=int(n*.70); nval=int(n*.15)
    return {"train":ordered[:ntrain],"validation":ordered[ntrain:ntrain+nval],"test":ordered[ntrain+nval:]}
def main():
    p=argparse.ArgumentParser();p.add_argument("--data-dir",type=Path,default=DEFAULT);p.add_argument("--models",nargs="+",default=["deepseek","qwen","zhipu","gemini","qwen-3b-local"],choices=MODEL_SPECS);p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--seed",type=int,default=20260722);p.add_argument("--apply",action="store_true");a=p.parse_args()
    tables={}
    for m in a.models:
        path=a.data_dir/MODEL_SPECS[m]["file"]; check=validate_file(path)
        if not check["passed"]:raise SystemExit(f"validation failed: {m}")
        rows,_=load_jsonl(path);tables[m]={r["task_id"]:r for r in rows}
    ids=set.intersection(*(set(x) for x in tables.values())); splits=split_ids(ids,a.seed)
    manifest={"schema":"kqapro-router-split-plan-v1","dry_run":not a.apply,"seed":a.seed,"ratios":{"train":.70,"validation":.15,"test":.15},"models":a.models,"tasks":len(ids),"counts":{k:len(v) for k,v in splits.items()},"disjoint":not(set(splits['train'])&set(splits['validation']) or set(splits['train'])&set(splits['test']) or set(splits['validation'])&set(splits['test']))}
    if not a.apply: print(json.dumps(manifest,ensure_ascii=False,indent=2));return
    if a.output_dir.exists():raise SystemExit(f"refusing to overwrite {a.output_dir}")
    a.output_dir.mkdir(parents=True)
    matrix=[]
    for tid in sorted(ids):
        first=tables[a.models[0]][tid];matrix.append({"task_id":tid,"query":first["query"],"ground_truth":first["ground_truth"],"choices":first["choices"],"models":{m:{**{k:tables[m][tid].get(k) for k in ("response","predicted_label","correct","performance","error_type","cost_proxy","response_time","input_tokens","output_tokens")},"status":normalized_status(tables[m][tid])} for m in a.models}})
    lookup={r['task_id']:r for r in matrix}
    for name,task_ids in splits.items():
        with (a.output_dir/f"{name}.jsonl").open('w') as f:
            for tid in task_ids:f.write(json.dumps(lookup[tid],ensure_ascii=False)+'\n')
        columns=["task_id","query","ground_truth"]+[f"{m}_{field}" for m in a.models for field in ("response","predicted_label","correct","status","cost_proxy","response_time","input_tokens","output_tokens")]
        with (a.output_dir/f"{name}.csv").open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
            for tid in task_ids:
                item=lookup[tid];flat={k:item[k] for k in ("task_id","query","ground_truth")}
                for m in a.models:
                    for field in ("response","predicted_label","correct","status","cost_proxy","response_time","input_tokens","output_tokens"):
                        flat[f"{m}_{field}"]=item["models"][m].get(field)
                writer.writerow(flat)
        (a.output_dir/f"{name}_task_ids.txt").write_text('\n'.join(task_ids)+'\n')
    manifest['dry_run']=False;(a.output_dir/'split_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2))
if __name__=="__main__":main()
