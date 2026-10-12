"""Enforced request-size bounds, not predictions of model quality or GPU speed."""
from dataclasses import dataclass,asdict
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun

@dataclass(frozen=True)
class StageBound:
    phase:str
    calls:int
    input_tokens:int
    output_tokens:int
    @property
    def reservation(self):return self.input_tokens+self.output_tokens

STAGES={
 'plan':StageBound('generation',1,2048,768),
 'repair':StageBound('generation',1,3072,768),
 'review':StageBound('generation',2,3072,384),
 'node':StageBound('execution',5,2048,256),
 'recovery':StageBound('execution',1,2048,256),
}

class ResourceEnvelope:
    def __init__(self,stages=None,*,task_requests=12,phase_tokens=None,request_timeout_s=30,cleanup_s=30):
        self.stages=dict(STAGES if stages is None else stages)
        for b in self.stages.values():
            if not isinstance(b,StageBound) or b.phase not in ('generation','execution') or any(type(v) is not int or v<=0 for v in (b.calls,b.input_tokens,b.output_tokens)):raise ValueError('Unbounded or invalid stage')
        if set(self.stages)!=set(STAGES):raise ValueError('All calling stages must be bounded')
        self.task_requests=task_requests;self.phase_tokens=dict(phase_tokens or {'generation':6000,'execution':6000})
        if set(self.phase_tokens)!={'generation','execution'} or any(type(v) is not int or v<=0 for v in self.phase_tokens.values()):raise ValueError('Invalid phase envelope')
        if type(task_requests) is not int or task_requests<=0 or request_timeout_s<=0 or cleanup_s<20:raise ValueError('Invalid request/wall envelope')
        self.timeout=request_timeout_s;self.cleanup=cleanup_s
    def totals(self):
        phases={p:sum(b.calls*b.reservation for b in self.stages.values() if b.phase==p) for p in self.phase_tokens}
        return dict(requests=sum(b.calls for b in self.stages.values()),tokens=sum(phases.values()),phase_tokens=phases)
    def to_dict(self):return dict(stages={k:asdict(v) for k,v in self.stages.items()},task_requests=self.task_requests,task_tokens=sum(self.phase_tokens.values()),phase_tokens=self.phase_tokens,request_timeout_s=self.timeout,cleanup_s=self.cleanup,totals=self.totals(),max_nodes=5,max_generation_repairs=1,max_execution_recoveries=1,guarantee='bounded dispatch resources; no quality, semantic-success or service-completion guarantee')
    def admit(self,tasks,caps):
        t=self.totals();reasons=[]
        if len(tasks)!=len(set(tasks)) or not tasks:raise ValueError('Unique tasks required')
        if t['requests']>self.task_requests:reasons.append('per_task_requests')
        for p,v in t['phase_tokens'].items():
            if v>self.phase_tokens[p]:reasons.append(p+'_worst_tokens')
        if len(tasks)*t['requests']>caps['new_request_attempts']:reasons.append('global_worst_requests')
        if len(tasks)*t['tokens']>caps['new_total_tokens']:reasons.append('global_worst_tokens')
        if 300+len(tasks)*t['requests']*self.timeout+self.cleanup>caps['wall_seconds']:reasons.append('nominal_wall_envelope')
        if reasons:raise StopRun('Envelope admission: '+','.join(reasons))
        return t
    def check_size(self,kind,ninput,maxout):
        b=self.stages[kind]
        if type(ninput) is not int or ninput<0 or type(maxout) is not int or maxout<=0:raise ValueError('Invalid token counts')
        if ninput>b.input_tokens:raise StopRun('Input length exceeds bounded '+kind+' envelope; never truncate dependencies')
        if maxout>b.output_tokens:raise StopRun('Output cap exceeds '+kind+' envelope')
        return ninput+maxout
    def remaining(self,counts,phase=None):
        slots={k:max(0,b.calls-counts.get(k,0)) for k,b in self.stages.items() if phase is None or b.phase==phase}
        return dict(tokens=sum(n*self.stages[k].reservation for k,n in slots.items()),requests=sum(slots.values()))

from contextlib import contextmanager
@contextmanager
def request_deadline(seconds):
    """Absolute HTTP duration bound; socket inactivity timeout alone is insufficient."""
    import signal,time
    old_handler=signal.getsignal(signal.SIGALRM);old_remaining,old_interval=signal.getitimer(signal.ITIMER_REAL);began=time.monotonic()
    def expired(signum,frame):raise StopRun('Request wall timeout; unknown usage reservation retained')
    signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,min(seconds,old_remaining) if old_remaining>0 else seconds)
    try:yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old_handler)
        if old_remaining>0:signal.setitimer(signal.ITIMER_REAL,max(.001,old_remaining-(time.monotonic()-began)),old_interval)
