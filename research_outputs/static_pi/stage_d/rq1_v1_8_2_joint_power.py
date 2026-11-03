#!/usr/bin/env python3
"""RQ1 V1.8.2 joint acceptance simulation (SYNTHETIC only; no API calls).
P0: P(G_Q & G_F & G_R); P1: key-fact methods; P2: H0 50k, scenarios 20k.
Fixed seed; synthetic task/model; not real GLM/DeepSeek ability."""
import sys,math,time,json
import numpy as np
sys.path.insert(0,'/tmp')
from rq1_v17_lib import make_tasks
SEED=20261107
GLM_T={'merge','verification','report'}
# model price / latency proxies (relative, synthetic)
PRICE={'GLM':1.0,'DS':0.6}; LAT={'GLM':1.0,'DS':0.75}
CRIT_SHARE=0.23

def build(n):
    tasks=make_tasks(n)
    for t in tasks:
        t['nodes']=[(f'{ty}_{i}',ty) for i,ty in enumerate(['extract','extract','timeline','merge','reason','verification','report'])]
        t['crit']=np.full(len(t['nodes']),CRIT_SHARE)
    return tasks

def exact_p_np(d):
    nz=np.array([x for x in d if x!=0],dtype=float); m=len(nz)
    if m==0: return 1.0
    order=np.argsort(np.abs(nz),kind='mergesort'); ranks=np.zeros(m); i=0
    while i<m:
        j=i
        while j+1<m and abs(nz[order[j+1]])==abs(nz[order[i]]): j+=1
        ranks[order[i:j+1]]=(i+j+2)/2.0; i=j+1
    ranks=ranks.astype(np.int64); W=int(ranks[nz>0].sum()); S=int(ranks.sum())
    c=np.zeros(S+1); c[0]=1.0
    for r in ranks:
        new=c.copy(); new[r:]+=c[:-r]; c=new
    total=float(1<<m); ge=c[W:].sum(); le=c[:W+1].sum()
    return 2.0*min(ge,le)/total

def pval(d):
    return exact_p_np(d)

def simulate(n,delta,N,up=1.0,parse=0.0,flip=False,partial=False,seed=1):
    rng=np.random.default_rng(seed); tasks=build(n); ntr=n//2
    out=[]
    p_glm={}; p_ds={}
    for t in tasks:
        for nid,typ in t['nodes']:
            s=-1.0 if (flip and (hash(t['id'])%2==1)) else 1.0
            eff_g=(delta if typ in GLM_T else -delta*0.33)*s
            eff_d=(delta if typ in ('extract','timeline') else -delta*0.33)*s
            if partial and typ not in GLM_T: eff_g=0.0
            if partial and typ in GLM_T: eff_d=-delta*0.33*s
            p_glm[(t['id'],nid)]=min(0.97,max(0.03,(0.62+eff_g)*up))
            p_ds[(t['id'],nid)]=min(0.97,max(0.03,(0.62+eff_d)*up))
    for b in range(N):
        perm=rng.permutation(n); tr=perm[:ntr]; te=perm[ntr:]
        obs=np.empty((n,7,2))
        for ti,t in enumerate(tasks):
            for ni,(nid,typ) in enumerate(t['nodes']):
                for mi,m in enumerate(('GLM','DS')):
                    p=(p_glm[(t['id'],nid)] if m=='GLM' else p_ds[(t['id'],nid)])
                    if parse and rng.random()<parse: p=0.0
                    obs[ti,ni,mi]=rng.binomial(2,p,size=1)[0]/2.0
        gt=obs[tr,:,0].mean(); dt=obs[tr,:,1].mean(); bu=0 if gt>=dt else 1
        tm={}
        for ti in tr:
            for ni,(nid,typ) in enumerate(tasks[ti]['nodes']):
                tm.setdefault(typ,[[],[]]); tm[typ][0].append(obs[ti,ni,0]); tm[typ][1].append(obs[ti,ni,1])
        tmch={ty:(0 if np.mean(v[0])>=np.mean(v[1]) else 1) for ty,v in tm.items()}
        def choose(strat,ti,ni,typ):
            if strat=='Best-Unified': return bu
            if strat=='Node-Type': return tmch.get(typ,bu)
            if strat=='Task-Conditioned': return 0 if typ in GLM_T else 1
            if strat=='Oracle-CF': return tmch.get(typ,bu)
            return bu
        def q(ti,strat):
            cov=0; kcov=0; ktot=0
            for ni,(nid,typ) in enumerate(tasks[ti]['nodes']):
                m=choose(strat,ti,ni,typ); cov+=obs[ti,ni,m]
                kc=tasks[ti]['crit'][ni]; ktot+=kc; kcov+=obs[ti,ni,m]*kc
            return cov/7.0,kcov/max(ktot,1e-9)
        def cost(ti,strat):
            c=0; l=0
            for ni,(nid,typ) in enumerate(tasks[ti]['nodes']):
                m=choose(strat,ti,ni,typ)
                c+=PRICE['GLM'] if m==0 else PRICE['DS']; l+=LAT['GLM'] if m==0 else LAT['DS']
            return c/7.0,l/7.0
        dq=[]; dk=[]; dc=[]; dl=[]
        for ti in te:
            qb,kb=q(ti,'Best-Unified'); qs,ks=q(ti,'Node-Type'); cb,lb=cost(ti,'Best-Unified'); cs,ls=cost(ti,'Node-Type')
            dq.append(qs-qb); dk.append(ks-kb); dc.append((cs-cb)/max(cb,1e-9)); dl.append((ls-lb)/max(lb,1e-9))
        dq=np.array(dq); dk=np.array(dk)
        mu=dq.mean(); se=dq.std(ddof=1)/math.sqrt(len(dq)) if len(dq)>1 else 0
        ci_lo=mu-1.96*se
        net=dk.sum(); p_k=pval(dk)
        GQ=(mu>=0.0625 and ci_lo>0)
        GF=(net>=1 and p_k<=0.05)
        GR=(np.mean(dc)<=0.10 and np.mean(dl)<=0.10)
        out.append((GQ,GF,GR,GQ and GF and GR,mu,ci_lo,net,p_k,np.mean(dc),np.mean(dl)))
    gq=[bool(x[0]) for x in out]; gf=[bool(x[1]) for x in out]; gr=[bool(x[2]) for x in out]
    jo=[bool(x[3]) for x in out]
    return {'GQ':sum(gq)/len(gq),'GF':sum(gf)/len(gf),'GR':sum(gr)/len(gr),'JOINT':sum(jo)/len(jo),
            'dq':float(np.mean([x[4] for x in out])),'dq_ci_lo':float(np.mean([x[5] for x in out])),
            'net':float(np.mean([x[6] for x in out])),'pk':float(np.mean([x[7] for x in out])),
            'dc':float(np.mean([x[8] for x in out])),'dl':float(np.mean([x[9] for x in out]))}

def mc_ci(p,n):
    se=math.sqrt(max(p*(1-p),1e-12)/n); return (p-1.96*se,p+1.96*se)

if __name__=='__main__':
    t0=time.time()
    print('RQ1 V1.8.2 joint acceptance (SYNTHETIC; seed 20261107)')
    print('condition: GQ=deltaQ>=6.25% & CI_lo>0; GF=critical net>=1 & p<=.05; GR=dC<=10% & dL<=10%; JOINT=all')
    scenarios=[
        ('H0',dict(n=40,delta=0.0,N=50000,seed=21)),
        ('H1 d=.15',dict(n=40,delta=0.15,N=20000,seed=22)),
        ('H1 d=.20',dict(n=40,delta=0.20,N=20000,seed=23)),
        ('up .85',dict(n=40,delta=0.15,N=20000,up=0.85,seed=24)),
        ('parse .10',dict(n=40,delta=0.15,N=20000,parse=0.10,seed=25)),
        ('up .85+parse .10',dict(n=40,delta=0.15,N=20000,up=0.85,parse=0.10,seed=26)),
        ('direction flip',dict(n=40,delta=0.15,N=20000,flip=True,seed=27)),
        ('partial',dict(n=40,delta=0.15,N=20000,partial=True,seed=28)),
        ('N=16 H1',dict(n=16,delta=0.15,N=20000,seed=29)),
        ('N=24 H1',dict(n=24,delta=0.15,N=20000,seed=30)),
    ]
    results={}
    for name,cfg in scenarios:
        t=time.time(); r=simulate(**cfg); results[name]=r
        print(f'\n[{name}] n={cfg["n"]} N={cfg["N"]}')
        for k in ('GQ','GF','GR','JOINT'):
            p=r[k]; lo,hi=mc_ci(p,cfg['N']); print(f'  {k}: {p:.4f} MC95CI=[{lo:.4f},{hi:.4f}]')
        print(f'  dQ={r["dq"]:+.4f} CI_lo={r["dq_ci_lo"]:+.4f} critNet={r["net"]:+.3f} p_key={r["pk"]:.4f} dC={r["dc"]*100:+.2f}% dL={r["dl"]*100:+.2f}%')
        print(f'  elapsed {time.time()-t:.1f}s')
    json.dump(results,open('RQ1_V1_8_2_JOINT_RESULTS.json','w'),indent=1)
    print(f'\ntotal {time.time()-t0:.1f}s; SYNTHETIC only; no real calls.')
