"""Hard-subset evaluation + DV ablation consolidation (zero model calls).

Split (frozen in VERIFIER_SUBSET_PROTOCOL.md, pre-execution feature):
  Easy = gold derivation with 1 arithmetic operator (74 tasks)
  Hard = >= 2 operators (46 tasks)
Outputs per-subset accuracy for Router / Static / Dynamic / Dynamic+Verifier in the
clean scenario and Router / Static / Dynamic in fault scenarios (20%, 30%),
plus the DV ablation table with costs and signal statistics.
Writes adaptive_benchmark/verifier_ablation/SUBSET_REPORT.md + SUBSET_RESULTS.json.
"""
import json
import re
import time

from .multidag_dynamic import OUT
from .benchmark_run import BENCH
from .verifier_run import DV


def n_ops(derivation):
    return len(re.findall(r'[+\-*/]', derivation))


def run():
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    n = len(tasks)
    uids = [t['uid'] for t in tasks]
    hard = {t['uid'] for t in tasks if n_ops(t['derivation']) >= 2}
    easy = set(uids) - hard
    clean = json.loads((BENCH / 'CLEAN_RESULTS.json').read_text())
    corrected = json.loads((OUT.parent / 'corrected_replay' / 'CORRECTED_ARMS.json').read_text())
    dv = json.loads((DV / 'DV_RESULT.json').read_text())
    dv_res = dv['dv']
    fault = {p: json.loads((BENCH / f'fault_p{p}' / 'FAULT_RESULT.json').read_text())
             for p in (20, 30)}

    def q(rows, subset):
        sel = subset if subset else uids
        return round(sum(1 for u in sel if rows[u]['ok']) / len(sel), 4)

    out = dict(generated_unix=time.time(),
               split=dict(easy=len(easy), hard=len(hard),
                          rule='Easy: 1 operator; Hard: >=2 operators (gold derivation, pre-execution feature)'),
               clean={}, fault={}, dv_ablation={}, dv_signal=dv['signal_stats'])
    # clean per-subset
    for name, rows in (('router', clean['router']), ('static', clean['static']), ('dynamic', clean['dynamic']),
                       ('dynamic_verifier', dv_res)):
        out['clean'][name] = dict(overall=q(rows, None), easy=q(rows, easy), hard=q(rows, hard))
    # fault per-subset
    for p, fr in fault.items():
        out['fault'][p] = {m: dict(overall=q(fr[m], None), easy=q(fr[m], easy), hard=q(fr[m], hard))
                           for m in ('router', 'static', 'dynamic')}
    # DV ablation table with costs
    def mean_used(rows):
        return round(sum(rows[u]['used'] for u in uids) / n, 1)

    def mean_lat(rows):
        return round(sum(rows[u]['lat'] for u in uids) / n, 2)

    out['dv_ablation'] = dict(
        static=dict(Q=out['clean']['static']['overall'], mean_tokens=mean_used(clean['static']),
                    mean_latency_s=mean_lat(clean['static'])),
        dynamic=dict(Q=out['clean']['dynamic']['overall'], mean_tokens=mean_used(clean['dynamic']),
                     mean_latency_s=mean_lat(clean['dynamic'])),
        dynamic_verifier=dict(Q=out['clean']['dynamic_verifier']['overall'], mean_tokens=mean_used(dv_res),
                              mean_latency_s=mean_lat(dv_res),
                              extra_calls_vs_dynamic=sum(len(dv_res[u]['keys']) - len(clean['dynamic'][u]['keys'])
                                                         for u in uids)))
    # paired DV vs Dynamic
    d_ok = [int(clean['dynamic'][u]['ok']) for u in uids]
    v_ok = [int(dv_res[u]['ok']) for u in uids]
    b = sum(1 for x, y in zip(v_ok, d_ok) if y == 0 and x == 1)
    c = sum(1 for x, y in zip(v_ok, d_ok) if y == 1 and x == 0)
    import math

    def mcnemar(b, c):
        m = b + c
        if m == 0:
            return 1.0
        return min(1.0, sum(math.comb(m, i) for i in range(0, min(b, c) + 1)) / 2 ** m * 2)
    out['dv_vs_dynamic_paired'] = dict(dQ=round((sum(v_ok) - sum(d_ok)) / n, 4), help=b, harm=c,
                                       p_exact=round(mcnemar(b, c), 6))
    # report
    lines = ['# Hard-Subset Evaluation & Dynamic+Verifier Ablation', '',
             f"Split (pre-execution, frozen): Easy = 1 operator ({len(easy)} tasks); "
             f"Hard = >=2 operators ({len(hard)} tasks).", '',
             '## Clean scenario per subset', '',
             '| Method | overall | easy | hard |', '|---|---:|---:|---:|']
    for name in ('router', 'static', 'dynamic', 'dynamic_verifier'):
        r = out['clean'][name]
        lines.append(f"| {name} | {r['overall']:.4f} | {r['easy']:.4f} | {r['hard']:.4f} |")
    lines += ['', '## Fault scenarios per subset (accuracy)', '',
              '| Scenario | Method | overall | easy | hard |', '|---|---|---:|---:|---:|']
    for p in (20, 30):
        for m in ('router', 'static', 'dynamic'):
            r = out['fault'][p][m]
            lines.append(f"| fault {p}% | {m} | {r['overall']:.4f} | {r['easy']:.4f} | {r['hard']:.4f} |")
    a = out['dv_ablation']
    lines += ['', '## Dynamic + Verifier ablation (clean)', '',
              '| Method | Accuracy | tokens/task | latency s |', '|---|---:|---:|---:|']
    for name in ('static', 'dynamic', 'dynamic_verifier'):
        lines.append(f"| {name} | {a[name]['Q']:.4f} | {a[name]['mean_tokens']:.0f} | {a[name]['mean_latency_s']:.2f} |")
    lines += ['', f"DV vs Dynamic paired: dQ={out['dv_vs_dynamic_paired']['dQ']}, "
              f"help/harm={b}/{c}, McNemar p={out['dv_vs_dynamic_paired']['p_exact']}.",
              f"Verifier signal stats: {json.dumps(dv['signal_stats'])}.",
              f"DV extra calls vs Dynamic: {a['dynamic_verifier']['extra_calls_vs_dynamic']}.", '']
    (DV / 'SUBSET_REPORT.md').write_text('\n'.join(lines))
    (DV / 'SUBSET_RESULTS.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print('\n'.join(lines))


if __name__ == '__main__':
    run()
