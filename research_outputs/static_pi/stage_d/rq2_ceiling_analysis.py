#!/usr/bin/env python3
"""RQ2 ceiling analysis from R5 per-task matrices (zero new calls).
Per-task constrained oracle: for each task choose the feasible 128 assignment with max
terminal Q; this is a non-deployable upper bound on any per-task dynamic allocation
without extra cost/latency. Estimate GQ/GF/JOINT by bootstrap 24-task splits.
"""
import json, numpy as np, math, os
from rq1_v1_8_2_r5_core import MVS
from rq1_v1_8_2_r4_p0_calibration import exact_p
OUT=os.path.dirname(os.path.abspath(__file__))
P=json.load(open(os.path.join(OUT,'RQ1_V1_8_2_R5_POPULATION.json')))
SC=['stable H1 .15','stable H1 .20','mixed H1 .15','upstream pressure','parse pressure','up+parse pressure','H0 pure null']
rng=np.random.default_rng(20261113)
NS=4000; NT=24

def gq_flags(dq):
    mu=float(dq.mean()); se=float(dq.std(ddof=1)/math.sqrt(len(dq))) if len(dq)>1 else 0.0
    return bool(mu>=MVS and mu-1.96*se>0)

def analyze(name):
    o=P[name]; slug=o['slug']
    z=np.load(os.path.join(OUT,f'RQ1_V1_8_2_R5_POP_{slug}.npz'))
    term=z['term_mat']; ctp=z['ctp_mat']; cfp=z['cfp_mat']
    masks=z['masks']; cost=z['cost']; mk=z['mk']; parse=z['parse']; contract=z['contract']
    base=o['base']; sm=o['static_mask']; base_idx=int(np.where(masks==sm)[0][0])
    st_term=term[base_idx]; st_ctp=ctp[base_idx]; st_cfp=cfp[base_idx]
    res={}
    for cap in (0.10,0.15,0.20):
        for mode,ratio in (('matched',1+cap),('strict',1.10)):
            feas=(cost<=base['cost']*(1+cap)+1e-12)&(mk<=base['mk']*ratio+1e-12)&(parse>=base['parse']-0.02-1e-12)&(contract>=base['contract']-0.02-1e-12)
            idx=np.where(feas)[0]
            if len(idx)==0:
                res[f'{int(cap*100)}_{mode}']={'n_feas':0}; continue
            sub=term[idx]  # nfeas x ntask
            best=idx[np.argmax(sub,axis=0)]  # per task
            q=term[best,np.arange(term.shape[1])]
            ctp_o=ctp[best,np.arange(term.shape[1])]
            cfp_o=cfp[best,np.arange(term.shape[1])]
            dq=q-st_term; net=(ctp_o-st_ctp)-(cfp_o-st_cfp)
            # bootstrap 24-task splits
            gq=gf=joint=0; dqs=[]; nets=[]
            for _ in range(NS):
                ii=rng.choice(len(dq),NT,replace=False)
                d=dq[ii]; n=net[ii]
                g=gq_flags(d)
                f=bool(n.sum()>=1 and exact_p(n.astype(int).tolist())<=0.05)
                gq+=g; gf+=f; joint+=(g and f)
                dqs.append(d.mean()); nets.append(n.sum())
            dq_t=q-st_term
            res[f'{int(cap*100)}_{mode}']={'n_feas':int(len(idx)),'mean_Q':float(q.mean()),
                'static_Q':float(st_term.mean()),'mean_dQ':float(dq_t.mean()),
                'GQ_boot':gq/NS,'GF_boot':gf/NS,'JOINT_boot':joint/NS,
                'best_mask_freq':int(np.bincount(best,minlength=128).argmax()),
                'best_mask_freq_share':float(np.bincount(best,minlength=128).max()/len(best))}
    # unconstrained per-task oracle
    best=np.argmax(term,axis=0)
    q=term[best,np.arange(term.shape[1])]; dq=q-st_term
    gq=gf=joint=0
    for _ in range(NS):
        ii=rng.choice(len(dq),NT,replace=False); d=dq[ii]
        bb=best[ii]; n=(ctp[bb,ii]-st_ctp[ii])-(cfp[bb,ii]-st_cfp[ii])
        g=gq_flags(d); f=bool(n.sum()>=1 and exact_p(n.astype(int).tolist())<=0.05)
        gq+=g; gf+=f; joint+=(g and f)
    res['unconstrained']={'mean_Q':float(q.mean()),'static_Q':float(st_term.mean()),
        'mean_dQ':float(dq.mean()),'GQ_boot':gq/NS,'GF_boot':gf/NS,'JOINT_boot':joint/NS}
    return res

R={}
for n in SC:
    R[n]=analyze(n)
    print('\n===',n)
    for k,v in R[n].items():
        print(' ',k,{kk:(round(vv,4) if isinstance(vv,float) else vv) for kk,vv in v.items()})
json.dump(R,open(os.path.join(OUT,'RQ2_CEILING_ANALYSIS.json'),'w'),indent=1)
