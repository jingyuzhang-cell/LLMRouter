#!/usr/bin/env python3
"""P2-0.7: information-driven heterogeneous re-execution & DAG resource joint
optimization (zero-call offline validation).

1) selection strategies: sham (pure random) / count / signal (runtime-only) /
   capability (train-measured copy-model choice; no test gold); oracle separate.
2) joint plans pi = (base assignment, speculative set); per-task cost from the
   copy models actually used (unconditional), family prep discount d=0.3;
   exact whole-graph makespan.
3) priced semantic verification: pay c_ver per clean-looking fact to reveal
   support before selection; measured on headline plan by node group.
4) attribution: H0 twins; Delta_hetero = dQ_stable - dQ_H0 (5pp gate unchanged).

Zero real API; copies are fresh re-rolls of the frozen mechanism; no new
mechanism probabilities.
"""
import os, json, numpy as np
from rq1_v1_8_2_r5_core import (FACT_PARENTS, DEC, RATES, PRICE, LAT, BASE_LAT,
    FP_RATE, prep_all, run_fast, mask_to_assign)
from rq1_v1_8_2_r5_main import SCENARIOS, task_pool

OUT = os.path.dirname(os.path.abspath(__file__))
N = 800
NODES = ['e0', 'e1', 't', 'm', 'r', 'v', 'p']
TOPO = list(range(7))
Rl = {0: RATES['loc'][0], 1: RATES['loc'][1]}
Rs = {0: RATES['sup'][0], 1: RATES['sup'][1]}
Rp = {0: RATES['parse'][0], 1: RATES['parse'][1]}
Rc = {0: RATES['contract'][0], 1: RATES['contract'][1]}
Runk = {0: RATES['unk'][0], 1: RATES['unk'][1]}
FAMILY = [(0, 1, 2), (3, 5, 6), (4,)]

def load(cfg):
    ts = task_pool(N, cfg['seed'] * 1000 + 501, cfg['sign_mode'])
    P = prep_all(ts, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    return P, [t['id'] for t in ts]

ST, ST_IDS = load(SCENARIOS[2])
H0P, H0_IDS = load(SCENARIOS[0])

def copy_rng(tid, ni):
    return np.random.default_rng(abs(hash((tid, ni, 'copy', 20261107))) % (2**32))

def q_fact(state, ni, fi):
    cons = FACT_PARENTS[ni][fi]
    if not cons:
        return 1.0
    return sum(1 for pn, pf in cons if state['out'][pn][pf] == 0) / float(len(cons))

def exec_node(P, i, ni, model, state, fresh=None):
    if fresh is None:
        up = P[i]['parse'][ni] <= P[i]['Rparse'][model] - P[i]['extra']
        uc = P[i]['contract'][ni] <= P[i]['Rcontract'][model]
        uf = P[i]['fact'][ni]
    else:
        up = fresh.random() <= P[i]['Rparse'][model]
        uc = fresh.random() <= P[i]['Rcontract'][model]
        uf = fresh.random((2, 5))
    if not (up and uc):
        return [2, 2], [False, False], [False, False], False
    b = P[i]['base'][model][ni]
    out = [2, 2]; loc = [False, False]; sup = [False, False]
    for fi in (0, 1):
        if ni == 6 and fi == 1:
            out[1] = 3 if uf[1][2] <= P[i]['Runk'][model] else 1
            continue
        qq = max(0.0, min(1.0, q_fact(state, ni, fi)))
        pp = b * (0.35 + 0.65 * qq)
        if ni == 5:
            pp = pp + 0.30 * (1 - qq) * (1 - b)
        pp = max(0.02, min(0.98, pp))
        u0, u1, _, u3, u4 = uf[fi]
        out[fi] = 0 if u0 <= pp else (1 if u1 < FP_RATE else 2)
        if out[fi] in (0, 1):
            loc[fi] = u3 <= P[i]['Rloc'][model]
            sup[fi] = u4 <= P[i]['Rsup'][model]
    return out, loc, sup, True

def n_clean(ni, out, loc):
    return sum(1 for fi in (0, 1) if (ni, fi) in DEC and out[fi] != 2 and loc[fi])

def n_produced(ni, out):
    return sum(1 for fi in (0, 1) if (ni, fi) in DEC and out[fi] != 2)

def n_true(ni, out, loc, sup):
    return sum(1 for fi in (0, 1) if (ni, fi) in DEC and out[fi] == 0 and loc[fi] and sup[fi])

def q_of(state, ni):
    vals = [state['out'][pn][pf] == 0 for fi in (0, 1) for (pn, pf) in FACT_PARENTS[ni][fi]]
    return 1.0 if not vals else float(np.mean(vals))

def capability_profile(P, n_train=400):
    prof = {}
    for ni in range(7):
        fis = [fi for fi in (0, 1) if (ni, fi) in DEC]
        acc = {}
        for m, mask in ((1, 127), (0, 0)):
            a = mask_to_assign(mask)
            c = t = 0
            for i in range(n_train):
                o, l, s, e = run_fast(P[i], a)
                for fi in fis:
                    t += 1
                    c += int(o[ni][fi] == 0 and l[ni][fi] and s[ni][fi])
            acc[m] = c / float(t)
        prof[ni] = {'DS': acc[1], 'GLM': acc[0], 'best': int(np.argmax([acc[0], acc[1]]))}
    return prof

CAP = capability_profile(ST)

def joint_run(P, ids, base, spec, rule, d=0.3, verify_nodes=(), c_ver=0.0):
    Qs = []; costs = []; flips = 0; ver_calls = 0; ver_task = 0
    for i in range(len(P)):
        state = {'out': [[2, 2] for _ in range(7)], 'loc': [[False, False] for _ in range(7)],
                 'sup': [[False, False] for _ in range(7)], 'eok': [False] * 7}
        lat = {}
        cost = float(np.mean(PRICE[np.array(base)]))
        chosen_models = {}
        for ni in TOPO:
            out, loc, sup, eok = exec_node(P, i, ni, base[ni], state)
            l_node = BASE_LAT[ni] * LAT[base[ni]]
            if ni in spec:
                rng = copy_rng(ids[i], ni)
                if rule == 'capability':
                    cm = CAP[ni]['best']
                elif rule == 'capability_c':
                    cm = 1 if ni == 4 else CAP[ni]['best']
                else:
                    cm = spec[ni]
                chosen_models[ni] = cm
                out2, loc2, sup2, eok2 = exec_node(P, i, ni, cm, state, fresh=rng)
                l_node = max(l_node, BASE_LAT[ni] * LAT[cm])
                verified = ni in verify_nodes
                if verified:
                    for fi in (0, 1):
                        if (ni, fi) in DEC and out[fi] != 2 and loc[fi] and out2[fi] != 2 and loc2[fi]:
                            ver_calls += 1; ver_task += 1
                if rule in ('capability', 'capability_c'):
                    a1 = n_clean(ni, out, loc); a2 = n_clean(ni, out2, loc2)
                    take2 = a2 > a1
                elif rule == 'sham':
                    take2 = rng.random() < 0.5
                elif rule == 'count':
                    a1 = n_clean(ni, out, loc); a2 = n_clean(ni, out2, loc2)
                    if verified:
                        a1 += sum(1 for fi in (0, 1) if (ni, fi) in DEC and out[fi] != 2
                                  and loc[fi] and sup[fi])
                        a2 += sum(1 for fi in (0, 1) if (ni, fi) in DEC and out2[fi] != 2
                                  and loc2[fi] and sup2[fi])
                    take2 = a2 > a1
                elif rule == 'signal':
                    s1 = 2 * n_clean(ni, out, loc) + n_produced(ni, out) + int(eok)
                    s2 = 2 * n_clean(ni, out2, loc2) + n_produced(ni, out2) + int(eok2)
                    if verified:
                        s1 += 2 * sum(1 for fi in (0, 1) if (ni, fi) in DEC and out[fi] != 2
                                      and loc[fi] and sup[fi])
                        s2 += 2 * sum(1 for fi in (0, 1) if (ni, fi) in DEC and out2[fi] != 2
                                      and loc2[fi] and sup2[fi])
                    take2 = s2 > s1
                elif rule == 'oracle':
                    take2 = n_true(ni, out2, loc2, sup2) > n_true(ni, out, loc, sup)
                else:
                    raise ValueError(rule)
                if take2:
                    out, loc, sup, eok = out2, loc2, sup2, eok2
                    flips += 1
            state['out'][ni] = out; state['loc'][ni] = loc
            state['sup'][ni] = sup; state['eok'][ni] = eok
            lat[ni] = l_node
        for fam in FAMILY:
            members = [ni for ni in fam if ni in chosen_models]
            if not members:
                continue
            csum = sum(PRICE[chosen_models[ni]] / 7.0 for ni in members)
            cost += csum * ((1 - d) if len(members) > 1 else 1.0)
        costs.append(cost + c_ver * ver_task / 7.0)
        ver_task = 0
        F = {0: lat[0], 1: lat[1], 2: lat[0] + lat[2]}
        F[3] = max(lat[0], lat[1]) + lat[3]
        F[4] = F[3] + lat[4]
        F[5] = max(F[3], F[2]) + lat[5]
        mk = max(F[4], F[5]) + lat[6]
        gate = state['eok'][6]
        Qs.append(np.mean([state['out'][n][f] == 0 and state['loc'][n][f] and state['sup'][n][f] and gate
                           for (n, f) in DEC]))
    q = np.array(Qs)
    cost_mean = float(np.mean(costs))
    return q, mk / 2.85, flips / float(len(P)), cost_mean, ver_calls / float(len(P))

def base_q(P, base):
    vals = []
    for i in range(len(P)):
        o, l, s, e = run_fast(P[i], np.array(base))
        vals.append(np.mean([o[n][f] == 0 and l[n][f] and s[n][f] and e[6] for (n, f) in DEC]))
    return float(np.mean(vals))

def boot(q, ns=2000, nt=24, seed=11):
    rng = np.random.default_rng(seed)
    vals = np.array([rng.choice(q, nt, replace=False).mean() for _ in range(ns)])
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))

DS7 = [1] * 7
PLANS = {
    'P1_DS_full_vDS': (DS7, {0: 1, 1: 1, 2: 1, 3: 0, 4: 1, 5: 1, 6: 0}),
    'P2_DS_strict':   (DS7, {0: 1, 1: 1, 2: 1, 3: 0, 4: 1, 5: 1, 6: 1}),
    'P3_DS_mpGLM':    (DS7, {0: 1, 1: 1, 2: 1, 3: 0, 4: 1, 6: 0}),
    'P4_base_mp':     ([1, 1, 1, 0, 1, 1, 0], {0: 1, 1: 1, 2: 1, 4: 1, 5: 1}),
    'P5_base_m':      ([1, 1, 1, 0, 1, 1, 1], {0: 1, 1: 1, 2: 1, 4: 1, 5: 1, 6: 1}),
    'P6_core_mvp':    (DS7, {3: 0, 5: 0, 6: 0}),
    'P7_base_mvp':    ([1, 1, 1, 0, 1, 0, 0], {0: 1, 1: 1, 2: 1, 4: 1}),
}

d = 0.3
BASE_ST = base_q(ST, DS7)
BASE_H0 = base_q(H0P, DS7)
results = {'capability_profile': {NODES[k]: v for k, v in CAP.items()},
           'base_Q_stable': BASE_ST, 'base_Q_H0': BASE_H0, 'd': d, 'plans': {}}
for pname, (base, spec) in PLANS.items():
    row = {'spec': {NODES[k]: ('GLM' if v == 0 else 'DS') for k, v in spec.items()},
           'base': ['GLM' if x == 0 else 'DS' for x in base], 'rules': {}}
    for rule in ('sham', 'count', 'signal', 'capability', 'capability_c'):
        q, mk, flip, cost, _ = joint_run(ST, ST_IDS, base, spec, rule, d)
        lo, hi = boot(q)
        row['rules'][rule] = {'Q': float(q.mean()), 'ci24': [lo, hi], 'mk': mk,
                              'cost_mult': cost / 0.6, 'flip_rate': flip}
    qo, mko, _, costo, _ = joint_run(ST, ST_IDS, base, spec, 'oracle', d)
    row['rules']['oracle_nondeployable'] = {'Q': float(qo.mean()), 'mk': mko, 'cost_mult': costo / 0.6}
    qh, mkh, _, costh, _ = joint_run(H0P, H0_IDS, base, spec, 'count', d)
    qhc, mkhc, _, costhc, _ = joint_run(H0P, H0_IDS, base, spec, 'capability_c', d)
    row['H0'] = {'Q_count': float(qh.mean()), 'cost_mult': costh / 0.6,
                 'dQ_stable': float(q.mean() - BASE_ST), 'dQ_H0': float(qh.mean() - BASE_H0),
                 'delta_hetero_pp': float((q.mean() - BASE_ST) - (qh.mean() - BASE_H0)) * 100}
    row['H0_capability_c'] = {'Q': float(qhc.mean()), 'cost_mult': costhc / 0.6,
                              'delta_hetero_pp': float((row['rules']['capability_c']['Q'] - BASE_ST) -
                                                       (qhc.mean() - BASE_H0)) * 100}
    results['plans'][pname] = row
    print(f"{pname}: " + ' '.join(f"{r}={v['Q']*100:.2f}%(x{v.get('cost_mult',0):.2f},mk{v.get('mk',0):.3f})"
          for r, v in row['rules'].items()) +
          f" | dHet={row['H0']['delta_hetero_pp']:.2f}pp", flush=True)

base, spec = PLANS['P1_DS_full_vDS']
ver = {}
for vn in (('m', 'v', 'p'), ('e0', 'e1', 't'), ('r',), ('e0', 'e1', 't', 'm', 'v', 'p')):
    vset = tuple(NODES.index(x) for x in vn)
    for c_ver in (0.02, 0.05, 0.10):
        for rule in ('signal', 'capability_c'):
            q, mk, flip, cost, vpc = joint_run(ST, ST_IDS, base, spec, rule, d,
                                               verify_nodes=vset, c_ver=c_ver)
            ver[f"{'+'.join(vn)}|c={c_ver}|{rule}"] = {'Q': float(q.mean()), 'mk': mk,
                                                        'cost_mult': cost / 0.6,
                                                        'verify_calls_per_task': vpc}
# attribution for signal rule and signal+verify-full
for tag, kwargs in (('signal', {}),
                    ('signal_verfull_c02', {'verify_nodes': (0,1,2,3,5,6), 'c_ver': 0.02}),
                    ('signal_verfull_c10', {'verify_nodes': (0,1,2,3,5,6), 'c_ver': 0.10})):
    qs, mks, _, cs, _ = joint_run(ST, ST_IDS, base, spec, 'signal', d, **kwargs)
    qh, mkh, _, ch, _ = joint_run(H0P, H0_IDS, base, spec, 'signal', d, **kwargs)
    ver[f'ATTR|{tag}'] = {'Q_stable': float(qs.mean()), 'Q_H0': float(qh.mean()),
                          'dQ_stable': float(qs.mean()-BASE_ST), 'dQ_H0': float(qh.mean()-BASE_H0),
                          'delta_hetero_pp': float((qs.mean()-BASE_ST)-(qh.mean()-BASE_H0))*100,
                          'cost_mult': cs/0.6, 'mk': mks}
json.dump({'results': results, 'verify': ver},
          open(os.path.join(OUT, 'P2_07_ANALYSIS.json'), 'w'), indent=1, default=float)
print('\nverify variants:')
for k, v in ver.items():
    if k.startswith('ATTR'):
        print(f"  {k}: stable={v['Q_stable']*100:.2f}% H0={v['Q_H0']*100:.2f}% dHet={v['delta_hetero_pp']:.2f}pp x{v['cost_mult']:.2f} mk={v['mk']:.3f}")
    else:
        print(f"  {k}: Q={v['Q']*100:.2f}% x{v['cost_mult']:.2f} vercalls/task={v['verify_calls_per_task']:.2f}")
