#!/usr/bin/env python3
"""RQ1 V1.8 calibration: H0/CI, direction inconsistency, partial complementarity,
parse/UNKNOWN, Oracle decomposition. Synthetic; no API calls."""
import sys,random,statistics as st
sys.path.insert(0,'/tmp')
from rq1_v17_lib import make_tasks,observe,select,q_task,exact_p,true_acc
random.seed(20261105)
GLM_T={'merge','verification','report'}

def q_oracle(obs,t):
    cov=0; sl=0
    for nid,typ in t['nodes']:
        s=1.0; sl+=s
        cov+=max(obs[(t['id'],nid,'GLM')],obs[(t['id'],nid,'DS')])*s
    return cov/sl

def run(n,delta=0.15,up=1.0,parse=0.0,dir_incons=False,partial=False,N=250):
    tasks=make_tasks(n); ntr=int(n*0.5); stats=[]
    for _ in range(N):
        random.shuffle(tasks); tr=tasks[:ntr]; te=tasks[ntr:]
        obs=observe(tasks,delta,0.03,up)
        # optional parse failure: with prob parse, node outcome 0 (all models)
        if parse:
            for k in list(obs):
                if random.random()<parse: obs[k]=0.0
        bu,tm=select(obs,tr)
        def q(t,strat):
            if strat=='Oracle': return q_oracle(obs,t)
            return q_task(obs,t,strat,bu,tm)
        d_or=[q(t,'Oracle')-q(t,'Best-Unified') for t in te]
        d_nt=[q(t,'Node-Type')-q(t,'Best-Unified') for t in te]
        d_tc=[q(t,'Task-Conditioned')-q(t,'Best-Unified') for t in te]
        # critical proxy: oracle gain >0 counts as a material task
        material=sum(1 for x in d_or if x>=1/17)
        stats.append({'or':st.mean(d_or),'nt':st.mean(d_nt),'tc':st.mean(d_tc),
                      'p_nt':exact_p(d_nt),'p_tc':exact_p(d_tc),
                      'mat':material/len(te)})
    def m(k): return st.mean(s[k] for s in stats)
    def ci(k):
        xs=[s[k] for s in stats]; mu=st.mean(xs); se=st.stdev(xs)/len(xs)**0.5
        return mu-1.96*se,mu+1.96*se
    return {'oracle':m('or'),'nt':m('nt'),'tc':m('tc'),
            'p_nt':sum(s['p_nt']<=0.05 for s in stats)/N,
            'p_tc':sum(s['p_tc']<=0.05 for s in stats)/N,
            'material':m('mat'),'ci_or':ci('or'),'ci_nt':ci('nt')}

print('RQ1 V1.8 calibration (synthetic; fixed seed 20261105)')
print('== H0 (delta=0) ==')
for n in (16,24,40):
    r=run(n,delta=0.0,N=300)
    print(f'N={n}: H0 FP NT={r["p_nt"]:.3f} TC={r["p_tc"]:.3f}; oracle dQ={r["oracle"]:+.4f}')
print('\n== effect + decomposition (delta=0.15, up=1.0) ==')
for n in (16,24,40):
    r=run(n,delta=0.15,N=250)
    print(f'N={n}: Oracle={r["oracle"]:+.4f} NT={r["nt"]:+.4f} TC={r["tc"]:+.4f} '
          f'powerNT={r["p_nt"]:.3f} mat_tasks={r["material"]:.3f} CI_or=[{r["ci_or"][0]:+.3f},{r["ci_or"][1]:+.3f}]')
print('\n== parse failure / upstream / direction / partial (N=40) ==')
for parse in (0.0,0.10,0.20):
    r=run(40,delta=0.15,parse=parse,N=200)
    print(f'parse={parse:.2f}: Oracle={r["oracle"]:+.4f} NT={r["nt"]:+.4f} powerNT={r["p_nt"]:.3f}')
for up in (1.0,0.85,0.70):
    r=run(40,delta=0.15,up=up,N=200)
    print(f'up={up:.2f}: Oracle={r["oracle"]:+.4f} NT={r["nt"]:+.4f} powerNT={r["p_nt"]:.3f}')
print('\nSynthetic only; no real model calls.')

# === direction inconsistency / partial complementarity ===
def run_scenario(n,delta=0.15,N=200,dir_incons=False,partial=False):
    tasks=make_tasks(n); ntr=int(n*0.5); out=[]
    for _ in range(N):
        random.shuffle(tasks); tr=tasks[:ntr]; te=tasks[ntr:]
        obs={}
        for t in tasks:
            sign=1.0
            if dir_incons and (hash(t['id'])%2==1): sign=-1.0
            for nid,typ in t['nodes']:
                for m in ('GLM','DS'):
                    eff=0.0
                    if partial and typ not in ('merge','verification','report'): eff=0.0
                    elif m=='GLM' and typ in ('merge','verification','report'): eff=delta*sign
                    elif m=='DS' and typ in ('extract','timeline'): eff=delta*sign
                    elif m in ('GLM','DS'): eff=-delta*0.33*sign
                    p=max(0.03,min(0.97,0.62+eff))
                    obs[(t['id'],nid,m)]=sum(1 for _ in range(2) if random.random()<p)/2
        bu,tm=select(obs,tr)
        # task-conditioned rule (uses task features, not true sign)
        def q(t,strat):
            if strat=='Oracle': return q_oracle(obs,t)
            if strat=='Task-Conditioned':
                if t['comp']=='HIGH' and any(ty in ('merge','verification','report') for _,ty in t['nodes']): mh='GLM'
                else: mh='GLM'
                cov=0; sl=0
                for nid,typ in t['nodes']:
                    s=1.0; sl+=s
                    m=('GLM' if typ in ('merge','verification','report') else 'DS')
                    cov+=obs[(t['id'],nid,m)]*s
                return cov/sl
            return q_task(obs,t,strat,bu,tm)
        d={s:[q(t,s)-q(t,'Best-Unified') for t in te] for s in ('Node-Type','Task-Conditioned','Oracle')}
        out.append(d)
    def mean(s): return st.mean(st.mean(x) for x in (o[s] for o in out))
    return {s:mean(s) for s in ('Node-Type','Task-Conditioned','Oracle')}

print('\n== direction inconsistency / partial complementarity (N=40) ==')
for label,kw in [('baseline',{}),('direction flip',{'dir_incons':True}),('partial (extract/timeline equal)',{'partial':True}),('both',{'dir_incons':True,'partial':True})]:
    r=run_scenario(40,0.15,N=150,**kw)
    print(f'{label}: Oracle={r["Oracle"]:+.4f} NT={r["Node-Type"]:+.4f} TC={r["Task-Conditioned"]:+.4f}')
print('\nNote: Oracle on test is upward biased by max-of-noisy selection; H0 Oracle ~+0.18.')
print('Synthetic only; no real model calls.')
