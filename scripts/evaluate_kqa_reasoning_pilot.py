#!/usr/bin/env python3
"""Evaluate completed rows from the KQAPro reasoning pilot against matched baselines."""
import argparse,json,math,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from kqa_routing_utils import MODEL_SPECS,load_jsonl
BASE=ROOT/'data/kqapro/router_data';PILOT=ROOT/'data/kqapro/reasoning_pilot_v1'
def q(v,p):
 if not v:return 0.0
 x=sorted(v);i=(len(x)-1)*p;a=math.floor(i);b=math.ceil(i);return x[a] if a==b else x[a]*(b-i)+x[b]*(i-a)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--pilot-dir',type=Path,default=PILOT);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();manifest=json.loads((a.pilot_dir/'manifest.json').read_text());wanted=set(manifest['task_ids']);baselines={}
 for m in manifest['models']:
  rows,_=load_jsonl(BASE/MODEL_SPECS[m]['file']);baselines[m]={r['task_id']:r for r in rows if r['task_id'] in wanted}
 results={}
 for path in sorted(a.pilot_dir.glob('*__*.jsonl')):
  m,v=path.stem.split('__',1);rows,_=load_jsonl(path);latest={r['task_id']:r for r in rows};ids=sorted(set(latest)&set(baselines[m]));by={}
  for typ in sorted({latest[t].get('question_type','unknown') for t in ids}):
   sub=[t for t in ids if latest[t].get('question_type','unknown')==typ];by[typ]={'n':len(sub),'accuracy':sum(latest[t]['correct'] for t in sub)/len(sub),'baseline_accuracy':sum(baselines[m][t]['correct'] for t in sub)/len(sub)}
  lat=[float(latest[t].get('response_time',0)) for t in ids];cost=sum(float(latest[t].get('estimated_cost',0)) for t in ids);acc=sum(latest[t]['correct'] for t in ids)/len(ids) if ids else 0;base=sum(baselines[m][t]['correct'] for t in ids)/len(ids) if ids else 0
  results[f'{m}__{v}']={'model':m,'variant':v,'completed':len(ids),'target':manifest['size'],'complete':len(ids)==manifest['size'],'accuracy':acc,'matched_baseline_accuracy':base,'accuracy_delta':acc-base,'coverage':sum(latest[t].get('status')=='ok' for t in ids)/len(ids) if ids else 0,'mean_latency_seconds':statistics.fmean(lat) if lat else 0,'p95_latency_seconds':q(lat,.95),'input_tokens':sum(int(latest[t].get('input_tokens',0)) for t in ids),'output_tokens':sum(int(latest[t].get('output_tokens',0)) for t in ids),'estimated_cost':cost,'cost_currency':MODEL_SPECS[m]['currency'],'by_question_type':by}
 report={'schema':'kqapro-reasoning-pilot-evaluation-v1','provisional':True,'target_tasks':manifest['size'],'results':results,'promotion_rule':{'minimum_completed':manifest['size'],'accuracy_delta_gt':0,'compare_cost_and_latency':True,'do_not_overwrite_baseline':True}}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'output':str(a.output),'variants':{k:{x:y for x,y in v.items() if x in ('completed','accuracy','accuracy_delta','mean_latency_seconds','estimated_cost')} for k,v in results.items()}},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
