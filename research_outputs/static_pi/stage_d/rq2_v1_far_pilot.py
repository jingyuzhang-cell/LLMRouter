#!/usr/bin/env python3
"""RQ2 Phase 1: F-AR (feedback-driven adaptive model reallocation) pilot.
Zero API. Reuses frozen R5 tasks/DAG/scoring/reliability; only the model choice is
made online from observed parent-fact TP fraction.

Policy: threshold token allocation. 10/15% and 20% strict: at most 1 GLM token among
m,v,p (all have makespan <= 1.10x Static). 20% matched: at most 2 GLM tokens among
m,r,v,p (all pairs have makespan <= 1.20x Static). Thresholds trained on 24 train
tasks; evaluated on 24 test tasks, 100 independent splits per scenario.
Non-deployable per-task oracle uses test outcomes only as an upper bound.
"""
import os, sys, json, math, time, itertools, numpy as np
import multiprocessing as mp
from rq1_v1_8_2_r5_core import (
    FACT_PARENTS, CRIT, UNK_FACT, DEC, PRICE, LAT, BASE_LAT, FP_RATE, MVS,
    prep_all, run_fast, score_full, parse_contract_rates, assignment_cost,
    eval_assignment, enumerate_all, makespan, mask_to_assign, assign_to_mask,
)
from rq1_v1_8_2_r5_main import (
    SCENARIOS, task_pool, summarize, summarize_row, static_mask, nt_mask,
    r4_models, budget_mask, greedy_mask,
)
from rq1_v1_8_2_r4_p0_calibration import exact_p

OUT = os.path.dirname(os.path.abspath(__file__))
SETTINGS = [
    dict(name='10', cap=0.10, deadline=1.10, max_tokens=1, allowed=('m', 'v', 'p')),
    dict(name='15', cap=0.15, deadline=1.10, max_tokens=1, allowed=('m', 'v', 'p')),
    dict(name='20m', cap=0.20, deadline=1.20, max_tokens=2, allowed=('m', 'r', 'v', 'p')),
    dict(name='20s', cap=0.20, deadline=1.10, max_tokens=1, allowed=('m', 'v', 'p')),
]
NODE_IDX = {'e0': 0, 'e1': 1, 't': 2, 'm': 3, 'r': 4, 'v': 5, 'p': 6}
GRID = (0.0, 0.25, 0.50, 0.75, 1.01)
REPS = 100
N_POOL = 48
N_TRAIN = 24
N_TEST = 24


class FixedPolicy:
    def __init__(self, assign):
        self.assign = np.asarray(assign, dtype=int)

    def choose(self, ni, q, tokens):
        return int(self.assign[ni])


class ThresholdPolicy:
    def __init__(self, max_tokens, thetas):
        self.max_tokens = int(max_tokens)
        self.thetas = dict(thetas)

    def choose(self, ni, q, tokens):
        if ni in (0, 1) or tokens >= self.max_tokens:
            return 1
        th = self.thetas.get(ni)
        if th is not None and q < th:
            return 0
        return 1


def parent_q(out, ni):
    cons = []
    for fi in (0, 1):
        cons += FACT_PARENTS[ni][fi]
    if not cons:
        return 1.0
    return sum(1 for pn, pf in cons if out[pn][pf] == 0) / float(len(cons))


def run_node(P, ni, m, out, loc, sup):
    """Exact R5 node execution for a chosen model; mutates out/loc/sup. Returns exec_ok."""
    if not (P['parse'][ni] <= P['Rparse'][m] - P['extra'] and
            P['contract'][ni] <= P['Rcontract'][m]):
        return False
    b = P['base'][m][ni]
    U = P['fact']
    for fi in (0, 1):
        if ni == 6 and fi == 1:
            out[6][1] = 3 if U[6][1][2] <= P['Runk'][m] else 1
            continue
        cons = FACT_PARENTS[ni][fi]
        q = (sum(1 for pn, pf in cons if out[pn][pf] == 0) / float(len(cons))) if cons else 1.0
        q = q * P['up']
        q = 0.0 if q < 0.0 else (1.0 if q > 1.0 else q)
        pp = b * (0.35 + 0.65 * q)
        if ni == 5:
            pp = pp + 0.30 * (1.0 - q) * (1.0 - b)
        pp = 0.02 if pp < 0.02 else (0.98 if pp > 0.98 else pp)
        u0, u1, _, u3, u4 = U[ni][fi]
        if u0 <= pp:
            out[ni][fi] = 0
        elif u1 < FP_RATE:
            out[ni][fi] = 1
        else:
            out[ni][fi] = 2
        if out[ni][fi] in (0, 1):
            loc[ni][fi] = u3 <= P['Rloc'][m]
            sup[ni][fi] = u4 <= P['Rsup'][m]
    return True


def run_dynamic(P, policy):
    out = [[2, 2] for _ in range(7)]
    loc = [[False, False] for _ in range(7)]
    sup = [[False, False] for _ in range(7)]
    exec_ok = [False] * 7
    assign = np.ones(7, dtype=int)
    tokens = 0
    for ni in range(7):
        q = parent_q(out, ni)
        m = policy.choose(ni, q, tokens)
        assign[ni] = m
        if m == 0:
            tokens += 1
        exec_ok[ni] = run_node(P, ni, m, out, loc, sup)
    s = score_full(out, loc, sup, exec_ok)
    parse = np.mean([1.0 if (P['parse'][ni] <= P['Rparse'][int(assign[ni])] - P['extra'] and
                             P['contract'][ni] <= P['Rcontract'][int(assign[ni])]) else 0.0
                     for ni in range(7)])
    contract = np.mean([1.0 if P['contract'][ni] <= P['Rcontract'][int(assign[ni])] else 0.0
                        for ni in range(7)])
    return {
        'term': s['term'], 'local': s['local'], 'ctp': s['ctp'], 'cfp': s['cfp'],
        'cfn': s['cfn'], 'unk': s['unk'], 'tp': s['tp'], 'fp': s['fp'], 'fn': s['fn'],
        'loc_all': s['loc_all'], 'sup_all': s['sup_all'], 'loc_cond': s['loc_cond'],
        'sup_cond': s['sup_cond'], 'cost': assignment_cost(assign), 'mk': makespan(assign),
        'parse': float(parse), 'contract': float(contract),
        'glm_share': float(np.mean(assign == 0)), 'assign': assign,
        'out': out, 'loc': loc, 'sup': sup, 'exec_ok': exec_ok,
    }


def eval_policy(prepped, policy):
    n = len(prepped)
    keys = ['term', 'local', 'ctp', 'cfp', 'cfn', 'unk', 'tp', 'fp', 'fn',
            'loc_all', 'sup_all', 'loc_cond', 'sup_cond']
    arr = {k: np.empty(n) for k in keys}
    cost = np.empty(n); mk = np.empty(n); parse = np.empty(n); contract = np.empty(n)
    glm = np.empty(n)
    for i, P in enumerate(prepped):
        r = run_dynamic(P, policy)
        for k in keys:
            arr[k][i] = r[k]
        cost[i] = r['cost']; mk[i] = r['mk']; parse[i] = r['parse']
        contract[i] = r['contract']; glm[i] = r['glm_share']
    return {'term_t': arr['term'], 'ctp_t': arr['ctp'], 'cfp_t': arr['cfp'],
            'cost_t': cost, 'mk_t': mk, 'parse_t': parse, 'contract_t': contract,
            'glm_t': glm}


def train_policy(trP, base_row, setting):
    """Grid-search thresholds on train tasks; require all-task cost/mk and mean non-inferior."""
    allowed = [NODE_IDX[x] for x in setting['allowed']]
    best = None
    base_cost = base_row['cost']; base_mk = base_row['mk']
    base_parse = base_row['parse_t'].mean(); base_contract = base_row['contract_t'].mean()
    for combo in itertools.product(GRID, repeat=len(allowed)):
        thetas = dict(zip(allowed, combo))
        pol = ThresholdPolicy(setting['max_tokens'], thetas)
        e = eval_policy(trP, pol)
        if (np.max(e['cost_t']) > base_cost * (1 + setting['cap']) + 1e-12 or
                np.max(e['mk_t']) > base_mk * setting['deadline'] + 1e-12):
            continue
        if (e['parse_t'].mean() < base_parse - 0.02 - 1e-12 or
                e['contract_t'].mean() < base_contract - 0.02 - 1e-12):
            continue
        q = float(e['term_t'].mean())
        key = (q, -float(e['cost_t'].mean()), -float(e['mk_t'].mean()))
        if best is None or key > best[0]:
            best = (key, pol, thetas, q, float(e['cost_t'].mean()), float(e['mk_t'].mean()))
    if best is None:
        # safe fallback: all-DS
        return ThresholdPolicy(0, {}), {}, float(base_row['term']), float(base_cost), float(base_mk)
    return best[1], best[2], best[3], best[4], best[5]


def oracle_summary(rows, base_row, setting):
    feas = [r for r in rows if
            r['cost'] <= base_row['cost'] * (1 + setting['cap']) + 1e-12 and
            r['mk'] <= base_row['mk'] * setting['deadline'] + 1e-12 and
            r['parse'] >= base_row['parse'] - 0.02 - 1e-12 and
            r['contract'] >= base_row['contract'] - 0.02 - 1e-12]
    if not feas:
        return summarize_row(base_row, base_row, setting['cap'])
    # per task choose max terminal Q among feasible
    term = np.vstack([r['term_t'] for r in feas])
    idx = np.argmax(term, axis=0)
    chosen = [feas[int(i)] for i in idx]
    term_t = np.array([r['term_t'][i] for i, r in enumerate(chosen)])
    ctp_t = np.array([r['ctp_t'][i] for i, r in enumerate(chosen)])
    cfp_t = np.array([r['cfp_t'][i] for i, r in enumerate(chosen)])
    # use mean cost/mk/parse/contract of chosen assignments per task
    cost_t = np.array([r['cost'] for r in chosen])
    mk_t = np.array([r['mk'] for r in chosen])
    parse_t = np.array([r['parse'] for r in chosen])
    contract_t = np.array([r['contract'] for r in chosen])
    glm_t = np.array([r['glm_share'] for r in chosen])
    s = summarize(term_t, ctp_t, cfp_t, cost_t, mk_t, parse_t, contract_t, glm_t,
                  base_row, setting['cap'])
    s['assignment_changes'] = int(np.sum([c['mask'] != base_row['mask'] for c in chosen]))
    return s


def run_split(args):
    si, rep = args
    cfg = SCENARIOS[si]
    seed = cfg['seed'] * 2000000 + rep * 10
    ts = task_pool(N_POOL, seed, cfg['sign_mode'])
    rng = np.random.default_rng(seed + 7)
    idx = rng.permutation(N_POOL)
    tr = [ts[i] for i in idx[:N_TRAIN]]
    te = [ts[i] for i in idx[N_TRAIN:]]
    trP = prep_all(tr, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    teP = prep_all(te, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    bu, nt, gain, tc = r4_models(tr, cfg)
    sm = static_mask(bu)
    base_tr = eval_assignment(trP, mask_to_assign(sm), store_tasks=True)
    base_te = eval_assignment(teP, mask_to_assign(sm), store_tasks=True)
    rows_te = enumerate_all(teP, store_tasks=True)
    out = {'scenario': cfg['name'], 'slug': cfg['slug'], 'rep': rep, 'bu': int(bu),
           'static_mask': int(sm), 'settings': {}}
    # static MGC proxies: m at 10/15/20s; m+v at 20m
    proxy_mask = {'10': 119, '15': 119, '20m': 87, '20s': 119}
    for setting in SETTINGS:
        ck = setting['name']
        pol, thetas, trq, trc, trm = train_policy(trP, base_tr, setting)
        e = eval_policy(teP, pol)
        far = summarize(e['term_t'], e['ctp_t'], e['cfp_t'], e['cost_t'], e['mk_t'],
                        e['parse_t'], e['contract_t'], e['glm_t'], base_te, setting['cap'])
        far.update({'mask': -1, 'glm_nodes': [], 'critical': [], 'selected_on': 'dynamic',
                    'theta': {str(k): float(v) for k, v in thetas.items()},
                    'train_q': trq, 'train_cost': trc, 'train_mk': trm})
        mgc = summarize_row(rows_te[proxy_mask[ck]], base_te, setting['cap'])
        mgc.update({'selected_on': 'static_proxy'})
        ora = oracle_summary(rows_te, base_te, setting)
        ora.update({'selected_on': 'test_oracle_non_deployable'})
        out['settings'][ck] = {'F-AR': far, 'MGC-proxy': mgc, 'per-task-oracle': ora,
                               'propensity_glm': float(e['glm_t'].mean())}
    return out


def agg(vals):
    a = np.asarray(vals, dtype=float)
    m = float(a.mean())
    ci = float(1.96 * a.std(ddof=1) / math.sqrt(len(a))) if len(a) > 1 else 0.0
    return m, ci


def aggregate(rep_results):
    reps = sorted(rep_results, key=lambda x: x['rep'])
    cfg_name = reps[0]['scenario']
    out = {'scenario': cfg_name, 'slug': reps[0]['slug'], 'N': len(reps),
           'P_Static_GLM': float(np.mean([r['bu'] == 0 for r in reps])), 'settings': {}}
    for setting in SETTINGS:
        ck = setting['name']
        arms = {}
        for arm in ('F-AR', 'MGC-proxy', 'per-task-oracle'):
            vals = [r['settings'][ck][arm] for r in reps]
            dq = [v['dq_mean'] for v in vals]
            net = [v['net_sum'] for v in vals]
            q = [v['q_mean'] for v in vals]
            cr = [v['cost_ratio'] for v in vals]
            mr = [v['mk_ratio'] for v in vals]
            m, ci = agg(dq); nm, nci = agg(net)
            arms[arm] = {
                'dq_mean': m, 'dq_ci95': [m - ci, m + ci],
                'net_sum_mean': nm, 'net_ci95': [nm - nci, nm + nci],
                'q_mean': float(np.mean(q)),
                'cost_ratio': float(np.mean(cr)), 'mk_ratio': float(np.mean(mr)),
                'GQ': float(np.mean([v['GQ'] for v in vals])),
                'GF': float(np.mean([v['GF'] for v in vals])),
                'GR_matched': float(np.mean([v['GR_matched'] for v in vals])),
                'GR_strict': float(np.mean([v['GR_strict'] for v in vals])),
                'JOINT_matched': float(np.mean([v['JOINT_matched'] for v in vals])),
                'JOINT_strict': float(np.mean([v['JOINT_strict'] for v in vals])),
                'glm_share': float(np.mean([v['glm_share'] for v in vals])),
                'win': float(np.mean([v['win'] for v in vals])),
                'tie': float(np.mean([v['tie'] for v in vals])),
                'lose': float(np.mean([v['lose'] for v in vals])),
            }
        out['settings'][ck] = arms
    return out


def main():
    t0 = time.time()
    print('RQ2 F-AR pilot: 4 scenarios x 100 splits x 4 settings; zero API', flush=True)
    # stable .15/.20, mixed negative, H0 zero
    si_list = [1, 2, 3, 0]
    args = [(si, rep) for si in si_list for rep in range(REPS)]
    results = []
    workers = min(48, os.cpu_count() or 1)
    with mp.Pool(processes=workers) as pool:
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
        print(f'\n=== {cfg["name"]} N={a["N"]} P(Static=GLM)={a["P_Static_GLM"]:.2f}', flush=True)
        for setting in SETTINGS:
            ck = setting['name']; c = a['settings'][ck]
            print(f' cap {ck} (cap={setting["cap"]}, deadline={setting["deadline"]}, tokens<={setting["max_tokens"]})', flush=True)
            for arm in ('MGC-proxy', 'F-AR', 'per-task-oracle'):
                d = c[arm]
                print(f'   {arm:18s} dQ={d["dq_mean"]:+.4f} Q={d["q_mean"]:.4f} net={d["net_sum_mean"]:+.2f} '
                      f'GQ={d["GQ"]:.2f} GF={d["GF"]:.2f} GRm={d["GR_matched"]:.2f} GRs={d["GR_strict"]:.2f} '
                      f'Jm={d["JOINT_matched"]:.2f} Js={d["JOINT_strict"]:.2f} '
                      f'cost={d["cost_ratio"]:.3f} mk={d["mk_ratio"]:.3f} glm={d["glm_share"]:.2f}', flush=True)
    with open(os.path.join(OUT, 'RQ2_FAR_PILOT.json'), 'w') as f:
        json.dump(final, f, indent=1)
    np.savez_compressed(os.path.join(OUT, 'RQ2_FAR_PILOT.npz'),
                        **{f'{k}__{ck}__{arm}__{m}': np.array([r['settings'][ck][arm][m] for r in by[final[k]['slug']]])
                           for k in final for ck in [s['name'] for s in SETTINGS]
                           for arm in ('F-AR', 'MGC-proxy', 'per-task-oracle')
                           for m in ('dq_mean', 'q_mean', 'net_sum')})
    print(f'\nTOTAL {time.time()-t0:.0f}s; zero API', flush=True)


if __name__ == '__main__':
    try:
        mp.set_start_method('fork', force=True)
    except RuntimeError:
        pass
    main()
