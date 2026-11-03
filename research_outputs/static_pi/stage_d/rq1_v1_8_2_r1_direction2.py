#!/usr/bin/env python3
"""Direction identifiability vs measurement budget (reps per node per model).
SYNTHETIC; zero API calls. Same generative truth as r1_direction."""
import numpy as np, json, time
exec(open('rq1_v1_8_2_r1_direction.py').read().split("def run(")[0])

def run_reps(n,eta,delta,reps,N,seed):
    rng=np.random.default_rng(seed)
    X,fav=build_tasks(n,eta,SEED); acc=acc_of(fav,delta)
    NT=[];TC=[];CF=[];TR=[];aTC=[];aNT=[]
    for b in range(N):
        r=rng.binomial(reps,acc)/float(reps)
        perm=rng.permutation(n); tr=perm[:n//2]; te=perm[n//2:]
        bu=0 if r[tr,:,0].mean()>=r[tr,:,1].mean() else 1
        ch={}
        for typ in ['extract','timeline','merge','reason','verification','report']:
            m=NTYPES==typ
            ch[typ]=0 if r[tr][:,m,0].mean()>=r[tr][:,m,1].mean() else 1
        nt=np.array([ch[t] for t in NTYPES])
        tc=np.zeros((n,7),dtype=int)
        for typ in {'extract','timeline','merge','reason','verification','report'}:
            m=NTYPES==typ
            y=(r[tr][:,m,1].mean(1)>=r[tr][:,m,0].mean(1)).astype(int)
            pr,_,_,_=stump(X[tr],y)
            tc[:,m]=np.repeat(pr(X)[:,None],m.sum(),axis=1)
        def dq(c):
            a=acc[np.arange(n)[:,None],np.arange(7)[None,:],c].mean(1)
            ab=acc[np.arange(n)[:,None],np.arange(7)[None,:],bu].mean(1)
            return (a-ab)[te].mean()
        NT.append(dq(np.tile(nt,(n,1)))); TC.append(dq(tc)); TR.append(dq(fav))
        aTC.append(float((tc[te]==fav[te]).mean())); aNT.append(float((np.tile(nt,(n,1))[te]==fav[te]).mean()))
    return {k:float(np.mean(v)) for k,v in dict(NT=NT,TC=TC,TR=TR,aTC=aTC,aNT=aNT).items()}

if __name__=='__main__':
    R={}
    print('Direction identifiability vs reps (eta=0.2, delta=0.15, N=1500)')
    for reps in (2,4,8,16):
        m=run_reps(40,0.2,0.15,reps,1500,seed=300+reps)
        R[f'reps={reps}']=m
        print(f'reps={reps:2d}: dQ NT={m["NT"]:+.4f} TC={m["TC"]:+.4f} TRUE={m["TR"]:+.4f} | dirAcc NT={m["aNT"]:.3f} TC={m["aTC"]:.3f}')
    json.dump(R,open('RQ1_V1_8_2_R1_DIRECTION_REPS.json','w'),indent=1)
    print('SYNTHETIC only.')
