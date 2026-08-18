#!/usr/bin/env python3
"""Inject real responses into the compatibility source and rerun M3--M5."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data/finance_router/finrome_300';RUN=ROOT/'run_logs/finrome_300'
def rows(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def main():
 source=RUN/'source_compat.json';payload=json.loads(source.read_text());responses={}
 for x in rows(DATA/'responses.jsonl'):responses[(x['task_id'],x['model'],x['repeat'])]=x
 for run in payload['raw_model_runs']:
  response=responses[(run['task_id'],run['model'],run['repeat'])];run['response']=response.get('answer','');run['ok']=bool(response.get('success'));run['raw_cost_usd']=response.get('cost_usd',run.get('raw_cost_usd',0));run['latency_ms']=response.get('latency_ms',run.get('latency_ms',0))
 source.write_text(json.dumps(payload,ensure_ascii=False)+'\n');import scripts.run_finrome_formal_oof as b;b.SOURCE=source;b.SPLIT=RUN/'split.json';b.EMB=RUN/'longformer_embeddings.pt';import scripts.tune_finrome_oof as t;t.OUT=RUN/'oof_tuning';import scripts.run_finrome_m3_m5 as m;m.OUT=RUN/'m3_m5';m.OUT.mkdir(parents=True,exist_ok=True);m.main()
if __name__=='__main__':main()
