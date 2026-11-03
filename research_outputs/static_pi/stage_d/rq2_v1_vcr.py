#!/usr/bin/env python3
"""RQ2 Phase 2: V-CR (verification + local repair) with pre-registered verifier
sensitivity analysis on TRAIN tasks, then test on independent splits.

Mechanism (new, synthetic; scoring/DAG/reliability frozen):
  - base execution: a fixed feasible assignment (all-DS, m, or m+v)
  - verifier flags a fact if it is bad (not TP/loc/sup) with probability sens,
    and flags a good fact with probability 1 - spec (false positive)
  - a flagged fact is repaired once: success prob p_rep converts it to
    TP & loc & sup; cost c_rep (node-price units) and latency l_rep (node-latency
    units) are charged per attempt, including false positives
  - report gate failure is verified/repaired first (sens_gate, p_rep)
  - greedy priority: gate, critical facts, other DEC facts; max_rep attempts;
    attempt only if cost <= cap and makespan <= deadline.
All draws are task-level CRN; V-CR is compared with its own base on the same tasks.
"""
import os, sys, json, math, time, itertools, numpy as np
import multiprocessing as mp
from rq1_v1_8_2_r5_core import (
    FACT_PARENTS, CRIT, UNK_FACT, DEC, PRICE, LAT, BASE_LAT, MVS,
    prep_all, run_fast, score_full, assignment_cost, makespan, mask_to_assign,
)
from rq1_v1_8_2_r5_main import SCENARIOS, task_pool, summarize, summarize_row, r4_models, static_mask
from rq1_v1_8_2_r4_p0_calibration import exact_p

OUT = os.path.dirname(os.path.abspath(__file__))
BASE = dict(sens=0.80, spec=0.90, p_rep=0.75, c_rep=0.02, l_rep=0.02,
            max_rep=3, sens_gate=0.90)
CONSERVATIVE = dict(sens=0.70, spec=0.85, p_rep=0.50, c_rep=0.10, l_rep=0.10,
                    max_rep=2, sens_gate=0.85)
REPS = 100
N_POOL = 48
N_TRAIN = 24
N_TEST = 24
BASE_MASK = {'DS': 127, 'm': 119, 'mv': 87}
CRIT_LIST = [(5, 0), (5, 1), (6, 0)]
OTHER_DEC = [x for x in DEC if x not in CRIT_LIST]


def makespan_extra(assign, extra):
    a = np.asarray(assign, dtype=int)
    lat = [BASE_LAT[i] * LAT[a[i]] + float(extra[i]) for i in range(7)]
    L2 = lat[0] + lat[2]
    L3 = max(lat[0], lat[1]) + lat[3]
    L4 = L3 + lat[4]
    L5 = max(L3, L2) + lat[5]
    return max(L4, L5) + lat[6]


def task_pool_vcr(n, seed, sign_mode):
    ts = task_pool(n, seed, sign_mode)
    rng = np.random.default_rng(seed + 70211)
    for t in ts:
        t['vcr'] = {
            'flag': rng.random((7, 2)),
            'rep': rng.random((7, 2)),
            'gate_flag': rng.random(),
            'gate_rep': rng.random(),
        }
    return ts


def repair_run(P, assign, static_caps, cap, deadline, params, draws, return_states=False):
    out, loc, sup, eok = run_fast(P, assign)
    cost = assignment_cost(assign)
    extra = np.zeros(7)
    attempts = 0
    gate_repaired = 0
    # gate first: a failed report gate zeroes all terminal slots
    if not eok[6] and attempts < params['max_rep']:
        if draws['gate_flag'] < params['sens_gate']:
            nc = cost + params['c_rep'] / 7.0
            ne = extra.copy(); ne[6] += params['l_rep']
            nm = makespan_extra(assign, ne)
            if (nc <= static_caps['cost'] * (1 + cap) + 1e-12 and
                    nm <= static_caps['mk'] * deadline + 1e-12):
                attempts += 1; cost = nc; extra = ne
                if draws['gate_rep'] < params['p_rep']:
                    eok[6] = True; gate_repaired = 1
    for (ni, fi) in CRIT_LIST + OTHER_DEC:
        if attempts >= params['max_rep']:
            break
        bad = not (out[ni][fi] == 0 and loc[ni][fi] and sup[ni][fi])
        if bad:
            flagged = draws['flag'][ni, fi] < params['sens']
        else:
            flagged = draws['flag'][ni, fi] > params['spec']  # 1 - spec
        if not flagged:
            continue
        nc = cost + params['c_rep'] / 7.0
        ne = extra.copy(); ne[ni] += params['l_rep']
        nm = makespan_extra(assign, ne)
        if (nc > static_caps['cost'] * (1 + cap) + 1e-12 or
                nm > static_caps['mk'] * deadline + 1e-12):
            continue
        attempts += 1; cost = nc; extra = ne
        if bad and draws['rep'][ni, fi] < params['p_rep']:
            out[ni][fi] = 0; loc[ni][fi] = True; sup[ni][fi] = True
    s = score_full(out, loc, sup, eok)
    if return_states:
        return s, cost, makespan_extra(assign, extra), attempts, gate_repaired, out, loc, sup, eok
    return s, cost, makespan_extra(assign, extra), attempts, gate_repaired


def eval_vcr(prepped, assign, static_caps, base_row, cap, deadline, params):
    n = len(prepped)
    term = np.empty(n); ctp = np.empty(n); cfp = np.empty(n)
    cost = np.empty(n); mk = np.empty(n); att = np.empty(n); gate = np.empty(n)
    for i, P in enumerate(prepped):
        s, c, m, a, g = repair_run(P, assign, static_caps, cap, deadline, params, P['vcr'])
        term[i] = s['term']; ctp[i] = s['ctp']; cfp[i] = s['cfp']
        cost[i] = c; mk[i] = m; att[i] = a; gate[i] = g
    parse = base_row['parse_t']; contract = base_row['contract_t']
    return {'term_t': term, 'ctp_t': ctp, 'cfp_t': cfp, 'cost_t': cost, 'mk_t': mk,
            'parse_t': parse, 'contract_t': contract,
            'glm_t': base_row['glm_t'], 'attempts': att, 'gate_rep': gate}


def base_eval(prepped, assign):
    n = len(prepped)
    term = np.empty(n); ctp = np.empty(n); cfp = np.empty(n)
    for i, P in enumerate(prepped):
        out, loc, sup, eok = run_fast(P, assign)
        s = score_full(out, loc, sup, eok)
        term[i] = s['term']; ctp[i] = s['ctp']; cfp[i] = s['cfp']
    c = assignment_cost(assign); m = makespan(assign)
    return {'term_t': term, 'ctp_t': ctp, 'cfp_t': cfp,
            'cost_t': np.full(n, c), 'mk_t': np.full(n, m),
            'parse_t': np.full(n, np.mean([1.0 if (P['parse'][ni] <= P['Rparse'][int(assign[ni])] - P['extra'] and P['contract'][ni] <= P['Rcontract'][int(assign[ni])]) else 0.0 for ni in range(7)])) if False else None,
            'contract_t': None, 'glm_t': np.full(n, float(np.mean(assign == 0)))}


def base_eval_full(prepped, assign):
    n = len(prepped)
    term = np.empty(n); ctp = np.empty(n); cfp = np.empty(n); parse = np.empty(n); contract = np.empty(n)
    for i, P in enumerate(prepped):
        out, loc, sup, eok = run_fast(P, assign)
        s = score_full(out, loc, sup, eok)
        term[i] = s['term']; ctp[i] = s['ctp']; cfp[i] = s['cfp']
        parse[i] = np.mean([1.0 if (P['parse'][ni] <= P['Rparse'][int(assign[ni])] - P['extra'] and
                                    P['contract'][ni] <= P['Rcontract'][int(assign[ni])]) else 0.0 for ni in range(7)])
        contract[i] = np.mean([1.0 if P['contract'][ni] <= P['Rcontract'][int(assign[ni])] else 0.0 for ni in range(7)])
    c = assignment_cost(assign); m = makespan(assign)
    return {'term_t': term, 'ctp_t': ctp, 'cfp_t': cfp,
            'cost_t': np.full(n, c), 'mk_t': np.full(n, m),
            'parse_t': parse, 'contract_t': contract,
            'glm_t': np.full(n, float(np.mean(assign == 0))),
            'cost': float(c), 'mk': float(m), 'parse': float(parse.mean()),
            'contract': float(contract.mean()), 'term': float(term.mean())}


def run_sensitivity():
    """One-at-a-time verifier sensitivity on TRAIN tasks; no test data."""
    cfg = SCENARIOS[2]  # stable .20
    tr = task_pool_vcr(300, cfg['seed'] * 3000000 + 11, cfg['sign_mode'])
    trP = prep_all(tr, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    for P, t in zip(trP, tr):
        P['vcr'] = t['vcr']
    assign = mask_to_assign(119)  # m base
    base = base_eval_full(trP, assign)
    static = base_eval_full(trP, mask_to_assign(127))
    rows = []
    variants = [
        ('base', {}),
        ('sens .60', {'sens': 0.60}), ('sens .95', {'sens': 0.95}),
        ('spec .80', {'spec': 0.80}), ('spec .95', {'spec': 0.95}),
        ('p_rep .50', {'p_rep': 0.50}), ('p_rep .90', {'p_rep': 0.90}),
        ('c_rep .01', {'c_rep': 0.01}), ('c_rep .03', {'c_rep': 0.03}),
        ('l_rep .01', {'l_rep': 0.01}), ('l_rep .03', {'l_rep': 0.03}),
        ('max_rep 1', {'max_rep': 1}), ('max_rep 5', {'max_rep': 5}),
    ]
    for name, over in variants:
        p = dict(BASE); p.update(over)
        e = eval_vcr(trP, assign, static, base, 0.20, 1.10, p)
        s = summarize(e['term_t'], e['ctp_t'], e['cfp_t'], e['cost_t'], e['mk_t'],
                      e['parse_t'], e['contract_t'], e['glm_t'], static, 0.20)
        rows.append({'variant': name, 'Q': s['q_mean'], 'dQ': s['dq_mean'],
                     'GQ': s['GQ'], 'GF': s['GF'], 'GRm': s['GR_matched'],
                     'GRs': s['GR_strict'], 'Jm': s['JOINT_matched'], 'Js': s['JOINT_strict'],
                     'cost': s['cost_ratio'], 'mk': s['mk_ratio'],
                     'attempts': float(e['attempts'].mean()), 'gate_rep': float(e['gate_rep'].mean())})
    out = {'scenario': cfg['name'], 'base_params': BASE, 'base_Q': float(base['term_t'].mean()),
           'grid': rows}
    json.dump(out, open(os.path.join(OUT, 'RQ2_VCR_SENSITIVITY.json'), 'w'), indent=1)
    print('V-CR verifier sensitivity (train only, stable .20, base m):', flush=True)
    for r in rows:
        print(f"  {r['variant']:12s} Q={r['Q']:.4f} dQ={r['dQ']:+.4f} GQ={r['GQ']:.2f} "
              f"GF={r['GF']:.2f} GRm={r['GRm']:.2f} GRs={r['GRs']:.2f} "
              f"Jm={r['Jm']:.2f} Js={r['Js']:.2f} cost={r['cost']:.3f} "
              f"mk={r['mk']:.3f} attempts={r['attempts']:.2f}", flush=True)
    return out


def run_split(args):
    si, rep = args
    cfg = SCENARIOS[si]
    seed = cfg['seed'] * 2100000 + rep * 10
    ts = task_pool_vcr(N_POOL, seed, cfg['sign_mode'])
    rng = np.random.default_rng(seed + 7)
    idx = rng.permutation(N_POOL)
    tr = [ts[i] for i in idx[:N_TRAIN]]
    te = [ts[i] for i in idx[N_TRAIN:]]
    trP = prep_all(tr, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    teP = prep_all(te, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    for P, t in zip(teP, te):
        P['vcr'] = t['vcr']
    bu, nt, gain, tc = r4_models(tr, cfg)
    static_assign = mask_to_assign(static_mask(bu))
    static = base_eval_full(teP, static_assign)
    out = {'scenario': cfg['name'], 'slug': cfg['slug'], 'rep': rep, 'settings': {}}
    for cap, ck, deadline, bases in (
            (0.10, '10', 1.10, ['DS', 'm']),
            (0.15, '15', 1.10, ['DS', 'm']),
            (0.20, '20m', 1.20, ['m', 'mv']),
            (0.20, '20s', 1.10, ['DS', 'm'])):
        out['settings'][ck] = {}
        for bname in bases:
            assign = mask_to_assign(BASE_MASK[bname])
            be = base_eval_full(teP, assign)
            bs = summarize(be['term_t'], be['ctp_t'], be['cfp_t'], be['cost_t'],
                           be['mk_t'], be['parse_t'], be['contract_t'], be['glm_t'],
                           static, cap)
            ve = eval_vcr(teP, assign, static, be, cap, deadline, BASE)
            vs = summarize(ve['term_t'], ve['ctp_t'], ve['cfp_t'], ve['cost_t'],
                           ve['mk_t'], ve['parse_t'], ve['contract_t'], ve['glm_t'],
                           static, cap)
            vs['attempts'] = float(ve['attempts'].mean())
            vs['gate_rep'] = float(ve['gate_rep'].mean())
            out['settings'][ck][bname] = {'base': bs, 'V-CR': vs}
    return out


def agg(vals):
    a = np.asarray(vals, dtype=float)
    m = float(a.mean())
    ci = float(1.96 * a.std(ddof=1) / math.sqrt(len(a))) if len(a) > 1 else 0.0
    return m, ci


def aggregate(reps):
    reps = sorted(reps, key=lambda x: x['rep'])
    out = {'scenario': reps[0]['scenario'], 'slug': reps[0]['slug'], 'N': len(reps), 'settings': {}}
    for cap, ck, deadline, bases in (
            (0.10, '10', 1.10, ['DS', 'm']),
            (0.15, '15', 1.10, ['DS', 'm']),
            (0.20, '20m', 1.20, ['m', 'mv']),
            (0.20, '20s', 1.10, ['DS', 'm'])):
        out['settings'][ck] = {}
        for bname in bases:
            arms = {}
            for arm in ('base', 'V-CR'):
                vals = [r['settings'][ck][bname][arm] for r in reps]
                dq = [v['dq_mean'] for v in vals]; net = [v['net_sum'] for v in vals]
                q = [v['q_mean'] for v in vals]; cr = [v['cost_ratio'] for v in vals]
                mr = [v['mk_ratio'] for v in vals]
                m, ci = agg(dq); nm, nci = agg(net)
                arms[arm] = {'dq_mean': m, 'dq_ci95': [m - ci, m + ci],
                             'net_sum_mean': nm, 'net_ci95': [nm - nci, nm + nci],
                             'q_mean': float(np.mean(q)), 'cost_ratio': float(np.mean(cr)),
                             'mk_ratio': float(np.mean(mr)),
                             'GQ': float(np.mean([v['GQ'] for v in vals])),
                             'GF': float(np.mean([v['GF'] for v in vals])),
                             'GR_matched': float(np.mean([v['GR_matched'] for v in vals])),
                             'GR_strict': float(np.mean([v['GR_strict'] for v in vals])),
                             'JOINT_matched': float(np.mean([v['JOINT_matched'] for v in vals])),
                             'JOINT_strict': float(np.mean([v['JOINT_strict'] for v in vals])),
                             'glm_share': float(np.mean([v['glm_share'] for v in vals]))}
            if 'attempts' in [r['settings'][ck][bname]['V-CR'] for r in reps][0]:
                arms['V-CR']['attempts'] = float(np.mean([r['settings'][ck][bname]['V-CR']['attempts'] for r in reps]))
                arms['V-CR']['gate_rep'] = float(np.mean([r['settings'][ck][bname]['V-CR']['gate_rep'] for r in reps]))
            out['settings'][ck][bname] = arms
    return out


def run_pilot(tag='BASE'):
    si_list = [2, 1, 3, 0]  # stable20, stable15, mixed, H0
    args = [(si, rep) for si in si_list for rep in range(REPS)]
    results = []; t0 = time.time()
    with mp.Pool(processes=min(48, os.cpu_count() or 1)) as pool:
        for i, r in enumerate(pool.imap_unordered(run_split, args, chunksize=1)):
            results.append(r)
            if (i + 1) % 50 == 0:
                print(f'  progress {i+1}/{len(args)} elapsed={time.time()-t0:.0f}s', flush=True)
    by = {}
    for r in results:
        by.setdefault(r['slug'], []).append(r)
    final = {}
    for si in si_list:
        cfg = SCENARIOS[si]
        a = aggregate(by[cfg['slug']])
        final[cfg['name']] = a
        print(f'\n=== {cfg["name"]} N={a["N"]}', flush=True)
        for ck in ('10', '15', '20m', '20s'):
            print(f' cap {ck}', flush=True)
            for bname, arms in a['settings'][ck].items():
                for arm in ('base', 'V-CR'):
                    d = arms[arm]
                    print(f'   {bname}+{arm:5s} dQ={d["dq_mean"]:+.4f} Q={d["q_mean"]:.4f} '
                          f'GQ={d["GQ"]:.2f} GF={d["GF"]:.2f} GRm={d["GR_matched"]:.2f} '
                          f'GRs={d["GR_strict"]:.2f} Jm={d["JOINT_matched"]:.2f} '
                          f'Js={d["JOINT_strict"]:.2f} cost={d["cost_ratio"]:.3f} '
                          f'mk={d["mk_ratio"]:.3f} att={d.get("attempts", 0):.2f}', flush=True)
    json.dump(final, open(os.path.join(OUT, f'RQ2_VCR_PILOT_{tag}.json'), 'w'), indent=1)
    print(f'\nTOTAL {time.time()-t0:.0f}s; zero API', flush=True)


if __name__ == '__main__':
    try:
        mp.set_start_method('fork', force=True)
    except RuntimeError:
        pass
    if len(sys.argv) > 1 and sys.argv[1] == 'sensitivity':
        run_sensitivity()
    elif len(sys.argv) > 1 and sys.argv[1] == 'conservative':
        BASE = CONSERVATIVE
        run_pilot('CONSERVATIVE')
    else:
        run_pilot('BASE')
