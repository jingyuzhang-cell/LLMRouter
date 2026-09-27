"""Attempt corrected executions using ONLY previously logged model/prompt pairs.

Missing calls abort the entire case. No model server, fabricated answers, or
partial-case quality scores are permitted. Output is a coverage audit, not an
independent experiment. Existing frozen results are never overwritten.
"""
import copy
import json
from pathlib import Path
from . import exact_pareto as ep, frozen200_run as fz
from .audited_cache import load_prompt_cache, cached_record, prompt_id
from .multi_seed_run import build_faults

BASE=Path(__file__).resolve().parent
DEST=BASE.parent/'paper_method_feedback_aware_dag/chapter4_audit_20260926'
class MissingCall(Exception):
    def __init__(self,key,model,prompt):self.detail=dict(key=key,model=model,prompt_sha256=prompt_id(model,prompt)[1])
class OfflineCaller:
    def __init__(self,cache):self.by_mp=cache;self.by_key={};self.faults={};self.count=0
    def set_fault(self,u,n,m,a,usage=None,lat=None):self.faults[u,n,m]=(a,usage,lat)
    def call(self,key,model,prompt,uid=None,node=None):
        self.count+=1
        if (uid,node,model) in self.faults:
            a,usage,lat=self.faults[uid,node,model]
            if usage is None or lat is None:
                raise ValueError('Missing measured fault cost reference')
            rec=dict(key=key,model=model,response=dict(status='delivered',answer=a,usage=usage,latency_s=lat,injected_fault=True))
        else:
            rec=cached_record(self.by_mp,key,model,prompt)
            if rec is None:raise MissingCall(key,model,prompt)
        self.by_key[key]=rec;return rec
    def cost(self,k):return float(self.by_key[k]['response']['usage']['total_tokens'])
    def lat(self,k):return self.by_key[k]['response']['latency_s']

def run():
    a=BASE/'adaptive_benchmark'
    dirs=[BASE/'multidag_dynamic_120',BASE/'multidag_ablation_120',BASE/'multidag_fullgraph_120',a/'router_clean']
    # Include only paired logs in the relevant evidence families, never arbitrary workspaces.
    dirs += sorted({p.parent for top in (a,BASE/'frozen200') for p in top.rglob('REQUESTS.jsonl') if 'BUGGY' not in str(p)})
    dirs=list(dict.fromkeys(d for d in dirs if d.exists()))
    cache=load_prompt_cache(dirs);cases=[]
    resp={}
    for d in (ep.OUT,ep.ABL,ep.FG):
        for line in (d/'RESPONSES.jsonl').read_text().splitlines():
            r=json.loads(line);resp[r['key']]=r
    tasks=json.loads((ep.OUT/'POLICY.json').read_text())['tasks'][:120]
    for mr in ep.MODELS:
        for mv in ep.MODELS:
            for z in ('none','switch'):
                for seed in ep.SEEDS:
                    c=OfflineCaller(cache);case=dict(family='exact',config=f'{mr}_{mv}_{z}',seed=seed)
                    try:
                        result=ep.run_config(mr,mv,z,seed,tasks,build_faults(seed,.3,tasks),resp,c)
                        case.update(status='complete_cache_replay',rows=result)
                    except MissingCall as e:case.update(status='blocked_missing_executed_prompt',first_missing=e.detail)
                    case['attempted_calls']=c.count;cases.append(case)
    tasks=json.loads((BASE/'frozen200/FROZEN200_POLICY.json').read_text())['tasks'];gold={t['uid']:t['answer'] for t in tasks}
    pools=json.loads((a/'FAULT_POOLS.json').read_text())
    # Clean reference costs are obtained from actual prompt-matched records, not zero/placeholder costs.
    ref=OfflineCaller(cache)
    for t in tasks:
        for nd,ctx in (('e1',t['ctx_table']),('e2',t['ctx_text'])):
            ref.call(f'fz:{nd}:{t["uid"]}','large',fz.v.eprompt(dict(question=t['question'],context=ctx)))
    # r/v reference costs: source records are used for accounting only, not execution cache decisions.
    frozen_responses={json.loads(l)['key']:json.loads(l) for l in (BASE/'frozen200/RESPONSES.jsonl').read_text().splitlines()}
    for seed in (None,*fz.SEEDS):
        faults={} if seed is None else fz.build_faults(seed,.3,tasks,pools)
        for arm in ('single','static','dynamic'):
            c=OfflineCaller(cache);case=dict(family='frozen',arm=arm,seed=seed)
            if arm!='single':
                for u,(node,answer) in faults.items():
                    rec=ref.by_key.get(f'fz:{node}:{u}',frozen_responses.get(f'fz:{node}:{u}'))
                    if rec is None:raise ValueError('Missing clean cost source '+node+u)
                    response=rec['response'];c.set_fault(u,node,{'e1':'large','e2':'large','r':'medium','v':'coder'}[node],answer,response.get('usage'),response.get('latency_s'))
            try:
                result=fz.run_arm(arm,tasks,faults,c,gold,seed is not None)
                case.update(status='complete_cache_replay',rows=result)
            except MissingCall as e:case.update(status='blocked_missing_executed_prompt',first_missing=e.detail)
            case['attempted_calls']=c.count;cases.append(case)
    output=dict(note='Zero new model calls. No partial-case Q. Complete cases are cache reanalyses, not new independent evidence.',source_directories=[str(d.relative_to(BASE)) for d in dirs],prompt_pairs=len(cache),cases=cases)
    (DEST/'CACHE_REPLAY_COVERAGE.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print('prompt pairs',len(cache))
    for family in ('exact','frozen'):
        rs=[c for c in cases if c['family']==family]
        print(family, len(rs),'cases, complete',sum(c['status']=='complete_cache_replay' for c in rs),'blocked',sum(c['status']!='complete_cache_replay' for c in rs))
if __name__=='__main__':run()
