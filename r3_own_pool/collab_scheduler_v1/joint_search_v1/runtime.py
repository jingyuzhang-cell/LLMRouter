"""Durable campaign quotas and exclusive single-GPU session lifecycle.

This module does not start models on import and has no executable experiment CLI.
Production entry points must call require_admission before run_session.
"""
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import time

from .evaluator import JointEvaluator,MeteredExecutor,SearchSession
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget,StopRun,append


class CampaignQuota:
    """Hold lock for entire session; crash reservations never disappear.

    Each reserved slot counts even if it fails. New process reads the durable
    journal. Incomplete/malformed journal is an admission error, never reset.
    """
    def __init__(self,directory,caps,protocol_sha):
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/'CAMPAIGN.jsonl'
        self.caps=copy.deepcopy(caps)
        self.lock=(self.directory/'campaign.lock').open('a+')
        try:
            fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.sessions={}
            if self.path.exists():
                events=[json.loads(l) for l in self.path.read_text().splitlines()]
                if not events or events[0] != dict(event='protocol',sha256=protocol_sha,caps=self.caps):
                    raise ValueError('Campaign protocol/caps mismatch')
                for event in events[1:]:
                    sid=event['session']
                    if event['event']=='reserved':
                        if sid in self.sessions:raise ValueError('Duplicate reservation')
                        self.sessions[sid]=dict(reserved=event['limits'],charge=event['limits'],settled=False)
                    elif event['event']=='settled':
                        item=self.sessions[sid]
                        if item['settled']:raise ValueError('Duplicate settlement')
                        item.update(charge=event['charge'],settled=True)
                    else:raise ValueError('Unknown journal event')
            else:
                append(self.path,dict(event='protocol',sha256=protocol_sha,caps=self.caps))
        except BaseException:
            self.lock.close()
            raise

    def close(self):self.lock.close()

    def reserve(self,sid,limits):
        if sid in self.sessions:raise ValueError('Session exists; no automatic retry/resume')
        if len(self.sessions)>=self.caps['sessions']:raise StopRun('campaign session cap')
        charge={k:limits[k] for k in ('new_request_attempts','new_total_tokens','wall_seconds')}
        if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in charge.values()):
            raise ValueError('Invalid reservation')
        for k,v in charge.items():
            if sum(s['charge'][k] for s in self.sessions.values())+v>self.caps[k]:
                raise StopRun('campaign '+k)
        append(self.path,dict(event='reserved',session=sid,limits=charge))
        self.sessions[sid]=dict(reserved=charge,charge=charge,settled=False)

    def settle(self,sid,charge,status):
        item=self.sessions[sid]
        if item['settled']:raise ValueError('Already settled')
        if set(charge)!=set(item['reserved']) or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in charge.values()):
            raise ValueError('Invalid actual charge')
        # Record even an overrun: hiding real spend would corrupt the ledger.
        append(self.path,dict(event='settled',session=sid,charge=charge,status=status))
        item.update(charge=charge,settled=True)


def require_admission(protocol_path,admission_path,approved_sha):
    """Fail closed before model import/startup; approval binds all input hashes."""
    path=Path(protocol_path)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if approved_sha!=digest or os.environ.get('JOINT_SEARCH_EXECUTE')!='1':
        raise PermissionError('Exact protocol approval and execution environment required')
    a=json.loads(Path(admission_path).read_text())
    if a.get('protocol_sha256')!=digest or a.get('status')!='READY' or a.get('blockers') or not a.get('execution_authorized'):
        raise PermissionError('Research/execution admission incomplete')
    for field in ('selector_review_pass','independent_splits_verified','new_semantics_real_validation_pass','runtime_tests_pass'):
        if a.get(field) is not True:raise PermissionError('Missing gate: '+field)
    bindings=a.get('bindings',{})
    if not bindings:raise PermissionError('No frozen input bindings')
    for name,expected in bindings.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=expected:
            raise PermissionError('Changed admitted input: '+name)
    return json.loads(path.read_text())


def run_session(*,campaign,protocol_sha,protocol,method,seed,tasks,states,selector,
                ledger,backend,bindings,gpu_lock_path):
    """One method/seed session. backend has start_model/call_model/stop_model/OUT.

    No historical/cross-session cache. Selector factory wiring is external.
    Low-level API used by Stub tests; production caller must require_admission.
    """
    if method not in protocol['methods'] or seed not in protocol['search_seeds']:
        raise ValueError('Unregistered method/seed')
    if [x[0] for x in states]!=protocol['states']:
        raise ValueError('State panel differs from protocol')
    if not 0 < protocol['initial_design_count'] <= protocol['max_selected_configurations_per_session'] <= 48:
        raise ValueError('Invalid initial/configuration budget')
    if set(bindings)!=set(('medium','large','coder')):
        raise ValueError('Complete model provenance required')
    sid=f'{method}_{seed}'
    quota=CampaignQuota(campaign,protocol['campaign_caps'],protocol_sha)
    directory=Path(campaign)/sid
    gpu_lock=None;proc=log=None;current=None;budget=None
    status='INCOMPLETE';reason='interrupted';cleanup_ok=True
    start=time.monotonic();old_out=backend.OUT
    previous={s:signal.getsignal(s) for s in (signal.SIGALRM,signal.SIGTERM)}
    reserved=False
    try:
        # Lock before reserving or starting a service, never kill others' work.
        gpu_lock=Path(gpu_lock_path).open('a+')
        fcntl.flock(gpu_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        directory.mkdir(exist_ok=False)
        quota.reserve(sid,protocol['per_session_caps']);reserved=True
        append(directory/'PROTOCOL_SNAPSHOT.jsonl',protocol)
        append(directory/'MODEL_BINDINGS.jsonl',bindings)
        append(directory/'TASK_PANEL.jsonl',tasks)
        append(directory/'STATE_PANELS.jsonl',states)
        budget=Budget(directory,protocol['per_session_caps'])
        backend.OUT=directory
        def stop_signal(*_):raise StopRun('session wall deadline or termination')
        for s in previous:signal.signal(s,stop_signal)
        # Leave 60s within the total envelope for backend shutdown (<=40s in engine).
        work_seconds=protocol['per_session_caps']['wall_seconds']-60
        if work_seconds<=0:raise ValueError('Wall cap must reserve cleanup time')
        signal.setitimer(signal.ITIMER_REAL,max(.001,work_seconds-(time.monotonic()-start)))
        def prepare(model):
            nonlocal proc,log,current
            budget.check()
            if model==current:return
            begin=time.monotonic()
            if proc is not None:
                backend.stop_model(proc,log);proc=log=None;current=None
            proc,log,_=backend.start_model(model);current=model
            append(directory/'MODEL_SWITCH.jsonl',dict(model=model,wall_s=time.monotonic()-begin))
            budget.check()
        executor=MeteredExecutor(directory,budget,backend.call_model,prepare,bindings)
        evaluator=JointEvaluator(executor,ledger,tasks)
        session=SearchSession(evaluator,method,protocol['max_selected_configurations_per_session'])
        # Shared random initial design, included in budget. No task labels used.
        import random
        from .evaluator import space
        initial=random.Random(seed).sample([c['id'] for c in space()],protocol['initial_design_count'])
        for cid in initial:
            session.step(lambda c,o,cid=cid:cid,states)
        while len(session.selected)<session.max_configurations:
            session.step(selector,states)
        status,reason='COMPLETE','configuration limit completed'
    except BaseException as exc:
        reason=repr(exc)
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        for s,handler in previous.items():signal.signal(s,handler)
        try:
            if proc is not None:backend.stop_model(proc,log)
        except BaseException as exc:
            cleanup_ok=False;status='INCOMPLETE';reason+='; cleanup failed: '+repr(exc)
        finally:
            backend.OUT=old_out
            elapsed=time.monotonic()-start
            if reserved:
                record=dict(status=status,reason=reason,cleanup_ok=cleanup_ok,
                    observed_wall_s=elapsed,new_requests=budget.attempts if budget else 0,
                    charged_tokens=budget.charged if budget else 0,
                    pending=budget.pending if budget else {})
                try:
                    append(directory/'STATUS.jsonl',record)
                    if cleanup_ok:
                        quota.settle(sid,dict(new_request_attempts=record['new_requests'],
                            new_total_tokens=record['charged_tokens'],wall_seconds=elapsed),status)
                    # Uncertain live work retains complete campaign reservation.
                finally:
                    quota.close()
                    if gpu_lock is not None:gpu_lock.close()
            else:
                quota.close()
                if gpu_lock is not None:gpu_lock.close()
    return dict(status=status,reason=reason,directory=str(directory))
