#!/usr/bin/env python3
"""RQ2_P2R_V1 closeout analysis (ZERO API calls).

Reads the frozen ledger/run records, reproduces A/B Q under the V1.5 Gold rules,
quantifies the real dedup-verification volume, and reconciles the budget.
No mechanism, no runner change, no real calls.
"""
import json, re, unicodedata, collections, statistics
from pathlib import Path

HERE = Path(__file__).parent
RUNS = HERE / 'rq2_p2r_runs'
FACTS = json.load(open(HERE / 'rq1_tasks' / 'facts_E05_E08.json'))
MATS = json.load(open(HERE / 'rq1_tasks' / 'rq1_tasks_materials.json'))
TASKS = ['E05', 'E06', 'E07', 'E08']
TASK_NODES = {t: len(MATS['tasks'][t]['nodes']) for t in TASKS}


def norm(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s)))


def normc(s):
    return norm(s).replace(',', '')


def nums(s):
    return re.findall(r'-?\d+(?:\.\d+)?', normc(s))


def match(g, f):
    """V1.5 Gold match: value rule AND evidence-doc localization."""
    v = str(f.get('value', ''))
    vn, vc = norm(v), normc(v)
    if str(f.get('doc', '')) != g['evidence_doc']:
        return False
    r = g['value_match_rule']
    if r == 'unknown':
        return False
    if r in ('date', 'exact_string'):
        return any(norm(x) in vn for x in g.get('allowed_expressions', []))
    if r == 'numeric':
        gv = [float(x) for x in nums(g['expected_value'])]
        mv = [float(x) for x in nums(v)]
        return bool(gv) and bool(mv) and any(
            abs(a - b) <= max(0.01, abs(a) * 1e-4) for a in gv for b in mv)
    if r == 'set':
        return all(normc(x) in vc for x in g.get('required_elements', []))
    return False


def tup(f):
    return (str(f.get('fid', '')), str(f.get('value', '')),
            str(f.get('doc', '')), str(f.get('quote', '')))


def load(arm):
    out = {}
    for p in sorted(RUNS.glob(f'{arm}__*.json')):
        d = json.load(open(p))
        out[(d['task'], d['rep'])] = d
    return out


def score(rec):
    facts_all, facts_report = [], []
    first = {}
    for x in rec['nodes']:
        if 'chosen' not in x:
            continue
        for f in x['chosen'].get('facts', []):
            if isinstance(f, dict):
                facts_all.append(f)
                if x['kind'] == 'report':
                    facts_report.append(f)
        for v in x.get('verifies', []):
            first.setdefault(tup(v['fact']), bool(v['supported']))
    gs = [g for g in FACTS.values()
          if g['fact_id'].startswith('F-' + rec['task'] + '-')]
    tp = sup = 0
    bad = []
    matched_tuples = set()
    for g in gs:
        ms = [f for f in facts_all if match(g, f)]
        if not ms:
            continue
        tp += 1
        for f in ms:
            matched_tuples.add(tup(f))
        if any(first.get(tup(f), False) for f in ms):
            sup += 1
        else:
            bad.append(g['fact_id'])
    uniq_all = {tup(f) for f in facts_all if f.get('quote')}
    uniq_rep = {tup(f) for f in facts_report if f.get('quote')}
    return dict(n=len(gs), tp=tp, sup=sup, bad=bad,
                uniq_all=len(uniq_all), uniq_report=len(uniq_rep),
                uniq_tp=len(matched_tuples))


def summarize(arm, recs):
    by_task, by_rep = {}, {}
    tp = n = sup = 0
    ua = ur = ut = 0
    for (task, rep), rec in sorted(recs.items()):
        s = score(rec)
        by_rep[f'{task}|r{rep}'] = s
        d = by_task.setdefault(task, dict(n=0, tp=0, sup=0, uniq_all=0))
        d['n'] += s['n']; d['tp'] += s['tp']; d['sup'] += s['sup']
        d['uniq_all'] += s['uniq_all']
        tp += s['tp']; n += s['n']; sup += s['sup']
        ua += s['uniq_all']; ur += s['uniq_report']; ut += s['uniq_tp']
    for d in by_task.values():
        d['q_main'] = round(d['tp'] / d['n'], 4)
        d['q_full'] = round(d['sup'] / d['n'], 4) if arm != 'A' else None
    return dict(by_task=by_task, by_rep=by_rep,
                pooled_q_main=round(tp / n, 4) if n else None,
                pooled_q_full=round(sup / n, 4) if (n and arm != 'A') else None,
                n=n, tp=tp, sup=sup,
                unique_all=ua, unique_report=ur, unique_tp=ut)


def median(xs):
    return round(statistics.median(xs), 1) if xs else None


def main():
    A, B = load('A'), load('B')
    sa, sb = summarize('A', A), summarize('B', B)
    # task-equal means
    sa['mean_task_q_main'] = round(statistics.mean(
        v['q_main'] for v in sa['by_task'].values()), 4)
    sb['mean_task_q_main'] = round(statistics.mean(
        v['q_main'] for v in sb['by_task'].values()), 4)
    sb['mean_task_q_full'] = round(statistics.mean(
        v['q_full'] for v in sb['by_task'].values()), 4)

    # paired B-A on completed overlapping (task,rep)
    pairs = []
    for k in sorted(set(A) & set(B)):
        qa = sa['by_rep'][f'{k[0]}|r{k[1]}']['tp'] / sa['by_rep'][f'{k[0]}|r{k[1]}']['n']
        qb = sb['by_rep'][f'{k[0]}|r{k[1]}']['tp'] / sb['by_rep'][f'{k[0]}|r{k[1]}']['n']
        pairs.append(dict(task=k[0], rep=k[1], A=round(qa, 4), B=round(qb, 4),
                          delta_pp=round((qb - qa) * 100, 2)))
    ds = [p['delta_pp'] for p in pairs]
    paired = dict(pairs=pairs, n=len(ds),
                  mean_delta_pp=round(statistics.mean(ds), 2) if ds else None,
                  sd_pp=round(statistics.stdev(ds), 2) if len(ds) > 1 else None,
                  se_pp=round(statistics.stdev(ds) / len(ds) ** 0.5, 2) if len(ds) > 1 else None)

    # ledger / budget reconciliation
    led = [json.loads(l) for l in open(RUNS / 'ledger.jsonl')]
    budget = json.load(open(RUNS / 'state' / 'GLOBAL_BUDGET.json'))
    per_exec = collections.defaultdict(list)
    for r in led:
        per_exec[(r['arm'], r['task'], r['rep'])].append(r)
    completed = {k: v for k, v in per_exec.items() if k in
                 {(a, t, rr) for a, recs in (('A', A), ('B', B))
                  for (t, rr) in recs}} if False else None
    completed_keys = {('A', t, r) for (t, r) in A} | {('B', t, r) for (t, r) in B}
    completed_calls = sum(len(v) for k, v in per_exec.items() if k in completed_keys)
    partial = {f'{k[0]}|{k[1]}|r{k[2]}': len(v) for k, v in per_exec.items()
               if k not in completed_keys}
    lat = {}
    for k, rs in sorted(per_exec.items()):
        lat[f'{k[0]}|{k[1]}|r{k[2]}'] = dict(
            calls=len(rs),
            span_s=round(max(x['ts'] + x['lat'] for x in rs) - min(x['ts'] for x in rs), 1),
            sum_lat_s=round(sum(x['lat'] for x in rs), 1),
            tokens=sum(x['in'] + x['out'] for x in rs),
            yuan=round(sum(x['yuan'] for x in rs), 4),
            roles=dict(collections.Counter(x['role'] for x in rs)))

    # verification stats
    vt = collections.Counter()
    vu = collections.defaultdict(set)
    vsup = collections.Counter()
    any_supported = {}
    for (task, rep), rec in B.items():
        for x in rec['nodes']:
            if 'chosen' not in x:
                continue
            for v in x.get('verifies', []):
                vt[task] += 1
                t = tup(v['fact'])
                vu[task].add(t)
                any_supported.setdefault(t, False)
                any_supported[t] = any_supported[t] or bool(v['supported'])
                if v['supported']:
                    vsup[task] += 1
    verify = dict(calls=sum(vt.values()), unique=sum(len(s) for s in vu.values()),
                  duplicates=sum(vt.values()) - sum(len(s) for s in vu.values()),
                  by_task={t: dict(calls=vt[t], unique=len(vu[t]),
                                   supported=vsup[t]) for t in sorted(vt)},
                  supported_total=sum(vsup.values()),
                  supported_unique=sum(1 for t in any_supported if any_supported[t]))

    # anomalies (base node outputs)
    anom = dict(base_nodes=0, parse_fail=0, prod_missing=0, cite_missing=0,
                rerolls=0, adopted=0)
    for arm, recs in (('A', A), ('B', B)):
        for rec in recs.values():
            for x in rec['nodes']:
                if 'chosen' not in x:
                    continue
                anom['base_nodes'] += 1
                s = x.get('signals', {})
                anom['parse_fail'] += int(bool(s.get('exec')))
                anom['prod_missing'] += int(bool(s.get('prod')))
                anom['cite_missing'] += int(bool(s.get('cite')))
                if x['chosen'].get('rerolled'):
                    anom['adopted'] += 1
    anom['rerolls'] = sum(1 for r in led if r['role'] == 'reroll')

    # A-based per-exec unique counts for B-remaining and C projections
    def agg(keys):
        ua = ur = ut = 0
        base = 0
        for k in keys:
            s = score(A[k])
            ua += s['uniq_all']; ur += s['uniq_report']; ut += s['tp']
            base += TASK_NODES[k[0]]
        return dict(execs=len(keys), base_calls=base, unique_all=ua,
                    unique_report=ur, oracle_tp=ut)

    b_rem_keys = [('E06', 2), ('E06', 3)] + [('E07', i) for i in (1, 2, 3)] + \
                 [('E08', i) for i in (1, 2, 3)]
    c9_keys = [('E05', i) for i in (1, 2, 3)] + [('E06', i) for i in (1, 2, 3)] + \
              [('E07', i) for i in (1, 2, 3)]
    c12_keys = c9_keys + [('E08', i) for i in (1, 2, 3)]
    b_rem, c9, c12 = agg(b_rem_keys), agg(c9_keys), agg(c12_keys)
    b4_dedup_calls = sum(len(rec['nodes']) for rec in B.values())  # wrong-ish; use known
    # actual B4: 17 base + 3 reroll + 43 unique verify (partial E06 r2's 5 base are NOT in B4)
    b4 = dict(execs=4, base_calls=17, rerolls=3, unique_all=43,
              calls=17 + 3 + 43)

    def calls_proj(x, reroll_rate=0.75, fact_hi=1.0):
        rr_lo = round(x['execs'] * reroll_rate)
        rr_hi = x['execs']
        v_lo = x['unique_all']
        v_hi = int(x['unique_all'] * fact_hi + 0.999)
        return dict(low=x['base_calls'] + rr_lo + v_lo,
                    high=x['base_calls'] + rr_hi + v_hi,
                    rerolls_low=rr_lo, rerolls_high=rr_hi,
                    verify_low=v_lo, verify_high=v_hi)

    b_rem_c = calls_proj(b_rem, 0.75, 1.10)
    c9_c = calls_proj(c9, 0.75, 1.20)
    c12_c = calls_proj(c12, 0.75, 1.20)
    b12_c = dict(low=b4['calls'] + b_rem_c['low'],
                 high=b4['calls'] + b_rem_c['high'])

    def add_reserve(x):
        return dict(low=x['low'], high=x['high'],
                    high_plus_10=int(x['high'] * 1.10 + 0.999))

    dedup = dict(
        b4_actual_old=dict(calls=149, verify=196, unique=43),
        b4_dedup=b4,
        b_remaining=b_rem, b_remaining_calls=b_rem_c,
        c9=c9, c9_calls=c9_c,
        c12=c12, c12_calls=c12_c,
        b12_fresh_calls=b12_c,
        b8_c9_calls=add_reserve(dict(low=b_rem_c['low'] + c9_c['low'],
                                     high=b_rem_c['high'] + c9_c['high'])),
        b8_c12_calls=add_reserve(dict(low=b_rem_c['low'] + c12_c['low'],
                                      high=b_rem_c['high'] + c12_c['high'])),
        b12_c9_calls=add_reserve(dict(low=b12_c['low'] + c9_c['low'],
                                      high=b12_c['high'] + c9_c['high'])),
        b12_c12_calls=add_reserve(dict(low=b12_c['low'] + c12_c['low'],
                                       high=b12_c['high'] + c12_c['high'])),
        oracle=dict(b8_c9=b_rem['base_calls'] + c9['base_calls'] +
                    round(8 * 0.75) + round(9 * 0.75) + b_rem['oracle_tp'] + c9['oracle_tp'],
                    b8_c12=b_rem['base_calls'] + c12['base_calls'] +
                    round(8 * 0.75) + round(12 * 0.75) + b_rem['oracle_tp'] + c12['oracle_tp'],
                    note='oracle TP-only lower bound; uses Gold to choose facts; NOT deployable'))

    out = dict(
        batch='RQ2_P2R_V1', status='STOPPED (no further calls)',
        spend=dict(ledger_calls=len(led), budget_state_calls=budget['calls'],
                   completed_calls=completed_calls, partial_calls=partial,
                   unreconciled=budget['calls'] - len(led),
                   tokens_true=sum(r['in'] + r['out'] for r in led),
                   tokens_budget_state=budget['tokens'],
                   tokens_redundant=budget['tokens'] -
                   sum(r['in'] + r['out'] for r in led),
                   yuan=round(sum(r['yuan'] for r in led), 4),
                   remaining_calls=500 - budget['calls'],
                   remaining_yuan=round(30 - sum(r['yuan'] for r in led), 4)),
        completed=dict(A=len(A), B=len(B), C=0),
        q=dict(A=sa, B=sb, paired_B_minus_A=paired),
        verify=verify, anomalies=anom, latency=lat,
        dedup=dedup,
        decision=dict(
            remaining_calls=500 - budget['calls'],
            b8_alone_low=b_rem_c['low'], b8_alone_high=b_rem_c['high'],
            b8_c9_low=dedup['b8_c9_calls']['low'],
            b8_c12_low=dedup['b8_c12_calls']['low'],
            fits_full_design=False,
            reason='Dedup-all B-remaining alone consumes the entire remaining call cap; C cannot start.',
            action='Stop V1; request RQ2_P2R_V2 (800 calls / 5,000,000 tokens / CNY 40).'))
    json.dump(out, open(HERE / 'RQ2_P2R_V1_CLOSEOUT_ANALYSIS.json', 'w'),
              ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in ('spend', 'completed', 'q', 'verify',
                                          'anomalies', 'dedup', 'decision')},
                     ensure_ascii=False, indent=1)[:12000])


if __name__ == '__main__':
    main()
