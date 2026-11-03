#!/usr/bin/env python3
"""JFR-P1 attribution: instrument D-mode repair on the exact pilot tasks.
Measures (zero new mechanism, zero API):
  - stage outcomes: fact recovery, localization, support (given fact ok), joint
  - deficit-state distribution per node; empirical vs naive-product joint rate
  - conversion yield per attempt by node; false-positive wasted attempts
  - missed bad facts on un-attempted nodes (sens gap + budget skips)
  - required joint success to reach 70%; shared-evidence multi-fact potential (P2 input)
Consistency: aggregate Q must equal pilot D (57.27% stable / 50.96% H0).
"""
import os, json, numpy as np
from rq1_v1_8_2_r5_core import DEC, prep_all, run_fast, score_full, assignment_cost, mask_to_assign
from rq1_v1_8_2_r5_main import SCENARIOS
from rq2_v1_vcr import task_pool_vcr, base_eval_full, makespan_extra
from rq2_jfr_p1 import (PRIORITY, SENS, SPEC, P_FACT, P_LOC, P_SUP, P_GATE,
                        MODECFG, attach_jfr, node_bad)

OUT = os.path.dirname(os.path.abspath(__file__))
BASE = mask_to_assign(127)
NODES = ['e0','e1','t','m','r','v','p']


def instrument_D(P, static, cap, deadline):
    out, loc, sup, eok = run_fast(P, BASE)
    cost = assignment_cost(BASE); extra = np.zeros(7)
    d = P['jfr']
    recs = []
    attempted_nodes = []
    for ni in PRIORITY:
        bad = node_bad(out, loc, sup, ni, eok)
        flagged = (d['flag'][ni] < SENS) if bad else (d['flag'][ni] > SPEC)
        if not flagged:
            continue
        c, l = MODECFG['D']
        nc = cost + c / 7.0
        ne = extra.copy(); ne[ni] += l
        nm = makespan_extra(BASE, ne)
        if nc > static['cost'] * (1 + cap) + 1e-12 or nm > static['mk'] * deadline + 1e-12:
            recs.append({'node': ni, 'fp': not bad, 'skipped': True})
            continue
        cost = nc; extra = ne
        attempted_nodes.append(ni)
        for fi in (0, 1):
            if (ni, fi) not in DEC:
                continue
            fb = out[ni][fi] != 0
            lb = not loc[ni][fi]
            sb = not sup[ni][fi]
            was_bad = fb or lb or sb
            fact_ok = (not fb) or (d['fact'][ni, fi] < P_FACT)
            loc_ok = (not lb) or (d['loc'][ni, fi] < P_LOC)
            sup_ok = (not sb) or (d['sup'][ni, fi] < P_SUP)
            joint = fact_ok and loc_ok and sup_ok
            conv = was_bad and joint
            if joint:
                out[ni][fi] = 0; loc[ni][fi] = True; sup[ni][fi] = True
            recs.append({'node': ni, 'fact': fi, 'fp': not bad, 'skipped': False,
                         'fb': fb, 'lb': lb, 'sb': sb, 'was_bad': was_bad,
                         'fact_ok': fact_ok, 'loc_ok': loc_ok, 'sup_ok': sup_ok,
                         'joint': joint, 'conv': conv})
        if ni == 6 and not eok[6] and d['gate'] < P_GATE:
            eok[6] = True
    s = score_full(out, loc, sup, eok)
    # un-attempted bad facts (missed by sens or budget) AFTER repairs
    missed = []
    for ni in range(7):
        if ni in attempted_nodes:
            continue
        for fi in (0, 1):
            if (ni, fi) in DEC and not (out[ni][fi] == 0 and loc[ni][fi] and sup[ni][fi]):
                missed.append((ni, fi))
    # shared-evidence potential: facts that are TP but loc/sup broken after repairs
    ev_recoverable = []
    for ni in range(7):
        for fi in (0, 1):
            if (ni, fi) in DEC and out[ni][fi] == 0 and not (loc[ni][fi] and sup[ni][fi]):
                ev_recoverable.append((ni, fi))
    return {'Q': s['term'], 'recs': recs, 'missed': missed,
            'ev_recoverable': ev_recoverable, 'attempts': len(attempted_nodes),
            'cost_ratio': cost / static['cost']}


def analyze(tasks, prepped, static, cap, deadline, label):
    n = len(prepped)
    Qs = []; all_recs = []; missed_all = []; ev_all = []; atts = []
    for P in prepped:
        r = instrument_D(P, static, cap, deadline)
        Qs.append(r['Q']); all_recs += r['recs']; missed_all += r['missed']
        ev_all += r['ev_recoverable']; atts.append(r['attempts'])
    Q = float(np.mean(Qs))
    fact_recs = [r for r in all_recs if not r.get('skipped') and 'fact' in r]
    bad = [r for r in fact_recs if r['was_bad'] and not r['fp']]
    # stage success among bad attempted facts
    fact_rate = float(np.mean([r['fact_ok'] for r in bad]))
    loc_rate = float(np.mean([r['loc_ok'] for r in bad]))
    sup_rate = float(np.mean([r['sup_ok'] for r in bad]))
    sup_given_fact = float(np.mean([r['sup_ok'] for r in bad if r['fact_ok']]))
    joint_rate = float(np.mean([r['joint'] for r in bad]))
    naive = P_FACT * P_LOC * P_SUP
    # deficit classes
    classes = {}
    for r in bad:
        k = (int(r['fb']), int(r['lb']), int(r['sb']))
        c = classes.setdefault(k, {'n': 0, 'joint': 0})
        c['n'] += 1; c['joint'] += int(r['joint'])
    for k, c in classes.items():
        c['rate'] = c['joint'] / c['n']
    # per node
    node_tab = {}
    for ni in range(7):
        rb = [r for r in bad if r['node'] == ni]
        att = [r for r in all_recs if r.get('skipped') is False and r['node'] == ni and 'fact' not in r]
        conv = sum(r['conv'] for r in rb)
        node_tab[NODES[ni]] = {
            'bad_facts': len(rb), 'conversions': int(conv),
            'yield_per_fact': (conv / len(rb)) if rb else None,
            'joint_rate': (sum(r['joint'] for r in rb) / len(rb)) if rb else None,
            'fn_share': (float(np.mean([r['fb'] for r in rb])) if rb else None)}
    fp_attempts = sum(1 for r in all_recs if r.get('skipped') is False and r.get('fp') and 'fact' not in r)
    skipped_fp = sum(1 for r in all_recs if r.get('skipped') and r.get('fp'))
    skipped_tp = sum(1 for r in all_recs if r.get('skipped') and not r.get('fp'))
    convs = sum(1 for r in bad if r['conv'])
    # needed conversions for 70%
    base_Q = float(static['term'])
    needed = (0.70 - base_Q) * 13 * n
    # shared-evidence potential (P2 input): per node facts TP but evidence broken
    ev_by_node = {}
    for (ni, fi) in ev_all:
        ev_by_node.setdefault(NODES[ni], 0)
        ev_by_node[NODES[ni]] += 1
    multi_ev_tasks = int(np.mean([sum(1 for (ni, fi) in r['ev_recoverable']
                                      if True) for r in [x for x in [{'ev_recoverable': ev_all[i*13:(i+1)*13]} for i in range(1)]]]) if False else 0)
    return {
        'label': label, 'N': n, 'Q': Q, 'base_Q': base_Q,
        'attempts_per_task': float(np.mean(atts)),
        'attempted_bad_facts': len(bad), 'conversions': int(convs),
        'conversions_per_task': convs / float(n),
        'stage_rates': {'fact': fact_rate, 'loc': loc_rate, 'sup': sup_rate,
                        'sup_given_fact': sup_given_fact, 'joint': joint_rate,
                        'naive_product': naive},
        'deficit_classes': {str(k): v for k, v in classes.items()},
        'node_table': node_tab,
        'false_positive_attempts': fp_attempts, 'skipped_flagged': {'fp': skipped_fp, 'true': skipped_tp},
        'missed_bad_facts_per_task': len(missed_all) / float(n),
        'ev_recoverable_per_task': len(ev_all) / float(n),
        'ev_recoverable_by_node': ev_by_node,
        'needed_conversions_for_70_per_task': needed / n / 13 * 13 / n,  # per task
        'needed_total': needed / n,
        'records': [r for r in all_recs if not r.get('skipped')][:0],  # keep light
    }


def main():
    cfg = SCENARIOS[2]; h0 = SCENARIOS[0]
    ts_s = task_pool_vcr(800, cfg['seed'] * 1000 + 501, cfg['sign_mode'])[:200]
    ts_h = task_pool_vcr(800, h0['seed'] * 1000 + 501, h0['sign_mode'])[:200]
    attach_jfr(ts_s, cfg['seed'] * 1000 + 501)
    attach_jfr(ts_h, h0['seed'] * 1000 + 501)
    PS = prep_all(ts_s, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    PH = prep_all(ts_h, h0['delta'], h0['up'], h0['extra_parse'], h0['pure_null'])
    for P, T in zip(PS, ts_s): P['jfr'] = T['jfr']
    for P, T in zip(PH, ts_h): P['jfr'] = T['jfr']
    st_s = base_eval_full(PS, BASE); st_h = base_eval_full(PH, BASE)
    res = {'stable_20m': analyze(ts_s, PS, st_s, 0.20, 1.20, 'stable .20 20m'),
           'H0_20m': analyze(ts_h, PH, st_h, 0.20, 1.20, 'H0 20m')}
    # consistency vs pilot
    pilot = json.load(open(os.path.join(OUT, 'JFR_P1_PILOT.json')))
    res['consistency'] = {
        'pilot_D_stable_20m': pilot['stable']['20m']['D']['Q'],
        'here_stable_20m': res['stable_20m']['Q'],
        'pilot_D_H0_20m': pilot['H0']['20m']['D']['Q'],
        'here_H0_20m': res['H0_20m']['Q']}
    json.dump(res, open(os.path.join(OUT, 'JFR_P1_ATTRIBUTION.json'), 'w'), indent=1)
    for k in ('stable_20m', 'H0_20m'):
        r = res[k]
        print(f'\n=== {r["label"]}: Q={r["Q"]:.4f} base={r["base_Q"]:.4f} '
              f'attempts/task={r["attempts_per_task"]:.2f} conv/task={r["conversions_per_task"]:.2f}', flush=True)
        sr = r['stage_rates']
        print(f'  stage: fact={sr["fact"]:.3f} loc={sr["loc"]:.3f} sup={sr["sup"]:.3f} '
              f'sup|fact={sr["sup_given_fact"]:.3f} joint={sr["joint"]:.3f} naive={sr["naive_product"]:.3f}', flush=True)
        print('  deficit classes (fb,lb,sb): n, joint-rate:', flush=True)
        for k2, v in sorted(r['deficit_classes'].items(), key=lambda x: -x[1]['n']):
            print(f'    {k2}: n={v["n"]} rate={v["rate"]:.3f}', flush=True)
        print('  node table:', flush=True)
        for nd, v in r['node_table'].items():
            if v['bad_facts'] == 0:
                continue
            print(f'    {nd}: bad={v["bad_facts"]} conv={v["conversions"]} '
                  f'yield={v["yield_per_fact"]:.3f} joint={v["joint_rate"]:.3f} FNshare={v["fn_share"]:.2f}', flush=True)
        print(f'  FP attempts={r["false_positive_attempts"]} skipped(flagged)={r["skipped_flagged"]} '
              f'missed bad facts/task={r["missed_bad_facts_per_task"]:.2f} '
              f'ev-recoverable/task={r["ev_recoverable_per_task"]:.2f}', flush=True)
        print(f'  ev by node {r["ev_recoverable_by_node"]}', flush=True)
        print(f'  needed conv/task for 70% = {r["needed_total"]:.2f}', flush=True)
    print('\nconsistency', res['consistency'], flush=True)


if __name__ == '__main__':
    main()
