#!/usr/bin/env python3
"""RQ1 V1.8.2-R1 direction identifiability (SYNTHETIC; zero API calls).
Can task FEATURES predict which model is better per node type?
Pre-registered truth: extract/timeline -> DS favored iff dispersion<0.5 and input_len<0.5;
merge/verification/report -> GLM favored iff conflicts>0.5; else opposite. Task-level
direction flips w.p. eta (fixed task property, seed-separated). Learners train-only."""
import numpy as np, math, json, time
SEED=20261109
NTYPES=np.array(['extract','extract','timeline','merge','reason','verification','report'])
FEATS=['docs','doc_len','dispersion','entities','conflicts','temp_cx','fact_density','up_sens','input_len']
GLM_T=np.array([0,0,0,1,0,1,1],bool)

def build_tasks(n,eta,seed):
    rng=np.random.default_rng(seed)
    X=rng.random((n,len(FEATS)))          # features fixed per task
    X[:,0]=rng.integers(2,6,n)/5.0
    fav=np.zeros((n,7),dtype=int)         # 0=GLM favored,1=DS favored
    for t in range(n):
        ds_ext = (X[t,2]<0.5) and (X[t,8]<0.5)
        for ni in range(7):
            if NTYPES[ni] in ('extract','timeline'):
                fav[t,ni]=1 if ds_ext else 0
            elif NTYPES[ni]=='merge' or NTYPES[ni]=='verification' or NTYPES[ni]=='report':
                fav[t,ni]=0 if X[t,4]>0.5 else 1
            else: fav[t,ni]=rng.integers(0,2)
        if rng.random()<eta: fav[t]=1-fav[t]
    return X,fav

def acc_of(fav,delta,up=1.0):
    n=fav.shape[0]; acc=np.empty((n,7,2))
    for t in range(n):
        for ni in range(7):
            f=fav[t,ni]
            acc[t,ni,f]=min(0.97,0.62+delta)
            acc[t,ni,1-f]=min(0.97,max(0.03,0.62-delta/3.0))
    return acc*up

def stump(Xtr,ytr):
    # best (feature,threshold,orient) minimizing misclassification; returns predictor
    best=None
    for fi in range(Xtr.shape[1]):
        for th in (0.25,0.5,0.75):
            for orient in (1,-1):
                pred=(Xtr[:,fi]>th).astype(int) if orient==1 else (Xtr[:,fi]<=th).astype(int)
                err=np.mean(pred!=ytr)
                if best is None or err<best[0]: best=(err,fi,th,orient)
    _,fi,th,orient=best
    def predict(X):
        return (X[:,fi]>th).astype(int) if orient==1 else (X[:,fi]<=th).astype(int)
    return predict,fi,th,orient

def run(n=40,eta=0.2,delta=0.15,N=3000,seed=1):
    rng=np.random.default_rng(seed)
    X,fav=build_tasks(n,eta,SEED); acc=acc_of(fav,delta)
    out={'NT':[],'TC':[],'CF':[],'TRUE':[],'dacc_TC':[],'dacc_NT':[],'jointTC':[],'GQ_TC':[],'GF_TC':[],'GR_TC':[],'cf5':[],'cf10':[],'cf20':[]}
    for b in range(N):
        reps=rng.binomial(2,acc)/2.0
        perm=rng.permutation(n); tr=perm[:n//2]; te=perm[n//2:]
        bu=0 if reps[tr,:,0].mean()>=reps[tr,:,1].mean() else 1
        # NT: per-type train majority
        ch={}
        for typ in ['extract','timeline','merge','reason','verification','report']:
            m=NTYPES==typ
            ch[typ]=0 if reps[tr][:,m,0].mean()>=reps[tr][:,m,1].mean() else 1
        nt=np.array([ch[t] for t in NTYPES])
        # TC: per-type stump on observed sign (train only)
        tc=np.zeros((n,7),dtype=int)
        for typ in {'extract','timeline','merge','reason','verification','report'}:
            m=NTYPES==typ
            y=(reps[tr][:,m,1].mean(1)>=reps[tr][:,m,0].mean(1)).astype(int)  # 1 if DS observed better
            pr,fi,th,orient=stump(X[tr],y)
            tc[:,m]=pr(X)[:,None]*np.ones((1,m.sum()))
        true_choice=fav
        # CF oracle: per type x quartile bin of best feature (train selection)
        cf=np.zeros((n,7),dtype=int)
        for typ in {'extract','timeline','merge','reason','verification','report'}:
            m=NTYPES==typ
            y=(reps[tr][:,m,1].mean(1)>=reps[tr][:,m,0].mean(1)).astype(int)
            _,fi,_,_=stump(X[tr],y)
            qs=np.quantile(X[tr,fi],[0.25,0.5,0.75])
            bins=np.digitize(X[:,fi],qs)
            for bk in range(4):
                sel=np.where(bins==bk)[0]
                trin=np.isin(sel,tr).nonzero()[0]
                trsel=sel[trin]
                if len(trsel)>0:
                    g=reps[trsel][:,m,0].mean(); d=reps[trsel][:,m,1].mean()
                    pick=0 if g>=d else 1
                else: pick=bu
                cf[np.ix_(sel,np.where(m)[0])]=pick
        def dq(choice):
            a=acc[np.arange(n)[:,None],np.arange(7)[None,:],choice].mean(1)
            ab=acc[np.arange(n)[:,None],np.arange(7)[None,:],bu].mean(1)
            return (a-ab)[te].mean()
        out['NT'].append(dq(np.tile(nt,(n,1)))); out['TC'].append(dq(tc))
        out['CF'].append(dq(cf)); out['TRUE'].append(dq(true_choice))
        out['dacc_TC'].append(float((tc[te]==fav[te]).mean()))
        out['dacc_NT'].append(float((np.tile(nt,(n,1))[te]==fav[te]).mean()))
    return {k:float(np.mean(v)) for k,v in out.items()}, {k:float(np.std(v)) for k,v in out.items()}

if __name__=='__main__':
    t0=time.time(); R={}
    print('RQ1 V1.8.2-R1 direction identifiability (SYNTHETIC; seed 20261109)')
    for eta in (0.2,0.4,0.5):
        m,sd=run(eta=eta,seed=200+int(eta*10)); R[f'eta={eta}']={'mean':m,'sd':sd}
        print(f'\n[eta={eta}] dQ vs BU: NT={m["NT"]:+.4f} TC={m["TC"]:+.4f} CF={m["CF"]:+.4f} TRUE={m["TRUE"]:+.4f}')
        print(f'  direction acc: NT={m["dacc_NT"]:.3f} TC={m["dacc_TC"]:.3f}')
    json.dump(R,open('RQ1_V1_8_2_R1_DIRECTION_RESULTS.json','w'),indent=1)
    print(f'\ntotal {time.time()-t0:.0f}s; SYNTHETIC only.')
