"""Diagnostic historical baseline; returns unsupported rather than synthetic priors."""
import math

def quantile(xs,p=.9):
    xs=sorted(xs)
    return xs[max(0,math.ceil(len(xs)*p)-1)] if xs else None

def wilson(k,n,z=1.96):
    if not n:return None
    p=k/n;den=1+z*z/n
    return ((p+z*z/(2*n))-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/den

class HistoricalBaseline:
    # Independent offline labels permitted for training; labels are NOT features.
    def __init__(self,rows,group_fields,*,quality_field='quality',min_tasks=20):
        self.fields=tuple(group_fields);self.quality_field=quality_field;self.min_tasks=min_tasks;self.groups={}
        allowed={'pool','model','operation','parameters_group','arm','task_type'}
        if set(self.fields)-allowed:raise ValueError('Outcome/oracle or unregistered feature forbidden')
        for r in rows:
            if r.get('synthetic') or r.get('cached'):continue
            key=tuple(r.get(f) for f in self.fields);self.groups.setdefault(key,[]).append(r)
    def predict(self,features,deadline=None):
        rs=self.groups.get(tuple(features.get(f) for f in self.fields),[])
        # One vote per task; repeated responses do not manufacture sample size.
        labels={};times={}
        for r in rs:
            if r.get(self.quality_field) is not None:labels.setdefault(r['uid'],[]).append(r[self.quality_field])
            if r.get('latency_s') is not None:times.setdefault(r['uid'],[]).append(r['latency_s'])
        ys=[sum(v)/len(v) for v in labels.values()];ts=[x for v in times.values() for x in v]
        q=sum(ys)/len(ys) if ys else None;smooth=(sum(ys)+1)/(len(ys)+2) if ys else None
        supported=len(ys)>=self.min_tasks
        return dict(status='DIAGNOSTIC_ONLY' if supported else 'INSUFFICIENT_DATA',n_quality_tasks=len(ys),
            quality_frequency=q,quality_smoothed=smooth,quality_lower95=wilson(sum(ys),len(ys)) if all(y in (0,1) for y in ys) else None,
            n_latency_tasks=len(times),latency_observations=len(ts),empirical_p90=quantile(ts),
            latency_status='DIAGNOSTIC_ONLY' if len(times)>=self.min_tasks else 'INSUFFICIENT_DATA',
            empirical_p_on=sum(x<=deadline for x in ts)/len(ts) if ts and deadline is not None else None,
            calibrated_guarantee=False)
