"""Read-only historical accounting audit and explicitly counterfactual admission."""
import argparse,hashlib,json,tempfile
from pathlib import Path
from .resource_envelope import ResourceEnvelope
from .fresh_acceptance import ScopedBudget,CAPS
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun

def lines(path):return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
def audit(root):
    names=['DISPATCH.jsonl','REQUEST_PRECHECK.jsonl','PHASE_BUDGET.jsonl','HTTP_INPUTS.jsonl','RESULTS.json','PROTOCOL.json']
    before={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in names}
    checks=lines(root/'REQUEST_PRECHECK.jsonl');ledger=lines(root/'DISPATCH.jsonl');phases=lines(root/'PHASE_BUDGET.jsonl');results=json.loads((root/'RESULTS.json').read_text())
    reserves={x['id']:x for x in ledger if x['event']=='reserved'};responses={x['id']:x for x in ledger if x['event']=='response'}
    scope={x['id']:x for x in phases if x['event']=='reserved'}
    rows=[];known=unknown=0
    for idx,r in reserves.items():
        c=checks[idx-1];resp=responses.get(idx);valid=bool(resp and resp.get('usage_valid'))
        cost=resp['response']['usage']['total_tokens'] if valid else r['tokens']
        if valid:known+=cost
        else:unknown+=cost
        rows.append(dict(id=idx,task=scope[idx]['task'],phase=scope[idx]['phase'],reservation=r['tokens'],expected_reservation=c['input_tokens']+c['max_output_tokens'],reservation_correct=r['tokens']==c['input_tokens']+c['max_output_tokens'],known_usage=cost if valid else None,unknown_retained=0 if valid else cost))
    blocked=checks[len(reserves):]
    tasks=list(results['budget']['task_attempts'])
    with tempfile.TemporaryDirectory() as d:
        b=ScopedBudget(Path(d))
        try:b.bind_envelope(ResourceEnvelope(),tasks);old_decision='ADMIT'
        except StopRun as e:old_decision=str(e)
    # Replay observed sizes/known charges under proposed larger envelope. Not authorization.
    counter=[]
    with tempfile.TemporaryDirectory() as d:
        b=ScopedBudget(Path(d),{**CAPS,'new_total_tokens':56000});b.bind_envelope(ResourceEnvelope(phase_tokens={'generation':14000,'execution':14000}),tasks)
        ops={'plan_typed_dag':'plan','repair_semantic_plan':'repair','review_coverage':'review'}
        for i,c in enumerate(checks,1):
            b.select(c['task'],c['phase'])
            try:
                b.check_request(ops[c['operation']],c['input_tokens'],c['max_output_tokens']);rid=b.reserve('historical-diagnostic')
                original=responses.get(i)
                if original:b.settle(rid,original['response'])
                decision='WOULD_ALLOW_RESERVATION'
            except StopRun as e:decision=str(e)
            counter.append(dict(original_request_index=i,original_dispatched=i in reserves,decision=decision))
    after={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in names}
    return dict(source=str(root),source_hashes=before,source_unchanged=before==after,attempts=len(reserves),known_tokens=known,unknown_retained_tokens=unknown,rows=rows,blocked_prechecks=blocked,default_24000_admission=old_decision,recommended_56000_counterfactual=counter,generation_did_not_borrow_execution=all(r['phase']=='generation' for r in rows) and all(v<=6000 for v in results['budget']['phase_charged'].values()),interpretation='Larger-envelope admission only; not new execution, quality or model-generation evidence')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);args=ap.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    base=Path(__file__).parent
    r=[audit(base/name) for name in ('stage3_fresh_acceptance_real_01','stage3_producer_fresh_real_01')]
    (out/'HISTORICAL_REPLAY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
    print(json.dumps([dict(source=x['source'],requests=x['attempts'],known_tokens=x['known_tokens'],unknown_retained=x['unknown_retained_tokens'],unchanged=x['source_unchanged']) for x in r]))
if __name__=='__main__':main()
