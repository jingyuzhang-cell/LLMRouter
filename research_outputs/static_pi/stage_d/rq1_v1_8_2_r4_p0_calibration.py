#!/usr/bin/env python3
"""R4-P0 fixes + 5-arm contrast calibration (SYNTHETIC; zero API calls).

P0-1 sign_mode: 'stable' (all tasks sign=+1, type-consistent H1) / 'mixed' (hash parity).
P0-2 terminal answer surface = 13 decidable slots; slot correct = TP & loc & sup & report
     executed; MVS = +1 TP on answer surface = 1/13 (definition re-anchored, +1 TP kept).
P0-3 GF critical TP requires TP & loc & sup (same口径 as G_Q); FN/UNKNOWN reported.
P0-4 pure null: model-specific rates (parse/contract/loc/sup/unk) equalized.
Arms: Static(=train Best-Unified) / Node-Type / Task-Conditioned / Budget-Constrained /
      Oracle(TRUE, non-deployable). Fact-level parents fixed (audit item D).
Originals untouched: rq1_v1_8_2_r3_*.py stay as history.
"""
import numpy as np, math, json, time, hashlib
SEED=20261112
NODES=['e0','e1','t','m','r','v','p']
TYPES=['extract','extract','timeline','merge','reason','verification','report']
GLM_T={3,5,6}
FACT_PARENTS={0:{0:[],1:[]},1:{0:[],1:[]},2:{0:[(0,0)],1:[(0,1)]},
              3:{0:[(0,0),(1,0)],1:[(0,1),(1,1)]},4:{0:[(3,0)],1:[(3,1)]},
              5:{0:[(3,0),(2,0)],1:[(3,1),(2,1)]},6:{0:[(4,0),(5,0)],1:[]}}
CRIT=[(5,0),(5,1),(6,0)]
UNK_FACT=(6,1)
DEC=[(n,f) for n in range(7) for f in range(2) if (n,f)!=UNK_FACT]
RATES={'parse':np.array([0.98,0.96]),'contract':np.array([0.99,0.995]),
       'loc':np.array([0.95,0.92]),'sup':np.array([0.93,0.90]),'unk':np.array([0.80,0.70])}
PRICE=np.array([1.0,0.6]); LAT=np.array([1.0,0.75])
BASE_LAT=np.array([1.0,1.0,0.8,0.9,1.2,1.1,0.7])
FP_RATE=0.10

def make_tasks(n,seed=SEED,sign_mode='mixed'):
    rng=np.random.default_rng(seed)
    tasks=[]
    for i in range(n):
        h=1 if int(hashlib.sha256(f'T{i:02d}'.encode()).hexdigest(),16)%2==0 else -1
        tasks.append({'id':f'T{i:02d}','sign':1 if sign_mode=='stable' else h,
                      'eff':float(rng.normal(0,0.05)),'feat':rng.random(5),'U':None})
    return tasks

def make_u(tasks,seed=SEED):
    rng=np.random.default_rng(seed+1)
    for t in tasks:
        t['U']={'parse':rng.random(7),'contract':rng.random(7),'fact':rng.random((7,2,5))}

def base_p(model,ni,task,delta):
    if model==0: adv=delta if ni in GLM_T else -delta/3
    else: adv=delta if ni in (0,1,2) else -delta/3
    return max(0.03,min(0.97,0.62+adv*task['sign']+task['eff']))

def run_task(task,assign,delta,up=1.0,extra_parse=0.0,corr=0.30,pure_null=False):
    R={k:(np.array([v.mean()]*2) if pure_null else v) for k,v in RATES.items()}
    U=task['U']; out=np.full((7,2),2,int); loc=np.zeros((7,2),bool); sup=np.zeros((7,2),bool)
    exec_ok=np.zeros(7,bool)
    for ni in range(7):
        m=int(assign[ni])
        pk=(U['parse'][ni]<=R['parse'][m]-extra_parse) and (U['contract'][ni]<=R['contract'][m])
        exec_ok[ni]=pk
        if not pk: continue
        b=base_p(m,ni,task,delta)
        for fi in range(2):
            if (ni,fi)==UNK_FACT:
                out[ni,fi]=3 if U['fact'][ni,fi,2]<=R['unk'][m] else 1
                continue
            cons=FACT_PARENTS[ni][fi]
            q=float(np.mean([out[pn,pf]==0 for pn,pf in cons])) if cons else 1.0
            q=max(0.0,min(1.0,q*up))
            pp=max(0.02,min(0.98,b*(0.35+0.65*q)))
            if ni==5: pp=min(0.98,pp+corr*(1-q)*(1-b))
            u=U['fact'][ni,fi,0]
            out[ni,fi]=0 if u<=pp else (1 if U['fact'][ni,fi,1]<FP_RATE else 2)
            if out[ni,fi] in (0,1):
                loc[ni,fi]=U['fact'][ni,fi,3]<=R['loc'][m]
                sup[ni,fi]=U['fact'][ni,fi,4]<=R['sup'][m]
    return out,loc,sup,exec_ok

def score(out,loc,sup,exec_ok):
    gate=exec_ok[6]
    term=float(np.mean([out[n,f]==0 and loc[n,f] and sup[n,f] and gate for n,f in DEC]))
    local=float(np.mean([out[n,f]==0 for n,f in DEC]))
    ctp=int(sum(out[n,f]==0 and loc[n,f] and sup[n,f] for n,f in CRIT))
    cfp=int(sum(out[n,f]==1 for n,f in CRIT))
    cfn=int(sum(out[n,f]==2 for n,f in CRIT))
    unk=int(out[UNK_FACT]==3)
    return local,term,ctp,cfp,cfn,unk

def makespan(assign):
    lat=BASE_LAT*LAT[assign]; L=np.zeros(7)
    L[2]=lat[0]+lat[2]; L[3]=max(lat[0],lat[1])+lat[3]
    L[4]=L[3]+lat[4]; L[5]=max(L[3],L[2])+lat[5]; L[6]=max(L[4],L[5])+lat[6]
    return L[6]

def exact_p(d):
    nz=np.asarray([x for x in d if x!=0],float); m=len(nz)
    if m==0: return 1.0
    order=np.argsort(np.abs(nz),kind='mergesort'); ranks=np.zeros(m,np.int64); i=0
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

def stump(X,y):
    best=None
    for fi in range(X.shape[1]):
        for th in (0.3,0.5,0.7):
            for o in (1,-1):
                pred=(X[:,fi]>th).astype(int) if o==1 else (X[:,fi]<=th).astype(int)
                err=float(np.mean(pred!=y))
                if best is None or err<best[0]: best=(err,fi,th,o)
    return best

def train_arm_models(tr,delta,up,extra_parse,pure_null):
    runs={m:[run_task(t,np.full(7,m),delta,up,extra_parse,pure_null=pure_null) for t in tr] for m in (0,1)}
    acc={m:{} for m in (0,1)}
    for m in (0,1):
        for (o,l,s,e), in [(r,) for r in runs[m]]:
            pass
    for m in (0,1):
        for t,r in zip(tr,runs[m]):
            o,l,s,e=r
            for ni in range(7):
                for fi in range(2):
                    if (ni,fi)==UNK_FACT: continue
                    acc[m].setdefault((ni,),[]).append(o[ni,fi]==0)
    type_acc={m:{} for m in (0,1)}
    for m in (0,1):
        for ty in set(TYPES):
            vals=[v for (ni,),vv in acc[m].items() for v in vv if TYPES[ni]==ty]
            type_acc[m][ty]=float(np.mean(vals))
    a0=[np.mean([o[ni,fi]==0 for ni in range(7) for fi in range(2) if (ni,fi)!=UNK_FACT]) for o in [r[0] for r in runs[0]]]
    a1=[np.mean([o[ni,fi]==0 for ni in range(7) for fi in range(2) if (ni,fi)!=UNK_FACT]) for o in [r[0] for r in runs[1]]]
    bu=0 if np.mean(a0)>=np.mean(a1) else 1
    nt={ty:(0 if type_acc[0][ty]>=type_acc[1][ty] else 1) for ty in set(TYPES)}
    gain={ty:type_acc[0][ty]-type_acc[1][ty] for ty in set(TYPES)}
    X=np.array([t['feat'] for t in tr]); tc={}
    for ty in set(TYPES):
        y=[]
        for t,r0,r1 in zip(tr,runs[0],runs[1]):
            idx=[ni for ni,x in enumerate(TYPES) if x==ty]
            g=np.mean([r0[0][ni,fi]==0 for ni in idx for fi in range(2) if (ni,fi)!=UNK_FACT])
            d=np.mean([r1[0][ni,fi]==0 for ni in idx for fi in range(2) if (ni,fi)!=UNK_FACT])
            y.append(1 if d>=g else 0)
        tc[ty]=stump(X,np.array(y))
    return bu,nt,gain,tc

def build_arms(tr,delta,up,extra_parse,pure_null):
    bu,nt,gain,tc=train_arm_models(tr,delta,up,extra_parse,pure_null)
    def static(t): return np.full(7,bu)
    def node_type(t): return np.array([nt[ty] for ty in TYPES])
    def task_cond(t):
        a=[]
        for ty in TYPES:
            err,fi,th,o=tc[ty]
            a.append(1 if ((t['feat'][fi]>th) if o==1 else (t['feat'][fi]<=th)) else 0)
        return np.array(a)
    def budget(t):
        a=np.full(7,bu)
        cbu=np.mean(PRICE[np.full(7,bu)]); mbu=makespan(np.full(7,bu))
        if bu==1:
            order=sorted([(gain[ty],ni) for ni,ty in enumerate(TYPES) if gain[ty]>0],reverse=True)
            for g,ni in order:
                trial=a.copy(); trial[ni]=0
                if np.mean(PRICE[trial])<=1.10*cbu and makespan(trial)<=1.10*mbu: a=trial
        else:
            for ni,ty in enumerate(TYPES):
                if gain[ty]<0: a[ni]=1
        return a
    def oracle(t):
        return np.array([0 if base_p(0,ni,t,delta)>=base_p(1,ni,t,delta) else 1 for ni in range(7)])
    return {'Static':static,'Node-Type':node_type,'Task-Cond':task_cond,'Budget-Con':budget,'Oracle':oracle}

def evaluate(te,fn,delta,up,extra_parse,pure_null):
    loc=[];term=[];ctp=[];cfp=[];cfn=[];unk=[];cost=[];mk=[];parr=[];carr=[];glm_n=[]
    for t in te:
        a=fn(t)
        out,lo,su,eok=run_task(t,a,delta,up,extra_parse,pure_null=pure_null)
        l,q,ct,cf,cn,un=score(out,lo,su,eok)
        loc.append(l);term.append(q);ctp.append(ct);cfp.append(cf);cfn.append(cn);unk.append(un)
        cost.append(float(np.mean(PRICE[a])));mk.append(makespan(a))
        R=RATES if not pure_null else {k:np.array([v.mean()]*2) for k,v in RATES.items()}
        parr.append(float(np.mean([t['U']['parse'][ni]<=R['parse'][a[ni]]-extra_parse and
                                   t['U']['contract'][ni]<=R['contract'][a[ni]] for ni in range(7)])))
        carr.append(float(np.mean([t['U']['contract'][ni]<=R['contract'][a[ni]] for ni in range(7)])))
        glm_n.append(float(np.mean(a==0)))
    return {k:np.array(v) for k,v in dict(local=loc,term=term,ctp=ctp,cfp=cfp,cfn=cfn,unk=unk,
        cost=cost,mk=mk,parse=parr,contract=carr,glm=glm_n).items()}

def calibrate(n,delta,N,sign_mode='stable',up=1.0,extra_parse=0.0,pure_null=False,seed=1):
    tasks=make_tasks(n,sign_mode=sign_mode); make_u(tasks)
    rng=np.random.default_rng(seed)
    MVS=1.0/len(DEC)
    res={a:{'GQ':0,'GF':0,'GR':0,'JOINT':0,'dq':[],'net':[],'win':0,'tie':0,'lose':0,
            'term':[],'local':[],'cost':[],'mk':[],'ctp':[],'cfp':[],'cfn':[],'unk':[],'glm':[]} 
         for a in ('Static','Node-Type','Task-Cond','Budget-Con','Oracle')}
    agree=[];bu_glm=0
    for b in range(N):
        idx=rng.permutation(n); tr=[tasks[i] for i in idx[:n//2]]; te=[tasks[i] for i in idx[n//2:]]
        A=build_arms(tr,delta,up,extra_parse,pure_null)
        bu_glm+= int(A['Static'](te[0])[0]==0)
        agree.append(float(np.mean(A['Node-Type'](te[0])==A['Oracle'](te[0]))))
        E={a:evaluate(te,A[a],delta,up,extra_parse,pure_null) for a in A}
        S=E['Static']
        for a in E:
            R=E[a]
            if a=='Static':
                dq=np.zeros(len(te)); net=np.zeros(len(te))
            else:
                dq=R['term']-S['term']; net=(R['ctp']-S['ctp'])-(R['cfp']-S['cfp'])
            mu=float(dq.mean()); se=float(dq.std(ddof=1)/math.sqrt(len(dq))) if len(dq)>1 else 0.0
            gq=bool(mu>=MVS and mu-1.96*se>0)
            gf=bool(net.sum()>=1 and exact_p(net.tolist())<=0.05) if a!='Static' else False
            dc=float(np.mean(R['cost']/S['cost']-1)); dm=float(np.mean(R['mk']/S['mk']-1))
            pni=bool(R['parse'].mean()>=S['parse'].mean()-0.02); cni=bool(R['contract'].mean()>=S['contract'].mean()-0.02)
            gr=bool(dc<=0.10 and dm<=0.10 and pni and cni)
            r=res[a]
            r['GQ']+=gq; r['GF']+=gf; r['GR']+=gr; r['JOINT']+=(gq and gf and gr)
            r['dq'].append(mu); r['net'].append(float(net.sum()))
            r['win']+=float(np.mean(dq>0)); r['tie']+=float(np.mean(dq==0)); r['lose']+=float(np.mean(dq<0))
            for k1,k2 in (('term','term'),('local','local'),('cost','cost'),('mk','mk'),
                          ('ctp','ctp'),('cfp','cfp'),('cfn','cfn'),('unk','unk'),('glm','glm')):
                r[k1].append(float(R[k2].mean()))
    out={'n':n,'N':N,'MVS':MVS,'P_Static_GLM':bu_glm/N,'NT_Oracle_agree':float(np.mean(agree))}
    for a in res:
        r=res[a]
        out[a]={'GQ':r['GQ']/N,'GF':r['GF']/N,'GR':r['GR']/N,'JOINT':r['JOINT']/N,
                'dQ':float(np.mean(r['dq'])),'net':float(np.mean(r['net'])),
                'win':r['win']/N,'tie':r['tie']/N,'lose':r['lose']/N,
                'term':float(np.mean(r['term'])),'local':float(np.mean(r['local'])),
                'cost':float(np.mean(r['cost'])),'mk':float(np.mean(r['mk'])),
                'ctp':float(np.mean(r['ctp'])),'cfp':float(np.mean(r['cfp'])),
                'cfn':float(np.mean(r['cfn'])),'unk':float(np.mean(r['unk'])),
                'glm_share':float(np.mean(r['glm']))}
    return out

if __name__=='__main__':
    t0=time.time()
    SC=[('H0 pure null',dict(n=40,delta=0.0,N=600,sign_mode='stable',pure_null=True,seed=401)),
        ('stable H1 .15',dict(n=40,delta=0.15,N=600,sign_mode='stable',seed=402)),
        ('stable H1 .20',dict(n=40,delta=0.20,N=600,sign_mode='stable',seed=403)),
        ('mixed H1 .15',dict(n=40,delta=0.15,N=400,sign_mode='mixed',seed=404)),
        ('stable .15 up+parse',dict(n=40,delta=0.15,N=400,sign_mode='stable',up=0.85,extra_parse=0.10,seed=405))]
    R={}
    print('R4-P0 5-arm contrast calibration (SYNTHETIC; MVS=1/13 on answer surface)',flush=True)
    for name,cfg in SC:
        r=calibrate(**cfg); R[name]=r
        print(f'\n=== {name} (N={cfg["N"]}) P(Static=GLM)={r["P_Static_GLM"]:.3f} NT-Oracle agree={r["NT_Oracle_agree"]:.3f}',flush=True)
        for a in ('Node-Type','Task-Cond','Budget-Con','Oracle'):
            d=r[a]
            print(f'  {a:12s} dQ={d["dQ"]:+.4f} net={d["net"]:+.2f} GQ={d["GQ"]:.3f} GF={d["GF"]:.3f} GR={d["GR"]:.3f} JOINT={d["JOINT"]:.3f} '
                  f'win/tie/lose={d["win"]:.2f}/{d["tie"]:.2f}/{d["lose"]:.2f} glm={d["glm_share"]:.2f} cost={d["cost"]:.3f} mk={d["mk"]:.3f}',flush=True)
        print(f'  Static      term={r["Static"]["term"]:.3f} local={r["Static"]["local"]:.3f} ctp={r["Static"]["ctp"]:.2f} cfn={r["Static"]["cfn"]:.2f} unk={r["Static"]["unk"]:.2f}',flush=True)
        o=r['Oracle']; print(f'  Oracle      term={o["term"]:.3f} local={o["local"]:.3f} (propagation gap local-term={o["local"]-o["term"]:+.3f})',flush=True)
    json.dump(R,open('RQ1_V1_8_2_R4_P0_RESULTS.json','w'),indent=1)
    print(f'\ntotal {time.time()-t0:.0f}s; SYNTHETIC only; no API calls.',flush=True)
