#!/usr/bin/env python3
"""RQ2_P2R_V2 scoring/analysis (ZERO API calls).

Reads V1 A records (reused) and V2 B/C records, scores V1.5 Gold,
computes paired B-A and C-B, cost/latency, dedup stats, and writes a
stratified V-1 human-labeling sample. No mechanism, no real calls.
"""
import json, re, unicodedata, statistics, itertools, random, collections
from pathlib import Path

HERE = Path(__file__).parent
V1 = HERE / 'rq2_p2r_runs'
V2 = HERE / 'rq2_p2r_v2_runs'
FACTS = json.load(open(HERE / 'rq1_tasks' / 'facts_E05_E08.json'))
MATS = json.load(open(HERE / 'rq1_tasks' / 'rq1_tasks_materials.json'))
TASKS = ['E05', 'E06', 'E07', 'E08']
GOLD = {t: [g for g in FACTS.values() if g['fact_id'].startswith('F-' + t + '-')]
        for t in TASKS}


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


def chosen_ok(x):
    """Parse success of the adopted output (reroll adopted iff facts non-empty)."""
    if 'chosen' not in x:
        return True
    if x['chosen'].get('rerolled'):
        return len(x['chosen'].get('facts', [])) > 0
    return not x.get('signals', {}).get('exec')


def load_records(path, arms):
    out = {}
    for arm in arms:
        for p in sorted(Path(path).glob(f'{arm}__*.json')):
            d = json.load(open(p))
            out[(arm, d['task'], d['rep'])] = d
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
    gs = GOLD[rec['task']]
    tp = sup = 0
    bad = []
    matched = []
    for g in gs:
        ms = [f for f in facts_all if match(g, f)]
        if not ms:
            continue
        tp += 1
        matched.extend(ms)
        if any(first.get(tup(f), False) for f in ms):
            sup += 1
        else:
            bad.append(g['fact_id'])
    # terminal gate: the ADOPTED report output must parse; a successful reroll counts.
    report_ok = any(x.get('kind') == 'report' and 'chosen' in x and chosen_ok(x)
                    for x in rec['nodes'])
    tp_eff = tp if report_ok else 0
    sup_eff = sup if report_ok else 0
    if not report_ok:
        bad.append('REPORT_GATE')
    return dict(n=len(gs), tp=tp_eff, sup=sup_eff,
                tp_raw=tp, sup_raw=sup, report_ok=report_ok, bad=bad,
                q_main=tp_eff / len(gs),
                q_main_raw=tp / len(gs),
                q_full=(sup_eff / len(gs) if rec['arm'] in ('B', 'C') else None),
                q_full_raw=(sup / len(gs) if rec['arm'] in ('B', 'C') else None),
                unique_all=len({tup(f) for f in facts_all if f.get('quote')}),
                unique_report=len({tup(f) for f in facts_report if f.get('quote')}),
                unique_tp=len({tup(f) for f in matched if f.get('quote')}))


def summarize(arm, recs):
    by_task, by_rep = {}, {}
    tp = n = sup = tp_raw = sup_raw = 0
    ua = ur = ut = 0
    for (a, task, rep), rec in sorted(recs.items()):
        if a != arm:
            continue
        s = score(rec)
        by_rep[f'{task}|r{rep}'] = dict(s, arm=arm, task=task, rep=rep)
        d = by_task.setdefault(task, dict(n=0, tp=0, sup=0, tp_raw=0, sup_raw=0,
                                         report_fail=0, uniq_all=0, reps=0,
                                         rep_scores=[]))
        d['n'] += s['n']; d['tp'] += s['tp']; d['sup'] += s['sup']
        d['tp_raw'] += s['tp_raw']; d['sup_raw'] += s['sup_raw']
        d['report_fail'] += int(not s['report_ok'])
        d['uniq_all'] += s['unique_all']; d['reps'] += 1
        d['rep_scores'].append(s)
        tp += s['tp']; n += s['n']; sup += s['sup']
        tp_raw += s['tp_raw']; sup_raw += s['sup_raw']
        ua += s['unique_all']; ur += s['unique_report']; ut += s['unique_tp']
    for d in by_task.values():
        d['q_main'] = round(d['tp'] / d['n'], 4)
        d['q_full'] = round(d['sup'] / d['n'], 4) if arm in ('B', 'C') else None
        d['q_main_raw'] = round(d['tp_raw'] / d['n'], 4)
        d['q_full_raw'] = (round(d['sup_raw'] / d['n'], 4)
                           if arm in ('B', 'C') else None)
        cond = [x for x in d['rep_scores'] if x['report_ok']]
        d['gate_rate'] = round((d['reps'] - d['report_fail']) / d['reps'], 4)
        d['q_main_cond'] = round(statistics.mean(
            x['q_main_raw'] for x in cond), 4) if cond else None
        d['q_full_cond'] = round(statistics.mean(
            x['q_full_raw'] for x in cond), 4) if (cond and arm in ('B', 'C')) else None
        d.pop('rep_scores', None)
    return dict(by_task=by_task, by_rep=by_rep,
                mean_task_q_main=round(statistics.mean(
                    v['q_main'] for v in by_task.values()), 4) if by_task else None,
                mean_task_q_full=round(statistics.mean(
                    v['q_full'] for v in by_task.values()), 4)
                if (by_task and arm in ('B', 'C')) else None,
                mean_task_q_main_raw=round(statistics.mean(
                    v['q_main_raw'] for v in by_task.values()), 4) if by_task else None,
                mean_task_gate_rate=round(statistics.mean(
                    v['gate_rate'] for v in by_task.values()), 4) if by_task else None,
                mean_task_q_main_cond=round(statistics.mean(
                    v['q_main_cond'] for v in by_task.values()), 4)
                if (by_task and all(v['q_main_cond'] is not None
                                    for v in by_task.values())) else None,
                mean_task_q_full_raw=round(statistics.mean(
                    v['q_full_raw'] for v in by_task.values()), 4)
                if (by_task and arm in ('B', 'C')) else None,
                mean_task_q_full_cond=round(statistics.mean(
                    v['q_full_cond'] for v in by_task.values()), 4)
                if (by_task and arm in ('B', 'C')
                    and all(v['q_full_cond'] is not None
                            for v in by_task.values())) else None,
                pooled_q_main=round(tp / n, 4) if n else None,
                pooled_q_full=round(sup / n, 4) if (n and arm in ('B', 'C')) else None,
                pooled_q_main_raw=round(tp_raw / n, 4) if n else None,
                pooled_q_full_raw=round(sup_raw / n, 4)
                if (n and arm in ('B', 'C')) else None,
                n=n, tp=tp, sup=sup, tp_raw=tp_raw, sup_raw=sup_raw,
                unique_all=ua, unique_report=ur, unique_tp=ut,
                n_execs=len(by_rep), n_tasks=len(by_task))


def task_means(summary):
    return {t: v['q_main'] for t, v in summary['by_task'].items()}


def paired_task(sa, sb, rep_of_a, rep_of_b, label):
    """Pair task-level means over common task×rep cells."""
    out = []
    for task in TASKS:
        common = sorted(set(rep_of_a.get(task, {})) & set(rep_of_b.get(task, {})))
        if not common:
            continue
        va = statistics.mean(rep_of_a[task][r] for r in common)
        vb = statistics.mean(rep_of_b[task][r] for r in common)
        out.append(dict(task=task, n_reps=len(common), a=round(va, 4), b=round(vb, 4),
                        delta_pp=round((vb - va) * 100, 2)))
    ds = [x['delta_pp'] for x in out]
    if not ds:
        return dict(label=label, tasks=out, n_tasks=0)
    obs = statistics.mean(ds)
    # exact sign-flip (two-sided); n=4 -> min p=0.125
    cnt = tot = 0
    for signs in itertools.product([1, -1], repeat=len(ds)):
        tot += 1
        if abs(statistics.mean([d * s for d, s in zip(ds, signs)])) >= abs(obs) - 1e-12:
            cnt += 1
    # cluster bootstrap by task (resample tasks, then reps)
    rng = random.Random(20261103)
    boot = []
    for _ in range(5000):
        pick = [rng.choice(out) for _ in out]
        vals = []
        for p in pick:
            task = p['task']
            common = sorted(set(rep_of_a.get(task, {})) & set(rep_of_b.get(task, {})))
            if not common:
                continue
            va = statistics.mean(rep_of_a[task][r] for r in common)
            vb = statistics.mean(rep_of_b[task][r] for r in common)
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


def rep_map(summary, field='q_main'):
    out = collections.defaultdict(dict)
    for k, v in summary['by_rep'].items():
        task, rep = k.split('|')
        out[task][int(rep[1:])] = v[field]
    return out


def load_ledger(path):
    p = Path(path) / 'ledger.jsonl'
    return [json.loads(l) for l in open(p)] if p.exists() else []


def exec_costs(ledger):
    ex = collections.defaultdict(list)
    for r in ledger:
        ex[(r['arm'], r['task'], r['rep'])].append(r)
    out = {}
    for k, rs in ex.items():
        out[k] = dict(calls=len(rs),
                      span_s=round(max(x['ts'] + x['lat'] for x in rs) -
                                   min(x['ts'] for x in rs), 1),
                      sum_lat_s=round(sum(x['lat'] for x in rs), 1),
                      tokens=sum(x['in'] + x['out'] for x in rs),
                      yuan=round(sum(x['yuan'] for x in rs), 4),
                      roles=dict(collections.Counter(x['role'] for x in rs)))
    return out


def arm_cost(execs, arm):
    vals = [v for (a, t, r), v in execs.items() if a == arm]
    return dict(execs=len(vals),
                calls=sum(v['calls'] for v in vals),
                tokens=sum(v['tokens'] for v in vals),
                yuan=round(sum(v['yuan'] for v in vals), 4),
                mean_span_s=round(statistics.mean(v['span_s'] for v in vals), 1)
                if vals else None,
                median_span_s=round(statistics.median(v['span_s'] for v in vals), 1)
                if vals else None)


def dedup_stats(recs, arm):
    u = v = reu = cap = 0
    for (a, t, r), rec in recs.items():
        if a != arm:
            continue
        d = rec.get('dedup', {})
        u += d.get('unique', 0); v += d.get('verify_calls', 0)
        reu += d.get('reused', 0); cap += d.get('cap_hits', 0)
    total = v + reu + cap
    return dict(execs=sum(1 for (a, t, r) in recs if a == arm),
                verify_calls=v, unique=u, reused=reu, cap_hits=cap,
                cited_facts=total,
                reuse_rate=round(reu / total, 4) if total else None)


def anomaly_stats(recs):
    out = collections.defaultdict(lambda: collections.Counter())
    for (arm, task, rep), rec in recs.items():
        for x in rec['nodes']:
            if 'chosen' not in x:
                continue
            s = x.get('signals', {})
            out[arm]['base_nodes'] += 1
            out[arm]['parse_fail'] += int(bool(s.get('exec')))
            out[arm]['base_parse_fail'] += int(bool(s.get('exec')))
            out[arm]['chosen_parse_fail'] += int(not chosen_ok(x))
            out[arm]['prod_missing'] += int(bool(s.get('prod')))
            out[arm]['cite_missing'] += int(bool(s.get('cite')))
            if x['chosen'].get('rerolled'):
                out[arm]['adopted'] += 1
    return {a: dict(c) for a, c in out.items()}


def silver_support(fact):
    """Diagnostic only: does quote contain the matched Gold evidence span?"""
    best = None
    for g in FACTS.values():
        if match(g, fact):
            if norm(g['evidence_span']) in norm(fact.get('quote', '')):
                best = True
            elif best is None:
                best = False
    return best


def v1_sample(recs, path, target=200):
    pairs = {}
    for (arm, task, rep), rec in recs.items():
        if arm not in ('B', 'C'):
            continue
        for x in rec['nodes']:
            if 'chosen' not in x:
                continue
            for v in x.get('verifies', []):
                k = tup(v['fact'])
                d = pairs.setdefault(k, dict(
                    fact=v['fact'], supported=bool(v['supported']),
                    tasks=set(), arms=set(), sources=[], verdicts=set()))
                d['tasks'].add(task); d['arms'].add(arm)
                d['sources'].append(f'{arm}|{task}|r{rep}')
                d['verdicts'].add(bool(v['supported']))
                # dedup: first verdict wins; keep it
    groups = collections.defaultdict(list)
    for k, d in pairs.items():
        key = (sorted(d['tasks'])[0], sorted(d['arms'])[0], d['supported'])
        groups[key].append((k, d))
    rng = random.Random(20261103)
    for key in groups:
        rng.shuffle(groups[key])
    picked = []
    idx = 0
    # round-robin across strata
    while len(picked) < min(target, len(pairs)):
        any_added = False
        for key in sorted(groups):
            if idx < len(groups[key]) and len(picked) < min(target, len(pairs)):
                picked.append(groups[key][idx])
                any_added = True
        if not any_added:
            break
        idx += 1
    rows = []
    for i, (k, d) in enumerate(picked, 1):
        f = d['fact']
        rows.append(dict(
            pair_id=f'V2-{i:03d}', task=sorted(d['tasks'])[0],
            arm=sorted(d['arms'])[0], fid=f.get('fid', ''), value=f.get('value', ''),
            doc=f.get('doc', ''), quote=f.get('quote', ''),
            verifier_supported=d['supported'],
            verifier_verdicts=sorted(d['verdicts']),
            silver_support=silver_support(f),
            source_execs=sorted(set(d['sources'])),
            human_label=None))
    with open(path, 'w') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    return dict(path=str(path), unique_pairs=len(pairs), sampled=len(rows),
                human_labeled=0,
                note='V-1 human labels pending; sample stratified by task x arm x verifier verdict.')


def verifier_stats(recs):
    out = {}
    for arm in ('B', 'C'):
        occ = sup_occ = 0
        uniq, sup_uniq = set(), set()
        for (a, t, r), rec in recs.items():
            if a != arm:
                continue
            for x in rec['nodes']:
                if 'chosen' not in x:
                    continue
                for v in x.get('verifies', []):
                    k = tup(v['fact'])
                    occ += 1
                    uniq.add(k)
                    if v['supported']:
                        sup_occ += 1
                        sup_uniq.add(k)
        out[arm] = dict(occurrences=occ, supported_occurrences=sup_occ,
                        unique=len(uniq), supported_unique=len(sup_uniq),
                        support_rate_occ=round(sup_occ / occ, 4) if occ else None,
                        support_rate_unique=round(len(sup_uniq) / len(uniq), 4)
                        if uniq else None)
    return out


def diagnostics(recs):
    out = {}
    for arm in ('B', 'C'):
        rep_fail = rep_fail_len = 0
        by_kind = collections.Counter()
        by_model = collections.Counter()
        for (a, t, r), rec in recs.items():
            if a != arm:
                continue
            rep = [x for x in rec['nodes'] if 'chosen' in x and x['kind'] == 'report']
            if rep and not chosen_ok(rep[0]):
                rep_fail += 1
                if any(x.get('node') == 'report'
                       and x.get('stop') in ('length', 'max_tokens')
                       for x in rec['nodes'] if 'role' in x):
                    rep_fail_len += 1
            for x in rec['nodes']:
                if 'chosen' not in x:
                    continue
                if not chosen_ok(x):
                    by_kind[x['kind']] += 1
                    by_model[str(x['chosen'].get('model', '?'))] += 1
        out[arm] = dict(report_gate_fail=rep_fail,
                        report_gate_fail_with_length=rep_fail_len,
                        parse_fail_by_kind=dict(by_kind),
                        parse_fail_by_model=dict(by_model))
    return out

def main():
    A = load_records(V1, ['A'])
    BC = load_records(V2, ['B', 'C'])
    B = {k: v for k, v in BC.items() if k[0] == 'B'}
    C = {k: v for k, v in BC.items() if k[0] == 'C'}
    sa, sb, sc = summarize('A', A), summarize('B', B), summarize('C', C)
    ra, rb, rc = rep_map(sa), rep_map(sb), rep_map(sc)
    rar, rbr, rcr = (rep_map(sa, 'q_main_raw'), rep_map(sb, 'q_main_raw'),
                     rep_map(sc, 'q_main_raw'))
    paired_ba = paired_task(sa, sb, ra, rb, 'B_minus_A')
    paired_cb = paired_task(sb, sc, rb, rc, 'C_minus_B')
    paired_ca = paired_task(sa, sc, ra, rc, 'C_minus_A')
    paired_ba_raw = paired_task(sa, sb, rar, rbr, 'B_minus_A_raw')
    paired_cb_raw = paired_task(sb, sc, rbr, rcr, 'C_minus_B_raw')
    paired_ca_raw = paired_task(sa, sc, rar, rcr, 'C_minus_A_raw')

    led_a = load_ledger(V1)
    led_bc = load_ledger(V2)
    ex_a = exec_costs(led_a)
    ex_bc = exec_costs(led_bc)
    cost = dict(A=arm_cost(ex_a, 'A'), B=arm_cost(ex_bc, 'B'),
                C=arm_cost(ex_bc, 'C'))
    # cost/latency deltas at arm level (descriptive)
    def delta(k1, k2):
        a, b = cost[k1], cost[k2]
        return {k: (round(b[k] - a[k], 4) if isinstance(a[k], (int, float)) else None)
                for k in ('calls', 'tokens', 'yuan', 'mean_span_s')}
    cost['C_minus_B'] = delta('B', 'C')
    cost['B_minus_A'] = delta('A', 'B')
    cost['C_minus_A'] = delta('A', 'C')

    dedup = dict(B=dedup_stats(B, 'B'), C=dedup_stats(C, 'C'))
    anomalies = anomaly_stats(BC)
    # A anomalies from V1 records (for reference)
    anomalies['A'] = anomaly_stats(A).get('A', {})
    diag = diagnostics(BC)
    vs = verifier_stats(BC)
    v1 = v1_sample(BC, HERE / 'RQ2_P2R_V2_V1_SAMPLE.jsonl')

    out = dict(
        batch='RQ2_P2R_V2', status='completed' if len(B) == 12 and len(C) == 12 else 'partial',
        counts=dict(A=len(A), B=len(B), C=len(C),
                    ledger_calls_v1=len(led_a), ledger_calls_v2=len(led_bc)),
        q=dict(A=sa, B=sb, C=sc, paired=dict(
            B_minus_A=paired_ba, C_minus_B=paired_cb, C_minus_A=paired_ca,
            B_minus_A_raw=paired_ba_raw, C_minus_B_raw=paired_cb_raw,
            C_minus_A_raw=paired_ca_raw)),
        cost_latency=cost, dedup=dedup, anomalies=anomalies,
        diagnostics=diag, verify_support=vs,
        v1_sample=v1,
        budget=json.load(open(V2 / 'state' / 'GLOBAL_BUDGET.json'))
        if (V2 / 'state' / 'GLOBAL_BUDGET.json').exists() else None,
    )
    json.dump(out, open(HERE / 'RQ2_P2R_V2_RESULTS.json', 'w'),
              ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in ('counts', 'q', 'cost_latency',
                                          'dedup', 'anomalies', 'v1_sample')},
                     ensure_ascii=False, indent=1)[:16000])


if __name__ == '__main__':
    main()
