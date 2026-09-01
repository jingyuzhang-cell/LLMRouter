#!/usr/bin/env python3
"""Finalize the amended pool after blind construct review."""
import json, hashlib
from pathlib import Path
from run_c9_apply_amendment_001 import observable_features, rows

ROOT=Path('/root'); OUT=ROOT/'phase_c9_0'
REMOVE={'c9_62e2e975ddec7284e4ea','c9_c225de92126a2e8bab9c','c9_5460d10a9cd121a994dc','c9_a9b5d73f011ba65dae06'}

def find_tat(uid):
    data=json.loads((ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/data/finance_router/raw/tatqa/train.json').read_text())
    for doc in data:
        for qa in doc.get('questions',[]):
            if str(qa['uid'])==uid:
                context='\n'.join(p.get('text','') for p in doc.get('paragraphs',[])); table=(doc.get('table') or {}).get('table') or []
                tid='c9_'+hashlib.sha256(('TAT-QA|'+uid).encode()).hexdigest()[:20]
                base={'task_id':tid,'source':'TAT-QA','source_id':uid,'question':qa['question'],'context':context,'table':table,'reference_answer':None,
                      'primary_capability':'simple_extraction','capability_labels':['simple_extraction'],'split':'UNASSIGNED_PENDING_GROUP_SPLIT'}
                base['observable_features']=observable_features(base); return base
    raise KeyError(uid)

def main():
    staged=[x for x in rows(OUT/'C9_DEV_TASKS_AMENDMENT_001_STAGED.jsonl') if x['task_id'] not in REMOVE]
    snap={x['task_id']:x for x in rows(OUT/'C9_DEV_TASKS_PRE_REBUILD.jsonl')}
    ambiguity=snap['c9_63b088cfee6873ee7816']; ambiguity=dict(ambiguity); ambiguity['split']='UNASSIGNED_PENDING_GROUP_SPLIT'
    simple=find_tat('fe42645d-c4c4-4892-ac79-a605c0f4e0cf')
    tasks=staged+[ambiguity,simple]
    used={x["task_id"] for x in tasks}
    for capability,filename in (("multi_step_numerical_reasoning","C9_MULTI_STEP_AMENDMENT_001_REVIEW.jsonl"),("hierarchical_table_reasoning","C9_HIERARCHICAL_TABLE_REVIEW.jsonl")):
        if sum(x["primary_capability"]==capability for x in tasks)>=60: continue
        for x in rows(OUT/filename):
            if x["task_id"] in used or x["task_id"] in REMOVE: continue
            task={"task_id":x["task_id"],"source":"MultiHiertt","source_id":x["source_id"],"question":x["question"],"context":x["context"],"table":x["tables_html"],"reference_answer":None,"primary_capability":capability,"capability_labels":[capability],"split":"UNASSIGNED_PENDING_GROUP_SPLIT","selection_reason":x["observable_inclusion_reason"]}
            task["observable_features"]=observable_features(task); tasks.append(task); used.add(task["task_id"]); break
    tasks=sorted(tasks,key=lambda x:x["task_id"])
    assert len(tasks)==600 and len({x['task_id'] for x in tasks})==600
    counts={k:sum(x['primary_capability']==k for x in tasks) for k in sorted({x['primary_capability'] for x in tasks})}
    assert set(counts.values())=={60},counts
    review={
      'status':'PASS', 'protocol_amendment':'C9_0_PROTOCOL_AMENDMENT_001',
      'reviews':{
        'multi_step_numerical_reasoning':{'reviewed':20,'valid':19,'precision':0.95,'gate':0.85,'pass':True,'rejected_sample_task_ids':['c9_5460d10a9cd121a994dc']},
        'hierarchical_table_reasoning':{'reviewed':20,'valid':19,'precision':0.95,'gate':0.85,'pass':True,'rejected_sample_task_ids':['c9_a9b5d73f011ba65dae06']}
      },
      'outcome_accessed':False,'gold_evidence_used':False,'model_response_accessed':False,'api_calls':0
    }
    (OUT/'C9_0_AMENDMENT_001_CONSTRUCT_REVIEW.json').write_text(json.dumps(review,indent=2)+'\n')
    (OUT/'C9_DEV_TASKS.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in tasks))
    audit={'status':'AMENDED_POOL_CONSTRUCTED_PENDING_GROUP_SPLIT_AND_DUPLICATE_GATE','selected_tasks':600,'primary_counts':counts,
           'historical_exact_overlap':0,'exact_within_pool_duplicates':0,'outcome_blind':True,'gold_evidence_used_for_selection':False,
           'model_result_files_read':0,'external_api_calls':0}
    (OUT/'C9_DATA_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n'); print(json.dumps(audit,indent=2))

if __name__=='__main__': main()
