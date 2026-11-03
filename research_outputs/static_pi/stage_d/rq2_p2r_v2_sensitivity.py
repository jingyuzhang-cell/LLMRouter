#!/usr/bin/env python3
"""RQ2_P2R_V2 sensitivity: UNKNOWN-slot and critical-only Q (ZERO API calls).

Primary remains all V1.5 Gold fact slots (consistent with the V1 interim scorer).
This script only checks whether the C-B / B-A signs depend on UNKNOWN handling.
"""
import json, statistics, itertools, random, collections
from pathlib import Path
import rq2_p2r_v2_analyze as M

HERE = Path(__file__).parent
A = M.load_records(M.V1, ['A'])
BC = M.load_records(M.V2, ['B', 'C'])
B = {k: v for k, v in BC.items() if k[0] == 'B'}
C = {k: v for k, v in BC.items() if k[0] == 'C'}


def score_variant(rec, mode):
    gs = [g for g in M.GOLD[rec['task']]
          if not (mode == 'no_unknown' and g['value_match_rule'] == 'unknown')
          and not (mode == 'critical' and not g['critical'])]
    facts_all = []
    first = {}
    for x in rec['nodes']:
        if 'chosen' not in x:
            continue
        for f in x['chosen'].get('facts', []):
            if isinstance(f, dict):
                facts_all.append(f)
        for v in x.get('verifies', []):
            first.setdefault(M.tup(v['fact']), bool(v['supported']))
    report_ok = any(x.get('kind') == 'report' and 'chosen' in x and M.chosen_ok(x)
                    for x in rec['nodes'])
    tp = sup = 0
    for g in gs:
        ms = [f for f in facts_all if M.match(g, f)]
        if not ms:
            continue
        tp += 1
        if any(first.get(M.tup(f), False) for f in ms):
            sup += 1
    if not report_ok:
        tp = sup = 0
    return dict(n=len(gs), tp=tp, sup=sup, q_main=tp / len(gs) if gs else None,
                q_full=sup / len(gs) if (gs and rec['arm'] in ('B', 'C')) else None)


def summarize(recs, arm, mode):
    by_task = collections.defaultdict(lambda: dict(n=0, tp=0, sup=0, reps=0))
    by_rep = collections.defaultdict(dict)
    for (a, task, rep), rec in recs.items():
        if a != arm:
            continue
        s = score_variant(rec, mode)
        d = by_task[task]
        d['n'] += s['n']; d['tp'] += s['tp']; d['sup'] += s['sup']; d['reps'] += 1
        by_rep[task][rep] = s['q_main']
    for d in by_task.values():
        d['q_main'] = round(d['tp'] / d['n'], 4) if d['n'] else None
        d['q_full'] = (round(d['sup'] / d['n'], 4)
                       if (d['n'] and arm in ('B', 'C')) else None)
    return dict(by_task=dict(by_task), by_rep=dict(by_rep),
                mean_q_main=round(statistics.mean(
                    d['q_main'] for d in by_task.values()), 4) if by_task else None,
                mean_q_full=(round(statistics.mean(
                    d['q_full'] for d in by_task.values()), 4)
                    if (by_task and arm in ('B', 'C')) else None))


def paired(a, b, label):
    out = []
    for task in M.TASKS:
        common = sorted(set(a['by_rep'].get(task, {})) & set(b['by_rep'].get(task, {})))
        if not common:
            continue
        va = statistics.mean(a['by_rep'][task][r] for r in common)
        vb = statistics.mean(b['by_rep'][task][r] for r in common)
        out.append(dict(task=task, n_reps=len(common),
                        a=round(va, 4), b=round(vb, 4),
                        delta_pp=round((vb - va) * 100, 2)))
    ds = [x['delta_pp'] for x in out]
    if not ds:
        return dict(label=label, tasks=out, n_tasks=0)
    obs = statistics.mean(ds)
    cnt = tot = 0
    for signs in itertools.product([1, -1], repeat=len(ds)):
        tot += 1
        if abs(statistics.mean([d * s for d, s in zip(ds, signs)])) >= abs(obs) - 1e-12:
            cnt += 1
    rng = random.Random(20261103)
    boot = []
    for _ in range(5000):
        pick = [rng.choice(out) for _ in out]
        vals = []
        for p in pick:
            task = p['task']
            common = sorted(set(a['by_rep'].get(task, {})) & set(b['by_rep'].get(task, {})))
            va = statistics.mean(a['by_rep'][task][r] for r in common)
            vb = statistics.mean(b['by_rep'][task][r] for r in common)
            vals.append((vb - va) * 100)
        boot.append(statistics.mean(vals))
    boot.sort()
    return dict(label=label, tasks=out, n_tasks=len(out),
                mean_delta_pp=round(obs, 2),
                sd_pp=round(statistics.stdev(ds), 2) if len(ds) > 1 else None,
                se_pp=round(statistics.stdev(ds) / len(ds) ** 0.5, 2)
                if len(ds) > 1 else None,
                signflip_p=round(cnt / tot, 4),
                cluster_bootstrap_ci95=[round(boot[int(0.025 * len(boot))], 2),
                                        round(boot[int(0.975 * len(boot)) - 1], 2)])


out = {}
for mode in ('all', 'no_unknown', 'critical'):
    sa = summarize(A, 'A', mode)
    sb = summarize(B, 'B', mode)
    sc = summarize(C, 'C', mode)
    out[mode] = dict(
        A=sa, B=sb, C=sc,
        paired=dict(B_minus_A=paired(sa, sb, 'B_minus_A'),
                    C_minus_B=paired(sb, sc, 'C_minus_B'),
                    C_minus_A=paired(sa, sc, 'C_minus_A')))
json.dump(out, open(HERE / 'RQ2_P2R_V2_SENSITIVITY.json', 'w'),
          ensure_ascii=False, indent=1)
for mode in out:
    print('\nMODE', mode)
    for arm in ('A', 'B', 'C'):
        print(' ', arm, 'meanQ', out[mode][arm]['mean_q_main'],
              'meanQfull', out[mode][arm]['mean_q_full'],
              'tasks', {t: v['q_main'] for t, v in out[mode][arm]['by_task'].items()})
    for k in ('B_minus_A', 'C_minus_B', 'C_minus_A'):
        p = out[mode]['paired'][k]
        print(' ', k, 'mean', p['mean_delta_pp'], 'p', p['signflip_p'],
              'ci', p['cluster_bootstrap_ci95'],
              'task_deltas', {x['task']: x['delta_pp'] for x in p['tasks']})
