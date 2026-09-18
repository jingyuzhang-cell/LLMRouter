"""Pilot-only recovery actions. Runtime files only; offline scoring is a separate process.
No automatic full experiment. Frozen prompt strings retained byte-for-byte.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import time
from pathlib import Path
from . import core, run as engine, tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_snapshot import OUT, assert_runtime, digest, build_snapshot

PROMPTS=json.loads((OUT.parent/'frozen_prompts.json').read_text())
D1,D2,RETRIEVE=(PROMPTS[k] for k in ('D1','D2','RETRIEVE'))
ACTIONS=['no_recovery','retry_same','switch_model','evidence_retrieval','local_decompose']

# Retrieval's frozen prompt requests `source` and a plain-text prefix. Accept that
# exact output contract without changing the prompt or using reference operands.
def parse_retrieval(text):
    decoder=json.JSONDecoder()
    for i,c in enumerate(text or ''):
        if c!='{':continue
        try:
            obj,_=decoder.raw_decode(text[i:])
            facts=obj['facts']
            normalized={'facts':[{'value':f['value'],'evidence':f.get('evidence') or f.get('source') or 'retrieval output'} for f in facts]}
            return v.parse_facts(json.dumps(normalized))
        except (ValueError,KeyError,TypeError,AssertionError):continue
    raise ValueError('no valid facts object in retrieval response')

def value_of(response,facts):
    try:
        expr=v.decode(response['answer'])['expression']
        return exec_calc(expr,facts),expr,None
    except (ValueError,KeyError,TypeError,AssertionError,IndexError,ZeroDivisionError,SyntaxError) as exc:
        return None,None,type(exc).__name__

def execute_action(runtime_snapshot,action,call):
    """All action inputs are runtime data. No task or offline payload accepted."""
    assert_runtime(runtime_snapshot)
    snap=copy.deepcopy(runtime_snapshot);sh=digest(snap)
    facts=copy.deepcopy(snap['facts_before']); calls=[]
    def invoke(model,prompt,stage):
        result=call(model,prompt,stage,sh)
        calls.append(dict(model=model,prompt=prompt,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),response=result,stage=stage))
        return result
    result=dict(action=action,snapshot_hash=sh,facts_source=snap['facts_source'],facts_before=facts,
                facts_after=copy.deepcopy(facts),gold_leak_check=False)
    if action=='no_recovery':
        result.update(value=None,tokens=0,dt_s=0.,calls=[],executed=False)
        return result
    if action in ('retry_same','switch_model'):
        r=invoke('large' if action=='switch_model' else 'medium',v.sprompt({'question':snap['question']},facts),'reason')
        value,expr,error=value_of(r,facts)
        result.update(value=value,expression=expr,executor_error=error)
    elif action=='evidence_retrieval':
        r=invoke('medium',RETRIEVE.format(q=snap['question'],ctx=snap['context'][:14000]),'retrieve')
        try:
            new=parse_retrieval(r['answer'])
            # Preserve frozen merging semantics and rounding.
            vals=list({round(f['value'],6) for f in facts['facts']} | {round(f['value'],6) for f in new['facts']})
            merged={'facts':[dict(value=x,evidence='merged') for x in vals]}
            result['retrieval_parse_error']=None
        except (ValueError,KeyError,TypeError,AssertionError) as exc:
            merged=facts;result['retrieval_parse_error']=type(exc).__name__
        result['facts_after']=merged
        r=invoke('medium',v.sprompt({'question':snap['question']},merged),'reason_after_retrieval')
        value,expr,error=value_of(r,merged);result.update(value=value,expression=expr,executor_error=error)
    elif action=='local_decompose':
        r=invoke('medium',D1.format(q=snap['question'],ctx=snap['context'][:14000],vals=[f['value'] for f in facts['facts']]),'D1')
        result['decomposition_nodes']=['D1']
        try:
            align=v.decode(r['answer'])
            r=invoke('medium',D2.format(q=snap['question'],align=json.dumps(align)),'D2')
            result['decomposition_nodes']+=['D2','tool']
            value,expr,error=value_of(r,facts)
            result.update(value=value,expression=expr,executor_error=error,decompose_executed=error is None)
        except (ValueError,KeyError,TypeError,AssertionError) as exc:
            result.update(value=None,executor_error=type(exc).__name__,decompose_executed=False)
    else:raise ValueError(action)
    # No missing usage/timing values are silently changed to zero.
    result.update(calls=calls,executed=True,
        tokens=sum(c['response']['usage']['total_tokens'] for c in calls) if all((c['response'].get('usage') or {}).get('total_tokens') is not None for c in calls) else None,
        dt_s=sum(c['response']['latency_s'] for c in calls) if all(c['response'].get('latency_s') is not None for c in calls) else None)
    assert sh==digest(snap)==digest(runtime_snapshot)
    return result

def run():
    if (OUT/'ACTIONS_DONE.json').exists():raise FileExistsError('Pilot actions already complete')
    snaps=[json.loads(p.read_text()) for p in sorted((OUT/'runtime').glob('*.json'))]
    assert len(snaps)==20 and all(s['valid'] for s in snaps)
    engine.OUT=OUT
    request_path=OUT/'REQUESTS.jsonl';response_path=OUT/'RESPONSES.jsonl'
    cache={}
    if response_path.exists():
        for l in response_path.read_text().splitlines():
            r=json.loads(l);cache[r['key']]=r['response']
    def append(path,obj):
        with path.open('a') as f:f.write(json.dumps(obj,ensure_ascii=False)+'\n');f.flush()
    proc=log=None;current=None;records=[]
    with (core.ROOT/'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            # Independent fixed-snapshot actions batched by model; no shared memory.
            for action_group in [['no_recovery','retry_same','evidence_retrieval','local_decompose'],['switch_model']]:
                for snap in snaps:
                    for action in action_group:
                        def call(model,prompt,stage,sh):
                            nonlocal proc,log,current
                            key=digest([snap['node_id'],action,stage,sh,model,prompt])
                            if key in cache:return cache[key]
                            if model!=current:
                                if proc is not None:engine.stop_model(proc,log);proc=log=None
                                proc,log,_=engine.start_model(model);current=model
                            append(request_path,dict(key=key,node_id=snap['node_id'],action=action,stage=stage,model=model,snapshot_hash=sh,prompt=prompt))
                            r=engine.call_model(model,prompt)
                            append(response_path,dict(key=key,node_id=snap['node_id'],action=action,stage=stage,model=model,response=r));cache[key]=r
                            if r.get('status')!='delivered':raise RuntimeError('Infrastructure failure: '+key)
                            return r
                        rec=execute_action(snap,action,call)
                        records.append(dict(node_id=snap['node_id'],**rec))
                        core.write(OUT/'STATUS.json',dict(phase='PILOT_RUNNING',completed_actions=len(records),total_actions=100,calls=len(cache),node_id=snap['node_id'],action=action))
                        print(json.dumps(dict(node_id=snap['node_id'],action=action,completed=len(records),calls=len(cache))),flush=True)
        finally:
            if proc is not None:engine.stop_model(proc,log)
    (OUT/'ACTION_RESULTS.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    core.write(OUT/'ACTIONS_DONE.json',dict(nodes=20,actions=len(records),calls=len(cache),unix_time=time.time(),full_started=False))
    core.write(OUT/'STATUS.json',dict(phase='PILOT_ACTIONS_COMPLETE_PENDING_AUDIT',nodes=20,calls=len(cache)))

if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args();run()
