#!/usr/bin/env python3
"""Freeze a balanced 300-task finance set before any new model outcomes."""
import hashlib,json,random
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from scripts.build_finance_experiment_sample import finqa_records,tatqa_records,obliqa_records,finreflect_records
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'data/finance_router/finrome_300';SEED=20260808
MODELS=['deepseek-chat','deepseek-coder','doubao','doubao-seed-2.1-turbo']
def main():
 random.seed(SEED);pools=[('FinQA',finqa_records(),75),('TAT-QA',tatqa_records(),75),('ObliQA',obliqa_records(),75),('FinReflectKG',finreflect_records(),75)];rows=[]
 for name,pool,n in pools:
  pool=sorted(pool,key=lambda x:x['id']);rng=random.Random(SEED+len(rows));rows.extend(rng.sample(pool,n))
 assert len(rows)==300 and len({x['id'] for x in rows})==300
 rng=random.Random(SEED);rng.shuffle(rows);split={'train':sorted(x['id'] for x in rows[:210]),'calibration':sorted(x['id'] for x in rows[210:255]),'test':sorted(x['id'] for x in rows[255:])};OUT.mkdir(parents=True,exist_ok=True);taskfile=OUT/'tasks.jsonl';taskfile.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows));sha=hashlib.sha256(taskfile.read_bytes()).hexdigest();protocol={'version':'finrome-300-v1','created_at':datetime.now(timezone.utc).isoformat(),'frozen_before_outcomes':True,'seed':SEED,'tasks':300,'dataset_counts':dict(Counter(x['dataset'] for x in rows)),'risk_counts':dict(Counter(x.get('risk_level') for x in rows)),'models':MODELS,'repeats':3,'required_answer_calls':3600,'split':split,'split_counts':{k:len(v) for k,v in split.items()},'task_sha256':sha,'stopping_rule':'complete all 3600 jobs; partial matrix is not merged or analysed as complete','retry_rule':'at most 2 retries for transport/429/5xx; authentication errors stop the provider','test_isolation':'test outcomes are written to checkpoint but not read until train/calibration decisions are frozen'};(OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in protocol.items() if k!='split'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
