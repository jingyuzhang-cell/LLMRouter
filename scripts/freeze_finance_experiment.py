"""Freeze the finance benchmark and protocol before final evaluation."""
from __future__ import annotations
import argparse, csv, hashlib, json, shutil
from datetime import datetime, timezone
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"data/finance_router/standardized/finance_router_tasks.jsonl"
MANIFEST=ROOT/"data/finance_router/standardized/finance_experiment_manifest.json"
FREEZE_DIR=ROOT/"data/finance_router/frozen/v1"

def sha(path):
 d=hashlib.sha256(); d.update(path.read_bytes()); return d.hexdigest()

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--allow-pending-review",action="store_true")
 ap.add_argument("--no-human-signoff",action="store_true")
 args=ap.parse_args()
 rows=[json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
 pending=[row for row in rows if str(row.get("review_status","")).endswith("pending")]
 if pending and not (args.allow_pending_review or args.no_human_signoff):
  raise SystemExit(f"Refusing final freeze: {len(pending)} samples still require human sign-off. Use --allow-pending-review for a candidate freeze.")
 FREEZE_DIR.mkdir(parents=True,exist_ok=True)
 frozen=FREEZE_DIR/"finance_benchmark_v1.jsonl"; shutil.copyfile(SOURCE,frozen)
 config_path=ROOT/"configs/openclaw_multi_provider.yaml"
 config=yaml.safe_load(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
 models=[]
 experiment_model_pool={"deepseek-chat","qwen-plus","qwen-turbo","glm-5.2"}
 for name,item in (config.get("llms") or {}).items():
  if name in experiment_model_pool: models.append({"name":name,"provider":item.get("provider"),"model":item.get("model"),"base_url":item.get("base_url"),"input_price":item.get("input_price"),"output_price":item.get("output_price")})
 status=("final_frozen_without_human_expert_review" if args.no_human_signoff
         else "candidate_frozen_pending_human_signoff" if pending else "final_frozen")
 protocol={
  "freeze_id":"finance-router-benchmark-v1","status":status,
  "created_utc":datetime.now(timezone.utc).isoformat(),"sample_count":len(rows),"sample_ids":[row["id"] for row in rows],
  "dataset_sha256":sha(frozen),"source_manifest_sha256":sha(MANIFEST),"sampling_seed":20260727,
  "weights":{"quality":.45,"cost":.20,"latency":.15,"reliability":.20},"risk_lambda":1.0,
  "normalization":{"cost_usd_budget":.02,"token_budget_when_price_missing":3000,"latency_sla_ms":10000},
  "repeats":3,"final_task_count":100,"pilot_task_count":10,"pilot_excluded_from_final":True,
  "quality_evaluation":{"objective_weight":.6,"judge_weight":.4,"judge_count":2,"manual_review_disagreement_threshold":.20},
  "models":models,"model_config_sha256":sha(config_path) if config_path.exists() else None,
  "prompt_implementation":{"file":"openclaw_router/server.py","sha256":sha(ROOT/"openclaw_router/server.py")},
  "pending_human_review_ids":[row["id"] for row in pending],
  "human_expert_review":False if args.no_human_signoff else not bool(pending),
  "human_review_disclosure":(
   "No human domain-expert sign-off was performed. Evidence checks were automated and must not be described as expert human review."
   if args.no_human_signoff else None
  ),
  "pilot_model_change":{
   "original_model":"gemini-2.5-flash",
   "replacement_model":"qwen-turbo",
   "stage":"pilot",
   "reason":"Gemini API quota exhaustion",
   "disclosure_required":True
  },
  "anti_cherry_picking":"After final_frozen status, sample replacement, weight changes, prompt changes, or model-pool changes require a new freeze version and must not overwrite v1."
 }
 (FREEZE_DIR/"experiment_protocol_v1.json").write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 with (FREEZE_DIR/"human_review.csv").open("w",encoding="utf-8",newline="") as f:
  w=csv.writer(f); w.writerow(["sample_id","dataset","question","gold_answer","evidence","reviewer","decision","notes","reviewed_at"]);
  for row in pending:
   if args.no_human_signoff:
    w.writerow([row["id"],row["dataset"],row["question"],row["gold_answer"],json.dumps(row.get("evidence"),ensure_ascii=False),"automated evidence audit","AI_EVIDENCE_PASS","Automated check only; no human domain-expert sign-off.",""])
   else:
    w.writerow([row["id"],row["dataset"],row["question"],row["gold_answer"],json.dumps(row.get("evidence"),ensure_ascii=False),"","PENDING","",""])
 print(json.dumps({"status":protocol["status"],"samples":len(rows),"pending_review":len(pending),"dataset_sha256":protocol["dataset_sha256"]},ensure_ascii=False))
if __name__=="__main__": main()
