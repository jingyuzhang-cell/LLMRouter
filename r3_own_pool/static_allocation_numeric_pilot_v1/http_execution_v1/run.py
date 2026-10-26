"""Bounded A/B HTTP entry. Default preflight is zero-call; --execute needs NEW authorization."""
import argparse,copy,datetime as dt,hashlib,importlib.util,json,os,threading,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from decimal import Decimal
from pathlib import Path
from binding import HERE,Halt,load_plan,verify_authorization,load_keys_after_authorization,sha
from meter import EstimatedMeter,price
from http_transport import call_once,parse_response

def get_terminal(plan):
    spec=importlib.util.spec_from_file_location('frozen_terminal_adapter_http',plan['scorer_path'])
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def json_write(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

def run_batch(plan,out_dir,*,authorization_path=None,mock_fixtures=None):
    begin=time.monotonic()
    frozen=load_plan()
    if plan!=frozen:raise Halt('PLAN_NOT_FROZEN')
    mock=mock_fixtures is not None
    authorization=None
    if not mock:
        authorization=verify_authorization(authorization_path,plan)
    # Claim BEFORE reading a credential; a used batch cannot be resumed.
    # Fake and real claims are separate and never share authority.
    out=Path(out_dir)
    out.mkdir(parents=True,exist_ok=True)
    real_claim=HERE/'REAL_BATCH_CLAIM.json'
    if not mock:
        with real_claim.open('x') as f:json.dump({'batch_id':plan['batch_id'],'authorization_sha256':sha(authorization_path),'no_resume':True},f)
    with (out/'RUN_CLAIM.json').open('x') as f:json.dump({'mode':'MOCK_HTTP' if mock else 'REAL_HTTP','no_resume':True},f)
    if not mock:json_write(out/'AUTHORIZATION.json',authorization)
    keys={m:'SYNTHETIC_AUTH_NOT_A_REAL_KEY' for m in plan['credential_env']} if mock else load_keys_after_authorization(plan)
    scorer=get_terminal(plan)
    meter=EstimatedMeter(plan)
    lock=threading.RLock();stop_event=threading.Event()
    ledger=[];arm_results=[];events=[];stop_reason=None
    preflight_s=time.monotonic()-begin
    batch_start=time.monotonic()
    def event(kind,**kw):
        record={'kind':kind,'monotonic_s':time.monotonic(),**kw}
        with lock:
            events.append(record)
            with (out/'EVENTS.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')

    def node_call(r,arm_start,arm_meter):
        started=time.monotonic();rid=r['request_id']
        rec={'request_id':rid,'arm':r['arm'],'repeat':r['repeat'],'node':r['node_id'],'model_requested':r['model'],
             'endpoint':r['endpoint'],'body_sha256':r['body_sha256'],'messages_sha256':r['messages_sha256'],
             'evidence_class':'MOCK_HTTP' if mock else 'REAL_HTTP_ATTEMPT','status':'STARTED',
             'actual_cash':None,'bill_status':'PENDING_ACCOUNT_BILL_VERIFICATION','automatic_retries':0,
             'usage':None,'public_cold_miss_estimate':None,'currency':plan['rates'][r['model']]['currency'],
             'cache_committed':False,'start_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
        raw_output=None
        try:
            if stop_event.is_set():raise Halt('BATCH_STOPPED_BEFORE_NODE_DISPATCH')
            remaining=min(plan['request_deadline_s'],plan['arm_deadline_s']-(started-arm_start),
                          plan['batch_deadline_s']-(started-batch_start))
            if remaining<=0:raise Halt('NO_CLIENT_TIME_BEFORE_DISPATCH')
            json_write(out/(rid+'_REQUEST.json'),r['body'])
            (out/(rid+'_REQUEST_BODY.bin')).write_bytes(json.dumps(r['body'],ensure_ascii=False,sort_keys=True).encode())
            event('NODE_DISPATCH',request_id=rid,deadline_s=remaining)
            rec['worker_dispatch_attempted']=True
            envelope=call_once(r,keys[r['model']],remaining,fixture=mock_fixtures[rid] if mock else None)
            raw=envelope.pop('raw_body',None)
            if raw is not None:(out/(rid+'_HTTP_RESPONSE.bin')).write_bytes(raw)
            json_write(out/(rid+'_TRANSPORT.json'),envelope)
            rec.update(transport=envelope)
            # Parsing uses the unchanged raw bytes; no response cleanup/repair.
            parsed=parse_response({**envelope,'raw_body':raw},r,plan['accepted_response_models'][r['model']])
            rec.update(parsed)
            raw_output=parsed['raw_output']
            (out/(rid+'_MODEL_OUTPUT.txt')).write_text(raw_output)
            u=parsed['usage'];rate=plan['rates'][r['model']]
            rec['public_cold_miss_estimate']=str(price(rate,u['prompt_tokens'],u['completion_tokens']))
            # Even if observed usage exceeds the estimate, settle the observed
            # estimate before failing; do not hide an overrun behind a reserve.
            meter_error=None
            for m in [meter,arm_meter]:
                try:m.settle(r,rate,u)
                except Halt as exc:meter_error=exc
            if meter_error:raise meter_error
            if u['prompt_tokens']>65536:raise Halt('INPUT_RESERVATION_ASSUMPTION_EXCEEDED')
            if u['completion_tokens']>r['body']['max_tokens']:raise Halt('OUTPUT_CAP_VIOLATION')
            if parsed['finish_reason']!='stop':raise Halt('TRUNCATED_OR_NONFINAL_OUTPUT')
            checked=scorer.evaluate({r['node_id']:raw_output})
            rec['branch_check']=checked['branches'][r['node_id']]
            if not rec['branch_check']['numeric_lane_legal']:
                # Retain independently scoreable content diagnostics while
                # preventing illegal branch delivery to the terminal.
                rec['partial_content_diagnostic']=checked
                raise Halt('NUMERIC_LANE_CONTRACT_FAILURE')
            rec['cache_committed']=True;rec['status']='COMMITTED'
            rec['input_fingerprint']=r['messages_sha256']
            rec['output_sha256']=hashlib.sha256(raw_output.encode()).hexdigest()
            event('NODE_COMMIT',request_id=rid)
            return rec
        except Exception as exc:
            rec['status']='FAILED';rec['error_type']=type(exc).__name__
            # Only controlled Halt messages are persisted; arbitrary exception
            # text might contain headers or other credential-bearing objects.
            rec['error_reason']=str(exc) if isinstance(exc,Halt) else 'UNEXPECTED_ERROR_DETAILS_SUPPRESSED'
            meter.fail();arm_meter.fail();stop_event.set()
            event('NODE_FAILURE',request_id=rid,reason=rec['error_reason'])
            return rec
        finally:
            rec['client_node_wall_s']=time.monotonic()-started
            rec['end_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
            with lock:
                ledger.append(rec)
                json_write(out/(rid+'_RECORD.json'),rec)
                with (out/'LEDGER.jsonl').open('a') as f:f.write(json.dumps(rec,ensure_ascii=False)+'\n')

    try:
        for schedule in plan['order']:
            for arm in schedule['arms']:
                if stop_event.is_set():raise Halt('BATCH_ALREADY_STOPPED')
                if time.monotonic()-batch_start>=plan['batch_deadline_s']:raise Halt('BATCH_CLIENT_DEADLINE')
                start=time.monotonic()
                rs=[r for r in plan['requests'] if r['repeat']==schedule['repeat'] and r['arm']==arm]
                if len(rs)!=2:raise Halt('DAG_BINDING_MISMATCH')
                arm_meter=EstimatedMeter(plan,caps=plan['common_arm_caps_native'],max_requests=2,max_output=16384)
                # Neither branch starts if either reservation fails.
                for r in rs:
                    meter.reserve(r,plan['rates'][r['model']]);arm_meter.reserve(r,plan['rates'][r['model']])
                    event('ESTIMATE_RESERVED',request_id=r['request_id'])
                event('ARM_START',arm=arm,repeat=schedule['repeat'],cache_initial_entries=0)
                completed={}
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures={pool.submit(node_call,r,start,arm_meter):r for r in rs}
                    for future in as_completed(futures):
                        rec=future.result();completed[rec['node']]=rec
                if stop_event.is_set():raise Halt('ARM_FAILED_NO_DOWNSTREAM_NO_MORE_ARMS')
                outputs={}
                for r in rs:
                    rec=completed[r['node_id']]
                    if not rec['cache_committed'] or rec['input_fingerprint']!=r['messages_sha256']:
                        raise Halt('CACHE_INPUT_FINGERPRINT_INVALID')
                    if hashlib.sha256(rec['raw_output'].encode()).hexdigest()!=rec['output_sha256']:
                        raise Halt('CACHE_OUTPUT_FINGERPRINT_INVALID')
                    outputs[r['node_id']]=rec['raw_output']
                event('MERGE_START',arm=arm,repeat=schedule['repeat'])
                evaluation=scorer.evaluate(outputs)
                # Terminal commit is the endpoint for measured task wall time.
                artifact=out/f"R{schedule['repeat']}_{arm}_TERMINAL.json"
                json_write(artifact,{'branch_outputs':outputs,'evaluation':evaluation,
                                      'evidence_class':'MOCK_HTTP' if mock else 'REAL_MODEL_OUTPUT'})
                wall=time.monotonic()-start
                service=sum(x['client_node_wall_s'] for x in completed.values())
                result={'arm':arm,'repeat':schedule['repeat'],'evaluation':evaluation,'arm_wall_s':wall,
                        'sum_client_node_service_s':service,'deadline_met':wall<=plan['arm_deadline_s'],
                        'cost':arm_meter.snapshot(),'shared_preflight_s':preflight_s,
                        'cold_start_wall_s':wall+preflight_s,'amortized_wall_s':wall+preflight_s/4,
                        'evidence_class':'MOCK_HTTP' if mock else 'REAL_MODEL_OUTPUT'}
                arm_results.append(result)
                json_write(out/f"R{schedule['repeat']}_{arm}_SUMMARY.json",result)
                event('MERGE_COMMIT',arm=arm,repeat=schedule['repeat'])
                if not result['deadline_met']:raise Halt('ARM_CLIENT_DEADLINE_EXCEEDED_NO_FURTHER_ARMS')
    except Exception as exc:
        meter.fail();stop_event.set()
        stop_reason=str(exc) if isinstance(exc,Halt) else type(exc).__name__
        event('BATCH_STOP',reason=stop_reason)
    finally:
        keys.clear()
    result={'status':'COMPLETE' if stop_reason is None else 'STOPPED','stop_reason':stop_reason,
            'arms':arm_results,'attempt_records':len(ledger),
            'real_request_attempts':0 if mock else sum(bool(r.get('worker_dispatch_attempted')) for r in ledger),
            'mock_request_attempts':sum(bool(r.get('worker_dispatch_attempted')) for r in ledger) if mock else 0,
            'post_start_receipts':sum(len(r.get('transport',{}).get('worker_events',[])) for r in ledger),
            'http_responses_saved':len(list(out.glob('*_HTTP_RESPONSE.bin'))),
            'automatic_retries':0,'estimate_meter':meter.snapshot(),
            'batch_wall_s':time.monotonic()-batch_start,'preflight_wall_s':preflight_s,
            'evidence_class':'MOCK_HTTP' if mock else 'REAL_MODEL_EXECUTION',
            'full_opinion_Q':None,'semantic_citation_accuracy':None,
            'actual_cost_benefit_verified':False,'independent_generalization_verified':False,
            'client_deadline_enforced_by_child_termination':True,'remote_cancellation_guaranteed':False}
    json_write(out/'RESULT.json',result)
    if mock:
        result['primary_exploratory_result']='NOT_EVALUATED_SYNTHETIC_FIXTURES'
    elif len(arm_results)==4:
        # Descriptive rule only, no significance claim and no actual-bill claim.
        a=[x for x in arm_results if x['arm']=='A'];b=[x for x in arm_results if x['arm']=='B']
        fx=Decimal(plan['research_FX_USD_to_CNY'])
        def normalized(x):
            amounts=x['cost']['estimate_spent_native'];return Decimal(amounts['CNY'])+Decimal(amounts['USD'])*fx
        mean_a=sum(normalized(x) for x in a)/2;mean_b=sum(normalized(x) for x in b)/2
        la=sum(x['arm_wall_s'] for x in a)/2;lb=sum(x['arm_wall_s'] for x in b)/2
        quality=all(x['evaluation']['content_Q']==1 and x['evaluation']['legal_correct_targets']==6 for x in b)
        result['primary_exploratory_result']={'B_two_repeats_legal_correct_six':quality,
            'A_mean_normalized_public_estimate_CNY':str(mean_a),'B_mean_normalized_public_estimate_CNY':str(mean_b),
            'estimate_cost_reduction_at_least_10_percent':mean_b<=mean_a*Decimal('.9'),
            'wall_increase_at_most_10_percent':lb<=la*1.1,'all_within_deadline':all(x['deadline_met'] for x in arm_results),
            'not_actual_bill_comparison':True,'not_statistical_confirmation':True}
    else:result['primary_exploratory_result']='UNIDENTIFIABLE_INCOMPLETE_BATCH'
    json_write(out/'RESULT.json',result)
    files={x.name:sha(x) for x in out.iterdir() if x.is_file() and x.name!='RESULT_MANIFEST.json'}
    json_write(out/'RESULT_MANIFEST.json',{'files':files,'freeze_sha256':sha(HERE/'FREEZE.json')})
    return result

def synthetic_http_fixtures(plan):
    # Test-only payloads stay outside requests; they never authorize real calls.
    scorer=get_terminal(plan);contract=scorer.CONTRACT
    ref={x['item_id']:x for x in contract['reference']['items']}
    source=json.loads(Path(plan['prior_binding_path']).read_text())['task']
    fixtures={}
    for r in plan['requests']:
        rows=[{'item_id':k,'fields':{'amount':copy.deepcopy(ref[k]['fields']['amount']['expected'])},
               'evidence_ids':list(source['evidence_catalog'])} for k in contract['assigned_slots'][r['node_id']]]
        payload={'id':'mock-'+r['request_id'],'model':r['model'],'choices':[{'index':0,'message':{'content':json.dumps({'items':rows},ensure_ascii=False)},'finish_reason':'stop'}],
                 'usage':{'prompt_tokens':5000,'completion_tokens':100,'total_tokens':5100}}
        fixtures[r['request_id']]={'raw_body':json.dumps(payload,ensure_ascii=False)}
    return fixtures

def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group();group.add_argument('--preflight',action='store_true');group.add_argument('--mock-out');group.add_argument('--execute',action='store_true')
    p.add_argument('--authorization');p.add_argument('--out')
    args=p.parse_args()
    try:
        plan=load_plan()
        if args.mock_out:
            print(json.dumps(run_batch(plan,args.mock_out,mock_fixtures=synthetic_http_fixtures(plan)),ensure_ascii=False));return 0
        if not args.execute:
            try:verify_authorization(args.authorization,plan)
            except Halt as exc:
                print(json.dumps({'freeze_valid':True,'execution_authorized':False,'reason':str(exc),'key_reads':0,'real_http_requests':0},ensure_ascii=False));return 2
            print(json.dumps({'freeze_valid':True,'execution_authorized':True,'key_reads':0,'real_http_requests':0}));return 0
        if not args.out:raise Halt('OUTPUT_DIRECTORY_REQUIRED')
        r=run_batch(plan,args.out,authorization_path=args.authorization)
        print(json.dumps(r,ensure_ascii=False));return 0 if r['status']=='COMPLETE' else 3
    except (Halt,FileExistsError) as exc:
        print(json.dumps({'status':'NOT_DISPATCHED','reason':str(exc),'real_http_requests':0},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
