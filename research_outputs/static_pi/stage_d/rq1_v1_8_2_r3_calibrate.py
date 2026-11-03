#!/usr/bin/env python3
"""R3-B/C calibration on the rebuilt mechanism (SYNTHETIC; zero API calls)."""
import numpy as np, math, json, time, sys
import rq1_v1_8_2_r3_mechanism as M
SEED=20261111

def stump(X,y):
    best=None
    for fi in range(X.shape[1]):
        for th in (0.3,0.5,0.7):
            for o in (1,-1):
                pred=(X[:,fi]>th).astype(int) if o==1 else (X[:,fi]<=th).astype(int)
                err=float(np.mean(pred!=y))
                if best is None or err<best[0]: best=(err,fi,th,o)
    return best

def build_strats(tr,delta,partial=False):
    R={m:M.full_run(tr,m,delta,partial=partial) for m in (0,1)}
    a0=M.per_type_acc(R[0]); a1=M.per_type_acc(R[1])
    def overall(run):
        v=[out[ni,fi]==0 for _,out,_,_ in run for ni in range(7) for fi in range(2) if not(ni==6 and fi==1)]
        return float(np.mean(v))
    ov={m:overall(R[m]) for m in (0,1)}; bu=0 if ov[0]>=ov[1] else 1
    nt={ty:(0 if a0[ty]>=a1[ty] else 1) for ty in set(M.TYPES)}
    # TC: per-type stump on task features -> label DS better (1)
    idx_of={tid:out for tid,out,_,_ in R[0]}
    idx_of1={tid:out for tid,out,_,_ in R[1]}
    tc={}
    X=np.array([t['feat'] for t in tr])
    for ty in set(M.TYPES):
        y=[]
        for t in tr:
            o0=idx_of[t['id']]; o1=idx_of1[t['id']]
            idx=[ni for ni,x in enumerate(M.TYPES) if x==ty]
            g=np.mean([o0[ni,fi]==0 for ni in idx for fi in range(2) if not(ni==6 and fi==1)])
            d=np.mean([o1[ni,fi]==0 for ni in idx for fi in range(2) if not(ni==6 and fi==1)])
            y.append(1 if d>=g else 0)
        tc[ty]=stump(X,np.array(y))
    def tcp(t):
        out=[]
        for ty in M.TYPES:
            err,fi,th,o=tc[ty]
            pred=1 if ((t['feat'][fi]>th) if o==1 else (t['feat'][fi]<=th)) else 0
            out.append(pred)
        return np.array(out)
    return dict(
        BU=lambda t:np.full(7,bu),
        NT=lambda t:np.array([nt[ty] for ty in M.TYPES]),
        TC=tcp,
        TRUE=lambda t:np.array([0 if M.base_p(0,ni,t,delta,partial)>=M.base_p(1,ni,t,delta,partial) else 1 for ni in range(7)])
    )

def metrics(te,fn,delta,up,extra_parse,partial):
    r=M.evaluate(te,fn,delta,up,extra_parse,partial=partial)
    return r

def run_cal(n,delta,nsim,up=1.0,extra_parse=0.0,flip=False,partial=False,seed=1):
    tasks=M.make_tasks(n); M.make_u(tasks)
    if flip:
        for i,t in enumerate(tasks):
            if i%2: t['sign']=-t['sign']
    rng=np.random.default_rng(seed)
    GQ=[];GF=[];GR=[];JOINT=[];DQ=[];NET=[];GRATE=[];DC=[];DM=[];DIR=[];TRUE=[]
    for b in range(nsim):
        idx=rng.permutation(n); tr=[tasks[i] for i in idx[:n//2]]; te=[tasks[i] for i in idx[n//2:]]
        S=build_strats(tr,delta,partial)
        B=metrics(te,S['BU'],delta,up,extra_parse,partial)
        R=metrics(te,S['NT'],delta,up,extra_parse,partial)
        T=metrics(te,S['TRUE'],delta,up,extra_parse,partial)
        dq=R['term']-B['term']; net=(R['ctp']-B['ctp'])-(R['cfp']-B['cfp'])
        mu=dq.mean(); se=dq.std(ddof=1)/math.sqrt(len(dq)); lo=mu-1.96*se
        gq=bool(mu>=0.0625 and lo>0)
        p=M.exact_p(net.tolist()); gf=bool(net.sum()>=1 and p<=0.05)
        dc=float(np.mean(R['cost']/B['cost']-1)); dm=float(np.mean(R['mk']/B['mk']-1))
        pni=float(R['parse'].mean()>=B['parse'].mean()-0.02)
        cni=float(R['contract'].mean()>=B['contract'].mean()-0.02)
        gr=bool(dc<=0.10 and dm<=0.10 and pni and cni)
        GQ.append(gq);GF.append(gf);GR.append(gr);JOINT.append(gq and gf and gr)
        DQ.append(mu);NET.append(net.sum());DC.append(dc);DM.append(dm)
        TRUE.append(T['term'].mean()-B['term'].mean())
        DIR.append(float(np.mean(R['term']>=B['term'])))
    def r(x): return float(np.mean(x))
    return dict(GQ=r(GQ),GF=r(GF),GR=r(GR),JOINT=r(JOINT),DQ=r(DQ),NET=r(NET),
                DC=r(DC),DM=r(DM),TRUE=r(TRUE),DIR=r(DIR),n=n,N=nsim)

if __name__=='__main__':
    t0=time.time(); R={}
    sc=[('H0',dict(n=40,delta=0.0,nsim=3000,seed=201)),
        ('H1 .15',dict(n=40,delta=0.15,nsim=1500,seed=202)),
        ('H1 .20',dict(n=40,delta=0.20,nsim=1000,seed=203)),
        ('up .85',dict(n=40,delta=0.15,nsim=1000,up=0.85,seed=204)),
        ('parse .10',dict(n=40,delta=0.15,nsim=1000,extra_parse=0.10,seed=205)),
        ('up+parse',dict(n=40,delta=0.15,nsim=1000,up=0.85,extra_parse=0.10,seed=206)),
        ('dir flip',dict(n=40,delta=0.15,nsim=1000,flip=True,seed=207)),
        ('partial',dict(n=40,delta=0.15,nsim=1000,partial=True,seed=208)),
        ('N=16',dict(n=16,delta=0.15,nsim=1000,seed=209)),
        ('N=24',dict(n=24,delta=0.15,nsim=1000,seed=210))]
    print('R3 calibration on rebuilt mechanism (SYNTHETIC)',flush=True)
    for name,cfg in sc:
        r=run_cal(**cfg); R[name]=r
        print(f'\n[{name}] GQ={r["GQ"]:.3f} GF={r["GF"]:.3f} GR={r["GR"]:.3f} JOINT={r["JOINT"]:.3f} '
              f'dQ={r["DQ"]:+.4f} net={r["NET"]:+.2f} dC={r["DC"]*100:+.1f}% dMk={r["DM"]*100:+.1f}% TRUE={r["TRUE"]:+.4f}',flush=True)
    json.dump(R,open('RQ1_V1_8_2_R3_CALIBRATION.json','w'),indent=1)
    print(f'\ntotal {time.time()-t0:.0f}s',flush=True)
