#!/usr/bin/env python3
"""RQ1 V1.8.2-R1 joint acceptance with discrete facts (SYNTHETIC; zero API calls).

Pre-registered before any run:
- Generative model fully specified below; fixed seeds; deterministic direction via sha256.
- PRIMARY fact test = M1 exact sign-flip (corrected avg-rank x2). Justification: exact under
  task-level exchangeability, no distributional assumptions. M2/M3/M4 are sensitivity only,
  chosen BEFORE seeing results, not by significance.
- PRIMARY strategy = Node-Type. Critical-Node (CN) is a pre-registered mechanism-search arm.
- Fixed: 7 nodes/task (extract x2, timeline, merge, reason, verification, report);
  2 decidable facts/node (14/task); critical = verification(2)+report(2)=4/task;
  1 UNKNOWN-allowed fact on report (excluded from Q and TP);
  DAG: e0->(timeline,merge), e1->merge, merge->(reason,verification), timeline->verification,
  (reason,verification)->report; unlimited parallel workers; makespan = longest path.
- Relative prices/latencies are SYNTHETIC proxies; money NOT modeled.
"""
import numpy as np, hashlib, json, time, math, sys
SEED=20261108
NODE_TYPES=np.array(['extract','extract','timeline','merge','reason','verification','report'])
GLM_ADV=np.array([0,0,0,1,0,1,1])           # 1 where GLM has +delta
DS_ADV=np.array([1,1,1,0,0,0,0])
CRIT=np.zeros((7,2),bool); CRIT[5,:]=True; CRIT[6,:]=True
BASE_LAT=np.array([1.0,1.0,0.8,0.9,1.2,1.1,0.7])
PRICE=np.array([1.0,0.6]); LAT=np.array([1.0,0.75])
PARSE=np.array([0.98,0.96]); CONTRACT=np.array([0.99,0.995])
UNK=np.array([0.8,0.7]); FP_RATE=0.10
EDGES=[(0,2),(0,3),(1,3),(3,4),(3,5),(2,5),(4,6),(5,6)]

def exact_p(d):
    nz=np.asarray([x for x in d if x!=0],dtype=float); m=len(nz)
    if m==0: return 1.0
    order=np.argsort(np.abs(nz),kind='mergesort'); ranks=np.zeros(m,dtype=np.int64); i=0
    while i<m:
        j=i
        while j+1<m and abs(nz[order[j+1]])==abs(nz[order[i]]): j+=1
        ranks[order[i:j+1]]=i+j+2  # 2 x average rank (exact integer; FIX of R1)
        i=j+1
    W=int(ranks[nz>0].sum()); S=int(ranks.sum())
    c=np.zeros(S+1); c[0]=1.0
    for r in ranks:
        new=c.copy(); new[r:]+=c[:-r]; c=new
    tot=float(1<<m); ge=c[W:].sum(); le=c[:W+1].sum()
    return min(1.0,2.0*min(ge,le)/tot)

def task_sign(tid):
    return 1 if int(hashlib.sha256(tid.encode()).hexdigest(),16)%2==0 else -1

def make_acc(n,delta,up,flip,partial):
    rng=np.random.default_rng(SEED)
    ids=[f'T{i:02d}' for i in range(n)]
    acc=np.empty((n,7,2))
    for ti,tid in enumerate(ids):
        s=task_sign(tid) if flip else 1
        for ni in range(7):
            g=delta*GLM_ADV[ni]-(delta/3.0)*(1-GLM_ADV[ni])
            d=delta*DS_ADV[ni]-(delta/3.0)*(1-DS_ADV[ni])
            if partial: d=np.where(DS_ADV[ni]==1,0.0,-delta/3.0)
            acc[ti,ni,0]=max(0.03,min(0.97,(0.62+g*s)*up))
            acc[ti,ni,1]=max(0.03,min(0.97,(0.62+d*s)*up))
    return ids,acc

def makespan(chosen):
    lat=BASE_LAT*LAT[chosen]  # (n,7)
    L=np.zeros((chosen.shape[0],7))
    for u,v in [(0,1),(0,2),(0,3),(1,3)]: pass
    # topological: 0,1 -> 2,3 -> 4,5 -> 6
    L[:,2]=lat[:,0]+lat[:,2]
    L[:,3]=np.maximum(lat[:,0],lat[:,1])+lat[:,3]
    L[:,4]=L[:,3]+lat[:,4]
    L[:,5]=np.maximum(L[:,3],L[:,2])+lat[:,5]
    L[:,6]=np.maximum(L[:,4],L[:,5])+lat[:,6]
    return L[:,6]

def run_scenario(n,delta,N,up=1.0,extra_parse=0.0,flip=False,partial=False,sparse_crit=False,seed=1,B=500):
    rng=np.random.default_rng(seed)
    ids,acc=make_acc(n,delta,up,flip,partial)
    crit=CRIT.copy()
    if sparse_crit: crit=np.zeros((7,2),bool); crit[5,0]=True
    ncrit=int(crit.sum())
    accG=acc[:,:,0]; accD=acc[:,:,1]
    true_bu=0 if accG.mean()>=accD.mean() else 1
    res={k:[] for k in ['GQ','GF1','GF2','GF3','GF4','GR','JOINT','dq','ci_lo','net','p1','dc','dl','pnis','cnis','cov_q','cov_b','jointCN','dqCN','dcCN','pool','realized','cfGain','unkS','unkB','locS','locB','supS','supB']}
    phi=[]
    for b in range(N):
        reps=rng.binomial(2,acc)/2.0
        perm=rng.permutation(n); tr=perm[:n//2]; te=perm[n//2:]
        bu=0 if reps[tr,:,0].mean()>=reps[tr,:,1].mean() else 1
        ch={}
        for typ in ['extract','timeline','merge','reason','verification','report']:
            m=NODE_TYPES==typ
            g=reps[tr][:,m,0].mean(); d=reps[tr][:,m,1].mean()
            ch[typ]=0 if g>=d else 1
        nt=np.array([ch[t] for t in NODE_TYPES])
        strat={'BU':np.full(7,bu),'NT':nt,
               'CN':np.array([1,1,1,1,1,0,0])}  # CN: GLM on verification+report only
        # TRUE per-task per-node argmax
        true_choice=np.argmax(acc,axis=2)
        out={}
        for s,c in strat.items():
            C=np.tile(c,(n,1)) if s!='TRUE' else true_choice
            p_ok=(rng.random((n,7))<PARSE[C])&(rng.random((n,7))>=extra_parse)
            tp=(rng.random((n,7,2))<acc[np.arange(n)[:,None],np.arange(7)[None,:],C][:,:,None])&p_ok[:,:,None]
            fp=(~tp)&p_ok[:,:,None]&(rng.random((n,7,2))<FP_RATE)
            q=tp.reshape(n,-1).sum(1)/14.0
            ctp=(tp*crit).reshape(n,-1).sum(1); cfp=(fp*crit).reshape(n,-1).sum(1)
            cost=PRICE[C].mean(1); mk=makespan(C)
            ctr_ok=rng.random((n,7))<CONTRACT[C]
            # UNKNOWN fact on report
            uok=p_ok[:,6]&(rng.random(n)<UNK[C[:,6]])
            out[s]=(q,ctp,cfp,cost,mk,p_ok.mean(1),ctr_ok.mean(1),uok.astype(float))
        def dq_pair(s):
            return out[s][0][te]-out['BU'][0][te], out[s][1][te]-out['BU'][1][te], out[s][2][te]-out['BU'][2][te]
        dq,dcn,dfp=dq_pair('NT'); dq=dq; net=dcn-dfp
        mu=dq.mean(); se=dq.std(ddof=1)/math.sqrt(len(dq)); lo=mu-1.96*se
        GQ=bool(mu>=0.0625 and lo>0)
        p1=exact_p(net.tolist())
        # M2 paired permutation (sign-flip) on VALUES with MC (1000 flips); obs = total sum
        nzv=net[net!=0]
        if len(nzv)>0:
            signs=rng.choice([-1.0,1.0],size=(1000,len(nzv)))
            Wc=(signs*np.abs(nzv)).sum(1)
            obs=nzv.sum()
            p2=min(1.0,2.0*min((Wc>=obs).mean(),(Wc<=obs).mean()))
        else: p2=1.0
        # M3 cluster bootstrap
        idx=rng.integers(0,len(net),size=(B,len(net)))
        bm=net[idx].mean(1)
        p3=0.0 if np.percentile(bm,2.5)>0 else 1.0
        GF3=bool(net.sum()>=1 and p3==0.0)
        # M4 cluster normal
        z=net.mean()/(net.std(ddof=1)/math.sqrt(len(net))+1e-12)
        p4=2*(1-0.5*(1+math.erf(abs(z)/math.sqrt(2))))
        GF1=bool(net.sum()>=1 and p1<=0.05); GF2=bool(net.sum()>=1 and p2<=0.05); GF4=bool(net.sum()>=1 and p4<=0.05)
        dc=(out['NT'][3][te]/out['BU'][3][te]-1).mean()
        dl=(out['NT'][4][te]/out['BU'][4][te]-1).mean()
        pni=out['NT'][5][te].mean()>=out['BU'][5][te].mean()-0.02
        cni=out['NT'][6][te].mean()>=out['BU'][6][te].mean()-0.02
        GR=bool(dc<=0.10 and dl<=0.10 and pni and cni)
        res['GQ'].append(GQ);res['GF1'].append(GF1);res['GF2'].append(GF2);res['GF3'].append(GF3);res['GF4'].append(GF4)
        res['GR'].append(GR);res['JOINT'].append(GQ and GF1 and GR)
        res['dq'].append(mu);res['ci_lo'].append(lo);res['net'].append(net.sum());res['p1'].append(p1)
        res['dc'].append(dc);res['dl'].append(dl);res['pnis'].append(bool(pni));res['cnis'].append(bool(cni))
        # coverage: true conditional mean dq from acc under chosen models
        aNT=acc[np.arange(n)[:,None],np.arange(7)[None,:],np.tile(nt,(n,1))].mean(1)
        aBU=acc[np.arange(n)[:,None],np.arange(7)[None,:],bu].mean(1)
        tq=(aNT-aBU)[te].mean()
        res['cov_q'].append(lo<=tq<=mu+1.96*se)
        bl=np.percentile(bm,2.5); bh=np.percentile(bm,97.5)
        tn=net.mean(); res['cov_b'].append(bl<=tn<=bh)
        # CN joint
        dq2=out['CN'][0][te]-out['BU'][0][te]; net2=(out['CN'][1][te]-out['BU'][1][te])-(out['CN'][2][te]-out['BU'][2][te])
        mu2=dq2.mean(); se2=dq2.std(ddof=1)/math.sqrt(len(dq2))
        dc2=(out['CN'][3][te]/out['BU'][3][te]-1).mean(); dl2=(out['CN'][4][te]/out['BU'][4][te]-1).mean()
        pni2=out['CN'][5][te].mean()>=out['BU'][5][te].mean()-0.02; cni2=out['CN'][6][te].mean()>=out['BU'][6][te].mean()-0.02
        res['jointCN'].append(bool(mu2>=0.0625 and mu2-1.96*se2>0 and net2.sum()>=1 and exact_p(net2.tolist())<=0.05 and dc2<=0.10 and dl2<=0.10 and pni2 and cni2))
        res['dqCN'].append(mu2);res['dcCN'].append(dc2)
        # decomposition
        aTR=acc[np.arange(n)[:,None],np.arange(7)[None,:],true_choice].mean(1)
        res['pool'].append((aTR-aBU)[te].mean()); res['realized'].append(mu)
        res['cfGain'].append(mu)
        res['unkS'].append(out['NT'][7][te].mean());res['unkB'].append(out['BU'][7][te].mean())
        phi.append((GQ,GF1,GR))
    P=np.array(phi,dtype=float)
    def rate(k): return float(np.mean(res[k]))
    def phi_ij(i,j):
        a=P[:,i];b_=P[:,j]
        pa=a.mean();pb=b_.mean()
        den=math.sqrt(pa*(1-pa)*pb*(1-pb))
        return float(((a*b_).mean()-pa*pb)/den) if den>0 else 0.0
    return {'GQ':rate('GQ'),'GF1':rate('GF1'),'GF2':rate('GF2'),'GF3':rate('GF3'),'GF4':rate('GF4'),
            'GR':rate('GR'),'JOINT':rate('JOINT'),'jointCN':rate('jointCN'),
            'dq':float(np.mean(res['dq'])),'ci_lo':float(np.mean(res['ci_lo'])),
            'net':float(np.mean(res['net'])),'p1':float(np.mean(res['p1'])),
            'dc':float(np.mean(res['dc'])),'dl':float(np.mean(res['dl'])),
            'pni':rate('pnis'),'cni':rate('cnis'),
            'cov_q':rate('cov_q'),'cov_b':rate('cov_b'),
            'dqCN':float(np.mean(res['dqCN'])),'dcCN':float(np.mean(res['dcCN'])),
            'pool':float(np.mean(res['pool'])),'unkS':float(np.mean(res['unkS'])),'unkB':float(np.mean(res['unkB'])),
            'phi_QF':phi_ij(0,1),'phi_QR':phi_ij(0,2),'phi_FR':phi_ij(1,2)}

def mcci(p,n): 
    s=math.sqrt(max(p*(1-p),1e-12)/n); return [p-1.96*s,p+1.96*s]

if __name__=='__main__':
    t0=time.time()
    print('RQ1 V1.8.2-R1 joint acceptance, discrete facts (SYNTHETIC; seed 20261108)')
    print('fixed exact test (rank x2); deterministic sha256 direction; M1 primary (pre-registered)')
    sc=[('H0',dict(n=40,delta=0.0,N=50000,seed=101)),
        ('H1 d=.15',dict(n=40,delta=0.15,N=20000,seed=102)),
        ('H1 d=.20',dict(n=40,delta=0.20,N=20000,seed=103)),
        ('up .85',dict(n=40,delta=0.15,N=20000,up=0.85,seed=104)),
        ('parse +.10',dict(n=40,delta=0.15,N=20000,extra_parse=0.10,seed=105)),
        ('up+parse',dict(n=40,delta=0.15,N=20000,up=0.85,extra_parse=0.10,seed=106)),
        ('dir flip',dict(n=40,delta=0.15,N=20000,flip=True,seed=107)),
        ('partial',dict(n=40,delta=0.15,N=20000,partial=True,seed=108)),
        ('sparse crit',dict(n=40,delta=0.15,N=20000,sparse_crit=True,seed=109)),
        ('N=16 H1',dict(n=16,delta=0.15,N=20000,seed=110)),
        ('N=24 H1',dict(n=24,delta=0.15,N=20000,seed=111))]
    R={}
    for name,cfg in sc:
        t=time.time(); r=run_scenario(**cfg); R[name]=r
        print(f'\n[{name}] n={cfg["n"]} N={cfg["N"]} ({time.time()-t:.0f}s)')
        for k in ('GQ','GF1','GF2','GF3','GF4','GR','JOINT','jointCN'):
            print(f'  {k}: {r[k]:.4f} MC95[{mcci(r[k],cfg["N"])[0]:.4f},{mcci(r[k],cfg["N"])[1]:.4f}]')
        print(f'  dq={r["dq"]:+.4f} ci_lo={r["ci_lo"]:+.4f} net={r["net"]:+.2f} p1={r["p1"]:.3f}')
        print(f'  dC={r["dc"]*100:+.2f}% dMakespan={r["dl"]*100:+.2f}% parseNI={r["pni"]:.3f} contractNI={r["cni"]:.3f}')
        print(f'  covQ(norm)={r["cov_q"]:.3f} covNet(boot)={r["cov_b"]:.3f} phi(Q,F)={r["phi_QF"]:+.3f} phi(Q,R)={r["phi_QR"]:+.3f} phi(F,R)={r["phi_FR"]:+.3f}')
        print(f'  CN: dq={r["dqCN"]:+.4f} dC={r["dcCN"]*100:+.2f}% | pool(True-BU)={r["pool"]:+.4f} unk S/B={r["unkS"]:.2f}/{r["unkB"]:.2f}')
    json.dump(R,open('RQ1_V1_8_2_R1_JOINT_RESULTS.json','w'),indent=1)
    print(f'\ntotal {time.time()-t0:.0f}s; SYNTHETIC only; no real API calls.')
