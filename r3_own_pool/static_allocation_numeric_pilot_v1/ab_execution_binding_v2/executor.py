"""Shared A/B DAG orchestration with an injected, offline-only FakeMeter.

No HTTP client, credential loader or paid dispatch path is supplied. Fake
outcomes are synthetic fixtures, never evidence of algorithmic benefit.
"""
import copy,hashlib,importlib.util,json,threading,time
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
sys.path.insert(0,str(PARENT))
from reservation_guard import ReservationGuard,Stop
spec=importlib.util.spec_from_file_location('fixed_terminal_evaluation',PARENT/'terminal_contract_v1/evaluate_terminal.py')
terminal=importlib.util.module_from_spec(spec);spec.loader.exec_module(terminal)

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_config():
    c=json.loads((HERE/'AB_CONFIG.json').read_text())
    for path,h in {**c['source_hashes'],**c['binding_files']}.items():
        if digest(path)!=h:raise Stop('FROZEN_IDENTITY_MISMATCH:'+path)
    return c

def cost(rate,usage):
    return (Decimal(usage['prompt_tokens'])*Decimal(rate['input'])+Decimal(usage['completion_tokens'])*Decimal(rate['output']))/Decimal(1000000)

class FakeMeter:
    evidence_class='SYNTHETIC_FAKE_METER'
    def __init__(self,fixtures,fail_id=None,bad_schema_id=None,token_overflow_id=None,cache_tamper_id=None):
        self.fixtures=fixtures;self.fail_id=fail_id;self.bad_schema_id=bad_schema_id
        self.token_overflow_id=token_overflow_id
        self.cache_tamper_id=cache_tamper_id
        self.calls=[];self.lock=threading.Lock()
    def call(self,r):
        with self.lock:self.calls.append(r['request_id'])
        time.sleep(.005)
        if r['request_id']==self.fail_id:raise RuntimeError('SYNTHETIC_TRANSPORT_FAILURE')
        payload=copy.deepcopy(self.fixtures[r['node_id']])
        if r['request_id']==self.bad_schema_id:payload=[]
        output=100 if r['request_id']!=self.token_overflow_id else r['body']['max_tokens']+1
        return {'raw_output':json.dumps(payload,ensure_ascii=False),
                'usage':{'prompt_tokens':5000,'completion_tokens':output,'total_tokens':5000+output},
                'finish_reason':'stop','source':'SYNTHETIC_NOT_A_MODEL_RESPONSE'}

def run(config,transport,out_dir,caps=None):
    if type(transport) is not FakeMeter:
        raise Stop('REAL_TRANSPORT_UNAVAILABLE_NO_PAID_AUTHORIZATION')
    if config['real_dispatch_enabled'] or config['paid_authorization']:
        raise Stop('OFFLINE_ENTRY_ONLY')
    if config!=load_config():raise Stop('CONFIG_NOT_FROZEN_AB_BINDING')
    # Fake token usage is known by construction. This certification applies
    # ONLY to simulated accounting, never to any provider tokenizer.
    guard=ReservationGuard(caps or config['proposed_caps_native'],max_calls=config['max_requests'],
                           max_output=config['max_output_tokens'],wall_s=config['batch_wall_s'],certified=True)
    out=Path(out_dir)
    out.mkdir(parents=True,exist_ok=True)
    claim=out/'RUN_CLAIM.json'
    with claim.open('x') as f:json.dump({'mode':'SYNTHETIC_FAKE_METER','resume_allowed':False},f)
    ledger=[];events=[];results=[];cache={};cache_versions={};stop_reason=None
    io_lock=threading.Lock()
    batch_start=time.monotonic()
    def write_event(event,**fields):
        record={'event':event,'monotonic_s':time.monotonic(),**fields}
        with io_lock:
            events.append(record)
            with (out/'EVENTS.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
    def invoke(r,arm_start,arm_guard):
        started=time.monotonic()
        write_event('BRANCH_START',request_id=r['request_id'],arm=r['arm'],node=r['node_id'])
        record={'request_id':r['request_id'],'arm':r['arm'],'repeat':r['repeat'],'node':r['node_id'],
                'model':r['model'],'body_sha256':r['body_sha256'],'messages_sha256':r['messages_sha256'],
                'source':'SYNTHETIC_FAKE_METER','retries':0,'started_monotonic':started,
                'usage':None,'native_currency':config['rates'][r['model']]['currency'],
                'cash_simulated':None,'cash_actual':None,'cache_committed':False}
        try:
            response=transport.call(copy.deepcopy(r))
            record.update(response)
            (out/(r['request_id']+'_OUTPUT.txt')).write_text(response['raw_output'])
            u=response['usage']
            if any(type(u.get(k))!=int or u[k]<0 for k in ['prompt_tokens','completion_tokens','total_tokens']):
                raise Stop('INVALID_USAGE')
            if u['total_tokens']!=u['prompt_tokens']+u['completion_tokens']:
                raise Stop('USAGE_SUM_MISMATCH')
            if u['prompt_tokens']>r['reservation_input_assumption'] or u['completion_tokens']>r['body']['max_tokens']:
                raise Stop('TOKEN_BOUND_VIOLATION')
            if response['finish_reason']!='stop':raise Stop('TRUNCATED_OR_INCOMPLETE')
            charge=cost(config['rates'][r['model']],u)
            record['cash_simulated']=str(charge)
            guard.settle(r['request_id'],charge)
            arm_guard.settle(r['request_id'],charge)
            checked=terminal.evaluate({r['node_id']:response['raw_output']})
            if not checked['branches'][r['node_id']]['numeric_lane_legal']:
                raise Stop('NUMERIC_LANE_CONTRACT_FAILURE')
            with io_lock:
                cache[r['request_id']]=response['raw_output']
                cache_versions[r['request_id']]={'messages':r['messages_sha256'],
                    'output':hashlib.sha256(response['raw_output'].encode()).hexdigest()}
                if r['request_id']==transport.cache_tamper_id:
                    cache_versions[r['request_id']]['messages']='SYNTHETIC_STALE_FINGERPRINT'
            record['cache_committed']=True;record['status']='COMMITTED'
            write_event('BRANCH_COMMIT',request_id=r['request_id'])
            return response['raw_output']
        except Exception as exc:
            if r['request_id'] in guard.claims and not guard.claims[r['request_id']]['settled']:
                try:guard.settle(r['request_id'],failed=True)
                except Stop:pass
            guard.stopped=True
            arm_guard.stopped=True
            record.update(status='FAILED',error=type(exc).__name__+':'+str(exc))
            write_event('BRANCH_FAILURE',request_id=r['request_id'],reason=record['error'])
            raise
        finally:
            record['ended_monotonic']=time.monotonic()
            record['client_local_service_s']=record['ended_monotonic']-started
            with io_lock:
                ledger.append(record)
                with (out/'LEDGER.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
    try:
        for schedule in config['order']:
            for arm in schedule['arms']:
                arm_start=time.monotonic()
                rs=[r for r in config['requests'] if r['repeat']==schedule['repeat'] and r['arm']==arm]
                if len(rs)!=2:raise Stop('GRAPH_BINDING_MISMATCH')
                arm_guard=ReservationGuard(config['common_arm_caps_native'],max_calls=2,max_output=16384,
                                           wall_s=config['common_arm_deadline_s'],certified=True)
                # Pre-reserve BOTH branches before any arm call, so a failed
                # second reservation cannot leave a half-admitted arm running.
                for r in rs:
                    rate=config['rates'][r['model']]
                    guard.reserve(r['request_id'],rate['currency'],r['conditional_reserve_native'],r['body']['max_tokens'])
                    arm_guard.reserve(r['request_id'],rate['currency'],r['conditional_reserve_native'],r['body']['max_tokens'])
                    write_event('RESERVED',request_id=r['request_id'],native_bound=r['conditional_reserve_native'])
                write_event('ARM_START',arm=arm,repeat=schedule['repeat'],initial_cache_entries=0)
                outputs={};failure=None
                with ThreadPoolExecutor(max_workers=2) as pool:
                    fs={pool.submit(invoke,r,arm_start,arm_guard):r for r in rs}
                    for f in as_completed(fs):
                        r=fs[f]
                        try:outputs[r['node_id']]=f.result()
                        except Exception as exc:failure=exc
                if failure:raise failure
                # Require exact input/version identity and a successful commit
                # for each dependency; never release failed cache to merge.
                for r in rs:
                    v=cache_versions.get(r['request_id'])
                    if not v or v['messages']!=r['messages_sha256']:raise Stop('CACHE_FINGERPRINT_INVALID')
                    if hashlib.sha256(cache[r['request_id']].encode()).hexdigest()!=v['output']:raise Stop('CACHE_OUTPUT_TAMPERED')
                write_event('MERGE_START',arm=arm,repeat=schedule['repeat'])
                scored=terminal.evaluate(outputs)
                # Branch outputs are final numerical results; merge consumes
                # both without model inference, reformatting or Gold filling.
                wall=time.monotonic()-arm_start
                result={'arm':arm,'repeat':schedule['repeat'],'evaluation':scored,
                        'local_fake_wall_s':wall,'deadline_met':wall<=config['common_arm_deadline_s'],
                        'evidence_class':'SYNTHETIC_FAKE_METER','real_model_benefit':None}
                results.append(result)
                (out/f"R{schedule['repeat']}_{arm}_TERMINAL.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
                write_event('MERGE_COMMIT',arm=arm,repeat=schedule['repeat'])
    except Exception as exc:
        stop_reason=type(exc).__name__+':'+str(exc)
        write_event('BATCH_STOP',reason=stop_reason)
    result={'status':'COMPLETE' if stop_reason is None else 'STOPPED','stop_reason':stop_reason,
            'results':results,'physical_fake_calls':len(transport.calls),'real_model_calls':0,
            'retries':0,'reserved_request_ids':list(guard.claims),
            'simulated_spent_native':{k:str(v) for k,v in guard.spent.items()},
            'retained_reservations_native':{k:str(v) for k,v in guard.reserved.items()},
            'simulated_output_reservations':guard.output_reserved,
            'local_fake_batch_wall_s':time.monotonic()-batch_start,
            'cache_keys':list(cache),'ledger_rows':len(ledger),'evidence_class':'SYNTHETIC_FAKE_METER',
            'real_inference_or_network_latency_validated':False,'real_token_upper_certified':False}
    (out/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result

def synthetic_fixtures():
    # Test-only Gold-derived payloads stay inside FakeMeter, NEVER in request
    # bodies or a real backend. This is not generated substitute model data.
    task=json.loads((PARENT/'BINDING.json').read_text())['task']
    ref={i['item_id']:i for i in terminal.CONTRACT['reference']['items']}
    ids=list(task['evidence_catalog'])
    return {node:{'items':[{'item_id':k,'fields':{'amount':copy.deepcopy(ref[k]['fields']['amount']['expected'])},
                           'evidence_ids':ids} for k in keys]} for node,keys in terminal.CONTRACT['assigned_slots'].items()}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fake-out',required=True)
    args=p.parse_args()
    print(json.dumps(run(load_config(),FakeMeter(synthetic_fixtures()),args.fake_out),ensure_ascii=False))
