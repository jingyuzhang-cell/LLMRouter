#!/usr/bin/env python3
"""RQ1 V1.7 plan power: A 8/8, B 12/12, C 20/20 (train/test), valid split test.
Synthetic only; no API calls. Local accuracy delta != terminal Q delta."""
import sys,random,statistics as st
sys.path.insert(0,'/tmp')
from rq1_v17_lib import make_tasks,observe,select,q_task,exact_p,true_acc
random.seed(20261104)

def node_true_delta(tasks,delta,up=1.0,complex_aware=False):
    # terminal true Q difference for Node-Type vs Best-Unified? Use oracle-free true rule.
    # True terminal Q: choose the truly better model per node type (oracle type rule).
    GLM_T={'merge','verification','report'}
    q={}
    for t in tasks:
        cov_or=0; cov_bu=0; sl=0
        for nid,typ in t['nodes']:
            s=1.0; sl+=s
            # true type-level: GLM on GLM_T, DS elsewhere
            m='GLM' if typ in GLM_T else 'DS'
            cov_or+=true_acc(m,typ,t['comp'],0.0,delta,complex_aware,up)*s
            # best unified true: GLM overall (3 types) vs DS (3 types) -> GLM if sum better
            cov_bu+=true_acc('GLM',typ,t['comp'],0.0,delta,complex_aware,up)*s
        q[t['id']]=(cov_or-cov_bu)/sl
    return st.mean(q.values())

def plan_power(n_train,n_test,delta,up=1.0,N=250,strat='Node-Type'):
    n=n_train+n_test; tasks=make_tasks(n); rej=0; eff=[]
    for _ in range(N):
        random.shuffle(tasks); tr=tasks[:n_train]; te=tasks[n_train:]
        obs=observe(tasks,delta,0.03,up)
        bu,tm=select(obs,tr)
        d=[q_task(obs,t,strat,bu,tm)-q_task(obs,t,'Best-Unified',bu,tm) for t in te]
        p=exact_p(d); rej+=p<=0.05; eff.append(st.mean(d))
    return rej/N, st.mean(eff)

print('RQ1 V1.7 plan power (synthetic; local delta vs terminal Q)')
print('true terminal Node-Type delta (up=1.0):')
for n in (16,24,40):
    ts=make_tasks(n)
    print(f'N={n}: local .10->{node_true_delta(ts,.10):+.4f} .15->{node_true_delta(ts,.15):+.4f} .20->{node_true_delta(ts,.20):+.4f}')
print('\nplan | local delta | up | power | mean terminal dQ')
for name,ntr,nte in [('A 8/8',8,8),('B 12/12',12,12),('C 20/20',20,20)]:
    for delta in (0.10,0.15,0.20):
        for up in (1.0,0.85):
            p,e=plan_power(ntr,nte,delta,up,N=200)
            print(f'{name} | {delta:.2f} | {up:.2f} | {p:.3f} | {e:+.4f}')
print('\nSynthetic only; no real model calls.')
