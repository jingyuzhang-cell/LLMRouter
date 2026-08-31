#!/usr/bin/env python3
"""Prepare human-readable near-duplicate review pairs without reading outcomes."""
import hashlib, json
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT=Path('/root'); OUT=ROOT/'phase_c9_0'
DATA=ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/data/finance_router'
def read_jsonl(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
pool=read_jsonl(OUT/'C9_DEV_TASKS.jsonl')
prior=read_jsonl(ROOT/'target_support_expansion_v1/combined_509_tasks_frozen.jsonl')
v3=DATA/'finrome_300_confirmatory_v3/tasks.jsonl'
if v3.exists(): prior += read_jsonl(v3)
pt=[str(x.get('question') or x.get('Question') or '') for x in prior]; st=[x['question'] for x in pool]
vec=TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),min_df=1).fit(pt+st)
xp,xs=vec.transform(pt),vec.transform(st)
sp=cosine_similarity(xs,xp); sw=cosine_similarity(xs); np.fill_diagonal(sw,0)
queue=[]
for i,x in enumerate(pool):
    pi=int(sp[i].argmax()); wi=int(sw[i].argmax()); ps=float(sp[i,pi]); ws=float(sw[i,wi])
    if ps>=.85 or ws>=.90:
        queue.append({'task_id':x['task_id'],'primary_capability':x['primary_capability'],'question':x['question'],
                      'prior_match':{'similarity':ps,'question':pt[pi]} if ps>=.85 else None,
                      'within_pool_match':{'similarity':ws,'task_id':pool[wi]['task_id'],'question':st[wi]} if ws>=.90 else None,
                      'review_decision':None,'review_reason':None})
path=OUT/'C9_BLIND_OVERLAP_REVIEW.jsonl'
path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in queue))
manifest={'status':'PENDING_HUMAN_BLIND_REVIEW','items':len(queue),'outcomes_read':False,'external_api_calls':0,
          'review_file_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
          'allowed_decisions':['keep_distinct','exclude_near_duplicate']}
(OUT/'C9_BLIND_REVIEW_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(manifest,ensure_ascii=False,indent=2))
