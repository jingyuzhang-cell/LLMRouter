#!/usr/bin/env python3
"""R5: full 128-assignment enumeration + budget-constrained DAG allocation Pareto.

Stages:
  pop    : population-level 128-assignment enumeration, Pareto front, constrained oracle
  splits : repeated train/test splits for deployable strategies (Static, Node-Type,
           Task-Cond, Budget-Con, Marginal-Gain/Cost, Critical-Path-Aware,
           Joint-Pareto, Constrained Oracle)
  all    : pop then splits

Frozen R3/R4 files are imported, never modified. Zero real API calls.
Primary feasibility: cost <= Static*(1+cap), makespan <= Static*(1+cap),
parse/contract non-inferior (>= Static-0.02).
Strict latency: makespan <= Static*1.10 for every cap.
"""
import os, sys, json, time, math, hashlib, numpy as np
import multiprocessing as mp
from rq1_v1_8_2_r5_core import (
    NODES, TYPES, GLM_T, FACT_PARENTS, CRIT, UNK_FACT, DEC, RATES, PRICE, LAT,
    BASE_LAT, FP_RATE, MVS, ALL_MASKS, mask_to_assign, assign_to_mask, glm_nodes,
    prep, prep_all, run_fast, score_full, parse_contract_rates, assignment_cost,
    eval_assignment, critical_path, enumerate_all, equivalence_check,
)
from rq1_v1_8_2_r4_p0_calibration import (
    make_tasks, make_u, makespan, exact_p, base_p, score, run_task, train_arm_models,
)

OUT = os.path.dirname(os.path.abspath(__file__))
CAPS = (0.10, 0.15, 0.20)
CAP_KEYS = ('10', '15', '20')
N_POP_TRAIN = 300
N_POP_EVAL = 800
N_REPS = 100
N_POOL = 48
N_TRAIN = 24
N_TEST = 24

SCENARIOS = [
    dict(name='H0 pure null', slug='H0', delta=0.0, sign_mode='stable', up=1.0,
         extra_parse=0.0, pure_null=True, seed=5101),
    dict(name='stable H1 .15', slug='stable15', delta=0.15, sign_mode='stable', up=1.0,
         extra_parse=0.0, pure_null=False, seed=5102),
    dict(name='stable H1 .20', slug='stable20', delta=0.20, sign_mode='stable', up=1.0,
         extra_parse=0.0, pure_null=False, seed=5103),
    dict(name='mixed H1 .15', slug='mixed15', delta=0.15, sign_mode='mixed', up=1.0,
         extra_parse=0.0, pure_null=False, seed=5104),
    dict(name='upstream pressure', slug='upstream', delta=0.15, sign_mode='stable', up=0.85,
         extra_parse=0.0, pure_null=False, seed=5105),
    dict(name='parse pressure', slug='parse', delta=0.15, sign_mode='stable', up=1.0,
         extra_parse=0.10, pure_null=False, seed=5106),
    dict(name='up+parse pressure', slug='upparse', delta=0.15, sign_mode='stable', up=0.85,
         extra_parse=0.10, pure_null=False, seed=5107),
]

ARM_NAMES = ['Static', 'Node-Type', 'Task-Cond', 'Budget-Con', 'MGC', 'CPA',
             'JP-matched', 'JP-strict', 'CO-matched', 'CO-strict', 'True-Oracle-R4ref']


def task_pool(n, seed, sign_mode):
    ts = make_tasks(n, seed=seed, sign_mode=sign_mode)
    make_u(ts, seed=seed + 100)
    return ts


def r4_models(tr, cfg):
    return train_arm_models(tr, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])


def static_mask(bu):
    return assign_to_mask(np.full(7, int(bu)))


def nt_mask(nt):
    return assign_to_mask(np.array([nt[ty] for ty in TYPES], dtype=int))


def budget_mask(gain, bu, cap):
    """Exact R4 Budget-Con construction; cap parameterized (R4 used 0.10)."""
    a = np.full(7, int(bu))
    cbu = float(np.mean(PRICE[np.full(7, int(bu))]))
    mbu = float(makespan(np.full(7, int(bu))))
    if int(bu) == 1:
        order = sorted([(gain[ty], ni) for ni, ty in enumerate(TYPES) if gain[ty] > 0],
                       reverse=True)
        for g, ni in order:
            trial = a.copy(); trial[ni] = 0
            if (np.mean(PRICE[trial]) <= (1.0 + cap) * cbu + 1e-12 and
                    makespan(trial) <= (1.0 + cap) * mbu + 1e-12):
                a = trial
    else:
        for ni, ty in enumerate(TYPES):
            if gain[ty] < 0:
                a[ni] = 1
    return assign_to_mask(a)


def feas(row, base, cap, deadline_ratio):
    return bool(row['cost'] <= base['cost'] * (1.0 + cap) + 1e-12 and
                row['mk'] <= base['mk'] * deadline_ratio + 1e-12 and
                row['parse'] >= base['parse'] - 0.02 - 1e-12 and
                row['contract'] >= base['contract'] - 0.02 - 1e-12)


def select_best(rows, base, cap, deadline_ratio):
    cand = [r for r in rows if feas(r, base, cap, deadline_ratio)]
    if not cand:
        return base
    return max(cand, key=lambda r: (r['term'], -r['cost'], -r['mk'], -r['mask']))


def greedy_mask(rows, base_mask, cap, deadline_ratio, mode):
    """MGC: marginal terminal gain / incremental cost, cost cap only.
       CPA: same but strict makespan deadline + critical-path/slack penalty.
    """
    by = {r['mask']: r for r in rows}
    base = by[base_mask]
    cur = base_mask
    visited = {cur}
    for _ in range(7):
        cur_row = by[cur]
        cp = critical_path(mask_to_assign(cur))
        best = None
        for ni in range(7):
            m2 = cur ^ (1 << ni)
            if m2 in visited:
                continue
            r = by[m2]
            dQ = r['term'] - cur_row['term']
            dc = r['cost'] - cur_row['cost']
            if dQ < -1e-12:
                continue
            if dc > 0 and dQ <= 1e-12:
                continue
            if mode == 'mgc':
                ok = (r['cost'] <= base['cost'] * (1.0 + cap) + 1e-12 and
                      r['parse'] >= base['parse'] - 0.02 - 1e-12 and
                      r['contract'] >= base['contract'] - 0.02 - 1e-12)
                if not ok:
                    continue
                if dc > 0:
                    score = dQ / dc
                else:
                    score = 1e6 + dQ * 1000.0 + (-dc)
            else:
                if not feas(r, base, cap, deadline_ratio):
                    continue
                if dc > 0:
                    old_lat = cp['lat'][ni]
                    new_lat = float(BASE_LAT[ni] * LAT[(m2 >> ni) & 1])
                    dl = new_lat - old_lat
                    slack = cp['slack'][ni]
                    pen = 1.0 + 0.5 * max(0.0, dl - slack) / max(slack, 0.1 * old_lat)
                    score = dQ / (dc * pen)
                else:
                    score = 1e6 + dQ * 1000.0 + (-dc)
            if best is None or score > best[0]:
                best = (score, m2)
        if best is None:
            break
        cur = best[1]
        visited.add(cur)
    return cur


def eval_task_choices(prepped, assign_fn):
    n = len(prepped)
    keys = ['term', 'local', 'ctp', 'cfp', 'cfn', 'unk', 'tp', 'fp', 'fn',
            'loc_all', 'sup_all', 'loc_cond', 'sup_cond']
    arr = {k: np.empty(n) for k in keys}
    cost = np.empty(n); mk = np.empty(n); parse = np.empty(n); contract = np.empty(n)
    glm = np.empty(n)
    for i, P in enumerate(prepped):
        a = assign_fn(P)
        out, lo, su, eok = run_fast(P, a)
        s = score_full(out, lo, su, eok)
        for k in keys:
            arr[k][i] = s[k]
        cost[i] = assignment_cost(a); mk[i] = makespan(a)
        parse[i], contract[i] = parse_contract_rates(P, a)
        glm[i] = float(np.mean(np.asarray(a) == 0))
    return {'term_t': arr['term'], 'ctp_t': arr['ctp'], 'cfp_t': arr['cfp'],
            'cost_t': cost, 'mk_t': mk, 'parse_t': parse, 'contract_t': contract,
            'glm_t': glm}


def summarize(term_t, ctp_t, cfp_t, cost_t, mk_t, parse_t, contract_t, glm_t,
              static, cap):
    n = len(term_t)
    dq = term_t - static['term_t']
    net = (ctp_t - static['ctp_t']) - (cfp_t - static['cfp_t'])
    mu = float(dq.mean())
    se = float(dq.std(ddof=1) / math.sqrt(n)) if n > 1 else 0.0
    gq = bool(mu >= MVS and mu - 1.96 * se > 0.0)
    gf = bool(net.sum() >= 1 and exact_p(net.astype(int).tolist()) <= 0.05)
    dcm = float(np.mean(cost_t / static['cost_t'] - 1.0))
    dmm = float(np.mean(mk_t / static['mk_t'] - 1.0))
    pni = bool(parse_t.mean() >= static['parse_t'].mean() - 0.02 - 1e-12)
    cni = bool(contract_t.mean() >= static['contract_t'].mean() - 0.02 - 1e-12)
    grm = bool(dcm <= cap + 1e-12 and dmm <= cap + 1e-12 and pni and cni)
    grs = bool(dcm <= cap + 1e-12 and dmm <= 0.10 + 1e-12 and pni and cni)
    return {
        'dq_mean': mu, 'dq_se': se, 'dq_ci95': [mu - 1.96 * se, mu + 1.96 * se],
        'net_sum': float(net.sum()), 'net_mean': float(net.mean()),
        'GQ': gq, 'GF': gf,
        'GR_matched': grm, 'GR_strict': grs,
        'JOINT_matched': bool(gq and gf and grm),
        'JOINT_strict': bool(gq and gf and grs),
        'q_mean': float(term_t.mean()),
        'cost_ratio': float(np.mean(cost_t / static['cost_t'])),
        'mk_ratio': float(np.mean(mk_t / static['mk_t'])),
        'parse': float(parse_t.mean()), 'contract': float(contract_t.mean()),
        'glm_share': float(glm_t.mean()),
        'win': float(np.mean(dq > 0)), 'tie': float(np.mean(dq == 0)),
        'lose': float(np.mean(dq < 0)),
    }


def summarize_row(row, static, cap):
    s = summarize(row['term_t'], row['ctp_t'], row['cfp_t'], row['cost_t'], row['mk_t'],
                  row['parse_t'], row['contract_t'], row['glm_t'], static, cap)
    s['mask'] = int(row['mask'])
    s['glm_nodes'] = list(row['glm_nodes'])
    s['critical'] = list(row.get('critical_nodes', []))
    return s


def row_brief(row):
    return {'mask': int(row['mask']), 'glm_nodes': list(row['glm_nodes']),
            'term': float(row['term']), 'local': float(row['local']),
            'cost': float(row['cost']), 'mk': float(row['mk']),
            'ctp': float(row['ctp']), 'cfp': float(row['cfp']), 'cfn': float(row['cfn']),
            'unk': float(row['unk']), 'tp': float(row['tp']), 'fp': float(row['fp']),
            'fn': float(row['fn']), 'loc_all': float(row['loc_all']),
            'sup_all': float(row['sup_all']), 'loc_cond': float(row['loc_cond']),
            'sup_cond': float(row['sup_cond']), 'parse': float(row['parse']),
            'contract': float(row['contract']), 'glm_share': float(row['glm_share']),
            'critical': list(row.get('critical_nodes', []))}


def pareto_rows(rows, dims):
    nd = []
    for p in rows:
        dom = False
        for q in rows:
            if q is p:
                continue
            if dims == '3d':
                better_or_equal = (q['cost'] <= p['cost'] + 1e-12 and q['mk'] <= p['mk'] + 1e-12 and
                                   q['term'] >= p['term'] - 1e-12)
                strict = (q['cost'] < p['cost'] - 1e-12 or q['mk'] < p['mk'] - 1e-12 or
                          q['term'] > p['term'] + 1e-12)
            elif dims == 'q_cost':
                better_or_equal = (q['cost'] <= p['cost'] + 1e-12 and q['term'] >= p['term'] - 1e-12)
                strict = (q['cost'] < p['cost'] - 1e-12 or q['term'] > p['term'] + 1e-12)
            else:
                better_or_equal = (q['mk'] <= p['mk'] + 1e-12 and q['term'] >= p['term'] - 1e-12)
                strict = (q['mk'] < p['mk'] - 1e-12 or q['term'] > p['term'] + 1e-12)
            if better_or_equal and strict:
                dom = True
                break
        if not dom:
            nd.append(int(p['mask']))
    return sorted(nd)


def cost_levels(rows):
    out = []
    by_k = {}
    for r in rows:
        k = int(round(r['glm_share'] * 7))
        by_k.setdefault(k, []).append(r)
    for k in sorted(by_k):
        best = max(by_k[k], key=lambda r: (r['term'], -r['cost'], -r['mk'], -r['mask']))
        out.append({'n_glm': k, 'mask': int(best['mask']), 'glm_nodes': list(best['glm_nodes']),
                    'term': float(best['term']), 'cost': float(best['cost']),
                    'mk': float(best['mk']), 'ctp': float(best['ctp']),
                    'cfp': float(best['cfp']), 'parse': float(best['parse']),
                    'contract': float(best['contract'])})
    return out


def max_glm_cost(base_cost, cap):
    best = 0
    for k in range(8):
        c = (k * 1.0 + (7 - k) * 0.6) / 7.0
        if c <= base_cost * (1.0 + cap) + 1e-12:
            best = k
    return best


def run_population(si):
    cfg = SCENARIOS[si]
    t0 = time.time()
    tr = task_pool(N_POP_TRAIN, cfg['seed'] * 1000 + 101, cfg['sign_mode'])
    ev = task_pool(N_POP_EVAL, cfg['seed'] * 1000 + 501, cfg['sign_mode'])
    trP = prep_all(tr, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    evP = prep_all(ev, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    tr_rows = enumerate_all(trP, store_tasks=False)
    ev_rows = enumerate_all(evP, store_tasks=True)
    bu, nt, gain, tc = r4_models(tr, cfg)
    sm = static_mask(bu); nm = nt_mask(nt)
    base_tr = tr_rows[sm]; base_ev = ev_rows[sm]

    def tc_assign(P):
        a = []
        for ty in TYPES:
            err, fi, th, o = tc[ty]
            a.append(1 if ((P['feat'][fi] > th) if o == 1 else (P['feat'][fi] <= th)) else 0)
        return np.array(a, dtype=int)

    def to_assign(P):
        return np.array([0 if P['base'][0][ni] >= P['base'][1][ni] else 1 for ni in range(7)],
                        dtype=int)

    tc_arr = eval_task_choices(evP, tc_assign)
    to_arr = eval_task_choices(evP, to_assign)
    static_summary = summarize_row(base_ev, base_ev, 0.0)
    out = {
        'scenario': cfg['name'], 'slug': cfg['slug'], 'cfg': {k: cfg[k] for k in
            ('delta', 'sign_mode', 'up', 'extra_parse', 'pure_null', 'seed')},
        'n_train': N_POP_TRAIN, 'n_eval': N_POP_EVAL,
        'bu': int(bu), 'static_mask': int(sm), 'nt_mask': int(nm),
        'static_glm': bool(int(bu) == 0),
        'base': {'cost': float(base_ev['cost']), 'mk': float(base_ev['mk']),
                 'parse': float(base_ev['parse']), 'contract': float(base_ev['contract']),
                 'term': float(base_ev['term']), 'glm_share': float(base_ev['glm_share'])},
        'nt_agree_test': None,
        'pareto3': pareto_rows(ev_rows, '3d'),
        'pareto_q_cost': pareto_rows(ev_rows, 'q_cost'),
        'pareto_q_mk': pareto_rows(ev_rows, 'q_mk'),
        'cost_levels': cost_levels(ev_rows),
        'caps': {},
        'true_oracle': summarize(to_arr['term_t'], to_arr['ctp_t'], to_arr['cfp_t'],
                                 to_arr['cost_t'], to_arr['mk_t'], to_arr['parse_t'],
                                 to_arr['contract_t'], to_arr['glm_t'], base_ev, 0.0),
        'timing_s': None,
        'enumeration': [row_brief(r) for r in ev_rows],
    }
    # true oracle summary is cap-independent except GR; recompute per cap below
    for cap, ck in zip(CAPS, CAP_KEYS):
        bc = budget_mask(gain, bu, cap)
        mgc = greedy_mask(tr_rows, sm, cap, 1.0 + cap, 'mgc')
        cpa = greedy_mask(tr_rows, sm, cap, 1.10, 'cpa')
        jpm = select_best(tr_rows, base_tr, cap, 1.0 + cap)['mask']
        jps = select_best(tr_rows, base_tr, cap, 1.10)['mask']
        com = select_best(ev_rows, base_ev, cap, 1.0 + cap)['mask']
        cos = select_best(ev_rows, base_ev, cap, 1.10)['mask']

        arms = {}
        for arm, mask, sel in (
            ('Static', sm, 'fixed'), ('Node-Type', nm, 'fixed'),
            ('Budget-Con', bc, 'train'), ('MGC', mgc, 'train'),
            ('CPA', cpa, 'train'), ('JP-matched', jpm, 'train'),
            ('JP-strict', jps, 'train'), ('CO-matched', com, 'test'),
            ('CO-strict', cos, 'test')):
            s = summarize_row(ev_rows[mask], base_ev, cap)
            s['selected_on'] = sel
            arms[arm] = s
        arms['Task-Cond'] = summarize(tc_arr['term_t'], tc_arr['ctp_t'], tc_arr['cfp_t'],
                                      tc_arr['cost_t'], tc_arr['mk_t'], tc_arr['parse_t'],
                                      tc_arr['contract_t'], tc_arr['glm_t'], base_ev, cap)
        arms['Task-Cond'].update({'mask': -1, 'glm_nodes': [], 'critical': [],
                                  'selected_on': 'task'})
        arms['True-Oracle-R4ref'] = summarize(to_arr['term_t'], to_arr['ctp_t'], to_arr['cfp_t'],
                                              to_arr['cost_t'], to_arr['mk_t'], to_arr['parse_t'],
                                              to_arr['contract_t'], to_arr['glm_t'], base_ev, cap)
        arms['True-Oracle-R4ref'].update({'mask': -1, 'glm_nodes': [], 'critical': [],
                                          'selected_on': 'task'})

        feas_m = [r for r in ev_rows if feas(r, base_ev, cap, 1.0 + cap)]
        feas_s = [r for r in ev_rows if feas(r, base_ev, cap, 1.10)]
        top_m = sorted(feas_m, key=lambda r: (-r['term'], r['cost'], r['mk'], r['mask']))[:5]
        top_s = sorted(feas_s, key=lambda r: (-r['term'], r['cost'], r['mk'], r['mask']))[:5]
        co_m = ev_rows[com]; co_s = ev_rows[cos]
        out['caps'][ck] = {
            'cap': cap,
            'max_glm_cost': max_glm_cost(base_ev['cost'], cap),
            'n_cost_feasible': len([r for r in ev_rows
                                    if r['cost'] <= base_ev['cost'] * (1.0 + cap) + 1e-12]),
            'n_matched_feasible': len(feas_m), 'n_strict_feasible': len(feas_s),
            'arms': arms,
            'CO-matched_brief': row_brief(co_m),
            'CO-strict_brief': row_brief(co_s),
            'CO_matched_dQ': float(co_m['term'] - base_ev['term']),
            'CO_strict_dQ': float(co_s['term'] - base_ev['term']),
            'top5_matched': [row_brief(r) for r in top_m],
            'top5_strict': [row_brief(r) for r in top_s],
            'CO_gap_matched_dQ': float(co_m['term'] - ev_rows[jpm]['term']),
            'CO_gap_strict_dQ': float(co_s['term'] - ev_rows[jps]['term']),
            'static_glm': bool(int(bu) == 0),
        }
    out['timing_s'] = time.time() - t0
    npz = {
        'masks': np.array([r['mask'] for r in ev_rows]),
        'cost': np.array([r['cost'] for r in ev_rows]),
        'mk': np.array([r['mk'] for r in ev_rows]),
        'parse': np.array([r['parse'] for r in ev_rows]),
        'contract': np.array([r['contract'] for r in ev_rows]),
        'term': np.array([r['term'] for r in ev_rows]),
        'term_mat': np.vstack([r['term_t'] for r in ev_rows]),
        'ctp_mat': np.vstack([r['ctp_t'] for r in ev_rows]),
        'cfp_mat': np.vstack([r['cfp_t'] for r in ev_rows]),
    }
    return out, npz


def run_rep(arg):
    si, rep = arg
    cfg = SCENARIOS[si]
    seed = cfg['seed'] * 1000000 + rep * 10
    ts = task_pool(N_POOL, seed, cfg['sign_mode'])
    rng = np.random.default_rng(seed + 7)
    idx = rng.permutation(N_POOL)
    tr = [ts[i] for i in idx[:N_TRAIN]]
    te = [ts[i] for i in idx[N_TRAIN:]]
    trP = prep_all(tr, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    teP = prep_all(te, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    tr_rows = enumerate_all(trP, store_tasks=False)
    te_rows = enumerate_all(teP, store_tasks=True)
    bu, nt, gain, tc = r4_models(tr, cfg)
    sm = static_mask(bu); nm = nt_mask(nt)
    base_tr = tr_rows[sm]; base_te = te_rows[sm]

    def tc_assign(P):
        a = []
        for ty in TYPES:
            err, fi, th, o = tc[ty]
            a.append(1 if ((P['feat'][fi] > th) if o == 1 else (P['feat'][fi] <= th)) else 0)
        return np.array(a, dtype=int)

    def to_assign(P):
        return np.array([0 if P['base'][0][ni] >= P['base'][1][ni] else 1 for ni in range(7)],
                        dtype=int)

    tc_arr = eval_task_choices(teP, tc_assign)
    to_arr = eval_task_choices(teP, to_assign)
    out = {'scenario': cfg['name'], 'slug': cfg['slug'], 'rep': rep,
           'bu': int(bu), 'static_mask': int(sm), 'nt_mask': int(nm), 'caps': {}}
    for cap, ck in zip(CAPS, CAP_KEYS):
        bc = budget_mask(gain, bu, cap)
        mgc = greedy_mask(tr_rows, sm, cap, 1.0 + cap, 'mgc')
        cpa = greedy_mask(tr_rows, sm, cap, 1.10, 'cpa')
        jpm = select_best(tr_rows, base_tr, cap, 1.0 + cap)['mask']
        jps = select_best(tr_rows, base_tr, cap, 1.10)['mask']
        com = select_best(te_rows, base_te, cap, 1.0 + cap)['mask']
        cos = select_best(te_rows, base_te, cap, 1.10)['mask']
        arms = {}
        for arm, mask, sel in (
            ('Static', sm, 'fixed'), ('Node-Type', nm, 'fixed'),
            ('Budget-Con', bc, 'train'), ('MGC', mgc, 'train'),
            ('CPA', cpa, 'train'), ('JP-matched', jpm, 'train'),
            ('JP-strict', jps, 'train'), ('CO-matched', com, 'test'),
            ('CO-strict', cos, 'test')):
            s = summarize_row(te_rows[mask], base_te, cap)
            s['selected_on'] = sel
            arms[arm] = s
        arms['Task-Cond'] = summarize(tc_arr['term_t'], tc_arr['ctp_t'], tc_arr['cfp_t'],
                                      tc_arr['cost_t'], tc_arr['mk_t'], tc_arr['parse_t'],
                                      tc_arr['contract_t'], tc_arr['glm_t'], base_te, cap)
        arms['Task-Cond'].update({'mask': -1, 'glm_nodes': [], 'critical': [],
                                  'selected_on': 'task'})
        arms['True-Oracle-R4ref'] = summarize(to_arr['term_t'], to_arr['ctp_t'], to_arr['cfp_t'],
                                              to_arr['cost_t'], to_arr['mk_t'], to_arr['parse_t'],
                                              to_arr['contract_t'], to_arr['glm_t'], base_te, cap)
        arms['True-Oracle-R4ref'].update({'mask': -1, 'glm_nodes': [], 'critical': [],
                                          'selected_on': 'task'})
        out['caps'][ck] = {'arms': arms, 'static_glm': bool(int(bu) == 0),
                           'masks': {'budget': int(bc), 'mgc': int(mgc), 'cpa': int(cpa),
                                     'jpm': int(jpm), 'jps': int(jps), 'com': int(com),
                                     'cos': int(cos)}}
    return out


def agg(vals):
    a = np.asarray(vals, dtype=float)
    m = float(a.mean())
    ci = float(1.96 * a.std(ddof=1) / math.sqrt(len(a))) if len(a) > 1 else 0.0
    return m, ci


def diff_stats(a, b):
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    m = float(d.mean())
    ci = float(1.96 * d.std(ddof=1) / math.sqrt(len(d))) if len(d) > 1 else 0.0
    return {'mean': m, 'ci95': [m - ci, m + ci], 'frac_pos': float(np.mean(d > 0))}


def aggregate_splits(si, reps):
    reps = sorted(reps, key=lambda x: x['rep'])
    cfg = SCENARIOS[si]
    out = {'scenario': cfg['name'], 'slug': cfg['slug'], 'N': len(reps),
           'static_glm_rate': float(np.mean([r['bu'] == 0 for r in reps])),
           'caps': {}, 'rep_arrays': {}}
    for cap, ck in zip(CAPS, CAP_KEYS):
        arm_names = list(reps[0]['caps'][ck]['arms'].keys())
        arms = {}; rep_arrays = {}
        for arm in arm_names:
            vals = [r['caps'][ck]['arms'][arm] for r in reps]
            dq = [v['dq_mean'] for v in vals]
            net = [v['net_sum'] for v in vals]
            q = [v['q_mean'] for v in vals]
            cr = [v['cost_ratio'] for v in vals]
            mr = [v['mk_ratio'] for v in vals]
            pa = [v['parse'] for v in vals]
            co = [v['contract'] for v in vals]
            gl = [v['glm_share'] for v in vals]
            m, ci = agg(dq)
            nm, nci = agg(net)
            arms[arm] = {
                'dq_mean': m, 'dq_ci95': [m - ci, m + ci],
                'net_sum_mean': nm, 'net_ci95': [nm - nci, nm + nci],
                'q_mean': float(np.mean(q)),
                'cost_ratio': float(np.mean(cr)), 'mk_ratio': float(np.mean(mr)),
                'parse': float(np.mean(pa)), 'contract': float(np.mean(co)),
                'glm_share': float(np.mean(gl)),
                'GQ': float(np.mean([v['GQ'] for v in vals])),
                'GF': float(np.mean([v['GF'] for v in vals])),
                'GR_matched': float(np.mean([v['GR_matched'] for v in vals])),
                'GR_strict': float(np.mean([v['GR_strict'] for v in vals])),
                'JOINT_matched': float(np.mean([v['JOINT_matched'] for v in vals])),
                'JOINT_strict': float(np.mean([v['JOINT_strict'] for v in vals])),
                'win': float(np.mean([v['win'] for v in vals])),
                'tie': float(np.mean([v['tie'] for v in vals])),
                'lose': float(np.mean([v['lose'] for v in vals])),
            }
            rep_arrays[arm] = {'dq': dq, 'net': net, 'q': q, 'cost_ratio': cr,
                               'mk_ratio': mr, 'glm': gl}
        pairs = {}
        for a, b in (('JP-matched', 'Budget-Con'), ('JP-matched', 'MGC'),
                     ('JP-matched', 'CPA'), ('JP-matched', 'Node-Type'),
                     ('JP-strict', 'Budget-Con'), ('JP-strict', 'MGC'),
                     ('CO-matched', 'JP-matched'), ('CO-strict', 'JP-strict'),
                     ('Budget-Con', 'Node-Type'), ('MGC', 'Node-Type'),
                     ('CPA', 'Node-Type')):
            if a in rep_arrays and b in rep_arrays:
                pairs[f'{a} vs {b}'] = {
                    'dq': diff_stats(rep_arrays[a]['dq'], rep_arrays[b]['dq']),
                    'net': diff_stats(rep_arrays[a]['net'], rep_arrays[b]['net']),
                    'cost_ratio': diff_stats(rep_arrays[a]['cost_ratio'],
                                             rep_arrays[b]['cost_ratio']),
                    'mk_ratio': diff_stats(rep_arrays[a]['mk_ratio'],
                                           rep_arrays[b]['mk_ratio']),
                }
        out['caps'][ck] = {'cap': cap, 'arms': arms, 'pairs': pairs}
        out['rep_arrays'][ck] = rep_arrays
    return out


def jsonable(obj):
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items() if not isinstance(v, np.ndarray)}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def save_population(results):
    import csv
    pop_json = {}
    header = ['scenario', 'slug', 'mask', 'glm_nodes', 'glm_share', 'term', 'local',
              'ctp', 'cfp', 'cfn', 'unk', 'tp', 'fp', 'fn', 'loc_all', 'sup_all',
              'loc_cond', 'sup_cond', 'cost', 'cost_ratio', 'mk', 'mk_ratio',
              'parse', 'contract', 'critical']
    rows = []
    for out, npz in results:
        pop_json[out['scenario']] = out
        np.savez_compressed(os.path.join(OUT, f'RQ1_V1_8_2_R5_POP_{out["slug"]}.npz'), **npz)
        base = out['base']
        for r in out['enumeration']:
            rows.append([out['scenario'], out['slug'], r['mask'], ';'.join(r['glm_nodes']),
                         r['glm_share'], r['term'], r['local'], r['ctp'], r['cfp'], r['cfn'],
                         r['unk'], r['tp'], r['fp'], r['fn'], r['loc_all'], r['sup_all'],
                         r['loc_cond'], r['sup_cond'], r['cost'], r['cost'] / base['cost'],
                         r['mk'], r['mk'] / base['mk'], r['parse'], r['contract'],
                         ';'.join(NODES[i] for i in r['critical'])])
    with open(os.path.join(OUT, 'RQ1_V1_8_2_R5_POPULATION.json'), 'w') as f:
        json.dump(jsonable(pop_json), f, indent=1)
    with open(os.path.join(OUT, 'RQ1_V1_8_2_R5_ENUMERATION.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
    return pop_json


def save_splits(results):
    by_sc = {}
    for r in results:
        by_sc.setdefault(r['slug'], []).append(r)
    split_json = {}
    arrays = {}
    for si, cfg in enumerate(SCENARIOS):
        agg_out = aggregate_splits(si, by_sc[cfg['slug']])
        split_json[cfg['scenario']] = {k: v for k, v in agg_out.items() if k != 'rep_arrays'}
        for ck, arms in agg_out['rep_arrays'].items():
            for arm, d in arms.items():
                key = f'{cfg["slug"]}__{ck}__{arm.replace("-", "_")}'
                for k, v in d.items():
                    arrays[f'{key}__{k}'] = np.asarray(v, dtype=float)
    with open(os.path.join(OUT, 'RQ1_V1_8_2_R5_SPLITS.json'), 'w') as f:
        json.dump(jsonable(split_json), f, indent=1)
    np.savez_compressed(os.path.join(OUT, 'RQ1_V1_8_2_R5_SPLITS.npz'), **arrays)
    return split_json


def save_splits_chunk(si, results):
    cfg = SCENARIOS[si]
    agg_out = aggregate_splits(si, results)
    summary = {k: v for k, v in agg_out.items() if k != 'rep_arrays'}
    with open(os.path.join(OUT, f'RQ1_V1_8_2_R5_SPLITS_{cfg["slug"]}.json'), 'w') as f:
        json.dump(jsonable(summary), f, indent=1)
    arrays = {}
    for ck, arms in agg_out['rep_arrays'].items():
        for arm, d in arms.items():
            key = f'{cfg["slug"]}__{ck}__{arm.replace("-", "_")}'
            for k, v in d.items():
                arrays[f'{key}__{k}'] = np.asarray(v, dtype=float)
    np.savez_compressed(os.path.join(OUT, f'RQ1_V1_8_2_R5_SPLITS_{cfg["slug"]}.npz'),
                        **arrays)
    return summary


def combine_chunks():
    split_json = {}
    arrays = {}
    for cfg in SCENARIOS:
        jp = os.path.join(OUT, f'RQ1_V1_8_2_R5_SPLITS_{cfg["slug"]}.json')
        zp = os.path.join(OUT, f'RQ1_V1_8_2_R5_SPLITS_{cfg["slug"]}.npz')
        if not (os.path.exists(jp) and os.path.exists(zp)):
            print(f'  combine missing {cfg["slug"]}', flush=True)
            continue
        with open(jp) as f:
            split_json[cfg['name']] = json.load(f)
        z = np.load(zp)
        for k in z.files:
            arrays[k] = z[k]
    with open(os.path.join(OUT, 'RQ1_V1_8_2_R5_SPLITS.json'), 'w') as f:
        json.dump(split_json, f, indent=1)
    np.savez_compressed(os.path.join(OUT, 'RQ1_V1_8_2_R5_SPLITS.npz'), **arrays)
    print(f'combined {len(split_json)} scenarios -> RQ1_V1_8_2_R5_SPLITS.json/.npz', flush=True)
    return split_json


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else 'all'
    t0 = time.time()
    print(f'R5 stage={stage} SYNTHETIC zero-API; frozen R4 mechanism', flush=True)
    eq = equivalence_check(verbose=True)
    with open(os.path.join(OUT, 'RQ1_V1_8_2_R5_EQUIVALENCE.json'), 'w') as f:
        json.dump(jsonable(eq), f, indent=1)
    if stage in ('pop', 'all'):
        print('POP: 128 assignments x 7 scenarios; train=%d eval=%d' %
              (N_POP_TRAIN, N_POP_EVAL), flush=True)
        with mp.Pool(processes=min(7, os.cpu_count() or 1)) as pool:
            results = pool.map(run_population, list(range(len(SCENARIOS))))
        pop = save_population(results)
        for name, o in pop.items():
            print(f'\n[POP] {name}: bu={o["bu"]} static={o["base"]}', flush=True)
            for ck in CAP_KEYS:
                c = o['caps'][ck]; a = c['arms']
                print(f'  cap {ck}% maxGLM={c["max_glm_cost"]} feasM={c["n_matched_feasible"]} '
                      f'feasS={c["n_strict_feasible"]} COm dQ={c["CO_matched_dQ"]:+.4f} '
                      f'COs dQ={c["CO_strict_dQ"]:+.4f}', flush=True)
                for arm in ('Static', 'Node-Type', 'Budget-Con', 'MGC', 'CPA',
                            'JP-matched', 'JP-strict'):
                    d = a[arm]
                    print(f'    {arm:12s} dQ={d["dq_mean"]:+.4f} net={d["net_sum"]:+.2f} '
                          f'GQ={d["GQ"]:.3f} GF={d["GF"]:.3f} GRm={d["GR_matched"]:.3f} '
                          f'GRs={d["GR_strict"]:.3f} Jm={d["JOINT_matched"]:.3f} '
                          f'Js={d["JOINT_strict"]:.3f} cost={d["cost_ratio"]:.3f} '
                          f'mk={d["mk_ratio"]:.3f} glm={d["glm_share"]:.3f}', flush=True)
        print(f'POP total {time.time()-t0:.0f}s', flush=True)
    if stage == 'split1':
        si = int(sys.argv[2])
        cfg = SCENARIOS[si]
        print(f'SPLIT1 scenario={cfg["name"]} N={N_REPS} pool={N_POOL} '
              f'train/test={N_TRAIN}/{N_TEST}', flush=True)
        args = [(si, rep) for rep in range(N_REPS)]
        results = []
        workers = min(32, os.cpu_count() or 1)
        with mp.Pool(processes=workers) as pool:
            for i, r in enumerate(pool.imap_unordered(run_rep, args, chunksize=1)):
                results.append(r)
                if (i + 1) % 20 == 0:
                    print(f'  chunk progress {i+1}/{len(args)} elapsed={time.time()-t0:.0f}s',
                          flush=True)
        s = save_splits_chunk(si, results)
        print(f'[CHUNK] {cfg["name"]}: N={s["N"]} P(Static=GLM)={s["static_glm_rate"]:.3f}',
              flush=True)
        for ck in CAP_KEYS:
            c = s['caps'][ck]
            print(f'  cap {ck}%', flush=True)
            for arm in ('Node-Type', 'Budget-Con', 'MGC', 'CPA', 'JP-matched',
                        'JP-strict', 'CO-matched', 'CO-strict'):
                d = c['arms'][arm]
                print(f'    {arm:12s} dQ={d["dq_mean"]:+.4f} net={d["net_sum_mean"]:+.2f} '
                      f'GQ={d["GQ"]:.3f} GF={d["GF"]:.3f} GRm={d["GR_matched"]:.3f} '
                      f'GRs={d["GR_strict"]:.3f} Jm={d["JOINT_matched"]:.3f} '
                      f'Js={d["JOINT_strict"]:.3f} cost={d["cost_ratio"]:.3f} '
                      f'mk={d["mk_ratio"]:.3f} glm={d["glm_share"]:.3f}', flush=True)
        print(f'CHUNK total {time.time()-t0:.0f}s', flush=True)
    if stage == 'combine':
        combine_chunks()
    if stage in ('splits', 'all'):
        print('SPLITS: N=%d reps x 7 scenarios; pool=%d train/test=%d/%d' %
              (N_REPS, N_POOL, N_TRAIN, N_TEST), flush=True)
        args = [(si, rep) for si in range(len(SCENARIOS)) for rep in range(N_REPS)]
        results = []
        workers = min(48, os.cpu_count() or 1)
        with mp.Pool(processes=workers) as pool:
            for i, r in enumerate(pool.imap_unordered(run_rep, args, chunksize=1)):
                results.append(r)
                if (i + 1) % 100 == 0:
                    print(f'  splits progress {i+1}/{len(args)} elapsed={time.time()-t0:.0f}s',
                          flush=True)
        split = save_splits(results)
        for name, o in split.items():
            print(f'\n[SPLIT] {name}: N={o["N"]} P(Static=GLM)={o["static_glm_rate"]:.3f}', flush=True)
            for ck in CAP_KEYS:
                c = o['caps'][ck]
                print(f'  cap {ck}%', flush=True)
                for arm in ('Node-Type', 'Budget-Con', 'MGC', 'CPA', 'JP-matched',
                            'JP-strict', 'CO-matched', 'CO-strict'):
                    d = c['arms'][arm]
                    print(f'    {arm:12s} dQ={d["dq_mean"]:+.4f} net={d["net_sum_mean"]:+.2f} '
                          f'GQ={d["GQ"]:.3f} GF={d["GF"]:.3f} GRm={d["GR_matched"]:.3f} '
                          f'GRs={d["GR_strict"]:.3f} Jm={d["JOINT_matched"]:.3f} '
                          f'Js={d["JOINT_strict"]:.3f} cost={d["cost_ratio"]:.3f} '
                          f'mk={d["mk_ratio"]:.3f} glm={d["glm_share"]:.3f}', flush=True)
        print(f'TOTAL {time.time()-t0:.0f}s', flush=True)
    print('DONE', flush=True)


if __name__ == '__main__':
    try:
        mp.set_start_method('fork', force=True)
    except RuntimeError:
        pass
    main()
