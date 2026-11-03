#!/usr/bin/env python3
"""JFR-P1 pilot: joint fact-evidence repair, five ablations, H0/Sham, realistic costs.
Frozen protocol in JFR_P1_PROTOCOL.md / JFR_P1_PARAMS.json. Zero API.
"""
import os, json, math, numpy as np
from rq1_v1_8_2_r5_core import (FACT_PARENTS, CRIT, UNK_FACT, DEC, PRICE, LAT, BASE_LAT,
    FP_RATE, prep_all, run_fast, score_full, assignment_cost, makespan, mask_to_assign)
from rq1_v1_8_2_r5_main import SCENARIOS, summarize
from rq2_v1_vcr import task_pool_vcr, base_eval_full, makespan_extra

OUT = os.path.dirname(os.path.abspath(__file__))
PRIORITY = [4, 2, 6, 3, 5, 0, 1]
MODECFG = {'B': (0.10, 0.08), 'C': (0.15, 0.10), 'D': (0.25, 0.12), 'E': (0.30, 0.15)}
SENS, SPEC, SHAM_RATE = 0.75, 0.85, 0.30
P_FACT, P_LOC, P_SUP, P_GATE = 0.70, 0.70, 0.70, 0.70
BASE = mask_to_assign(127)


def attach_jfr(tasks, seed):
    rng = np.random.default_rng(seed + 888)
    for t in tasks:
        t['jfr'] = {'flag': rng.random(7), 'sham': rng.random(7),
                    'fact': rng.random((7, 2)), 'loc': rng.random((7, 2)),
                    'sup': rng.random((7, 2)), 'gate': rng.random()}


def node_bad(out, loc, sup, ni, eok):
    for fi in (0, 1):
        if (ni, fi) in DEC and not (out[ni][fi] == 0 and loc[ni][fi] and sup[ni][fi]):
            return True
    if ni == 6 and not eok[6]:
        return True
    return False


def commit_joint(out, loc, sup, ni, fi, d):
    # mechanism gate: all three must succeed; no partial writeback
    was_bad = not (out[ni][fi] == 0 and loc[ni][fi] and sup[ni][fi])
    fact_ok = (out[ni][fi] == 0) or (d['fact'][ni, fi] < P_FACT)
    loc_ok = loc[ni][fi] or (d['loc'][ni, fi] < P_LOC)
    sup_ok = sup[ni][fi] or (d['sup'][ni, fi] < P_SUP)
    if fact_ok and loc_ok and sup_ok:
        out[ni][fi] = 0; loc[ni][fi] = True; sup[ni][fi] = True
        return 1 if was_bad else 0
    return 0


def jfr_run(P, mode, static, cap, deadline, sham=False):
    out, loc, sup, eok = run_fast(P, BASE)
    base_pass = {(ni, fi): (out[ni][fi] == 0 and loc[ni][fi] and sup[ni][fi])
                 for (ni, fi) in DEC}
    cost = assignment_cost(BASE); extra = np.zeros(7)
    attempts = 0; committed = 0; skipped = 0; gate_rep = 0
    d = P['jfr']
    for ni in PRIORITY:
        bad = node_bad(out, loc, sup, ni, eok)
        if sham:
            flagged = d['sham'][ni] < SHAM_RATE
        elif bad:
            flagged = d['flag'][ni] < SENS
        else:
            flagged = d['flag'][ni] > SPEC  # 1 - spec false positive
        if not flagged:
            continue
        c, l = MODECFG[mode]
        nc = cost + c / 7.0
        ne = extra.copy(); ne[ni] += l
        nm = makespan_extra(BASE, ne)
        if nc > static['cost'] * (1 + cap) + 1e-12 or nm > static['mk'] * deadline + 1e-12:
            skipped += 1
            continue
        attempts += 1; cost = nc; extra = ne
        if sham:
            continue
        for fi in (0, 1):
            if (ni, fi) not in DEC:
                continue
            badf = not (out[ni][fi] == 0 and loc[ni][fi] and sup[ni][fi])
            if mode == 'B':
                if badf and d['fact'][ni, fi] < P_FACT:
                    out[ni][fi] = 0
            elif mode == 'C':
                if out[ni][fi] == 0:
                    if not loc[ni][fi] and d['loc'][ni, fi] < P_LOC:
                        loc[ni][fi] = True
                    if not sup[ni][fi] and d['sup'][ni, fi] < P_SUP:
                        sup[ni][fi] = True
            else:  # D/E
                committed += commit_joint(out, loc, sup, ni, fi, d)
        if mode in ('D', 'E') and ni == 6 and not eok[6]:
            if d['gate'] < P_GATE:
                eok[6] = True; gate_rep += 1
    # E: one upstream parent recovery attempt (extra cost/latency)
    if mode == 'E' and attempts > 0 and not sham:
        for pn in (3, 2, 0, 1):
            bad = node_bad(out, loc, sup, pn, eok)
            if not bad:
                continue
            c, l = MODECFG['E']
            nc = cost + c / 7.0
            ne = extra.copy(); ne[pn] += l
            nm = makespan_extra(BASE, ne)
            if nc > static['cost'] * (1 + cap) + 1e-12 or nm > static['mk'] * deadline + 1e-12:
                skipped += 1; break
            attempts += 1; cost = nc; extra = ne
            for fi in (0, 1):
                if (pn, fi) in DEC:
                    committed += commit_joint(out, loc, sup, pn, fi, d)
            break
    s = score_full(out, loc, sup, eok)
    conv = sum(1 for (ni, fi) in DEC if (out[ni][fi] == 0 and loc[ni][fi] and sup[ni][fi]) and not base_pass[(ni, fi)])
    return {'Q': s['term'], 'cost': cost, 'mk': makespan_extra(BASE, extra),
            'attempts': attempts, 'committed': committed, 'conversions': conv,
            'skipped': skipped, 'gate_rep': gate_rep}


def run_mode(PP, mode, static, cap, deadline, sham=False):
    q = []; cost = []; mk = []; att = []; com = []; conv = []; skip = []; gr = []
    for P in PP:
        r = jfr_run(P, mode, static, cap, deadline, sham)
        q.append(r['Q']); cost.append(r['cost']); mk.append(r['mk'])
        att.append(r['attempts']); com.append(r['committed']); conv.append(r['conversions']); skip.append(r['skipped']); gr.append(r['gate_rep'])
    q = np.array(q)
    return {'Q': float(q.mean()), 'q': q, 'cost_ratio': float(np.mean(np.array(cost) / static['cost'])),
            'mk_ratio': float(np.mean(np.array(mk) / static['mk'])),
            'attempts': float(np.mean(att)), 'committed': float(np.mean(com)),
            'conversions': float(np.mean(conv)), 'skipped': float(np.mean(skip)),
            'gate_rep': float(np.mean(gr))}


def bootstrap_q(q, ns=3000, nt=24):
    rng = np.random.default_rng(12345)
    vals = np.array([rng.choice(q, nt, replace=False).mean() for _ in range(ns)])
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def main():
    # stable .20 and H0: use R5 800-task eval sets, first 200 for pilot
    cfg = SCENARIOS[2]; h0 = SCENARIOS[0]
    ts_s = task_pool_vcr(800, cfg['seed'] * 1000 + 501, cfg['sign_mode'])[:200]
    ts_h = task_pool_vcr(800, h0['seed'] * 1000 + 501, h0['sign_mode'])[:200]
    attach_jfr(ts_s, cfg['seed'] * 1000 + 501)
    attach_jfr(ts_h, h0['seed'] * 1000 + 501)
    PS = prep_all(ts_s, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    PH = prep_all(ts_h, h0['delta'], h0['up'], h0['extra_parse'], h0['pure_null'])
    for P, T in zip(PS, ts_s): P['jfr'] = T['jfr']
    for P, T in zip(PH, ts_h): P['jfr'] = T['jfr']
    static_s = base_eval_full(PS, BASE); static_h = base_eval_full(PH, BASE)
    print('stable base DS Q', static_s['term'], 'H0 base DS Q', static_h['term'], flush=True)
    settings = [('20m', 0.20, 1.20), ('20s', 0.20, 1.10), ('15', 0.15, 1.10), ('10', 0.10, 1.10)]
    res = {'stable': {}, 'H0': {}, 'sham': {}, 'base': {'stable': float(static_s['term']), 'H0': float(static_h['term'])},
           'A_VCR': {'20m': 0.5716, '20s': 0.5419, '15': 0.5419, '10': 0.4995}}
    for ck, cap, dl in settings:
        res['stable'][ck] = {}; res['H0'][ck] = {}; res['sham'][ck] = {}
        for mode in ('B', 'C', 'D', 'E'):
            r = run_mode(PS, mode, static_s, cap, dl, sham=False)
            lo, hi = bootstrap_q(r['q'])
            r['ci95'] = [lo, hi]
            res['stable'][ck][mode] = {k: r[k] for k in ('Q', 'ci95', 'cost_ratio', 'mk_ratio', 'attempts', 'committed', 'conversions', 'skipped', 'gate_rep')}
            h = run_mode(PH, mode, static_h, cap, dl, sham=False)
            hlo, hhi = bootstrap_q(h['q'])
            res['H0'][ck][mode] = {k: h[k] for k in ('Q', 'cost_ratio', 'mk_ratio', 'attempts', 'committed', 'conversions')}
            res['H0'][ck][mode]['ci95'] = [hlo, hhi]
            sh = run_mode(PS, mode, static_s, cap, dl, sham=True)
            res['sham'][ck][mode] = {'Q': sh['Q'], 'cost_ratio': sh['cost_ratio'],
                                     'mk_ratio': sh['mk_ratio'], 'attempts': sh['attempts']}
            print(f'{ck:3s} {mode}: stable Q={r["Q"]:.4f} CI[{lo:.4f},{hi:.4f}] '
                  f'cost={r["cost_ratio"]:.3f} mk={r["mk_ratio"]:.3f} att={r["attempts"]:.2f} '
                  f'conv={r["conversions"]:.2f} skip={r["skipped"]:.2f} | H0 Q={h["Q"]:.4f} | '
                  f'shamQ={sh["Q"]:.4f}', flush=True)
    # gates
    gates = {}
    for ck, _, _ in settings:
        d = res['stable'][ck]['D']; h = res['H0'][ck]['D']; sh = res['sham'][ck]['D']
        gates[ck] = {
            'quality_Q': bool(d['Q'] >= 0.70 and d['ci95'][0] > 0.70),
            'attribution': bool((d['Q'] - res['base']['stable']) - (h['Q'] - res['base']['H0']) >= 0.05),
            'sham': bool(abs(sh['Q'] - res['base']['stable']) <= 0.005),
            'resource': bool(d['cost_ratio'] <= {'20m': 1.20, '20s': 1.20, '15': 1.15, '10': 1.10}[ck] + 1e-9 and
                             d['mk_ratio'] <= {'20m': 1.20, '20s': 1.10, '15': 1.10, '10': 1.10}[ck] + 1e-9),
        }
        gates[ck]['all'] = all(gates[ck].values())
        res['stable'][ck]['D']['delta_vs_base'] = d['Q'] - res['base']['stable']
        res['H0'][ck]['D']['delta_vs_base'] = h['Q'] - res['base']['H0']
        res['sham'][ck]['D']['delta_vs_base'] = sh['Q'] - res['base']['stable']
    res['gates'] = gates
    json.dump(res, open(os.path.join(OUT, 'JFR_P1_PILOT.json'), 'w'), indent=1)
    print('\nGATES', json.dumps(gates, indent=1), flush=True)
    print('pilot done; zero API', flush=True)


if __name__ == '__main__':
    main()
