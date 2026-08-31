#!/usr/bin/env python3
"""Construct an outcome-blind, capability-stratified 600-task financial development pool."""
import hashlib, json, math, re
from collections import Counter
from pathlib import Path

import numpy as np
from c9_strict_constructs import eligible
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path('/root')
DATA = ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/data/finance_router'
OUT = ROOT/'phase_c9_0'; SCHEMA = OUT/'CAPABILITY_SCHEMA.json'; PROTOCOL = OUT/'C9_0_PROTOCOL.json'
SEED = 20260831
EXCLUDED_TASK_IDS = {'c9_5e584f78602577603174','c9_cb651cedf7ea24ff24a6','c9_ce68212528a1a3cc6759','c9_bcdf69b7c8acf5fdebd3','c9_3e85e41149e53646f614','c9_c54b846ac180beeb6945','c9_2877bb81eaef3320535d','c9_34b9157a3c2a878aee37','c9_a4660adcff418a3146c4','c9_affe46df441bb2b2b372','c9_b26f55a0f9d9f6784fbe','c9_f90d00dc66acbd589537'}
def candidate_task_id(x): return 'c9_'+hashlib.sha256((x['source']+'|'+x['source_id']).encode()).hexdigest()[:20]

def load(path): return json.loads(Path(path).read_text())
def read_jsonl(path): return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
def norm(s): return re.sub(r'\W+', ' ', str(s).lower(), flags=re.UNICODE).strip()
def toks(s): return re.findall(r'[a-zA-Z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]', str(s).lower())
def stable(s): return hashlib.sha256(f'{SEED}|{s}'.encode()).hexdigest()

def features(task):
    q, c, table = str(task['question']), str(task.get('context') or ''), task.get('table') or []
    text=(q+' '+c).lower(); qt=toks(q); ct=toks(c); cells=[str(v) for row in table if isinstance(row,list) for v in row]
    terms=lambda words: sum(text.count(w) for w in words)
    qterms=lambda words: sum(q.lower().count(w) for w in words)
    nums=re.findall(r'[-+]?[$£€]?\d[\d,.]*%?', text)
    numeric_cells=sum(bool(re.search(r'\d',x)) for x in cells)
    paragraphs=[x for x in re.split(r'\n\s*\n|\n',c) if x.strip()]
    return {
      'query_token_count':len(qt),'context_token_count':len(ct),'sentence_count':len(re.findall(r'[.!?]+',c)),
      'paragraph_count':len(paragraphs),'numeric_count':len(nums),'percentage_count':len(re.findall(r'\d\s*%|percent',text)),
      'currency_count':len(re.findall(r'[$£€]|\b(?:usd|dollar|million|billion)\b',text)),
      'arithmetic_cue_count':terms(('difference','increase','decrease','ratio','percent','average','total','sum','minus','divided','growth','change'))+len(re.findall(r'[+*/=]',q)),
      'table_rows':len(table),'table_columns':max([len(r) for r in table if isinstance(r,list)] or [0]),'table_cell_count':len(cells),
      'numeric_cell_ratio':numeric_cells/max(1,len(cells)),'comparison_cue_count':terms(('compare','between','versus','higher','lower','largest','smallest','respectively')),
      'reasoning_cue_count':terms(('why','how','therefore','calculate','determine','relationship','relate','based on')),
      'conjunction_count':len(re.findall(r'\b(?:and|then|both|while)\b',q.lower())),'cross_reference_count':qterms(('section','article','rule','paragraph','clause','regulation','regulatory','requirement','filing')),
      'modal_count':qterms(('must','shall','should','may','required','prohibited','permitted','eligible','comply','compliance')),'negation_count':len(re.findall(r'\b(?:not|no|never|without|neither)\b|不',text)),
      'exception_count':qterms(('except','unless','notwithstanding','subject to','provided that','only if')),'uncertainty_count':qterms(('unclear','ambiguous','uncertain','possibly','likely','may')),
      'conditional_count':len(re.findall(r'\b(?:if|when|provided|assuming|given that)\b',q.lower())),'evidence_cue_count':terms(('according to','based on','evidence','disclosed','support','explain','relate')),
      'question_entity_count':len(re.findall(r'\b[A-Z][A-Za-z.&-]+',q)),'context_dispersion_proxy':min(len(paragraphs),20)+min(len(c)//1000,20)
    }

def scores(f):
    table=math.log1p(f['table_cell_count']); long=math.log1p(f['context_token_count']); num=math.log1p(f['numeric_count']+2*f['arithmetic_cue_count'])
    return {
      'simple_extraction': 3.0*(f['reasoning_cue_count']==0 and f['arithmetic_cue_count']==0 and f['query_token_count']<24)+1/(1+f['query_token_count'])+0.2*(f['context_token_count']<500),
      'numerical_arithmetic':num+0.5*f['percentage_count']+0.3*f['currency_count'],
      'multi_step_numerical_reasoning':num+0.8*f['reasoning_cue_count']+0.6*f['conjunction_count']+0.4*f['comparison_cue_count'],
      'cross_row_column_table_reasoning':table+1.2*f['comparison_cue_count']+0.5*(f['table_rows']>=4)+0.5*(f['table_columns']>=3),
      'table_text_hybrid_reasoning':table+long+1.5*(f['table_cell_count']>0 and f['context_token_count']>60),
      'long_context_understanding':long+0.3*f['context_dispersion_proxy'],
      'multi_hop_reasoning':0.8*f['reasoning_cue_count']+0.8*f['conjunction_count']+0.5*f['question_entity_count']+0.2*long,
      'evidence_synthesis':f['evidence_cue_count']+0.5*f['paragraph_count']+0.6*f['comparison_cue_count']+0.2*long,
      'compliance_regulation_reasoning':10*(f['modal_count']+f['exception_count'])+f['cross_reference_count']*(1+0.5*f['conditional_count']+0.5*f['negation_count']),
      'ambiguity_negation_exception':f['exception_count']+f['negation_count']+f['conditional_count']+0.7*f['uncertainty_count']
    }

candidates=[]
finqa=load(DATA/'raw/finqa/train.json')
for x in finqa:
    qa=x['qa']; candidates.append({'source':'FinQA','source_id':str(x['id']),'question':qa['question'],'context':'\n'.join(x.get('pre_text',[])+x.get('post_text',[])),'table':x.get('table_ori') or x.get('table') or [],'reference_answer':qa.get('answer')})
tat=load(DATA/'raw/tatqa/train.json')
for doc in tat:
    context='\n'.join(p.get('text','') for p in doc.get('paragraphs',[])); table=(doc.get('table') or {}).get('table') or []
    for qa in doc.get('questions',[]): candidates.append({'source':'TAT-QA','source_id':str(qa['uid']),'question':qa['question'],'context':context,'table':table,'reference_answer':qa.get('answer')})
obli=load(DATA/'raw/obliqa/dev.json')
for x in obli: candidates.append({'source':'ObliQA','source_id':str(x['QuestionID']),'question':x['Question'],'context':'\n\n'.join(p.get('Passage','') for p in x.get('Passages',[])),'table':[],'reference_answer':None})
kg=load(DATA/'raw/finreflectkg-multihopqa/final_master_dataset.json')['questions']
for x in kg:
    path=x.get('path_data') or {}; chunks=[]
    for key,val in path.items():
        if isinstance(val,dict) and val.get('chunk_text'): chunks.append(val['chunk_text'])
    candidates.append({'source':'FinReflectKG','source_id':str(x['question_id']),'question':x['question'],'context':'\n\n'.join(chunks),'table':[],'reference_answer':x.get('answer')})

# Official FinLongDocQA: one outcome-blind question per full company-year report.
finlong=read_jsonl(OUT/"external/FinLongDocQA/dataset_qa.jsonl")
by_document={}
for row in finlong:
    key=(str(row["company"]),str(row["year"]))
    if key not in by_document or stable("finlong|"+str(row["id"])) < stable("finlong|"+str(by_document[key]["id"])):
        by_document[key]=row
finlong_docs=[]
for (company,year),row in by_document.items():
    report=OUT/"external/FinLongDocQA/reports"/company/(year+".md")
    if not report.exists(): continue
    context=report.read_text(errors="ignore"); token_count=len(toks(context))
    if 2000 <= token_count <= 48000:
        finlong_docs.append((stable("finlong-doc|"+company+"|"+year),row,context))
for _,row,context in sorted(finlong_docs)[:120]:
    candidates.append({"source":"FinLongDocQA","source_id":str(row["company"])+"|"+str(row["year"])+"|"+str(row["id"]),"question":row["question"],"context":context,"table":[],"reference_answer":row.get("answer")})

prior=[]
for path in (EXP:=ROOT/'target_support_expansion_v1',): prior += read_jsonl(path/'combined_509_tasks_frozen.jsonl')
v3=DATA/'finrome_300_confirmatory_v3/tasks.jsonl'
if v3.exists(): prior += read_jsonl(v3)
prior_questions={norm(x.get('question') or x.get('Question')) for x in prior}
dedup={}
for x in candidates:
    nq=norm(x['question'])
    if nq and nq not in prior_questions and nq not in dedup: dedup[nq]=x
candidates=list(dedup.values())
for x in candidates:
    x['observable_features']=features(x); x['capability_scores']=scores(x['observable_features'])
    x['capability_labels']=[k for k,v in x['capability_scores'].items() if v>=1.0]

schema=load(SCHEMA); selected=[]; used=set()
for review_stratum in ("multi_step_numerical_reasoning","table_text_hybrid_reasoning"):
    review_candidates=sorted((x for x in candidates if candidate_task_id(x) not in EXCLUDED_TASK_IDS and eligible(x,review_stratum)),key=lambda x:(-x["capability_scores"][review_stratum],stable("review|"+x["source"]+"|"+x["source_id"])))[:250]
    (OUT/("C9_"+review_stratum.upper()+"_POSITIVE_REVIEW.jsonl")).write_text("".join(json.dumps({"task_id":candidate_task_id(x),"source_dataset":x["source"],"question":x["question"],"context":x["context"],"table":x["table"],"proposed_capability":review_stratum,"review_decision":None,"review_reason":None},ensure_ascii=False)+"\n" for x in review_candidates))

print("STRICT_ELIGIBLE_COUNTS", json.dumps({s:sum(eligible(x,s) and candidate_task_id(x) not in EXCLUDED_TASK_IDS for x in candidates) for s in schema["primary_strata"]},sort_keys=True))
for stratum in schema['stratum_order']:
    ranked=sorted((x for x in candidates if x['source_id']+'|'+x['source'] not in used and candidate_task_id(x) not in EXCLUDED_TASK_IDS and x['capability_scores'][stratum]>=schema['eligibility_min_score'] and eligible(x,stratum)),key=lambda x:(-x['capability_scores'][stratum],stable(x['source']+'|'+x['source_id'])))
    assert len(ranked)>=60, (stratum,len(ranked))
    for x in ranked[:60]:
        x['primary_capability']=stratum; x['task_id']=candidate_task_id(x)
        used.add(x['source_id']+'|'+x['source']); selected.append(x)
assert len(selected)==600 and len({x['task_id'] for x in selected})==600

for stratum in schema['primary_strata']:
    group=sorted((x for x in selected if x['primary_capability']==stratum),key=lambda x:stable('split|'+x['task_id']))
    val={x['task_id'] for x in group[:12]}
    for x in group: x['split']='support_matched_validation' if x['task_id'] in val else 'development_train'

prior_text=[str(x.get('question') or x.get('Question') or '') for x in prior]; selected_text=[x['question'] for x in selected]
vectorizer=TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),min_df=1).fit(prior_text+selected_text)
xp=vectorizer.transform(prior_text); xs=vectorizer.transform(selected_text)
sim_prior=cosine_similarity(xs,xp,dense_output=False).max(axis=1).toarray().ravel()
within=cosine_similarity(xs); np.fill_diagonal(within,0); sim_within=within.max(axis=1)
flags=[]
for i,x in enumerate(selected):
    if sim_prior[i]>=.85 or sim_within[i]>=.90: flags.append({'task_id':x['task_id'],'max_prior_similarity':float(sim_prior[i]),'max_within_pool_similarity':float(sim_within[i])})

safe_tasks=[]
for x in selected:
    safe_tasks.append({k:x[k] for k in ('task_id','source','source_id','question','context','table','reference_answer','primary_capability','capability_labels','observable_features','split')})
safe_tasks.sort(key=lambda x:x['task_id'])
audit={'status':'C9_0_POOL_CONSTRUCTED_PENDING_BLIND_REVIEW','outcome_blind':True,'candidate_count_after_exact_exclusion':len(candidates),'selected_tasks':600,
       'primary_counts':dict(Counter(x['primary_capability'] for x in selected)),'split_counts':dict(Counter(x['split'] for x in selected)),'source_counts':dict(Counter(x['source'] for x in selected)),
       'exact_prior_overlap':0,'exact_within_pool_duplicates':0,'near_duplicate_flags':len(flags),'flags':flags,'model_result_files_read':0,'external_api_calls':0,
       'schema_sha256':hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),'protocol_sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()}
(OUT/'C9_DEV_TASKS.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in safe_tasks))
(OUT/'C9_DATA_AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
targets=(SCHEMA,PROTOCOL,OUT/'C9_DEV_TASKS.jsonl',OUT/'C9_DATA_AUDIT.json')
(OUT/'C9_0_SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in targets))
print(json.dumps(audit,ensure_ascii=False,indent=2))
