#!/usr/bin/env python3
from __future__ import annotations
import json,math,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from openclaw_router.checkpoint import load_successful
PROGRESS=ROOT/'run_logs/llmrouter_experiment_progress_v1.json';CP=ROOT/'run_logs/llmrouter_experiment_checkpoint_v1.jsonl';OUT=ROOT/'configs/judge_calibration.json';REPORT=ROOT/'run_logs/judge_calibration_fit.json'
def main():
 p=json.loads(PROGRESS.read_text());completed=load_successful(CP,p['signature']);xs=[];ys=[]
 for r in completed.values():
  scores={x['model']:float(x['score']) for x in (r.get('judge_scores') or [])}
  if 'qwen-turbo' not in scores:continue
  strict=[scores[m] for m in ('deepseek-chat','qwen-plus') if m in scores]
  if strict:xs.append(scores['qwen-turbo']);ys.append(statistics.mean(strict))
 mx,my=statistics.mean(xs),statistics.mean(ys);var=sum((x-mx)**2 for x in xs);slope=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/var if var else 1;intercept=my-slope*mx
 pred=[max(0,min(1,intercept+slope*x)) for x in xs];rmse=lambda a,b:math.sqrt(statistics.mean((x-y)**2 for x,y in zip(a,b)))
 config={'enabled':False,'status':'candidate_pending_post_run_validation','fit_snapshot_signature':p['signature'],'fit_sample_count':len(xs),'models':{'qwen-turbo':{'enabled':True,'method':'linear_to_mean_of_deepseek_and_qwen_plus','intercept':round(intercept,6),'slope':round(slope,6)}}}
 report={'n':len(xs),'raw_mean':round(mx,4),'target_mean':round(my,4),'calibrated_mean':round(statistics.mean(pred),4),'rmse_before':round(rmse(xs,ys),4),'rmse_after':round(rmse(pred,ys),4),'config':config}
 OUT.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n');REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
