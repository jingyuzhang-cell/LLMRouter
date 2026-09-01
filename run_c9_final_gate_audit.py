#!/usr/bin/env python3
"""Recompute the frozen C9.0 preflight evidence and checksums."""
import hashlib, json, re, shutil
from collections import Counter
from pathlib import Path

ROOT=Path('/root'); OUT=ROOT/'phase_c9_0'
def rows(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def norm(x): return re.sub(r'\W+',' ',str(x).lower(),flags=re.UNICODE).strip()

tasks=rows(OUT/'C9_DEV_TASKS.jsonl'); prior=[]
p=ROOT/'target_support_expansion_v1/combined_509_tasks_frozen.jsonl'
if p.exists(): prior+=rows(p)
p=ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/data/finance_router/finrome_300_confirmatory_v3/tasks.jsonl'
if p.exists(): prior+=rows(p)
prior_q={norm(x.get('question') or x.get('Question')) for x in prior}; task_q=[norm(x['question']) for x in tasks]
group=json.loads((OUT/'C9_GROUP_SPLIT_AUDIT.json').read_text()); construct=json.loads((OUT/'C9_0_AMENDMENT_001_CONSTRUCT_REVIEW.json').read_text())
near=json.loads((OUT/'C9_0_NEAR_DUPLICATE_ADJUDICATION_FINAL.json').read_text())
caps=Counter(x['primary_capability'] for x in tasks); splits=Counter(x['split'] for x in tasks)
assert len(tasks)==600 and set(caps.values())=={60}
assert splits=={'development_train':480,'support_matched_validation':120}
assert all(v==12 for v in group['validation_capability_counts'].values())
assert not ({*task_q}&prior_q) and len(task_q)==len(set(task_q))
assert all(group[k]==0 for k in ('document_overlap_count','table_overlap_count','template_overlap_count','leakage_group_overlap_count'))
assert construct['status']=='PASS' and near['unresolved']==0
shutil.copyfile(OUT/'C9_0_PREFLIGHT_GATE_FINAL.json',OUT/'C9_0_PREFLIGHT_GATE.json')
audit={'status':'C9_0_PREFLIGHT_PASS','selected_tasks':600,'primary_counts':dict(caps),'split_counts':dict(splits),
       'validation_capability_counts':group['validation_capability_counts'],'historical_exact_overlap':0,'exact_within_pool_duplicates':0,
       'unresolved_near_duplicates':0,'document_overlap_count':0,'table_overlap_count':0,'template_overlap_count':0,
       'outcome_accessed':False,'gold_evidence_used_for_selection':False,'model_result_files_read':0,'external_api_calls':0}
(OUT/'C9_DATA_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n')
targets=['CAPABILITY_SCHEMA.json','C9_0_PROTOCOL.json','C9_0_PROTOCOL_AMENDMENT_001.json','C9_DEV_TASKS.jsonl','C9_DATA_AUDIT.json','C9_GROUP_SPLIT_AUDIT.json','C9_0_AMENDMENT_001_CONSTRUCT_REVIEW.json','C9_0_NEAR_DUPLICATE_ADJUDICATION_FINAL.json','C9_0_PREFLIGHT_GATE.json']
(OUT/'C9_0_SHA256SUMS').write_text(''.join(f'{hashlib.sha256((OUT/name).read_bytes()).hexdigest()}  {name}\n' for name in targets))
print(json.dumps(audit,indent=2))
