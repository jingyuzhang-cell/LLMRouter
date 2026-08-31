#!/usr/bin/env python3
"""Select and stage the two amended C9 strata without outcomes or gold fields."""
import hashlib, json, re
from pathlib import Path

ROOT=Path('/root'); OUT=ROOT/'phase_c9_0'; SEED='20260831|C9_0_PROTOCOL_AMENDMENT_001'
REPLACED={'multi_step_numerical_reasoning','table_text_hybrid_reasoning','hierarchical_table_reasoning'}

def rows(path): return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
def norm(x): return re.sub(r'\W+',' ',str(x).lower(),flags=re.UNICODE).strip()
def stable(x): return hashlib.sha256((SEED+'|'+x).encode()).hexdigest()
def toks(x): return re.findall(r'[a-zA-Z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]',str(x).lower())

def observable_features(task):
    q=str(task['question']); c=str(task.get('context') or ''); tables=task.get('table') or []
    rendered=' '.join(map(str,tables)); text=(q+' '+c+' '+rendered).lower(); qt=toks(q); ct=toks(c)
    cells=re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>',rendered,flags=re.I|re.S)
    cells=[re.sub(r'<[^>]+>',' ',x) for x in cells]
    paragraphs=[x for x in re.split(r'\n\s*\n|\n',c) if x.strip()]
    terms=lambda ws:sum(text.count(w) for w in ws); qterms=lambda ws:sum(q.lower().count(w) for w in ws)
    numeric_cells=sum(bool(re.search(r'\d',x)) for x in cells)
    return {
      'query_token_count':len(qt),'context_token_count':len(ct),'sentence_count':len(re.findall(r'[.!?]+',c)),
      'paragraph_count':len(paragraphs),'numeric_count':len(re.findall(r'[-+]?[$£€]?\d[\d,.]*%?',text)),
      'percentage_count':len(re.findall(r'\d\s*%|percent',text)),'currency_count':len(re.findall(r'[$£€]|\b(?:usd|dollar|million|billion)\b',text)),
      'arithmetic_cue_count':terms(('difference','increase','decrease','ratio','percent','average','total','sum','minus','divided','growth','change'))+len(re.findall(r'[+*/=]',q)),
      'table_rows':len(re.findall(r'<tr[ >]',rendered,re.I)),'table_columns':0,'table_cell_count':len(cells),
      'numeric_cell_ratio':numeric_cells/max(1,len(cells)),'comparison_cue_count':terms(('compare','between','versus','higher','lower','largest','smallest','respectively')),
      'reasoning_cue_count':terms(('why','how','therefore','calculate','determine','relationship','relate','based on')),
      'conjunction_count':len(re.findall(r'\b(?:and|then|both|while)\b',q.lower())),'cross_reference_count':qterms(('section','article','rule','paragraph','clause','regulation','regulatory','requirement','filing')),
      'modal_count':qterms(('must','shall','should','may','required','prohibited','permitted','eligible','comply','compliance')),
      'negation_count':len(re.findall(r'\b(?:not|no|never|without|neither)\b|不',text)),'exception_count':qterms(('except','unless','notwithstanding','subject to','provided that','only if')),
      'uncertainty_count':qterms(('unclear','ambiguous','uncertain','possibly','likely','may')),'conditional_count':len(re.findall(r'\b(?:if|when|provided|assuming|given that)\b',q.lower())),
      'evidence_cue_count':terms(('according to','based on','evidence','disclosed','support','explain','relate')),
      'question_entity_count':len(re.findall(r'\b[A-Z][A-Za-z.&-]+',q)),'context_dispersion_proxy':min(len(paragraphs),20)+min(len(c)//1000,20)
    }

def main():
    old=rows(OUT/'C9_DEV_TASKS.jsonl'); frozen=[x for x in old if x['primary_capability'] not in REPLACED]
    assert len(frozen)==480, len(frozen)
    prior=[]
    prior_path=ROOT/'target_support_expansion_v1/combined_509_tasks_frozen.jsonl'
    if prior_path.exists(): prior+=rows(prior_path)
    v3=ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/data/finance_router/finrome_300_confirmatory_v3/tasks.jsonl'
    if v3.exists(): prior+=rows(v3)
    forbidden_q={norm(x.get('question') or x.get('Question')) for x in prior+frozen}
    used_ids={x['task_id'] for x in frozen}; used_q=set(forbidden_q)
    specs=[('multi_step_numerical_reasoning','C9_MULTI_STEP_AMENDMENT_001_REVIEW.jsonl'),('hierarchical_table_reasoning','C9_HIERARCHICAL_TABLE_REVIEW.jsonl')]
    selected=[]
    for capability,filename in specs:
        eligible=[]
        for x in rows(OUT/filename):
            nq=norm(x['question'])
            if x['task_id'] in used_ids or not nq or nq in used_q: continue
            eligible.append(x); used_ids.add(x['task_id']); used_q.add(nq)
            if len(eligible)==60: break
        assert len(eligible)==60,(capability,len(eligible))
        for x in eligible:
            task={'task_id':x['task_id'],'source':'MultiHiertt','source_id':x['source_id'],'question':x['question'],
                  'context':x['context'],'table':x['tables_html'],'reference_answer':None,'primary_capability':capability,
                  'capability_labels':[capability],'observable_features':observable_features({'question':x['question'],'context':x['context'],'table':x['tables_html']}),
                  'split':'UNASSIGNED_PENDING_GROUP_SPLIT','selection_reason':x['observable_inclusion_reason']}
            selected.append(task)
        sample=sorted(eligible,key=lambda x:stable('review20|'+x['task_id']))[:20]
        (OUT/('C9_'+capability.upper()+'_BLIND_REVIEW_20.jsonl')).write_text(''.join(json.dumps({k:x[k] for k in ('task_id','source_dataset','question','context','tables_html','observable_inclusion_reason')}|{'review_decision':None,'review_reason':None},ensure_ascii=False)+'\n' for x in sample))
    staged=sorted(frozen+selected,key=lambda x:x['task_id'])
    assert len(staged)==600 and len({x['task_id'] for x in staged})==600
    (OUT/'C9_DEV_TASKS_AMENDMENT_001_STAGED.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in staged))
    audit={'status':'STAGED_PENDING_20_ITEM_BLIND_REVIEWS','counts':{k:sum(x['primary_capability']==k for x in staged) for k in sorted({x['primary_capability'] for x in staged})},
           'historical_exact_overlap':0,'pool_exact_duplicate':0,'outcome_accessed':False,'gold_evidence_used_for_selection':False,'external_model_calls':0}
    (OUT/'C9_0_AMENDMENT_001_STAGING_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n'); print(json.dumps(audit,indent=2))

if __name__=='__main__': main()
