#!/usr/bin/env python3
"""PD vs FC 16组配对差值功效分析（零模型调用，纯离线）。
数据源: research_outputs/static_pi/stage_d/runs_final/ 192次真实执行中的
S3/S4 16组 Proposed-Dynamic vs Fixed-Composite 配对（与论文复算表逐组核验一致）。
检验: 与存档分析同型的 平均秩+正秩和 符号翻转检验（单侧 alpha=0.05，零差剔除）。
功效模拟: 符号库蒙特卡洛 (B=4096)，数据集与符号库独立，每配置 nsim=3000。
"""
import json, random, statistics as st
from pathlib import Path
import numpy as np

RD = Path('/root/research_outputs/static_pi/stage_d/runs_final')
OUT = Path('/root/research_outputs/PD_FC_POWER_ANALYSIS_20261107')
ALPHA = 0.05
NSIM, B = 3000, 4096
SEED = 20261107

def run(arm, s, r):
    d = json.load(open(RD / f'{arm}__{s}__r{r}.json'))
    return dict(tp=d['score']['tp'], makespan_s=d['makespan_s'],
                accounting_yuan=d['accounting_yuan'], cash_yuan=d['actual_cash_yuan'],
                tokens_in=d['tokens_in'], tokens_out=d['tokens_out'],
                calls=d['calls'], status=d['status'], on_time=d['on_time'])

pairs = []
for s in ('S3', 'S4'):
    for r in range(1, 9):
        a, b = run('Proposed-Dynamic', s, r), run('Fixed-Composite', s, r)
        pairs.append(dict(scenario=s, rep=r, pd=a, fc=b, d_tp=a['tp'] - b['tp']))

s5 = [dict(scenario='S5', rep=r,
           pd_tp=run('Proposed-Dynamic','S5',r)['tp'], fc_tp=run('Fixed-Composite','S5',r)['tp'])
      for r in range(1, 9)]
for p in s5: p['d_tp'] = p['pd_tp'] - p['fc_tp']

deltas = [p['d_tp'] for p in pairs]
s3 = [p['d_tp'] for p in pairs if p['scenario'] == 'S3']
s4 = [p['d_tp'] for p in pairs if p['scenario'] == 'S4']

def q(x, p): return float(np.percentile(np.array(x), p))
desc = dict(
    n=16, mean=float(np.mean(deltas)), sd=float(np.std(deltas, ddof=1)),
    median=float(np.median(deltas)), q1=q(deltas,25), q3=q(deltas,75),
    zeros=int(sum(d==0 for d in deltas)), wins=int(sum(d>0 for d in deltas)),
    losses=int(sum(d<0 for d in deltas)),
    S3=dict(mean=float(np.mean(s3)), sd=float(np.std(s3,ddof=1)),
            wins=int(sum(d>0 for d in s3)), zeros=int(sum(d==0 for d in s3)),
            losses=int(sum(d<0 for d in s3))),
    S4=dict(mean=float(np.mean(s4)), sd=float(np.std(s4,ddof=1)),
            wins=int(sum(d>0 for d in s4)), zeros=int(sum(d==0 for d in s4)),
            losses=int(sum(d<0 for d in s4))),
    S5_excluded=dict(mean=float(np.mean([p['d_tp'] for p in s5])),
                     wins=int(sum(p['d_tp']>0 for p in s5)),
                     zeros=int(sum(p['d_tp']==0 for p in s5)),
                     losses=int(sum(p['d_tp']<0 for p in s5))),
)

# ---- 检验复现 ----
def avg_ranks(nz):
    abss = sorted(abs(d) for d in nz); out=[]
    for d in nz:
        v=abs(d); lo=sum(1 for x in abss if x<v); eq=sum(1 for x in abss if x==v)
        out.append(lo+(eq+1)/2)
    return out

def rank_signflip_p(diffs):
    nz=[d for d in diffs if d!=0]; m=len(nz)
    ranks=avg_ranks(nz); W=sum(r for r,d in zip(ranks,nz) if d>0)
    S=np.array(list(np.ndindex(*(2,)*m)),dtype=np.int8)*2-1  # 2^m x m
    Wd=(S>0)@np.array(ranks)
    return float(np.count_nonzero(Wd>=W-1e-12)/len(Wd)), W, m

def diffsum_signflip_p(diffs):
    nz=np.array([d for d in diffs if d!=0]); m=len(nz)
    S=np.array(list(np.ndindex(*(2,)*m)),dtype=np.int8)*2-1
    sums=S@nz
    return float(np.count_nonzero(sums>=sum(nz)-1e-9)/len(sums))

nz=[d for d in deltas if d!=0]
p_rank,W,m = rank_signflip_p(deltas)
p_sum = diffsum_signflip_p(deltas)
import math as _m
p_sign = sum(_m.comb(8,k) for k in range(6,9))/256
tests=dict(rank_signflip_p=p_rank, W_obs=W, m=m,
           diffsum_signflip_p=p_sum, sign_only_p=p_sign)

# ---- Q/C/L ----
def pct(a,b): return (a-b)/b*100 if b else None
qcl=dict(
    cost_accounting_delta_pct=float(np.mean([pct(p['pd']['accounting_yuan'],p['fc']['accounting_yuan']) for p in pairs])),
    cost_cash_delta_pct=float(np.mean([pct(p['pd']['cash_yuan'],p['fc']['cash_yuan']) for p in pairs])),
    makespan_delta_pct=float(np.mean([pct(p['pd']['makespan_s'],p['fc']['makespan_s']) for p in pairs])),
    makespan_pd_mean=float(np.mean([p['pd']['makespan_s'] for p in pairs])),
    makespan_fc_mean=float(np.mean([p['fc']['makespan_s'] for p in pairs])),
    cost_pd_mean=float(np.mean([p['pd']['accounting_yuan'] for p in pairs])),
    cost_fc_mean=float(np.mean([p['fc']['accounting_yuan'] for p in pairs])),
    cost_cash_pd_mean=float(np.mean([p['pd']['cash_yuan'] for p in pairs])),
    cost_cash_fc_mean=float(np.mean([p['fc']['cash_yuan'] for p in pairs])),
    makespan_pd_wins=int(sum(p['pd']['makespan_s']<p['fc']['makespan_s'] for p in pairs)),
    cost_accounting_ratio_of_means_pct=float((np.mean([p['pd']['accounting_yuan'] for p in pairs])/np.mean([p['fc']['accounting_yuan'] for p in pairs])-1)*100),
    cost_cash_ratio_of_means_pct=float((np.mean([p['pd']['cash_yuan'] for p in pairs])/np.mean([p['fc']['cash_yuan'] for p in pairs])-1)*100),
)

# ---- 功效模拟 ----
_bank={}
def bank(mm):
    if mm not in _bank:
        rng=np.random.default_rng(SEED+mm)
        _bank[mm]=(rng.integers(0,2,size=(B,mm))*2-1)>0
    return _bank[mm]

def test_mc(diffs):
    nz=[d for d in diffs if d!=0]; m=len(nz)
    if m==0: return False
    ranks=np.array(avg_ranks(nz)); W=sum(r for r,d in zip(ranks,nz) if d>0)
    Wn=bank(m)@ranks
    return (1+np.count_nonzero(Wn>=W-1e-12))/(B+1) < ALPHA

def power(gen, n, nsim=NSIM, seed=SEED):
    rng=random.Random(seed); sig=0
    for _ in range(nsim):
        if test_mc(gen(rng,n)): sig+=1
    return sig/nsim

def gen_strat(rng,n):  # 场景平衡：一半S3型差值、一半S4型差值（经验自助）
    h=(n+1)//2
    return [rng.choice(s3) for _ in range(h)]+[rng.choice(s4) for _ in range(n-h)]
def gen_pool(rng,n):   # 16池无分层自助
    return [rng.choice(deltas) for _ in range(n)]
def gen_zerofrac(pz):
    nzm=[d for d in deltas if d!=0]
    return lambda rng,n: [0 if rng.random()<pz else rng.choice(nzm) for _ in range(n)]
def gen_gauss(mu,sd,pz):
    return lambda rng,n: [0 if rng.random()<pz else int(round(rng.gauss(mu,sd))) for _ in range(n)]

nzm=[d for d in deltas if d!=0]
mu_nz, sd_nz = float(np.mean(nzm)), float(np.std(nzm,ddof=1))

Ns=[16,24,32,40,48,56,64,80,96]
curves={}
curves['fresh_stratified']={n:power(gen_strat,n) for n in Ns}
curves['fresh_pooled_bootstrap']={n:power(gen_pool,n) for n in Ns}
curves['fresh_gauss_calibrated']={n:power(gen_gauss(mu_nz,sd_nz,0.5),n) for n in Ns}
curves['zerofrac_sensitivity_N32']={pz:power(gen_zerofrac(pz),32) for pz in (0.3,0.4,0.5,0.6,0.7)}
curves['S3_only']={n:power(lambda r,k:[r.choice(s3) for _ in range(k)],n,nsim=2000) for n in (8,16,24,32,48)}
curves['S4_only']={n:power(lambda r,k:[r.choice(s4) for _ in range(k)],n,nsim=2000) for n in (8,16,24,32,48)}

# 增量设计：现有16 + k 新（合并分析，非确认性，仅参考）
def gen_incr(rng,k):
    return deltas + gen_strat(rng,k)
curves['incremental_pool_with_existing16']={k:power(gen_incr,k,nsim=2000) for k in (8,16,24,32,48,64)}

def n_for(curve,target):
    ns=sorted(curve)
    for n in ns:
        if curve[n]>=target: return n
    return None

plan=dict(
    stratified_N80=n_for(curves['fresh_stratified'],0.80),
    stratified_N90=n_for(curves['fresh_stratified'],0.90),
    pooled_N80=n_for(curves['fresh_pooled_bootstrap'],0.80),
    pooled_N90=n_for(curves['fresh_pooled_bootstrap'],0.90),
    gauss_N80=n_for(curves['fresh_gauss_calibrated'],0.80),
    gauss_N90=n_for(curves['fresh_gauss_calibrated'],0.90),
    incr_N80=n_for(curves['incremental_pool_with_existing16'],0.80),
    incr_N90=n_for(curves['incremental_pool_with_existing16'],0.90),
)

res=dict(generated_utc='2026-11-07', nsim=NSIM, B=B, seed=SEED, alpha=ALPHA,
         data_source='static_pi/stage_d/runs_final (192 real executions), S3/S4 PD-vs-FC 16 pairs, TP cross-checked vs PAPER_COMPLEX_TASK_MULTIAGENT_CH5 RECALCULATED_RESULTS.json',
         pairs=[dict(scenario=p['scenario'],rep=p['rep'],
                     pd_tp=p['pd']['tp'],fc_tp=p['fc']['tp'],d_tp=p['d_tp'],
                     pd_makespan_s=p['pd']['makespan_s'],fc_makespan_s=p['fc']['makespan_s'],
                     pd_accounting_yuan=p['pd']['accounting_yuan'],fc_accounting_yuan=p['fc']['accounting_yuan'],
                     pd_cash_yuan=p['pd']['cash_yuan'],fc_cash_yuan=p['fc']['cash_yuan'],
                     pd_status=p['pd']['status'],fc_status=p['fc']['status']) for p in pairs],
         s5_appendix=s5, descriptive=desc, tests_reproduced=tests, qcl=qcl,
         power_curves=curves, sample_size_plan=plan)
json.dump(res, open(OUT/'POWER_RESULTS.json','w'), indent=1, ensure_ascii=False)

import csv
with open(OUT/'PAIRS_TABLE.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['scenario','rep','pd_tp','fc_tp','d_tp','pd_makespan_s','fc_makespan_s','pd_accounting_yuan','fc_accounting_yuan','pd_cash_yuan','fc_cash_yuan','pd_status','fc_status'])
    for p in res['pairs']:
        w.writerow([p[k] for k in ['scenario','rep','pd_tp','fc_tp','d_tp','pd_makespan_s','fc_makespan_s','pd_accounting_yuan','fc_accounting_yuan','pd_cash_yuan','fc_cash_yuan','pd_status','fc_status']])

print('TESTS', json.dumps(tests))
print('DESC', json.dumps(desc))
print('QCL', json.dumps({k:round(v,3) for k,v in qcl.items()}))
for name,c in curves.items(): print(name, {k:round(v,3) for k,v in c.items()})
print('PLAN', json.dumps(plan))
