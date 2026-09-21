"""Decomposition benchmark scorer: offline, deterministic, no model calls.

Scores the three frozen arms per task, then reports:
  Table A  Mono-L vs DAG-L/L  (pure decomposition effect)
  Table B  DAG-L/L vs DAG-L/M (heterogeneous stage allocation)
  Complexity stratification on the Table-A pair (buckets 1-2 / 3 / 4+)
  Paired bootstrap CI (10k, seed 20260916) and exact McNemar per pair.
"""
import json
import re
import time
from math import comb
from pathlib import Path

import numpy as np

from . import core
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

ROOT = core.ROOT / 'static_dag_v0'
FSC = ROOT / 'fresh_static_confirmation'
TQB = ROOT / 'tatqa_benchmark'
SU = ROOT / 'scale_up'
BENCH = ROOT / 'decomposition_benchmark'
RUN = BENCH / 'paired_run'


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def extract_value(text):
    m = re.findall(r'Answer:\s*(-?[\d,]+(?:\.\d+)?)', text or '') or \
        re.findall(r'(-?[\d,]+(?:\.\d+)?)\s*$', (text or '').strip())
    if not m:
        return None
    try:
        return float(m[-1].replace(',', ''))
    except ValueError:
        return None


def tq_n_ops(derivation):
    d = (derivation or '').strip()
    return len(re.findall(r'[+*/]', d)) + len(re.findall(r'(?<=[\d)])\s*-', d))


def mh_n_ops(program):
    return len(re.findall(r'\b(add|sub|mul|div)\b', program or ''))


def bucket(n):
    return '1-2' if n <= 2 else ('3' if n == 3 else '4+')


def mcnemar_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    p_obs = comb(n, b) * 0.5 ** n
    p = 0.0
    for k in range(n + 1):
        pk = comb(n, k) * 0.5 ** n
        if pk <= p_obs + 1e-12:
            p += pk
    return min(1.0, p)


def paired_ci(diffs, seed=20260916, iters=10000):
    diffs = np.array(diffs)
    rng = np.random.default_rng(seed)
    means = [rng.choice(diffs, len(diffs)).mean() for _ in range(iters)]
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def load_tasks():
    mh_freeze = json.loads((BENCH / 'decomposition_final_multihiertt_100.json').read_text())
    tq_freeze = json.loads((BENCH / 'decomposition_final_tatqa_200.json').read_text())
    mh = {t['uid']: t for t in json.loads((FSC / 'TASKS.json').read_text())}
    tq = {t['uid']: t for t in json.loads((TQB / 'TASKS.json').read_text())}
    tq.update({t['uid']: t for t in json.loads((SU / 'TQ_TASKS.json').read_text())})
    tasks = []
    for e in mh_freeze:
        t = mh[e['task_id']]
        tasks.append(dict(dataset='MultiHiertt', dom='mh', uid=t['uid'], answer=t['answer'],
                          n_ops=mh_n_ops(t['program'])))
    for e in tq_freeze:
        t = tq[e['task_id']]
        tasks.append(dict(dataset='TAT-QA', dom='tq', uid=t['uid'], answer=t['answer'],
                          n_ops=tq_n_ops(t['derivation'])))
    assert len(tasks) == 300, len(tasks)
    return tasks


def arm_ok(row, gold, facts=None):
    if row is None or row.get('status') != 'delivered':
        return False
    if facts is None:
        return bool(close(extract_value(row.get('answer')), gold))
    try:
        expr = v.decode(row['answer'])['expression']
        return bool(close(exec_calc(expr, facts), gold))
    except Exception:
        return False


def main():
    if not (RUN / 'ALL_DONE').exists():
        raise FileExistsError('paired run not complete; run decomp_benchmark_run.py first')
    rows = {json.loads(l)['key']: json.loads(l) for l in (RUN / 'RESPONSES.jsonl').open()}
    tasks = load_tasks()
    per_task = []
    infra = dict(mono=0, ext=0, rsnL=0, rsnM=0)
    parse_fail = 0
    for t in tasks:
        k = dict(mono=f'{t["dom"]}:{t["uid"]}:mono', ext=f'{t["dom"]}:{t["uid"]}:ext',
                 rsnL=f'{t["dom"]}:{t["uid"]}:rsnL', rsnM=f'{t["dom"]}:{t["uid"]}:rsnM')
        mono = rows.get(k['mono'])
        ext = rows.get(k['ext'])
        rsnL = rows.get(k['rsnL'])
        rsnM = rows.get(k['rsnM'])
        for arm, r in [('mono', mono), ('ext', ext), ('rsnL', rsnL), ('rsnM', rsnM)]:
            if r is None or (r.get('status') not in ('delivered', 'skipped_parse_failure')):
                infra[arm] += 1
        facts = None
        if ext and ext.get('status') == 'delivered':
            try:
                facts = v.parse_facts(ext['answer'])
            except Exception:
                facts = None
        if facts is None:
            parse_fail += 1
        ok = dict(mono=arm_ok(mono, t['answer']),
                  dagLL=arm_ok(rsnL, t['answer'], facts),
                  dagLM=arm_ok(rsnM, t['answer'], facts))
        tok = lambda r: ((r or {}).get('usage') or {}).get('total_tokens', 0)
        lat = lambda r: (r or {}).get('latency_s', 0.0)
        per_task.append(dict(task_id=t['uid'], dataset=t['dataset'], n_ops=t['n_ops'],
                             bucket=bucket(t['n_ops']), **ok,
                             tokens=dict(mono=tok(mono), ext=tok(ext), rsnL=tok(rsnL), rsnM=tok(rsnM),
                                         dag_LL=tok(ext) + tok(rsnL), dag_LM=tok(ext) + tok(rsnM)),
                             latency=dict(mono=lat(mono), ext=lat(ext), rsnL=lat(rsnL), rsnM=lat(rsnM),
                                          dag_LL=lat(ext) + lat(rsnL), dag_LM=lat(ext) + lat(rsnM))))

    def cell(sel, arm_a, arm_b, cost_a, cost_b):
        pts = [p for p in per_task if sel(p)]
        n = len(pts)
        d = [int(p[arm_b]) - int(p[arm_a]) for p in pts]
        d = np.array(d)
        b = sum(1 for p in pts if p[arm_a] and not p[arm_b])
        c = sum(1 for p in pts if not p[arm_a] and p[arm_b])
        ci = paired_ci(d) if n else (None, None)
        return dict(n=n, acc_a=float(np.mean([p[arm_a] for p in pts])) if n else None,
                    acc_b=float(np.mean([p[arm_b] for p in pts])) if n else None,
                    delta_q=float(d.mean()) if n else None, ci=ci,
                    mcnemar_b=b, mcnemar_c=c, mcnemar_p=mcnemar_p(b, c),
                    tokens_a=float(np.mean([p['tokens'][cost_a] for p in pts])) if n else None,
                    tokens_b=float(np.mean([p['tokens'][cost_b] for p in pts])) if n else None,
                    latency_a=float(np.mean([p['latency'][cost_a] for p in pts])) if n else None,
                    latency_b=float(np.mean([p['latency'][cost_b] for p in pts])) if n else None)

    out = dict(created_unix=time.time(), n_tasks=len(tasks), parse_failures=parse_fail, infra=infra,
               table_A={}, table_B={}, complexity={})
    for ds in ['MultiHiertt', 'TAT-QA', 'Overall']:
        sel = (lambda p, ds=ds: p['dataset'] == ds) if ds != 'Overall' else (lambda p: True)
        out['table_A'][ds] = cell(sel, 'mono', 'dagLL', 'mono', 'dag_LL')
        out['table_B'][ds] = cell(sel, 'dagLL', 'dagLM', 'dag_LL', 'dag_LM')
    for ds in ['MultiHiertt', 'TAT-QA']:
        out['complexity'][ds] = {
            bkt: cell(lambda p, ds=ds, bkt=bkt: p['dataset'] == ds and p['bucket'] == bkt,
                      'mono', 'dagLL', 'mono', 'dag_LL')
            for bkt in ['1-2', '3', '4+']}

    core.write(BENCH / 'paired_run' / 'RESULTS.json', out)
    with (BENCH / 'paired_run' / 'per_task.jsonl').open('w') as f:
        for p in per_task:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
