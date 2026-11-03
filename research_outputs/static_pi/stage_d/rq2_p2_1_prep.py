#!/usr/bin/env python3
"""P2-1 preregistration prep: power analysis + (Q,C,L,R) audit (zero-call).
Uses deterministic reruns of the frozen P2/P5 arms (PYTHONHASHSEED=0).
Outputs: P2_1_POWER_AUDIT.json with per-task arrays summary, power tables,
cost/latency/reliability itemization. No new mechanisms, no API.
"""
import os, json, math, numpy as np
from rq1_v1_8_2_r5_core import DEC, PRICE, LAT, BASE_LAT, RATES, prep_all, run_fast, mask_to_assign
from rq1_v1_8_2_r5_main import SCENARIOS, task_pool
import rq2_p2_07 as M   # deterministic module (requires PYTHONHASHSEED=0)

OUT = os.path.dirname(os.path.abspath(__file__))
N = 800
NODES = ['e0', 'e1', 't', 'm', 'r', 'v', 'p']
D = 0.3

def arm_arrays():
    """Return per-task Q arrays + cost/mk/reliability for each arm/world."""
    out = {}
    specs = {
        'Static': ([1]*7, {}, 'count', {}),
        'ShamP2': (M.PLANS['P2_DS_strict'][0], M.PLANS['P2_DS_strict'][1], 'sham', {}),
        'P2arm': (M.PLANS['P2_DS_strict'][0], M.PLANS['P2_DS_strict'][1], 'signal',
                  {'verify_nodes': (0, 1, 2, 3, 5, 6), 'c_ver': 0.05}),
        'P5arm': (M.PLANS['P5_base_m'][0], M.PLANS['P5_base_m'][1], 'signal',
                  {'verify_nodes': (0, 1, 2, 3, 5, 6), 'c_ver': 0.05}),
    }
    for name, (base, spec, rule, vk) in specs.items():
        qs, mk, flip, cost, vpc = M.joint_run(M.ST, M.ST_IDS, base, spec, rule, D, **vk)
        qh, mkh, costh, _, _ = M.joint_run(M.H0P, M.H0_IDS, base, spec, rule, D, **vk)[:1] + (None, None, None, None) if False else (None, None, None, None, None)
        qh, mkh, _, costh, _ = M.joint_run(M.H0P, M.H0_IDS, base, spec, rule, D, **vk)
        out[name] = {'q_stable': qs, 'q_H0': qh, 'mk': mk, 'mk_H0': mkh,
                     'cost': cost, 'cost_H0': costh, 'base': base, 'spec': spec,
                     'rule': rule, 'verify': bool(vk)}
    return out

ARMS = arm_arrays()
BASE_ST = float(np.mean([np.mean([o[n][f] == 0 and l[n][f] and s[n][f] and e[6] for (n, f) in DEC])
                         for o, l, s, e in (run_fast(M.ST[i], mask_to_assign(127)) for i in range(N))]))

def sd(x):
    return float(np.std(x, ddof=1))

power = {}
# E1 quality: n for CI-lower >= .70
for arm in ('P2arm', 'P5arm'):
    q = ARMS[arm]['q_stable']
    mu = float(q.mean()); s = sd(q)
    row = {'mean_Q': mu, 'sd': s}
    for target_gap in (0.005, 0.01, 0.015, 0.02, 0.025):
        n = (1.96 * s / target_gap) ** 2
        row[f'n_gap{target_gap*1000:.0f}bp'] = n
    row['n_at_own_mean_vs_70'] = (1.96 * s / (mu - 0.70)) ** 2 if mu > 0.70 else None
    power[arm] = row
# E2 attribution: dHet = dQ_stable - dQ_H0, independent worlds, equal n
for arm in ('P2arm', 'P5arm'):
    ds = ARMS[arm]['q_stable'] - ARMS['Static']['q_stable']
    dh = ARMS[arm]['q_H0'] - ARMS['Static']['q_H0']
    dHet = float(ds.mean() - dh.mean())
    se = math.sqrt(sd(ds)**2 + sd(dh)**2)
    row = {'dHet_pp': dHet * 100, 'sd_ds': sd(ds), 'sd_dh': sd(dh), 'se_n1': se}
    for margin in (0.0, 0.05):
        gap = dHet - margin
        row[f'n_CIlower>margin{margin}'] = (1.96 * se / gap) ** 2 if gap > 0 else None
    power[arm]['attribution'] = row
# E3 P2 vs P5 paired
d_paired = ARMS['P2arm']['q_stable'] - ARMS['P5arm']['q_stable']
power['P2_vs_P5_paired'] = {'mean_diff_pp': float(d_paired.mean()) * 100, 'sd_diff': sd(d_paired),
    'n_detect_1pp_80pct': ((1.96 + 0.8416) * sd(d_paired) / 0.01) ** 2}
# Holm inflation for 3 co-primaries
power['holm3_z'] = 2.394
power['holm3_n_inflation'] = (2.394 / 1.96) ** 2

# (Q,C,L,R) audit
qclr = {}
for name in ('Static', 'ShamP2', 'P2arm', 'P5arm'):
    a = ARMS[name]
    q = a['q_stable']
    # reliability of final outputs: recompute exec/gate rates quickly
    gate = []; parse_ok = []
    base = a['base']; spec = a['spec']
    for i in range(N):
        # replicate final state cheaply: rerun joint for one task is costly; use stored mk only
        pass
    qclr[name] = {'Q': float(q.mean()), 'C_mult': a['cost'] / 0.6,
                  'L_ratio': a['mk'], 'C_H0_mult': a['cost_H0'] / 0.6,
                  'verify': a['verify']}
# cost itemization (arithmetic from frozen configs)
def itemize(base, spec, c_ver=0.05, vpc=4.93):
    c_base = float(np.mean(PRICE[np.array(base)]))
    fam = {0: [0, 1, 2], 1: [3, 5, 6], 2: [4]}
    items = {'base': c_base}
    tot = c_base
    for f, nodes in fam.items():
        members = [ni for ni in nodes if ni in spec]
        if not members:
            continue
        csum = sum(PRICE[spec[ni]] / 7.0 for ni in members)
        c = csum * (0.7 if len(members) > 1 else 1.0)
        items[f'copies_family{f}'] = c
        tot += c
    items['verify'] = c_ver * vpc / 7.0
    tot += items['verify']
    items['total'] = tot
    items['mult'] = tot / 0.6
    return items
qclr['P2arm']['cost_items'] = itemize(ARMS['P2arm']['base'], ARMS['P2arm']['spec'])
qclr['P5arm']['cost_items'] = itemize(ARMS['P5arm']['base'], ARMS['P5arm']['spec'])

res = {'BASE_ST': BASE_ST, 'power': power, 'qclr': qclr,
       'n_tasks': N,
       'notes': ['per-task arrays from deterministic reruns (PYTHONHASHSEED=0)',
                 'dHet: independent stable/H0 worlds, equal n, se=sqrt(var_s/n+var_h/n)',
                 'Holm-3 first-test z=2.394 inflates n by 1.49x if co-primary',
                 'reliability R: gate/parse rates require joint-run instrumentation (V-2 audit script)']}
json.dump(res, open(os.path.join(OUT, 'P2_1_POWER_AUDIT.json'), 'w'), indent=1, default=float)
print('BASE_ST', BASE_ST)
print(json.dumps(power, indent=1, default=float))
print(json.dumps(qclr, indent=1, default=float))
