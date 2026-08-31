#!/usr/bin/env python3
"""Attach document/table/template groups and create a leakage-safe grouped split."""
import hashlib, json, re
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import StratifiedGroupKFold

ROOT=Path('/root'); OUT=ROOT/'phase_c9_0'; SEED=20260831
def rows(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def norm(x): return re.sub(r'\W+',' ',str(x).lower()).strip()
def digest(x): return hashlib.sha256(x.encode()).hexdigest()[:20]
def stable_hash(x): return int(hashlib.sha256((str(SEED)+"|"+x).encode()).hexdigest(),16)
tasks=rows(OUT/'C9_DEV_TASKS.jsonl'); n=len(tasks)
parent=list(range(n))
def find(x):
    while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
    return x
def union(a,b):
    a,b=find(a),find(b)
    if a!=b: parent[max(a,b)]=min(a,b)

doc_buckets=defaultdict(list); template_buckets=defaultdict(list)
for i,t in enumerate(tasks):
    rendered=json.dumps(t.get('table') or [],ensure_ascii=False,sort_keys=True)
    document_id=digest(t['source']+'|'+norm(t.get('context'))+'|'+norm(rendered))
    table_id=digest(t['source']+'|'+norm(rendered)) if t.get('table') else None
    template=re.sub(r'\b(?:19|20)\d{2}\b|\d+(?:\.\d+)?','<NUM>',norm(t['question']))
    template=re.sub(r'\s+',' ',template).strip()
    template_id=digest(template)
    t.update({'source_dataset':t.pop('source'),'source_document_id':document_id,'source_table_id':table_id,'template_family_id':template_id})
    doc_buckets[(t['source_dataset'],document_id)].append(i); template_buckets[template_id].append(i)
for bucket in list(doc_buckets.values())+list(template_buckets.values()):
    for i in bucket[1:]: union(bucket[0],i)

# Near-identical question templates are one leakage group even when wording differs slightly.
q=[re.sub(r'\d+(?:\.\d+)?','<NUM>',norm(t['question'])) for t in tasks]
x=TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),min_df=1).fit_transform(q)
sim=cosine_similarity(x); np.fill_diagonal(sim,0)
for a,b in zip(*np.where(np.triu(sim>=.90,1))): union(int(a),int(b))
groups=np.asarray([find(i) for i in range(n)])
labels=np.asarray([t['primary_capability']+'|'+t['source_dataset'] for t in tasks])
splitter=StratifiedGroupKFold(5,shuffle=True,random_state=SEED)
candidates=[]
for fold,(_,va) in enumerate(splitter.split(np.zeros(n),labels,groups)):
    cap=Counter(tasks[i]['primary_capability'] for i in va); src=Counter(tasks[i]['source_dataset'] for i in va)
    loss=(len(va)-120)**2+sum((cap[k]-12)**2 for k in set(t['primary_capability'] for t in tasks))
    candidates.append((loss,fold,set(map(int,va)),cap,src))
_,fold,valid,cap_counts,source_counts=min(candidates,key=lambda z:(z[0],z[1]))
# Reach the preregistered 120 exactly by moving a singleton leakage group.
group_members=defaultdict(list)
for i,g in enumerate(groups): group_members[int(g)].append(i)
if len(valid) < 120:
    deficits=Counter({k:12-cap_counts.get(k,0) for k in set(t["primary_capability"] for t in tasks)})
    singletons=[m[0] for m in group_members.values() if len(m)==1 and m[0] not in valid]
    chosen=max(singletons,key=lambda i:(deficits[tasks[i]["primary_capability"]],stable_hash(tasks[i]["task_id"])))
    valid.add(chosen); cap_counts[tasks[chosen]["primary_capability"]]+=1; source_counts[tasks[chosen]["source_dataset"]]+=1
elif len(valid) > 120:
    singletons=[m[0] for m in group_members.values() if len(m)==1 and m[0] in valid]
    chosen=max(singletons,key=lambda i:(cap_counts[tasks[i]["primary_capability"]]-12,stable_hash(tasks[i]["task_id"])))
    valid.remove(chosen); cap_counts[tasks[chosen]["primary_capability"]]-=1; source_counts[tasks[chosen]["source_dataset"]]-=1
for i,t in enumerate(tasks):
    t['split']='support_matched_validation' if i in valid else 'development_train'
    t['leakage_group_id']='group_'+digest(str(find(i)))

def overlap(field):
    tr={t[field] for t in tasks if t['split']=='development_train' and t.get(field)}
    va={t[field] for t in tasks if t['split']=='support_matched_validation' and t.get(field)}
    return sorted(tr&va)
matrix=defaultdict(Counter)
for t in tasks: matrix[t['primary_capability']][t['source_dataset']]+=1
audit={'status':'GROUP_SPLIT_COMPLETE','selected_fold':fold,'split_counts':dict(Counter(t['split'] for t in tasks)),
       'validation_capability_counts':dict(cap_counts),'validation_source_counts':dict(source_counts),
       'document_overlap_count':len(overlap('source_document_id')),'table_overlap_count':len(overlap('source_table_id')),
       'template_overlap_count':len(overlap('template_family_id')),'leakage_group_overlap_count':len(overlap('leakage_group_id')),
       'source_capability_matrix':{k:dict(v) for k,v in sorted(matrix.items())},'outcomes_read':False,'external_api_calls':0}
(OUT/'C9_DEV_TASKS_GROUPED.jsonl').write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in sorted(tasks,key=lambda z:z['task_id'])))
(OUT/'C9_GROUP_SPLIT_AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(audit,ensure_ascii=False,indent=2))
