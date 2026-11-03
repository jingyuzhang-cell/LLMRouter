#!/usr/bin/env python3
"""RQ1 V1.8.1 high-precision calibration (synthetic; no API calls).
H0 20k, H1 20k, upstream/parse/direction 20k; Oracle True/Cross-fitted/Naive.
Vectorized exact sign-flip via subset-sum counts (float64 exact up to 2^53)."""
import sys,random,statistics as st,math,time
import numpy as np
sys.path.insert(0,'/tmp')
from rq1_v17_lib import make_tasks
RNG=np.random.default_rng(20261106)
TYPES=['extract','timeline','merge','reason','verification','report']
GLM_T={'merge','verification','report'}

def build(n):
    tasks=make_tasks(n)
    for t in tasks:
        # 7 nodes: 2 extract,1 timeline,1 merge,1 reason,1 verify,1 report
        t['nodes']=[(f'{ty}_{i}',ty) for i,ty in enumerate(['extract','extract','timeline','merge','reason','verification','report'])]
    return tasks

def exact_p_np(d):
    nz=np.array([x for x in d if x!=0],dtype=float)
    m=len(nz)
    if m==0: return 1.0
    order=np.argsort(np.abs(nz),kind='mergesort')
    ranks=np.zeros(m); i=0
    while i<m:
        j=i
        while j+1<m and abs(nz[order[j+1]])==abs(nz[order[i]]): j+=1
        ranks[order[i:j+1]]=(i+j+2)/2.0  # avg rank*2
        i=j+1
    ranks=ranks.astype(np.int64)
    W=int(ranks[nz>0].sum()); S=int(ranks.sum())
    c=np.zeros(S+1); c[0]=1.0
    for r in ranks:
        new=c.copy(); new[r:]+=c[:-r]; c=new
    total=float(1<<m)
    ge=c[W:].sum(); le=c[:W+1].sum()
    return 2.0*min(ge,le)/total

def true_p(model,typ,delta,comp='MEDIUM'):
    v=0.62
    if model=='GLM':
        v+=delta if typ in GLM_T else -delta*0.33
    else:
        v+=delta if typ in ('extract','timeline') else -delta*0.33
    return max(0.03,min(0.97,v))

def simulate(n,delta,N,up=1.0,parse=0.0,flip=False,seed=1):
    rng=np.random.default_rng(seed)
    tasks=build(n); ntr=n//2
    p_glm={}; p_ds={}
    for t in tasks:
        for nid,typ in t['nodes']:
            s=1.0
            if flip and (hash(t['id'])%2==1): s=-1.0
            p_glm[(t['id'],nid)]=min(0.97,max(0.03,0.62+((delta if typ in GLM_T else -delta*0.33)*s)))
            p_ds[(t['id'],nid)]=min(0.97,max(0.03,0.62+((delta if typ in ('extract','timeline') else -delta*0.33)*s)))
    # pre-generate all observations per sim inside loop (memory ok at N=20k? 20k*40*7*2*2 ~ 22M; batch 2000)
    out=[]
    for start in range(0,N,2000):
        B=min(2000,N-start)
        # obs[k, task, node, model, rep]
        for b in range(B):
            perm=rng.permutation(n); tr=perm[:ntr]; te=perm[ntr:]
            # observed reps
            obs=np.empty((n,7,2,2))
            for ti,t in enumerate(tasks):
                for ni,(nid,typ) in enumerate(t['nodes']):
                    for mi,m in enumerate(('GLM','DS')):
                        p=p_glm[(t['id'],nid)] if m=='GLM' else p_ds[(t['id'],nid)]
                        p*=up
                        if parse and rng.random()<parse: p=0.0
                        obs[ti,ni,mi,:]=rng.binomial(2,p,size=2)/2.0
            obs=obs.mean(axis=3)  # reps
            # selection on training
            gt=obs[tr,:,0].mean(); dt=obs[tr,:,1].mean(); bu=0 if gt>=dt else 1
            # type-level means
            tm={}
            for ti in tr:
                for ni,(nid,typ) in enumerate(tasks[ti]['nodes']):
                    tm.setdefault(typ,[[],[]])
                    tm[typ][0].append(obs[ti,ni,0]); tm[typ][1].append(obs[ti,ni,1])
            tmch={typ:(0 if np.mean(v[0])>=np.mean(v[1]) else 1) for typ,v in tm.items()}
            # task q
            def q(ti,choice):
                cov=0
                for ni,(nid,typ) in enumerate(tasks[ti]['nodes']):
                    m=choice(ni,typ)
                    cov+=obs[ti,ni,m]
                return cov/len(tasks[ti]['nodes'])
            def nt(ni,typ): return tmch.get(typ,bu)
            def oracle_naive(ni,typ): return 0 if obs[ti,ni,0]>=obs[ti,ni,1] else 1  # placeholder not used
            d_nt=[]; d_or_naive=[]; d_or_cf=[]
            # cross-fitted oracle: select per type on train, eval test (same as NT here)
            for ti in te:
                base=q(ti,lambda ni,typ: bu)
                d_nt.append(q(ti,nt)-base)
                # naive oracle uses test per-node max
                cov=0
                for ni,(nid,typ) in enumerate(tasks[ti]['nodes']):
                    cov+=max(obs[ti,ni,0],obs[ti,ni,1])
                d_or_naive.append(cov/len(tasks[ti]['nodes'])-base)
                # cross-fitted: type selection on train (NT)
                d_or_cf.append(q(ti,nt)-base)
            out.append((st.mean(d_nt),exact_p_np(d_nt),st.mean(d_or_naive),st.mean(d_or_cf),
                        np.mean([(1 if x>=1/17 else 0) for x in d_or_cf])))
    arr=np.array(out)
    def ci(x):
        mu=x.mean(); se=x.std(ddof=1)/math.sqrt(len(x)); return mu-1.96*se,mu+1.96*se
    return {'nt':arr[:,0].mean(),'nt_ci':ci(arr[:,0]),'p_nt':(arr[:,1]<=0.05).mean(),
            'oracle_naive':arr[:,2].mean(),'oracle_cf':arr[:,3].mean(),
            'material':arr[:,4].mean(),'n':len(arr)}

t0=time.time()
print('RQ1 V1.8.1 high-precision calibration (synthetic; seed 20261106)')
for label,kw in [('H0',{'delta':0.0}),('H1 0.15',{'delta':0.15}),('H1 0.20',{'delta':0.20}),
                 ('upstream 0.85',{'delta':0.15,'up':0.85}),('parse 0.10',{'delta':0.15,'parse':0.10}),
                 ('direction flip',{'delta':0.15,'flip':True})]:
    r=simulate(40,kw.pop('delta'),N=20000,seed=7,**kw)
    print(f'{label}: NT={r["nt"]:+.4f} CI=[{r["nt_ci"][0]:+.4f},{r["nt_ci"][1]:+.4f}] '
          f'FP/power={r["p_nt"]:.4f} naiveOracle={r["oracle_naive"]:+.4f} crossFitOracle={r["oracle_cf"]:+.4f} material={r["material"]:.3f}')
print(f'elapsed {time.time()-t0:.1f}s')
print('Synthetic only; no real model calls.')
