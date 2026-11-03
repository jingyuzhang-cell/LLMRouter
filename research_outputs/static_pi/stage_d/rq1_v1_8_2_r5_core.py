#!/usr/bin/env python3
"""R5 core: frozen-mechanism evaluator, fast port, 128-assignment enumeration.

Frozen inputs are imported from R4 (rq1_v1_8_2_r4_p0_calibration.py, untouched):
  NODES/TYPES/GLM_T, FACT_PARENTS, CRIT, UNK_FACT, DEC, RATES, PRICE/LAT/BASE_LAT,
  make_tasks/make_u, makespan, exact_p, base_p, score, run_task.
The fast port is validated bit-for-bit against R4 run_task/score before use.
Zero real model/API calls.
"""
import numpy as np, math, time
from rq1_v1_8_2_r4_p0_calibration import (
    NODES, TYPES, GLM_T, FACT_PARENTS, CRIT, UNK_FACT, DEC, RATES, PRICE, LAT,
    BASE_LAT, FP_RATE, make_tasks, make_u, makespan, exact_p, base_p, score, run_task,
)

DEC_N = len(DEC)  # 13 decidable slots
MVS = 1.0 / DEC_N
ALL_MASKS = list(range(128))


def mask_to_assign(mask):
    return np.array([(mask >> ni) & 1 for ni in range(7)], dtype=int)


def assign_to_mask(a):
    return int(sum(int(a[ni]) << ni for ni in range(7)))


def glm_nodes(mask):
    return [NODES[ni] for ni in range(7) if ((mask >> ni) & 1) == 0]


def prep(task, delta, up, extra_parse, pure_null):
    """Precompute everything task/model-invariant for the fast port."""
    R = {k: (np.array([v.mean()] * 2) if pure_null else v) for k, v in RATES.items()}
    U = task['U']
    P = {
        'parse': U['parse'].tolist(),
        'contract': U['contract'].tolist(),
        'fact': U['fact'].tolist(),  # [ni][fi][u0,u1,uunk,uloc,usup]
        'Rparse': R['parse'].tolist(), 'Rcontract': R['contract'].tolist(),
        'Rloc': R['loc'].tolist(), 'Rsup': R['sup'].tolist(), 'Runk': R['unk'].tolist(),
        'extra': float(extra_parse), 'up': float(up),
        'base': [[0.0] * 7 for _ in range(2)],
        'sign': float(task['sign']), 'eff': float(task['eff']),
        'feat': np.asarray(task['feat'], dtype=float),
    }
    for m in (0, 1):
        for ni in range(7):
            if m == 0:
                adv = delta if ni in GLM_T else -delta / 3.0
            else:
                adv = delta if ni in (0, 1, 2) else -delta / 3.0
            P['base'][m][ni] = max(0.03, min(0.97, 0.62 + adv * P['sign'] + P['eff']))
    return P


def prep_all(tasks, delta, up=1.0, extra_parse=0.0, pure_null=False):
    return [prep(t, delta, up, extra_parse, pure_null) for t in tasks]


def run_fast(P, assign):
    """Exact port of R4 run_task (validated in equivalence test)."""
    U = P['fact']
    out = [[2, 2] for _ in range(7)]
    loc = [[False, False] for _ in range(7)]
    sup = [[False, False] for _ in range(7)]
    exec_ok = [False] * 7
    RP, RC = P['Rparse'], P['Rcontract']
    extra, up, base = P['extra'], P['up'], P['base']
    Rloc, Rsup, Runk = P['Rloc'], P['Rsup'], P['Runk']
    for ni in range(7):
        m = int(assign[ni])
        if not (P['parse'][ni] <= RP[m] - extra and P['contract'][ni] <= RC[m]):
            continue
        exec_ok[ni] = True
        b = base[m][ni]
        for fi in (0, 1):
            if ni == 6 and fi == 1:
                out[6][1] = 3 if U[6][1][2] <= Runk[m] else 1
                continue
            cons = FACT_PARENTS[ni][fi]
            if cons:
                q = sum(1 for pn, pf in cons if out[pn][pf] == 0) / float(len(cons))
            else:
                q = 1.0
            q = q * up
            if q < 0.0:
                q = 0.0
            elif q > 1.0:
                q = 1.0
            pp = b * (0.35 + 0.65 * q)
            if ni == 5:
                pp = pp + 0.30 * (1.0 - q) * (1.0 - b)
            if pp < 0.02:
                pp = 0.02
            elif pp > 0.98:
                pp = 0.98
            u0, u1, _, u3, u4 = U[ni][fi]
            if u0 <= pp:
                out[ni][fi] = 0
            elif u1 < FP_RATE:
                out[ni][fi] = 1
            else:
                out[ni][fi] = 2
            if out[ni][fi] == 0 or out[ni][fi] == 1:
                loc[ni][fi] = u3 <= Rloc[m]
                sup[ni][fi] = u4 <= Rsup[m]
    return out, loc, sup, exec_ok


def score_full(out, loc, sup, exec_ok):
    gate = exec_ok[6]
    term = 0.0
    local = 0.0
    ctp = cfp = cfn = 0
    tp = fp = fn = 0
    loc_all = sup_all = 0.0
    n_cond = 0
    loc_cond = sup_cond = 0.0
    for n, f in DEC:
        o = out[n][f]
        if o == 0:
            local += 1.0
            tp += 1
            if loc[n][f]:
                loc_all += 1.0
            if sup[n][f]:
                sup_all += 1.0
            if loc[n][f] and sup[n][f] and gate:
                term += 1.0
        elif o == 1:
            fp += 1
        else:
            fn += 1
        if o == 0 or o == 1:
            n_cond += 1
            if loc[n][f]:
                loc_cond += 1.0
            if sup[n][f]:
                sup_cond += 1.0
    for n, f in CRIT:
        o = out[n][f]
        if o == 0 and loc[n][f] and sup[n][f]:
            ctp += 1
        elif o == 1:
            cfp += 1
        elif o == 2:
            cfn += 1
    unk = 1 if out[UNK_FACT[0]][UNK_FACT[1]] == 3 else 0
    return {
        'term': term / float(DEC_N), 'local': local / float(DEC_N),
        'ctp': ctp, 'cfp': cfp, 'cfn': cfn, 'unk': unk,
        'tp': tp, 'fp': fp, 'fn': fn,
        'loc_all': loc_all / float(DEC_N), 'sup_all': sup_all / float(DEC_N),
        'loc_cond': (loc_cond / n_cond) if n_cond else 0.0,
        'sup_cond': (sup_cond / n_cond) if n_cond else 0.0,
        'n_cond': n_cond,
    }


def parse_contract_rates(P, assign):
    RP, RC = P['Rparse'], P['Rcontract']
    extra = P['extra']
    ps = [1.0 if (P['parse'][ni] <= RP[int(assign[ni])] - extra and
                 P['contract'][ni] <= RC[int(assign[ni])]) else 0.0 for ni in range(7)]
    cs = [1.0 if P['contract'][ni] <= RC[int(assign[ni])] else 0.0 for ni in range(7)]
    return float(np.mean(ps)), float(np.mean(cs))


def assignment_cost(assign):
    return float(np.mean(PRICE[np.asarray(assign, dtype=int)]))


def eval_assignment(prepped, assign, store_tasks=False):
    assign = np.asarray(assign, dtype=int)
    n = len(prepped)
    term = np.empty(n)
    local = np.empty(n)
    ctp = np.empty(n, dtype=int)
    cfp = np.empty(n, dtype=int)
    cfn = np.empty(n, dtype=int)
    unk = np.empty(n, dtype=int)
    tp = np.empty(n, dtype=int)
    fp = np.empty(n, dtype=int)
    fn = np.empty(n, dtype=int)
    loc_all = np.empty(n)
    sup_all = np.empty(n)
    loc_cond = np.empty(n)
    sup_cond = np.empty(n)
    parse = np.empty(n)
    contract = np.empty(n)
    for i, P in enumerate(prepped):
        out, lo, su, eok = run_fast(P, assign)
        s = score_full(out, lo, su, eok)
        term[i] = s['term']; local[i] = s['local']
        ctp[i] = s['ctp']; cfp[i] = s['cfp']; cfn[i] = s['cfn']; unk[i] = s['unk']
        tp[i] = s['tp']; fp[i] = s['fp']; fn[i] = s['fn']
        loc_all[i] = s['loc_all']; sup_all[i] = s['sup_all']
        loc_cond[i] = s['loc_cond']; sup_cond[i] = s['sup_cond']
        parse[i], contract[i] = parse_contract_rates(P, assign)
    agg = {
        'term': float(term.mean()), 'local': float(local.mean()),
        'ctp': float(ctp.mean()), 'cfp': float(cfp.mean()), 'cfn': float(cfn.mean()),
        'unk': float(unk.mean()), 'tp': float(tp.mean()), 'fp': float(fp.mean()),
        'fn': float(fn.mean()), 'loc_all': float(loc_all.mean()),
        'sup_all': float(sup_all.mean()), 'loc_cond': float(loc_cond.mean()),
        'sup_cond': float(sup_cond.mean()),
        'cost': assignment_cost(assign), 'mk': float(makespan(assign)),
        'parse': float(parse.mean()), 'contract': float(contract.mean()),
        'glm_share': float(np.mean(assign == 0)),
        'mask': assign_to_mask(assign), 'glm_nodes': glm_nodes(assign_to_mask(assign)),
    }
    if store_tasks:
        agg.update({'term_t': term, 'ctp_t': ctp, 'cfp_t': cfp, 'local_t': local,
                    'cfn_t': cfn, 'unk_t': unk, 'tp_t': tp, 'fp_t': fp, 'fn_t': fn,
                    'parse_t': parse, 'contract_t': contract,
                    'cost_t': np.full(n, agg['cost']), 'mk_t': np.full(n, agg['mk']),
                    'glm_t': np.full(n, agg['glm_share'])})
    return agg


def critical_path(assign):
    """Zero-slack nodes on the longest path (assignment-level, deterministic)."""
    a = np.asarray(assign, dtype=int)
    lat = [BASE_LAT[i] * LAT[a[i]] for i in range(7)]
    F = [0.0] * 7
    F[0] = lat[0]; F[1] = lat[1]; F[2] = F[0] + lat[2]
    F[3] = max(F[0], F[1]) + lat[3]; F[4] = F[3] + lat[4]
    F[5] = max(F[3], F[2]) + lat[5]; F[6] = max(F[4], F[5]) + lat[6]
    M = F[6]
    LF = [0.0] * 7
    LF[6] = M; LF[5] = M - lat[6]; LF[4] = M - lat[6]
    LF[3] = min(LF[4] - lat[4], LF[5] - lat[5])
    LF[2] = LF[5] - lat[5]
    LF[1] = LF[3] - lat[3]
    LF[0] = min(LF[2] - lat[2], LF[3] - lat[3])
    ES = [0.0] * 7
    ES[0] = 0.0; ES[1] = 0.0; ES[2] = lat[0]
    ES[3] = max(lat[0], lat[1]); ES[4] = ES[3] + lat[3]
    ES[5] = max(F[3], F[2]); ES[6] = max(F[4], F[5])
    crit = [i for i in range(7) if abs(LF[i] - (ES[i] + lat[i])) < 1e-9]
    return {'makespan': M, 'critical': crit, 'slack': [LF[i] - (ES[i] + lat[i]) for i in range(7)],
            'lat': lat, 'LF': LF, 'ES': ES}


def enumerate_all(prepped, store_tasks=False):
    """All 128 assignments on the same task sample (CRN)."""
    rows = []
    for mask in ALL_MASKS:
        a = mask_to_assign(mask)
        r = eval_assignment(prepped, a, store_tasks=store_tasks)
        r['critical_nodes'] = critical_path(a)['critical']
        rows.append(r)
    return rows


def equivalence_check(verbose=True):
    """Bit-for-bit check of fast port vs R4 run_task/score on all 128 assignments."""
    cases = [
        ('stable .15', dict(delta=0.15, up=1.0, extra_parse=0.0, pure_null=False, sign_mode='stable')),
        ('mixed .15', dict(delta=0.15, up=1.0, extra_parse=0.0, pure_null=False, sign_mode='mixed')),
        ('up .85', dict(delta=0.15, up=0.85, extra_parse=0.0, pure_null=False, sign_mode='stable')),
        ('parse .10', dict(delta=0.15, up=1.0, extra_parse=0.10, pure_null=False, sign_mode='stable')),
        ('H0', dict(delta=0.0, up=1.0, extra_parse=0.0, pure_null=True, sign_mode='stable')),
    ]
    rng = np.random.default_rng(777)
    total = 0
    mism = []
    for name, cfg in cases:
        ts = make_tasks(16, seed=9000 + total, sign_mode=cfg['sign_mode'])
        make_u(ts, seed=9000 + total)
        total += 1
        for t in ts:
            P = prep(t, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
            for mask in ALL_MASKS:
                a = mask_to_assign(mask)
                o1, l1, s1, e1 = run_task(t, a, cfg['delta'], cfg['up'], cfg['extra_parse'],
                                          pure_null=cfg['pure_null'])
                o2, l2, s2, e2 = run_fast(P, a)
                if not (np.array_equal(o1, np.array(o2)) and np.array_equal(l1, np.array(l2))
                        and np.array_equal(s1, np.array(s2)) and np.array_equal(e1, np.array(e2))):
                    mism.append((name, t['id'], mask, 'outcomes'))
                    continue
                sc1 = score(o1, l1, s1, e1)
                sc2 = score_full(o2, l2, s2, e2)
                keys = ['local', 'term', 'ctp', 'cfp', 'cfn', 'unk']
                if any(abs(float(sc1[i]) - float(sc2[k])) > 1e-12 for i, k in enumerate(keys)):
                    mism.append((name, t['id'], mask, 'score'))
                if makespan(a) > 0 and abs(assignment_cost(a) - float(np.mean(PRICE[a]))) > 1e-12:
                    mism.append((name, t['id'], mask, 'cost'))
    ok = len(mism) == 0
    if verbose:
        print(f'equivalence: {"PASS" if ok else "FAIL"} cases={len(cases)} tasks={len(cases)*16} '
              f'assignments={len(cases)*16*128} mismatches={len(mism)}', flush=True)
        for m in mism[:10]:
            print('  MISMATCH', m, flush=True)
    return {'ok': ok, 'cases': len(cases), 'tasks': len(cases) * 16,
            'assignments': len(cases) * 16 * 128, 'mismatches': mism[:50]}


if __name__ == '__main__':
    t0 = time.time()
    eq = equivalence_check()
    # micro-benchmark: 2000 run_fast calls
    ts = make_tasks(8, seed=1234, sign_mode='stable'); make_u(ts, seed=1234)
    P = [prep(t, 0.15, 1.0, 0.0, False) for t in ts]
    t1 = time.time()
    for mask in range(128):
        for p in P:
            run_fast(p, mask_to_assign(mask))
    dt = time.time() - t1
    print(f'bench: 1024 run_fast in {dt:.3f}s -> {dt/1024*1000:.3f} ms/run', flush=True)
    print(f'total {time.time()-t0:.1f}s', flush=True)
