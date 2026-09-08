"""Freeze a query-only cohort and split before full collection; never overwrite."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import random
import sys
R=Path(__file__).resolve().parent
sys.path.insert(0,str(R/'collect'))
from datasets.sources import load_sources,FULL_QUOTA

def main():
    rows=load_sources(FULL_QUOTA)
    assert len(rows)>=5000
    assert len({r['query_id'] for r in rows})==len({r['query'] for r in rows})==len(rows)
    payload=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows)
    split={'train':[],'validation':[],'test':[]}
    rng=random.Random(42)
    for ds in sorted({r['dataset'] for r in rows}):
        ids=sorted(r['query_id'] for r in rows if r['dataset']==ds)
        rng.shuffle(ids)
        a=round(len(ids)*.7); b=a+round(len(ids)*.15)
        for key,subset in zip(split,(ids[:a],ids[a:b],ids[b:])):
            split[key].extend(subset)
    manifest=dict(version='r3-full-5000-v2',n_queries=len(rows),n_response_cells=len(rows)*4,
                  counts=dict(Counter(r['dataset'] for r in rows)),query_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                  split_counts={k:len(v) for k,v in split.items()},seed=42,
                  note='Within-source prompt-disjoint split, not source-held-out generalization; pilot overlaps this cohort. No outcomes used to split.')
    dest=R/'data/cohort_full_v2'; dest.mkdir(parents=True,exist_ok=True)
    for name,text in [('queries.jsonl',payload),('split.json',json.dumps(split,indent=2)),('MANIFEST.json',json.dumps(manifest,indent=2))]:
        p=dest/name
        if p.exists():
            assert p.read_text()==text, f'Frozen cohort changed: {p}'
        else:
            with p.open('x') as f:f.write(text)
    print(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
