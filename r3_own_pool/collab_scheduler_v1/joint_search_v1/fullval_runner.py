"""One authorized FULL validation, <=1h, <=30 dispatches, <=30000 tokens.

Default creates no calls. Freeze builds a versioned approval manifest. Execute
checks that manifest before GPU startup. No retries or overwrite/resume.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import time
from .evaluator import JointEvaluator,MeteredExecutor,NODES
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget,StopRun,append

ROOT=Path('/root/r3_own_pool')
HERE=Path(__file__).resolve().parent
MANIFEST=HERE/'FULLVAL_AUTHORIZED_1H.json'
UIDS=['5c5cb310-0607-4285-ba9f-d8b996c700db','1078998f-a141-45fc-918e-17ddf1da0d89','51f8785b-7864-4bb2-88b4-5367547de061','09aaae63-03dd-4173-ba29-1a4a60946982']
X=('large','large','medium','coder')
FAULT='###SYNTHETIC UNPARSEABLE r-output [directed syntax corruption]###'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'))


def tasks():
    from static_dag_v0.multidag_dynamic import hybrid_pool,ctx_table,ctx_text
    pool={t['uid']:t for t in hybrid_pool()}
    result=[]
    for uid in UIDS:
        t=dict(pool[uid]);t['ctx_table']=ctx_table(t['para']);t['ctx_text']=ctx_text(t['para'])
        result.append(t)
    return result


def freeze():
    if MANIFEST.exists():raise FileExistsError('Manifest exists; no silent rebinding')
    paths=[Path(__file__),HERE/'evaluator.py',ROOT/'collab_scheduler_v1/fault30_run.py',
           ROOT/'collab_scheduler_v1/fault30_protocol.py',ROOT/'static_dag_v0/run.py',
           ROOT/'static_dag_v0/multidag_dynamic.py',ROOT/'static_dag_v0/tool_aware_v1.py',
           ROOT/'collab_scheduler_v1/joint_search_smoke/proposal_v2/smoke_runner.py']
    models={}
    for slot in ('medium','large','coder'):
        provenance=ROOT/'router_v2/label_repair_experiment/raw'/f'{slot}_MODEL_PROVENANCE.json'
        paths.append(provenance)
        models[slot]=sha(provenance)  # manifest includes weight hashes; engine verifies actual weights
    m=dict(version='authorized_fullval_1h_v1',authorization='User: 你直接执行就行，然后跑一个小时的实验',
      caps=dict(new_request_attempts=30,new_total_tokens=30000,wall_seconds=3600,
        request_token_reservation=8192,max_output_tokens=512,logical_calls_per_task_config_state=12,automatic_retries=0),
      tasks=tasks(),bindings={str(p):sha(p) for p in paths},models=models,
      protocol_amendment='One hour is maximum, keep 30 requests/30k tokens. Prioritize first complete FULL before optional coverage. No claim of guaranteed FULL completion under unknown response sizes.',
      order='t1 S1,S4,S3,S2 then t2..t4 S1,S4,S2,S3; fresh validation-wide underlying-response cache; corruption never cached',
      limits='Calibration only; no formal search or statistical/algorithm advantage claim. Model switching counts toward wall. Cleanup may extend elapsed wall slightly.')
    MANIFEST.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(manifest=str(MANIFEST),sha256=sha(MANIFEST),model_calls=0)))


class ValidationExecutor(MeteredExecutor):
    def begin_cell(self,state,cid):
        super().begin_cell('fullval_shared_underlying',self.scenario+':'+cid)


def run(m,directory,backend):
    from collab_scheduler_v1.fault30_protocol import Ledger
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    append(directory/'MANIFEST.jsonl',m)
    budget=Budget(directory,m['caps']);start=time.monotonic()
    proc=log=None;current=None;lock=None
    old_out=backend.OUT;backend.OUT=directory
    status='VALIDATION_INCOMPLETE';reason='interrupted';full_completed=[];completed=[]
    previous={s:signal.getsignal(s) for s in (signal.SIGALRM,signal.SIGTERM)}
    def deadline(*_):raise StopRun('wall deadline or termination')
    try:
        lock=(ROOT/'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for s in previous:signal.signal(s,deadline)
        signal.setitimer(signal.ITIMER_REAL,m['caps']['wall_seconds'])
        def prepare(model):
            nonlocal proc,log,current
            budget.check()
            if model==current:return
            began=time.monotonic()
            if proc is not None:
                backend.stop_model(proc,log);proc=log=None;current=None
            proc,log,_=backend.start_model(model);current=model
            append(directory/'MODEL_SWITCH.jsonl',dict(model=model,wall_s=time.monotonic()-began))
            budget.check()
        ex=ValidationExecutor(directory,budget,backend.call_model,prepare,m['models'])
        led=Ledger()
        # Reinstantiate evaluator view to allow exact S1 rerun while retaining
        # the same validated underlying-response cache and global Budget.
        for i,t in enumerate(m['tasks']):
            sequence=('S1','S4','S3','S2') if i==0 else ('S1','S4','S2','S3')
            for scene in sequence:
                budget.check();ex.scenario=scene
                z={'S1':'NONE','S4':'NONE','S2':'LOCAL','S3':'FULL'}[scene]
                cid='__'.join((*X,z))
                fault={} if scene in ('S1','S4') else {t['uid']:('r',FAULT)}
                before=budget.attempts
                evaluator=JointEvaluator(ex,led,[t])
                result=evaluator.evaluate(cid,'clean' if not fault else 'fault30',fault)
                if scene=='S4':
                    if budget.attempts!=before or len(ex.events)!=4 or not all(e.get('alias_of') and ':S1:' in e['alias_of'] for e in ex.events):
                        raise StopRun('S4 provenance/new-request mismatch')
                if scene=='S3':
                    replay=[e for e in ex.workflow if ':replay:' in e['key']]
                    if len(replay)!=4 or {e['key'].split(':')[3] for e in replay}!=set(NODES) or len(ex.workflow)!=8:
                        raise StopRun('FULL four-node traversal incomplete')
                    full_completed.append(t['uid'])
                append(directory/'SCENARIOS.jsonl',dict(scenario=scene,uid=t['uid'],result=result,
                    injected_logical_calls=sum(bool(e['response'].get('injected_fault')) for e in ex.workflow),
                    replay_nodes=[e['key'] for e in ex.workflow if ':replay:' in e['key']]))
                completed.append([scene,t['uid']])
                if scene=='S1' and i==0:
                    append(directory/'L_SCALE_CALIBRATION.jsonl',dict(scale_max=result['objectives']['L']*1.4,
                      semantics='serial service-demand reconstruction',basis_uid=t['uid'],
                      rule='First S1 only, freeze before first S3; small diagnostic calibration. No later adjustment.'))
        status='COMPLETE';reason='all sixteen task/scenario cells completed'
    except BaseException as exc:
        reason=repr(exc)
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        for s,h in previous.items():signal.signal(s,h)
        try:
            if proc is not None:backend.stop_model(proc,log)
        except BaseException as exc:
            status='VALIDATION_INCOMPLETE';reason+='; cleanup failure '+repr(exc)
        finally:
            backend.OUT=old_out
            if lock is not None:lock.close()
            report=dict(status=status,reason=reason,full_status='FULL_PATH_VERIFIED' if full_completed else 'FULL_UNVERIFIED',
              completed=completed,full_completed=full_completed,requests=budget.attempts,
              tokens_known=budget.actual_tokens,tokens_charged_with_pending=budget.charged,
              pending=budget.pending,observed_wall_s=time.monotonic()-start,
              note='Physical ledger includes failures/pending. Incomplete cells have no complete objective. No automatic retry.')
            append(directory/'STATUS.jsonl',report)
    print(json.dumps(report,ensure_ascii=False))
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--execute',action='store_true');p.add_argument('--manifest-sha256');p.add_argument('--run-id',default='fullval_authorized_1h_01');a=p.parse_args()
    if a.freeze:freeze();return
    m=json.loads(MANIFEST.read_text())
    for path,digest in m['bindings'].items():
        if sha(path)!=digest:raise ValueError('Binding mismatch '+path)
    if canonical(tasks())!=canonical(m['tasks']):raise ValueError('Task content mismatch')
    if not a.execute:
        print(json.dumps(dict(status='PREFLIGHT_PASS',manifest_sha256=sha(MANIFEST),caps=m['caps'],model_calls=0)));return
    if os.environ.get('P1B_FULLVAL_EXECUTE')!='1' or a.manifest_sha256!=sha(MANIFEST):raise PermissionError('Approved manifest hash and environment required')
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in a.run_id):raise ValueError('Unsafe run id')
    from static_dag_v0 import run as engine
    report=run(m,HERE/'fullval_runs'/a.run_id,engine)
    raise SystemExit(0 if report['status']=='COMPLETE' else 2)

if __name__=='__main__':main()
