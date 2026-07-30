#!/usr/bin/env python3
"""Read-only readiness gate for the NVIDIA confirmatory workflow."""
import argparse,hashlib,json,subprocess
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(name,ok,detail,rows,critical=True):rows.append({"name":name,"passed":bool(ok),"critical":critical,"detail":detail})
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--phase",choices=["waiting","pre_confirmation"],default="waiting");a=ap.parse_args();rows=[];d=ROOT/"data/nvidia_confirm_v1";seal=json.loads((d/"SEAL.json").read_text());pre=json.loads((d/"PREREGISTRATION.json").read_text());auth=json.loads((d/"AUTHORIZATION.json").read_text())
 check("preregistration_hash",sha(d/"PREREGISTRATION.json")== (d/"PREREGISTRATION.sha256").read_text().split()[0],sha(d/"PREREGISTRATION.json"),rows)
 check("queries_seal",sha(d/"queries_sealed.jsonl")==seal["queries_sha256"],seal["queries_sha256"],rows)
 check("manifest_seal",sha(d/"manifest.jsonl")==seal["manifest_sha256"],seal["manifest_sha256"],rows)
 q=pd.read_json(d/"queries_sealed.jsonl",lines=True);dev=pd.read_json(ROOT/"data/nvidia_current_v1/queries.jsonl",lines=True);m=pd.read_json(d/"manifest.jsonl",lines=True)
 check("sealed_query_count",len(q)==1000,len(q),rows);check("development_confirmation_overlap",not set(q["query"])&set(dev["query"]),len(set(q["query"])&set(dev["query"])),rows)
 keys=m[["query","model_name","repeat_index"]];check("manifest_jobs",len(m)==12000,len(m),rows);check("manifest_unique_jobs",not keys.duplicated().any(),int(keys.duplicated().sum()),rows)
 check("authorization_scope",auth.get("authorized_calls")==12000 and auth.get("sequence_enforced"),auth,rows)
 text=(ROOT/"scripts/run_nvidia_confirm_pipeline.sh").read_text();positions=[text.find(x) for x in ["aggregate_nvidia_current_pool.py","llmrouter train","FROZEN_ROUTER.json","predict_nvidia_confirm_router.py","collect_mlprouter_reevaluations.py --manifest data/nvidia_confirm_v1","evaluate_nvidia_confirm_once.py"]]
 check("pipeline_order",all(x>=0 for x in positions) and positions==sorted(positions),positions,rows)
 ignored=subprocess.run(["git","check-ignore","-q",".env"],cwd=ROOT).returncode==0;tracked=subprocess.run(["git","ls-files","--error-unmatch",".env"],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
 check("env_ignored_and_untracked",ignored and not tracked,{"ignored":ignored,"tracked":tracked},rows)
 result_exists=(d/"results.jsonl").exists();lock_exists=(ROOT/"run_logs/nvidia_confirm_v1/evaluation/EVALUATED_ONCE").exists()
 if not seal.get("api_calls_started"):check("no_early_confirmation_results",not result_exists,result_exists,rows)
 check("no_early_evaluation_lock",not lock_exists or seal.get("collection_complete",False),lock_exists,rows)
 current=sum(1 for _ in (ROOT/"data/nvidia_current_v1/results.jsonl").open());check("development_progress_bounds",0<=current<=3600,current,rows)
 sessions=subprocess.run(["screen","-ls"],capture_output=True,text=True).stdout;check("development_collector_alive","nvidia_current_v1" in sessions,sessions.strip(),rows);check("continuation_pipeline_alive","nvidia_confirm_pipeline" in sessions,sessions.strip(),rows)
 if a.phase=="pre_confirmation":
  check("development_complete",current>=3600,current,rows);cp=ROOT/"llmrouter/saved_models/mlprouter/mlprouter_nvidia_current_v1_seed42.pkl";check("checkpoint_exists",cp.exists(),str(cp),rows)
 report={"phase":a.phase,"passed":all(x["passed"] for x in rows if x["critical"]),"checks":rows};out=ROOT/"run_logs/nvidia_confirm_v1/readiness.json";out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
 if not report["passed"]:raise SystemExit(2)
if __name__=="__main__":main()
