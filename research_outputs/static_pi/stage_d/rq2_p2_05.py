#!/usr/bin/env python3
"""P2-0.5: joint cost & detection feasibility (zero-call, existing data only).
1) observable-signal detectors vs synthetic verifier (sens/spec vs gold badness)
2) shared-evidence cost discount d swept; required d per budget tier
3) Q-vs-budget frontier with bootstrap CI (first-moment); min budget for Q>=70
4) latency: speculative vs serial rebuild arithmetic
No new mechanism probabilities; d is swept, not assumed. Zero real API.
"""
import os, json, numpy as np
from rq1_v1_8_2_r5_core import (FACT_PARENTS, DEC, RATES, PRICE, LAT, BASE_LAT,
    prep_all, run_fast, mask_to_assign)
from rq1_v1_8_2_r5_main import SCENARIOS, task_pool

OUT = os.path.dirname(os.path.abspath(__file__))
cfg = SCENARIOS[2]
N = 800
ts = task_pool(N, cfg['seed'] * 1000 + 501, cfg['sign_mode'])
P = prep_all(ts, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
NODES = ['e0', 'e1', 't', 'm', 'r', 'v', 'p']
DS = mask_to_assign(127)
C = {'DS': 0.086, 'GLM': 0.143}
NODE_MODEL = {'e0': 'DS', 'e1': 'DS', 't': 'DS', 'm': 'GLM', 'r': 'GLM', 'v': 'GLM', 'p': 'GLM'}
MIDX = {'DS': 1, 'GLM': 0}
GROUPS = [('ext_t', ['e0', 'e1', 't']), ('mv', ['m', 'v']), ('r', ['r']), ('p', ['p'])]

outL = []; locL = []; supL = []; eokL = []; qL = []
for p in P:
    o, l, s, e = run_fast(p, DS)
    outL.append(o); locL.append(l); supL.append(s); eokL.append(e)
    qn = {}
    for ni in range(7):
        vals = [o[pn][pf] == 0 for fi in (0, 1) for (pn, pf) in FACT_PARENTS[ni][fi]]
        qn[ni] = 1.0 if not vals else float(np.mean(vals))
    qL.append(qn)

def bad_fact(i, ni, fi):
    return not (outL[i][ni][fi] == 0 and locL[i][ni][fi] and supL[i][ni][fi])

def node_bad(i, ni):
    return any(bad_fact(i, ni, fi) for fi in (0, 1) if (ni, fi) in DEC)

def pp_model(p, ni, m, q):
    b = p['base'][m][ni]
    v = b * (0.35 + 0.65 * q)
    if ni == 5:
        v = v + 0.30 * (1 - q) * (1 - b)
    return max(0.02, min(0.98, v))

Rl = {0: RATES['loc'][0], 1: RATES['loc'][1]}
Rs = {0: RATES['sup'][0], 1: RATES['sup'][1]}
Re = {0: RATES['parse'][0] * RATES['contract'][0], 1: RATES['parse'][1] * RATES['contract'][1]}

EC = np.zeros((N, 7))
for i in range(N):
    for ni in range(7):
        m = MIDX[NODE_MODEL[NODES[ni]]]
        q = qL[i][ni]
        EC[i, ni] = sum(pp_model(P[i], ni, m, q) * Rl[m] * Rs[m] * Re[m]
                        for fi in (0, 1) if (ni, fi) in DEC and bad_fact(i, ni, fi))
BASE_Q = np.array([np.mean([outL[i][ni][fi] == 0 and locL[i][ni][fi] and supL[i][ni][fi]
                            and eokL[i][6] for (ni, fi) in DEC]) for i in range(N)])
base_q = float(BASE_Q.mean())

def detA(i, ni):
    if not eokL[i][ni]:
        return True
    for fi in (0, 1):
        if (ni, fi) not in DEC:
            continue
        o = outL[i][ni][fi]
        if o == 2:
            return True
        if o in (0, 1) and not (locL[i][ni][fi] and supL[i][ni][fi]):
            return True
    return False

def detB(i, ni):
    if not eokL[i][ni]:
        return True
    return any(outL[i][ni][fi] == 2 for fi in (0, 1) if (ni, fi) in DEC)

det = {}
for name, f in (('A', detA), ('B', detB)):
    tp = fp_ = fn = tn = 0
    for i in range(N):
        for ni in range(7):
            b = node_bad(i, ni); d = f(i, ni)
            tp += b and d; fn += b and (not d); fp_ += (not b) and d; tn += (not b) and (not d)
    det[name] = {'sens': tp / float(tp + fn), 'spec': tn / float(tn + fp_),
                 'undetected_bad_nodes': int(fn), 'total_bad_nodes': int(tp + fn)}
und = [(i, ni) for i in range(N) for ni in range(7) if node_bad(i, ni) and not detA(i, ni)]
pure_fp = sum(1 for (i, ni) in und
              if all(outL[i][ni][fi] == 1 and locL[i][ni][fi] and supL[i][ni][fi]
                     for fi in (0, 1) if (ni, fi) in DEC and bad_fact(i, ni, fi)))
det['A']['undetected_pure_FP'] = int(pure_fp)

def parent_prod(i, ni):
    vals = []
    for fi in (0, 1):
        for (pn, pf) in FACT_PARENTS[ni][fi]:
            vals.append(outL[i][pn][pf] != 2)
    return float(np.mean(vals)) if vals else 1.0

SPEC_NODES = [3, 4, 5, 6]
par_rows = []
for tau in (0.25, 0.5, 0.75, 0.999):
    tp = fn = fp_ = tn = 0
    for i in range(400, N):
        for ni in SPEC_NODES:
            b = node_bad(i, ni); d = parent_prod(i, ni) < tau
            tp += b and d; fn += b and (not d); fp_ += (not b) and d; tn += (not b) and (not d)
    par_rows.append({'tau': tau, 'sens': tp / float(tp + fn), 'spec': tn / float(tn + fp_),
                     'fire_rate': (tp + fp_) / float(tp + fp_ + fn + tn)})

def frontier(d):
    convs = np.zeros(N); cost = np.zeros(N)
    for gname, nodes in GROUPS:
        idx = [NODES.index(x) for x in nodes]
        gcost = sum(C[NODE_MODEL[NODES[ni]]] for ni in idx) * ((1 - d) if len(idx) > 1 else 1.0)
        gconv = EC[:, idx].sum(axis=1)
        trigger = np.array([any(node_bad(i, ni) for ni in idx) for i in range(N)])
        convs += gconv * trigger
        cost += gcost * trigger
    return convs, cost

def boot_ci(q_per_task, ns=3000, seed=1):
    rng = np.random.default_rng(seed)
    vals = np.array([rng.choice(q_per_task, 24, replace=False).mean() for _ in range(ns)])
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))

tiers = [0.06, 0.09, 0.12, 0.20, 0.30, 0.40, 0.50, 0.63]
front = {}
for d in (0.0, 0.2, 0.3, 0.4, 0.5):
    convs, cost = frontier(d)
    row = {}
    for add in tiers:
        frac = np.where(cost > 0, np.minimum(1.0, add / np.maximum(cost, 1e-12)), 1.0)
        qpt = BASE_Q + convs * frac / 13.0
        lo, hi = boot_ci(qpt)
        row[f'{add:.2f}'] = {'Q': float(qpt.mean()), 'ci': [lo, hi],
                             'mean_cost_add': float(np.mean(cost * frac)),
                             'full_tasks_share': float(np.mean(cost <= add + 1e-9))}
    front[f'd={d}'] = row

min_tier = {}
for d in (0.0, 0.2, 0.3, 0.4, 0.5):
    convs, cost = frontier(d)
    mean_cost = float(np.mean(cost))
    conv_full = float(np.mean(convs))
    min_tier[f'd={d}'] = {'expected_conv_full': conv_full,
                          'Q_full': base_q + conv_full / 13.0,
                          'mean_cost_add_full': mean_cost,
                          'budget_multiple_full': 1 + mean_cost / 0.6}

lat = {ni: BASE_LAT[ni] * LAT[DS[ni]] for ni in range(7)}
F = {0: lat[0], 1: lat[1], 2: lat[0] + lat[2]}
F[3] = max(lat[0], lat[1]) + lat[3]
F[4] = F[3] + lat[4]
F[5] = max(F[3], F[2]) + lat[5]
MK = max(F[4], F[5]) + lat[6]
latrows = {}
for ni in range(7):
    m = MIDX[NODE_MODEL[NODES[ni]]]
    ln = BASE_LAT[ni] * LAT[m]
    spec = MK + max(0.0, ln - lat[ni])
    serial = MK + ln
    latrows[NODES[ni]] = {'model': NODE_MODEL[NODES[ni]], 'lat_add': ln,
                          'speculative_pct': spec / MK - 1, 'serial_pct': serial / MK - 1,
                          'spec_strict10': spec / MK - 1 <= 0.10 + 1e-9,
                          'spec_matched20': spec / MK - 1 <= 0.20 + 1e-9}

res = {'base_Q': base_q, 'detectors': det, 'parent_detector': par_rows,
       'frontier': front, 'min_tier': min_tier, 'latency': latrows,
       'notes': ['observable detector assumes missing/invalid evidence linkage is detectable',
                 'hidden failure class = confident FP with evidence (out==1, loc, sup)',
                 'd swept not assumed; frontier is first-moment expectation with bootstrap CI over tasks',
                 'frac scaling = proportional inclusion approximation at tier']}
def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    return o

json.dump(_clean(res), open(os.path.join(OUT, 'P2_05_ANALYSIS.json'), 'w'), indent=1)

print(f'base Q={base_q:.4f}')
print('detectors:', json.dumps(det, indent=1))
print('parent detector (eval half):')
for r in par_rows:
    print(f"  tau={r['tau']}: sens={r['sens']:.3f} spec={r['spec']:.3f} fire={r['fire_rate']:.3f}")
print('\nfrontier (Q by tier add):')
for d in (0.0, 0.2, 0.3, 0.4, 0.5):
    row = front[f'd={d}']
    print(f"  d={d}: " + ' '.join(f"{k}:{v['Q']*100:.1f}%" for k, v in row.items()))
print('\nfull-program requirements:')
for k, v in min_tier.items():
    print(f"  {k}: conv={v['expected_conv_full']:.2f} Q={v['Q_full']*100:.1f}% "
          f"cost_add={v['mean_cost_add_full']:.3f} mult={v['budget_multiple_full']:.2f}x")
print('\nlatency:')
for k, v in latrows.items():
    print(f"  {k}({v['model']}): spec +{v['speculative_pct']*100:.1f}% serial +{v['serial_pct']*100:.1f}% "
          f"strict10={v['spec_strict10']} matched20={v['spec_matched20']}")
