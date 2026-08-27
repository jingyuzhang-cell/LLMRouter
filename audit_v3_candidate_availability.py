#!/usr/bin/env python3
"""Outcome-blind availability audit for the proposed 120-task v3 holdout."""
import hashlib,json
from collections import Counter
from pathlib import Path
ROOT=Path('/root');DATA=ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/data/finance_router';EXP=ROOT/'target_support_expansion_v1';OUT=ROOT/'phase_c3'
SOURCES=('finrome_legacy_v2_confirmatory','finrome_300_confirmatory_v3','finrome_300','safety_expansion_v1');QUOTA={('TAT-QA','medium'):60,('TAT-QA','low'):20,('ObliQA','high'):40}
def read(p):return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
used=read(EXP/'combined_509_tasks_frozen.jsonl');v2=read(DATA/'safety_expansion_v2_counterexample_enrichment/tasks.jsonl');used_ids={x['id'] for x in used};v2_ids={x['id'] for x in v2};used_text={hashlib.sha256(' '.join((str(x.get('question',''))+' '+str(x.get('context',''))).lower().split()).encode()).hexdigest() for x in used};seen_ids=set();seen_text=set();counts=Counter()
for source in SOURCES:
 for x in read(DATA/source/'tasks.jsonl'):
  key=(str(x.get('dataset')),str(x.get('risk_level')).lower());kind=str(x.get('task_type'));digest=hashlib.sha256(' '.join((str(x.get('question',''))+' '+str(x.get('context',''))).lower().split()).encode()).hexdigest()
  if key not in QUOTA or x['id'] in used_ids or x['id'] in v2_ids or x['id'] in seen_ids or digest in used_text or digest in seen_text:continue
  if key[0]=='TAT-QA' and kind!='financial_table_text_reasoning':continue
  if key[0]=='ObliQA' and kind!='financial_audit_compliance_qa':continue
  seen_ids.add(x['id']);seen_text.add(digest);counts[key]+=1
availability={f'{k[0]}:{k[1]}':{'required':q,'available':counts[k],'sufficient':counts[k]>=q,'shortfall':max(0,q-counts[k])} for k,q in QUOTA.items()};report={'selection_outcome_blind':True,'excluded_existing_509':len(used_ids),'excluded_v2':len(v2_ids),'normalized_text_deduplication':True,'availability':availability,'can_freeze_requested_120':all(x['sufficient'] for x in availability.values()),'external_api_calls':0,'next_action':'obtain new source tasks for deficient strata; do not reuse v2 or existing tasks' if not all(x['sufficient'] for x in availability.values()) else 'freeze v3 task manifest'}
(OUT/'V3_CANDIDATE_AVAILABILITY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
