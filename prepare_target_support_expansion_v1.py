#!/usr/bin/env python3
"""Freeze an outcome-blind 300-task target-support development expansion."""

import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


SEED=20260828
ROOT=Path('/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/data/finance_router')
PILOT=Path('/root/gemini_frar_pilot/five_model_v1')
OUT=Path('/root/target_support_expansion_v1')
SOURCES=('finrome_legacy_v2_confirmatory','finrome_300_confirmatory_v3','finrome_300','safety_expansion_v1')
QUOTA={('TAT-QA','medium'):150,('TAT-QA','low'):50,('ObliQA','high'):100}
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash')

def read(path):return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
used={x['id'] for x in read(PILOT/'gemini_training_pilot_tasks.jsonl')};v2={x['id'] for x in read(ROOT/'safety_expansion_v2_counterexample_enrichment/tasks.jsonl')}
seen_id=set();seen_text=set();pools=defaultdict(list)
for source in SOURCES:
    for task in read(ROOT/source/'tasks.jsonl'):
        if task['id'] in used or task['id'] in v2 or task['id'] in seen_id:continue
        key=(str(task.get('dataset')),str(task.get('risk_level')).lower());kind=str(task.get('task_type'))
        if key not in QUOTA:continue
        if key[0]=='TAT-QA' and kind!='financial_table_text_reasoning':continue
        if key[0]=='ObliQA' and kind!='financial_audit_compliance_qa':continue
        normalized=' '.join((str(task.get('question',''))+' '+str(task.get('context',''))).lower().split());digest=hashlib.sha256(normalized.encode()).hexdigest()
        if digest in seen_text:continue
        seen_id.add(task['id']);seen_text.add(digest);row=dict(task);row['_source_dataset_dir']=source;pools[key].append(row)
rng=random.Random(SEED);selected=[]
for key,count in QUOTA.items():
    values=sorted(pools[key],key=lambda x:x['id']);rng.shuffle(values);assert len(values)>=count;selected.extend(values[:count])
rng.shuffle(selected)
assert len(selected)==300 and len({x['id'] for x in selected})==300 and not ({x['id'] for x in selected}&used) and not ({x['id'] for x in selected}&v2)
OUT.mkdir(parents=True,exist_ok=True);tasks_path=OUT/'TARGET_SUPPORT_EXPANSION_TASKS.jsonl';tasks_path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in selected))
protocol={'version':'target-support-expansion-v1','status':'FROZEN_BEFORE_GEMINI_OUTCOMES','seed':SEED,'selection_outcome_blind':True,
          'selection_features':['dataset','risk_level','task_type','task id uniqueness','normalized text uniqueness','four-model key completeness'],
          'forbidden_selection_features':['quality','utility','failure','winner','any model response text','v2 diagnostic outcomes'],
          'tasks':300,'distribution':dict(Counter(f"{x['dataset']}:{x['risk_level']}" for x in selected)),'source_distribution':dict(Counter(x['_source_dataset_dir'] for x in selected)),
          'models':MODELS,'repeats':3,'existing_four_model_calls':300*4*3,'new_gemini_response_calls':300*3,
          'compliance_tasks':100,'new_dual_judge_calls':100*3*2,'old_pilot_overlap':0,'v2_overlap':0,
          'quality_rule':'objective; compliance=0.55*objective+0.45*dual_judge_mean','repeat_aggregation':'mean','best_repeat_prohibited':True,
          'next_gate':'rerun frozen C1 and group-conditional protocols; no FRAR or v3 unless gate passes'}
protocol_path=OUT/'TARGET_SUPPORT_EXPANSION_PROTOCOL.json';protocol_path.write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n')
for path in (tasks_path,protocol_path):(OUT/(path.name+'.sha256')).write_text(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name+'\n')
print(json.dumps(protocol,ensure_ascii=False,indent=2))
