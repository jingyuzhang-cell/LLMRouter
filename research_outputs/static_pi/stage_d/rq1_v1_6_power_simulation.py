#!/usr/bin/env python3
"""RQ1 V1.6 zero-call power optimization. Synthetic only; no API calls.
Questions: N needed for 70%/80% power; upstream dilution; task heterogeneity;
Complexity-Aware vs Node-Type vs Task-Conditioned; clustering; H0 calibration.
"""
import random,statistics as st,math,json
random.seed(20261103)
TYPES=['extract','timeline','merge','reason','verification','report']
TSHARE={'extract':0.40,'timeline':0.12,'merge':0.15,'reason':0.08,'verification':0.12,'report':0.13}
CLUSTERS=['regulatory','ma','disclosure','mixed']
def make_tasks(n):
    tasks=[]
    for i in range(n):
        # type mix per task: 5-7 nodes, all six types represented with weights
        nodes=[]
        for typ in TYPES:
            k=max(1,round(TSHARE[typ]*6))
            for j in range(k): nodes.append((f'{typ}_{j}',typ))
        comp='HIGH' if i%3==0 else 'MEDIUM'
        cluster=CLUSTERS[i%len(CLUSTERS)]
        tasks.append({'id':f'T{i:02d}','comp':comp,'cluster':cluster,'nodes':nodes})
    return tasks

def true_acc(model,typ,comp,task_effect,delta,complex_aware=False,up=1.0):
    v=0.62+task_effect
    if model=='GLM':
        v+=delta if typ in ('merge','verification','report') else -delta*0.33
        if complex_aware and comp=='HIGH' and typ in ('merge','verification','report'): v+=delta*0.5
    else:
        v+=delta if typ in ('extract','timeline') else -delta*0.33
        if complex_aware and comp=='HIGH' and typ in ('merge','verification','report'): v-=delta*0.25
    return max(0.03,min(0.97,v*up))

def observe(tasks,delta,het,up,reps=2,complex_aware=False,cluster_corr=0.0):
    # task effect: global + cluster + idio
    cl={c:random.gauss(0,het) for c in CLUSTERS}
    obs={}
    for t in tasks:
        te=cl[t['cluster']]+random.gauss(0,het*(1-cluster_corr))
        for nid,typ in t['nodes']:
            for m in ('GLM','DS'):
                p=true_acc(m,typ,t['comp'],te,delta,complex_aware,up)
                obs[(t['id'],nid,m)]=sum(1 for _ in range(reps) if random.random()<p)/float(reps)
    return obs

def select(obs,tr):
    gm={m:st.mean([obs[(t['id'],n,m)] for t in tr for n,typ in t['nodes']]) for m in ('GLM','DS')}
    bu='GLM' if gm['GLM']>=gm['DS'] else 'DS'
    tm={}
    for typ in TYPES:
        vals={m:[obs[(t['id'],n,m)] for t in tr for n,ty in t['nodes'] if ty==typ] for m in ('GLM','DS')}
        tm[typ]=('GLM' if st.mean(vals['GLM'])>=st.mean(vals['DS']) else 'DS') if vals['GLM'] else bu
    return bu,tm

def choose(strat,typ,comp,bu,tm,tr_obs):
    if strat=='Node-Type': return tm[typ]
    if strat=='Task-Conditioned':
        # complexity + type rule
        if comp=='HIGH' and typ in ('merge','verification','report'): return 'GLM'
        if typ in ('extract','timeline'): return 'DS'
        return 'GLM'
    if strat=='Complexity-Aware':
        # type + complexity + dependency proxy (merge/verify/report are deeper)
        if typ in ('merge','verification','report'):
            return 'GLM' if comp=='HIGH' else ('GLM' if typ in ('verification','report') else 'DS')
        if typ in ('extract','timeline'): return 'DS'
        return 'GLM'
    return bu

def q_task(obs,t,strat,bu,tm):
    cov=0; sl=0
    for nid,typ in t['nodes']:
        s=TSHARE[typ]*len(t['nodes']); sl+=s
        m=choose(strat,typ,t['comp'],bu,tm,None)
        cov+=obs[(t['id'],nid,m)]*s
    return cov/sl

def exact_p(d):
    # two-sided exact sign-flip via subset-sum DP (O(m*rank_sum)), no 2^m
    nz=[x for x in d if x!=0]; m=len(nz)
    if m==0: return 1.0
    order=sorted(range(m),key=lambda i:abs(nz[i])); ranks=[0]*m; i=0
    while i<m:
        j=i
        while j+1<m and abs(nz[order[j+1]])==abs(nz[order[i]]): j+=1
        r=(i+j+2)  # avg rank *2, integer
        for k in range(i,j+1): ranks[order[k]]=r
        i=j+1
    W=sum(ranks[i] for i in range(m) if nz[i]>0)
    counts={0:1}
    for r in ranks:
        nxt={}
        for s,c in counts.items():
            nxt[s]=nxt.get(s,0)+c
            nxt[s+r]=nxt.get(s+r,0)+c
        counts=nxt
    total=1<<m
    ge=sum(c for s,c in counts.items() if s>=W)
    le=sum(c for s,c in counts.items() if s<=W)
    return 2.0*min(ge,le)/total

def power_for(n,delta,het,up,strat,N=300,complex_aware=False,cluster_corr=0.0):
    tasks=make_tasks(n); rej=0; eff=[]; pvals=[]
    for _ in range(N):
        obs=observe(tasks,delta,het,up,complex_aware=complex_aware,cluster_corr=cluster_corr)
        d=[]
        for held in tasks:
            tr=[t for t in tasks if t['id']!=held['id']]
            bu,tm=select(obs,tr)
            d.append(q_task(obs,held,strat,bu,tm)-q_task(obs,held,'Best-Unified',bu,tm))
        p=exact_p(d); pvals.append(p); rej+=p<=0.05; eff.append(st.mean(d))
    return rej/N, st.mean(eff), st.mean(pvals)


def power_split(n,delta,het,up,strat,N=300,test_frac=0.5,complex_aware=False,cluster_corr=0.0):
    """Valid test: select on train tasks, evaluate on disjoint held-out tasks."""
    tasks=make_tasks(n); ntr=max(2,int(round(n*(1-test_frac)))); rej=0; effs=[]
    for _ in range(N):
        random.shuffle(tasks); tr=tasks[:ntr]; te=tasks[ntr:]
        obs=observe(tasks,delta,het,up,complex_aware=complex_aware,cluster_corr=cluster_corr)
        bu,tm=select(obs,tr)
        d=[q_task(obs,t,strat,bu,tm)-q_task(obs,t,'Best-Unified',bu,tm) for t in te]
        p=exact_p(d); rej+=p<=0.05; effs.append(st.mean(d))
    return rej/N, st.mean(effs)

print('RQ1 V1.6 power optimization (synthetic; fixed seed 20261103)')
print('\n[A] LOTO sign-flip diagnostic (INVALID under selection dependence)')
for n in (8,12,16,20,24):
    p,_,_=power_for(n,0.0,0.03,1.0,'Node-Type',N=200)
    print(f'H0 LOTO N={n}: rejection at 0.05 = {p:.3f}')
print('\n[B] Valid split test: train 50% / held-out 50%; sign-flip on held-out')
print('N | testN | delta | Node-Type | Task-Cond | Complexity-Aware | H0 FP')
for n in (8,12,16,20,24):
    ntest=n-int(round(n*0.5))
    for delta in (0.10,0.15,0.20):
        p1,_=power_split(n,delta,0.03,1.0,'Node-Type',N=250)
        p2,_=power_split(n,delta,0.03,1.0,'Task-Conditioned',N=250)
        p3,_=power_split(n,delta,0.03,1.0,'Complexity-Aware',N=250,complex_aware=True)
        print(f'{n:2d} | {ntest:2d} | {delta:.2f} | {p1:.3f} | {p2:.3f} | {p3:.3f}')
    fp,_=power_split(n,0.0,0.03,1.0,'Node-Type',N=300)
    print(f'{n:2d} | {ntest:2d} | 0.00 | H0 FP = {fp:.3f}')
print('\n[C] Upstream / heterogeneity sensitivity (valid split, delta=0.15)')
for up in (1.0,0.85,0.70):
    p,_=power_split(24,0.15,0.03,up,'Node-Type',N=200)
    print(f'N=24 up={up:.2f}: Node-Type power={p:.3f}')
for het in (0.02,0.04,0.06):
    p,_=power_split(24,0.15,het,1.0,'Node-Type',N=200)
    print(f'N=24 het={het:.2f}: Node-Type power={p:.3f}')
for cc in (0.0,0.5,0.8):
    p,_=power_split(24,0.15,0.03,1.0,'Node-Type',N=200,cluster_corr=cc)
    print(f'N=24 cluster_corr={cc:.1f}: Node-Type power={p:.3f}')
print('\nSynthetic only; no real model calls.')
