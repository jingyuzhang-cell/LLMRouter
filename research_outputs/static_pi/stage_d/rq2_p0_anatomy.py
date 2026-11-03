#!/usr/bin/env python3
"""RQ2 P0: terminal-Q anatomy and quality-loss upper bounds (zero API).

Uses stable .20 R5 eval tasks (800) and the frozen terminal scoring. Compares
Static, MGC (m / m+v), Node-Type, conservative V-CR. Reports:
  - TP/FP/FN/UNKNOWN, localization, support, report gate
  - exclusive loss categories (gate-first and gate-last)
  - perfect-repair upper bounds (fact / loc / sup / gate / combinations)
  - upstream q=1 counterfactual
  - node-level and fact-error cause breakdown
No scoring/Gold/DAG/task changes. Zero real model calls.
"""
import os, json, math, numpy as np
from rq1_v1_8_2_r5_core import (
    FACT_PARENTS, CRIT, UNK_FACT, DEC, PRICE, LAT, BASE_LAT, FP_RATE, MVS,
    prep_all, run_fast, score_full, mask_to_assign, enumerate_all,
)
from rq1_v1_8_2_r5_main import SCENARIOS, summarize
from rq2_v1_vcr import task_pool_vcr, repair_run, BASE_MASK, CONSERVATIVE, base_eval_full

OUT = os.path.dirname(os.path.abspath(__file__))
cfg = SCENARIOS[2]  # stable .20
N = 800
TASKS = task_pool_vcr(N, cfg['seed'] * 1000 + 501, cfg['sign_mode'])
PP = prep_all(TASKS, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
for P, T in zip(PP, TASKS):
    P['vcr'] = T['vcr']
STATIC_ASSIGN = mask_to_assign(127)
STATIC = base_eval_full(PP, STATIC_ASSIGN)
STATIC_Q = float(STATIC['term_t'].mean())
NODES = ['e0', 'e1', 't', 'm', 'r', 'v', 'p']


def slot_states(prepped, assign, vcr_params=None):
    out = np.full((len(prepped), 7, 2), 2, dtype=int)
    loc = np.zeros((len(prepped), 7, 2), dtype=bool)
    sup = np.zeros((len(prepped), 7, 2), dtype=bool)
    gate = np.zeros(len(prepped), dtype=bool)
    base_p = np.zeros((len(prepped), 7), dtype=float)
    qraw = np.zeros((len(prepped), 7), dtype=float)
    execs = np.zeros((len(prepped), 7), dtype=bool)
    tries = np.zeros(len(prepped), dtype=int)
    gate_rep = np.zeros(len(prepped), dtype=int)
    for i, P in enumerate(prepped):
        if vcr_params is None:
            o, l, s, e = run_fast(P, assign)
            out[i] = np.array(o); loc[i] = np.array(l); sup[i] = np.array(s)
            gate[i] = e[6]; execs[i] = e
        else:
            sc, cost, mk, a, g, o, l, s, e = repair_run(
                P, assign, STATIC, 0.20, 1.20, vcr_params, P['vcr'], return_states=True)
            out[i] = np.array(o); loc[i] = np.array(l); sup[i] = np.array(s)
            gate[i] = e[6]; execs[i] = e; tries[i] = a; gate_rep[i] = g
        for ni in range(7):
            base_p[i, ni] = P['base'][int(assign[ni])][ni]
            cons = FACT_PARENTS[ni]
            vals = []
            for fi in (0, 1):
                for pn, pf in cons.get(fi, []):
                    vals.append(out[i, pn, pf] == 0)
            qraw[i, ni] = 1.0 if not vals else float(np.mean(vals))
    return {'out': out, 'loc': loc, 'sup': sup, 'gate': gate, 'base_p': base_p,
            'qraw': qraw, 'exec': execs, 'tries': tries, 'gate_rep': gate_rep}


def anatomy(name, st):
    n = st['out'].shape[0]
    dec = list(DEC)
    out, loc, sup, gate = st['out'], st['loc'], st['sup'], st['gate']
    # per-slot pass (13 slots)
    passed = np.zeros((n, len(dec)), dtype=bool)
    for k, (ni, fi) in enumerate(dec):
        passed[:, k] = (out[:, ni, fi] == 0) & loc[:, ni, fi] & sup[:, ni, fi] & gate
    Q = float(passed.mean())
    # exclusive first-failure, gate first
    cat_gf = {k: 0 for k in ('pass', 'gate', 'fact_FP', 'fact_FN', 'loc', 'sup')}
    cat_gl = {k: 0 for k in ('pass', 'gate', 'fact_FP', 'fact_FN', 'loc', 'sup')}
    for k, (ni, fi) in enumerate(dec):
        for i in range(n):
            o = out[i, ni, fi]; g = gate[i]; l = loc[i, ni, fi]; s = sup[i, ni, fi]
            if not g:
                cat_gf['gate'] += 1
            elif o == 1:
                cat_gf['fact_FP'] += 1
            elif o == 2:
                cat_gf['fact_FN'] += 1
            elif not l:
                cat_gf['loc'] += 1
            elif not s:
                cat_gf['sup'] += 1
            else:
                cat_gf['pass'] += 1
            # gate last
            if o == 1:
                cat_gl['fact_FP'] += 1
            elif o == 2:
                cat_gl['fact_FN'] += 1
            elif not l:
                cat_gl['loc'] += 1
            elif not s:
                cat_gl['sup'] += 1
            elif not g:
                cat_gl['gate'] += 1
            else:
                cat_gl['pass'] += 1
    total = n * len(dec)
    cat_gf = {k: v / total for k, v in cat_gf.items()}
    cat_gl = {k: v / total for k, v in cat_gl.items()}
    # upper bounds: each slot's pass under perfect repair of selected components
    bounds = {}
    def q(cond):
        return float(np.mean([[cond(i, ni, fi) for (ni, fi) in dec] for i in range(n)]))
    bounds['fact_only'] = q(lambda i, ni, fi: loc[i, ni, fi] & sup[i, ni, fi] & gate[i])
    bounds['loc_only'] = q(lambda i, ni, fi: (out[i, ni, fi] == 0) & sup[i, ni, fi] & gate[i])
    bounds['sup_only'] = q(lambda i, ni, fi: (out[i, ni, fi] == 0) & loc[i, ni, fi] & gate[i])
    bounds['gate_only'] = q(lambda i, ni, fi: (out[i, ni, fi] == 0) & loc[i, ni, fi] & sup[i, ni, fi])
    bounds['fact_loc'] = q(lambda i, ni, fi: sup[i, ni, fi] & gate[i])
    bounds['fact_sup'] = q(lambda i, ni, fi: loc[i, ni, fi] & gate[i])
    bounds['loc_sup'] = q(lambda i, ni, fi: (out[i, ni, fi] == 0) & gate[i])
    bounds['fact_loc_sup'] = q(lambda i, ni, fi: gate[i])
    bounds['all'] = 1.0
    # counts
    dec_out = np.array([[out[i, ni, fi] for (ni, fi) in dec] for i in range(n)])
    tp = int(np.sum(dec_out == 0)); fp = int(np.sum(dec_out == 1)); fn = int(np.sum(dec_out == 2))
    unk = int(np.sum(out[:, 6, 1] == 3))
    gate_rate = float(gate.mean())
    # node table
    node_rows = []
    for ni in range(7):
        slots = [(ni, fi) for fi in (0, 1) if (ni, fi) in dec]
        k = len(slots)
        if k == 0:
            continue
        ps = np.mean([[out[i, ni, fi] == 0 and loc[i, ni, fi] and sup[i, ni, fi] and gate[i]
                       for (ni2, fi) in slots] for i in range(n)])
        t = np.mean([[out[i, ni, fi] == 0 for (ni2, fi) in slots] for i in range(n)])
        f = np.mean([[out[i, ni, fi] == 1 for (ni2, fi) in slots] for i in range(n)])
        m = np.mean([[out[i, ni, fi] == 2 for (ni2, fi) in slots] for i in range(n)])
        node_rows.append({'node': NODES[ni], 'slots': k, 'Q': float(ps),
                          'TP': float(t), 'FP': float(f), 'FN': float(m)})
    # fact-error causes among failed DEC slots
    causes = {'exec_fail': 0, 'base_low': 0, 'base_mid': 0, 'base_high': 0,
              'q_low': 0, 'q_high': 0}
    for k, (ni, fi) in enumerate(dec):
        for i in range(n):
            if out[i, ni, fi] == 0:
                continue
            if not st['exec'][i, ni]:
                causes['exec_fail'] += 1
            bp = st['base_p'][i, ni]
            if bp < 0.5:
                causes['base_low'] += 1
            elif bp < 0.7:
                causes['base_mid'] += 1
            else:
                causes['base_high'] += 1
            if st['qraw'][i, ni] < 0.8:
                causes['q_low'] += 1
            else:
                causes['q_high'] += 1
    return {'strategy': name, 'Q': Q, 'loss': 1.0 - Q,
            'slots': total, 'pass': int(passed.sum()),
            'TP': tp, 'FP': fp, 'FN': fn, 'UNKNOWN': unk,
            'gate_rate': gate_rate,
            'cat_gate_first': cat_gf, 'cat_gate_last': cat_gl,
            'bounds': bounds, 'node': node_rows, 'causes': causes,
            'attempts': float(st['tries'].mean()), 'gate_rep': float(st['gate_rep'].mean())}


def run_q1(P, assign):
    """Counterfactual perfect upstream: q=1 for every fact (no parent dependence)."""
    out = [[2, 2] for _ in range(7)]; loc = [[False, False] for _ in range(7)]
    sup = [[False, False] for _ in range(7)]; eok = [False] * 7
    for ni in range(7):
        m = int(assign[ni])
        if not (P['parse'][ni] <= P['Rparse'][m] - P['extra'] and
                P['contract'][ni] <= P['Rcontract'][m]):
            continue
        eok[ni] = True
        b = P['base'][m][ni]
        for fi in (0, 1):
            if ni == 6 and fi == 1:
                out[6][1] = 3 if P['fact'][6][1][2] <= P['Runk'][m] else 1
                continue
            q = 1.0
            pp = b * (0.35 + 0.65 * q)
            if ni == 5:
                pp = pp + 0.30 * (1 - q) * (1 - b)
            pp = max(0.02, min(0.98, pp))
            u0, u1, _, u3, u4 = P['fact'][ni][fi]
            out[ni][fi] = 0 if u0 <= pp else (1 if u1 < FP_RATE else 2)
            if out[ni][fi] in (0, 1):
                loc[ni][fi] = u3 <= P['Rloc'][m]
                sup[ni][fi] = u4 <= P['Rsup'][m]
    return score_full(out, loc, sup, eok)


def main():
    print('static Q check:', STATIC_Q, flush=True)
    strategies = {
        'Static': (mask_to_assign(127), None),
        'MGC-m': (mask_to_assign(119), None),
        'MGC-mv': (mask_to_assign(87), None),
        'Node-Type': (mask_to_assign(7), None),
        'V-CR-m': (mask_to_assign(119), CONSERVATIVE),
    }
    res = {}
    csv_rows = []
    for name, (assign, params) in strategies.items():
        print('running', name, flush=True)
        st = slot_states(PP, assign, params)
        a = anatomy(name, st)
        res[name] = a
        print(f"  Q={a['Q']:.4f} loss={a['loss']:.4f} TP/FP/FN={a['TP']}/{a['FP']}/{a['FN']} "
              f"gate={a['gate_rate']:.3f} attempts={a['attempts']:.2f}", flush=True)
        # per-slot CSV
        dec = list(DEC)
        for i in range(len(PP)):
            for k, (ni, fi) in enumerate(dec):
                csv_rows.append([name, TASKS[i]['id'], NODES[ni], fi, int(st['out'][i, ni, fi]),
                                 int(st['loc'][i, ni, fi]), int(st['sup'][i, ni, fi]),
                                 int(st['gate'][i]), int(st['out'][i, ni, fi] == 0 and
                                 st['loc'][i, ni, fi] and st['sup'][i, ni, fi] and st['gate'][i]),
                                 float(st['base_p'][i, ni]), float(st['qraw'][i, ni])])
    # upstream q=1 for static/MGC/NT (V-CR excluded: repair counterfactual differs)
    q1 = {}
    for name, (assign, params) in strategies.items():
        if params is not None:
            continue
        vals = [run_q1(P, assign)['term'] for P in PP]
        q1[name] = float(np.mean(vals))
    res['upstream_q1'] = q1
    # repair conversion stats for V-CR
    base_st = slot_states(PP, mask_to_assign(119), None)
    vcr_st = slot_states(PP, mask_to_assign(119), CONSERVATIVE)
    conversions = 0
    for i in range(len(PP)):
        for (ni, fi) in DEC:
            before = base_st['out'][i, ni, fi] == 0 and base_st['loc'][i, ni, fi] and base_st['sup'][i, ni, fi]
            after = vcr_st['out'][i, ni, fi] == 0 and vcr_st['loc'][i, ni, fi] and vcr_st['sup'][i, ni, fi]
            if not before and after:
                conversions += 1
    res['vcr_conversions'] = conversions
    with open(os.path.join(OUT, 'RQ2_P0_TERMINAL_ANATOMY.json'), 'w') as f:
        json.dump(res, f, indent=1)
    with open(os.path.join(OUT, 'RQ2_P0_SLOTS.csv'), 'w') as f:
        f.write('strategy,task,node,fact,out,loc,sup,gate,pass,base_p,parent_q\n')
        for r in csv_rows:
            f.write(','.join(str(x) for x in r) + '\n')
    print('\n=== summary ===', flush=True)
    for name in strategies:
        a = res[name]
        print(f"{name:10s} Q={a['Q']:.4f} loss={a['loss']:.4f} "
              f"catGF={a['cat_gate_first']} catGL={a['cat_gate_last']}", flush=True)
        print('  bounds', {k: round(v, 4) for k, v in a['bounds'].items()}, flush=True)
        print('  node', [(x['node'], round(x['Q'], 3)) for x in a['node']], flush=True)
        print('  causes', a['causes'], flush=True)
    print('upstream_q1', q1, 'vcr_conversions', conversions, flush=True)


if __name__ == '__main__':
    main()
