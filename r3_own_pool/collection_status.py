"""Read-only full-cohort coverage report; never count attempts as unique cells."""
from collections import Counter
import json
from pathlib import Path
import sys
R=Path(__file__).resolve().parent
sys.path.insert(0,str(R/'collect'))
import storage

def main():
    cohort=R/'data/cohort_full_v2'
    sources=[json.loads(x) for x in (cohort/'queries.jsonl').read_text().split('\n') if x.strip()]
    expected={r['query_id'] for r in sources}
    result={'expected_queries':len(expected),'expected_response_cells':len(expected)*4,'slots':{}}
    coverage=[]
    successes=[]
    for slot in ('small','medium','large','reasoning'):
        path=R/'data/raw'/f'{slot}.jsonl'
        canonical=storage.canonical_rows(path)
        selected={k:v for k,v in canonical.items() if k in expected}
        good={k for k,v in selected.items() if v.get('status')=='ok'}
        coverage.append(set(selected));successes.append(good)
        result['slots'][slot]={'recorded_unique':len(selected),'ok':len(good),'missing':len(expected-set(selected)),
            'statuses':dict(Counter(v.get('status','unknown') for v in selected.values()))}
    result['four_slot_queries_recorded']=len(set.intersection(*coverage))
    result['four_slot_queries_ok']=len(set.intersection(*successes))
    result['lanes']={}
    for name in ('local','reasoning'):
        p=R/'data/full_run_v2'/f'{name}.json'
        if p.exists():result['lanes'][name]=json.loads(p.read_text())
    result['training_ready']=False
    result['note']='Raw coverage only; quality, cost provenance, split/hash and scoring validation must pass separately.'
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
