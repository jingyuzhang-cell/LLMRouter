#!/usr/bin/env python3
"""RQ1 V1.8.2-R3 mechanism rebuild (SYNTHETIC; zero API calls).

DAG: e0,e1 -> t(e0), m(e0,e1) -> r(m), v(m,t) -> p(r,v)
- Downstream consumes REAL parent outcomes; q = fraction of consumed parents that are TP.
- p(correct)=base*(0.35+0.65*q*up); verification adds correction 0.30*(1-q)*(1-base).
- Terminal = v0,v1,p0 require TP & localization & support; local Q = 13 decidable facts TP.
- CRN: one U array per (task,node,fact) shared by ALL strategies; strategy only changes model.
- Scores: TP/FP/FN/UNKNOWN + localization + support, all recorded separately.
"""
import numpy as np, math, json, hashlib, time, itertools
SEED=20261110
NODES=['e0','e1','t','m','r','v','p']
TYPES=['extract','extract','timeline','merge','reason','verification','report']
GLM_T={3,5,6}   # merge, verification, report
PARENTS={0:[],1:[],2:[(0,0),(0,1)],3:[(0,0),(1,0)],4:[(3,0)],
         5:[(3,0),(2,0)],6:[(4,0)]}
# fact-level parents: fact f of node n consumes given parent facts
FACT_PARENTS={0:{0:[],1:[]},1:{0:[],1:[]},2:{0:[(0,0)],1:[(0,1)]},
              3:{0:[(0,0),(1,0)],1:[(0,1),(1,1)]},4:{0:[(3,0)],1:[(3,1)]},
              5:{0:[(3,0),(2,0)],1:[(3,1),(2,1)]},6:{0:[(4,0),(5,0)],1:[]}}
CRIT=[(5,0),(5,1),(6,0)]  # terminal slots
UNK_FACT=(6,1)            # unknown-allowed, excluded from Q/TP
PARSE=np.array([0.98,0.96]); CONTRACT=np.array([0.99,0.995])
LOC=np.array([0.95,0.92]); SUP=np.array([0.93,0.90]); UNKR=np.array([0.80,0.70])
PRICE=np.array([1.0,0.6]); LAT=np.array([1.0,0.75])
BASE_LAT=np.array([1.0,1.0,0.8,0.9,1.2,1.1,0.7])
FP_RATE=0.10

def task_sign(tid):
    return 1 if int(hashlib.sha256(tid.encode()).hexdigest(),16)%2==0 else -1

def make_tasks(n, seed=SEED):
    rng=np.random.default_rng(seed)
    tasks=[]
    for i in range(n):
        tasks.append({'id':f'T{i:02d}','sign':task_sign(f'T{i:02d}'),
                      'eff':float(rng.normal(0,0.05)),
                      'feat':rng.random(5),'U':None})
    return tasks

def make_u(tasks, seed=SEED):
    rng=np.random.default_rng(seed+1)
    for t in tasks:
        t['U']={'parse':rng.random(7),'contract':rng.random(7),
                'fact':rng.random((7,2,5))}  # correct,fp,unk,loc,sup

def base_p(model,ni,task,delta,partial):
    adv=0.0
    if partial:
        if model==0: adv=delta if ni in GLM_T else 0.0
        else: adv=delta if ni in (0,1,2) else 0.0
    else:
        if model==0: adv=delta if ni in GLM_T else -delta/3
        else: adv=delta if ni in (0,1,2) else -delta/3
    return max(0.03,min(0.97,0.62+adv*task['sign']+task['eff']))

def run_task(task, assign, delta, up=1.0, extra_parse=0.0, corr=0.30,
             force=None, loc_override=None, sup_override=None, partial=False):
    """assign: 7 model indices. Returns outcome (0 TP,1 FP,2 FN,3 UNK), loc, sup."""
    U=task['U']
    out=np.full((7,2),2,dtype=int); loc=np.zeros((7,2),bool); sup=np.zeros((7,2),bool)
    for ni in range(7):
        m=int(assign[ni])
        p_ok = U['parse'][ni] <= (PARSE[m]-extra_parse)
        c_ok = U['contract'][ni] <= CONTRACT[m]
        if not (p_ok and c_ok):
            out[ni,:]=2; continue
        q=1.0
        if FACT_PARENTS[ni][0]:
            cons=[(pn,pf) for (pn,pf) in FACT_PARENTS[ni][0]]
            q=float(np.mean([out[pn,pf]==0 for pn,pf in cons]))
        q=max(0.0,min(1.0,q*up))
        b=base_p(m,ni,task,delta,partial)
        for fi in range(2):
            if ni==6 and fi==1:
                if U['fact'][ni,fi,2]<=UNKR[m]: out[ni,fi]=3
                else: out[ni,fi]=1
                continue
            pp=b*(0.35+0.65*q)
            if ni==5: pp=pp+corr*(1-q)*(1-b)   # verification correction
            pp=max(0.02,min(0.98,pp))
            u=U['fact'][ni,fi,0]
            if force is not None and (ni,fi) in force:
                out[ni,fi]=force[(ni,fi)]
            elif u<=pp: out[ni,fi]=0
            elif U['fact'][ni,fi,1]<FP_RATE: out[ni,fi]=1
            else: out[ni,fi]=2
        for fi in range(2):
            if out[ni,fi] in (0,1):
                lo=U['fact'][ni,fi,3]<=LOC[m]; so=U['fact'][ni,fi,4]<=SUP[m]
                if loc_override is not None: lo=bool(loc_override)
                if sup_override is not None: so=bool(sup_override)
                loc[ni,fi]=lo; sup[ni,fi]=so
    return out,loc,sup

def score_task(out,loc,sup):
    dec=[(n,f) for n in range(7) for f in range(2) if (n,f)!=UNK_FACT]
    local=float(np.mean([out[n,f]==0 for n,f in dec]))
    term=float(np.mean([out[n,f]==0 and loc[n,f] and sup[n,f] for n,f in CRIT]))
    ctp=int(sum(out[n,f]==0 for n,f in CRIT)); cfp=int(sum(out[n,f]==1 for n,f in CRIT))
    cfn=int(sum(out[n,f]==2 for n,f in CRIT))
    return local,term,ctp,cfp,cfn,int(np.sum(out==3)),float(loc.mean()),float(sup.mean())

def makespan(assign):
    lat=BASE_LAT*LAT[assign]
    L=np.zeros(7)
    L[2]=lat[0]+lat[2]
    L[3]=max(lat[0],lat[1])+lat[3]
    L[4]=L[3]+lat[4]
    L[5]=max(L[3],L[2])+lat[5]
    L[6]=max(L[4],L[5])+lat[6]
    return L[6]

def full_run(tasks,model,delta,up=1.0,extra_parse=0.0,partial=False):
    res=[]
    for t in tasks:
        out,loc,sup=run_task(t,np.full(7,model),delta,up,extra_parse,partial=partial)
        res.append((t['id'],out,loc,sup))
    return res

def per_type_acc(run):
    acc={}
    for tid,out,loc,sup in run:
        for ni,ty in enumerate(TYPES):
            for fi in range(2):
                if ni==6 and fi==1: continue
                acc.setdefault(ty,[]).append(out[ni,fi]==0)
    return {ty:float(np.mean(v)) for ty,v in acc.items()}

def exact_p(d):
    nz=np.asarray([x for x in d if x!=0],float); m=len(nz)
    if m==0: return 1.0
    order=np.argsort(np.abs(nz),kind='mergesort'); ranks=np.zeros(m,dtype=np.int64); i=0
    while i<m:
        j=i
        while j+1<m and abs(nz[order[j+1]])==abs(nz[order[i]]): j+=1
        ranks[order[i:j+1]]=i+j+2; i=j+1
    W=int(ranks[nz>0].sum()); S=int(ranks.sum())
    c=np.zeros(S+1); c[0]=1.0
    for r in ranks:
        new=c.copy(); new[r:]+=c[:-r]; c=new
    tot=float(1<<m); ge=c[W:].sum(); le=c[:W+1].sum()
    return min(1.0,2.0*min(ge,le)/tot)

def evaluate(tasks,choose,delta,up=1.0,extra_parse=0.0,partial=False):
    loc=[];term=[];ctp=[];cfp=[];cfn=[];unk=[];dc=[];dm=[];pk=[];ck=[]
    for t in tasks:
        a=choose(t)
        out,lo_,su_=run_task(t,a,delta,up,extra_parse,partial=partial)
        l,q,ct,cf,cn,u,lr,sr=score_task(out,lo_,su_)
        loc.append(l);term.append(q);ctp.append(ct);cfp.append(cf);cfn.append(cn);unk.append(u)
        dc.append(np.mean(PRICE[a]));dm.append(makespan(a))
        pk.append(np.mean([t['U']['parse'][ni] <= PARSE[a[ni]]-extra_parse
                           and t['U']['contract'][ni] <= CONTRACT[a[ni]] for ni in range(7)]))
        ck.append(np.mean([t['U']['contract'][ni] <= CONTRACT[a[ni]] for ni in range(7)]))
    return dict(local=np.array(loc),term=np.array(term),ctp=np.array(ctp),cfp=np.array(cfp),
                cfn=np.array(cfn),unk=np.array(unk),cost=np.array(dc),mk=np.array(dm),
                parse=np.array(pk),contract=np.array(ck))

def strategies(tr_tasks,delta,partial=False):
    R={0:full_run(tr_tasks,0,delta,partial=partial),1:full_run(tr_tasks,1,delta,partial=partial)}
    a0=per_type_acc(R[0]); a1=per_type_acc(R[1])
    def overall_acc(run):
        vals=[out[ni,fi]==0 for _,out,_,_ in run for ni in range(7) for fi in range(2)
              if not (ni==6 and fi==1)]
        return float(np.mean(vals))
    overall={m:overall_acc(R[m]) for m in (0,1)}
    bu=0 if overall[0]>=overall[1] else 1
    nt={ty:(0 if a0[ty]>=a1[ty] else 1) for ty in set(TYPES)}
    # per-node training (overfit "naive")
    node_acc={m:{} for m in (0,1)}
    for m in (0,1):
        for tid,out,_,_ in R[m]:
            for ni in range(7):
                for fi in range(2):
                    if ni==6 and fi==1: continue
                    node_acc[m].setdefault((tid,ni),[]).append(out[ni,fi]==0)
    node={}
    for tid in {t['id'] for t in tr_tasks}:
        for ni in range(7):
            g=np.mean(node_acc[0][(tid,ni)]); d=np.mean(node_acc[1][(tid,ni)])
            node[(tid,ni)]=0 if g>=d else 1
    return dict(BU=lambda t:np.full(7,bu), NT=lambda t:np.array([nt[ty] for ty in TYPES]),
                NODE=lambda t:np.array([node[(t['id'],ni)] if (t['id'],ni) in node else bu for ni in range(7)]),
                TRUE=lambda t:np.array([0 if base_p(0,ni,t,delta,False)>=base_p(1,ni,t,delta,False) else 1 for ni in range(7)]))

# ---------------- R3 tests ----------------
def t1_t2_upstream():
    def rate(forced):
        ts=make_tasks(300); make_u(ts)
        vals=[]
        for t in ts:
            out,_,_=run_task(t,np.full(7,1),0.15,
                             force=({(0,0):1,(0,1):1} if forced else None))
            vals.append(out[3,0]==0)  # m fact0 consumes e0
        return float(np.mean(vals))
    clean=rate(False); dirty=rate(True)
    return dirty < clean - 0.05

def t3_correction():
    # many tasks; compare v with corr=0 vs corr=.3 under degraded input
    ts=make_tasks(200); make_u(ts)
    for t in ts: t['eff']-=0.15
    def term(corr):
        vals=[]
        for t in ts:
            out,lo,su=run_task(t,np.array([1,1,1,0,0,1,0]),0.15,up=0.6,corr=corr)
            vals.append(score_task(out,lo,su)[1])
        return float(np.mean(vals))
    return term(0.30)>term(0.0)

def t4_terminal_separation():
    ts=make_tasks(100); make_u(ts)
    ls=[];qs=[]
    for t in ts:
        out,lo,su=run_task(t,np.zeros(7,dtype=int),0.0,sup_override=False)
        l,q,_,_,_,_,_,_=score_task(out,lo,su); ls.append(l); qs.append(q)
    return float(np.mean(ls))>0 and float(np.mean(qs))==0.0

def t5_scoring_complete():
    ts=make_tasks(50); make_u(ts)
    for t in ts:
        out,lo,su=run_task(t,np.zeros(7,dtype=int),0.1)
        l,q,ct,cf,cn,u,lr,sr=score_task(out,lo,su)
        n=13
        cnt=int(np.sum(out==0))+int(np.sum(out==1))+int(np.sum(out==2))+int(np.sum(out==3))
        if cnt!=14: return False
        if not (0<=l<=1 and 0<=q<=1 and 0<=lr<=1 and 0<=sr<=1): return False
    return True

def t6_crn():
    ts=make_tasks(40); make_u(ts)
    a=lambda t:np.array([0,1,0,1,0,1,0])
    r1=evaluate(ts,a,0.15); r2=evaluate(ts,a,0.15)
    return all(np.array_equal(r1[k],r2[k]) for k in r1)

def t7_pairing():
    ts=make_tasks(40); make_u(ts)
    a=lambda t:np.array([0,1,0,1,0,1,0])
    b=lambda t:np.array([0,1,0,1,0,1,1])
    ra=evaluate(ts,a,0.15); rb=evaluate(ts,b,0.15)
    # identical assignment must give identical outcomes (CRN); different assignment must differ somewhere
    ra2=evaluate(ts,a,0.15)
    same=all(np.array_equal(ra[k],ra2[k]) for k in ra)
    diff=not np.array_equal(ra['term'],rb['term'])
    return same and diff

def t8_exact():
    import random
    rng=random.Random(11)
    def brute(d):
        nz=[x for x in d if x!=0]; m=len(nz)
        if m==0: return 1.0
        srt=sorted(range(m),key=lambda i:abs(nz[i])); ranks=[0.0]*m; i=0
        while i<m:
            j=i
            while j+1<m and abs(nz[srt[j+1]])==abs(nz[srt[i]]): j+=1
            r=(i+j+2)/2.0
            for k in range(i,j+1): ranks[srt[k]]=r
            i=j+1
        obs=sum(r for r,x in zip(ranks,nz) if x>0); ge=le=0
        for sg in itertools.product([1,-1],repeat=m):
            w=sum(r for r,s in zip(ranks,sg) if s>0)
            ge+=w>=obs; le+=w<=obs
        return min(1.0,2.0*min(ge,le)/(1<<m))
    for _ in range(500):
        m=rng.randint(1,9); d=[rng.choice([-3,-2,-2,-1,0,0,1,2,2,3]) for _ in range(m)]
        if abs(exact_p(d)-brute(d))>1e-12: return False
    return True

def main():
    print('RQ1 V1.8.2-R3 mechanism tests (SYNTHETIC; zero API calls)',flush=True)
    tests=[('T1/T2 upstream propagation',t1_t2_upstream),('T3 correction',t3_correction),
           ('T4 local/terminal separation',t4_terminal_separation),('T5 scoring completeness',t5_scoring_complete),
           ('T6 CRN',t6_crn),('T7 pairing',t7_pairing),('T8 exact test',t8_exact)]
    R={}
    for name,fn in tests:
        t=time.time()
        try: ok=bool(fn()); err=''
        except Exception as e: ok=False; err=repr(e)
        R[name]={'pass':ok,'secs':round(time.time()-t,3),'err':err}
        print(f'{name}: {"PASS" if ok else "FAIL"} {err} ({time.time()-t:.2f}s)',flush=True)
    json.dump(R,open('RQ1_V1_8_2_R3_TESTS.json','w'),indent=1)

if __name__=='__main__':
    main()
