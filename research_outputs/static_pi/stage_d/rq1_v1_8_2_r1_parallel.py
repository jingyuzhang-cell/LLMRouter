#!/usr/bin/env python3
"""Parallel driver for R1 joint scenarios (SYNTHETIC; zero API calls)."""
import sys, json, time, math, multiprocessing as mp
sys.argv=['x']
import rq1_v1_8_2_r1_joint as M

SC=[('H0',dict(n=40,delta=0.0,N=50000,seed=101)),
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

def work(item):
    name,cfg=item; t=time.time(); r=M.run_scenario(**cfg); r['_secs']=time.time()-t
    return name,r,cfg

def mcci(p,n):
    s=math.sqrt(max(p*(1-p),1e-12)/n); return (p-1.96*s,p+1.96*s)

if __name__=='__main__':
    t0=time.time(); R={}
    print('RQ1 V1.8.2-R1 joint (parallel, SYNTHETIC, corrected exact test)', flush=True)
    with mp.Pool(processes=6) as pool:
        for name,r,cfg in pool.imap_unordered(work, SC):
            R[name]=r; N=cfg['N']
            print(f'\n[{name}] n={cfg["n"]} N={N} ({r["_secs"]:.0f}s)', flush=True)
            for k in ('GQ','GF1','GF2','GF3','GF4','GR','JOINT','jointCN'):
                lo,hi=mcci(r[k],N); print(f'  {k}={r[k]:.4f} CI[{lo:.4f},{hi:.4f}]', flush=True)
            print(f'  dq={r["dq"]:+.4f} ci_lo={r["ci_lo"]:+.4f} net={r["net"]:+.2f} p1={r["p1"]:.3f}', flush=True)
            print(f'  dC={r["dc"]*100:+.2f}% dMk={r["dl"]*100:+.2f}% parseNI={r["pni"]:.3f} contractNI={r["cni"]:.3f}', flush=True)
            print(f'  covQ={r["cov_q"]:.3f} covNet={r["cov_b"]:.3f} phiQF={r["phi_QF"]:+.3f} phiQR={r["phi_QR"]:+.3f} phiFR={r["phi_FR"]:+.3f}', flush=True)
            print(f'  CN dq={r["dqCN"]:+.4f} dC={r["dcCN"]*100:+.2f}% pool={r["pool"]:+.4f}', flush=True)
    json.dump(R,open('RQ1_V1_8_2_R1_JOINT_RESULTS.json','w'),indent=1)
    print(f'\ntotal {time.time()-t0:.0f}s', flush=True)
