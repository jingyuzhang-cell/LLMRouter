"""Paired analysis for the joint-scheduling confirmatory experiment
(zero calls; consumes JOINT_VERIFY_RESULTS.json from a COMPLETE run).

Reports (frozen definitions — R_conditional primary, service-T):
  per-arm summaries (Q, C, T, on-time-correct, R_cond mean, degrade rate)
  ΔR = R_DD − R_SS   (primary; task-paired mean + sign-flip MC p +
      task-cluster bootstrap 95% CI)
  DD−DS, DD−SD       (secondary, same machinery)
  I = DD − DS − SD + SS  (interaction; same machinery + the n=60
      underpowering caveat: non-significant ⇒ 'not established')
Non-significant results are reported as 'failed to demonstrate',
never as equivalence.
"""
from __future__ import annotations

import json
import random
from pathlib import Path


def load_rows(results_path):
    res = json.loads(Path(results_path).read_text())
    assert res.get('statuses') and all(
        v == 'COMPLETE' for v in res['statuses'].values()), \
        'analysis refuses non-COMPLETE runs'
    per = {}
    for arm, rows in res['rows'].items():
        for r in rows:
            s = r['R_settlement']
            per.setdefault(r['uid'], {})[arm] = dict(
                Q=s['Q'], C_inc=s['C_attribution']['arm_incremental'],
                T=s['T'], D=s['D'],
                on_time=s['on_time_correct'],
                R=s['R_conditional'], degraded=s['degraded'])
    return res, per


def paired_diffs(per, a, b, key='R'):
    return [per[u][a][key] - per[u][b][key] for u in sorted(per)]


def sign_flip_p(diffs, B=100000, seed=20261105):
    obs = sum(diffs) / len(diffs)
    rng = random.Random(seed)
    cnt = 0
    for _ in range(B):
        s = sum(d if rng.random() < 0.5 else -d for d in diffs)
        if s / len(diffs) >= obs:
            cnt += 1
    return (1 + cnt) / (B + 1)


def bootstrap_ci(diffs, B=10000, seed=20261106, alpha=0.05):
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n
                   for _ in range(B))
    lo = means[int(alpha / 2 * B)]
    hi = means[int((1 - alpha / 2) * B) - 1]
    return round(lo, 4), round(hi, 4)


def contrast(per, a, b):
    d = paired_diffs(per, a, b)
    return dict(n=len(d), mean=round(sum(d) / len(d), 4),
                ci95=bootstrap_ci(d), p_signflip=round(sign_flip_p(d), 5),
                verdict=('POSITIVE' if sum(d) / len(d) > 0
                         and sign_flip_p(d) <= 0.05 else
                         'failed to demonstrate' if sum(d) / len(d) > 0
                         else 'negative-or-null'))


def interaction(per):
    ds = [per[u]['DD']['R'] - per[u]['DS']['R'] - per[u]['SD']['R']
          + per[u]['SS']['R'] for u in sorted(per)]
    p = sign_flip_p(ds)
    m = sum(ds) / len(ds)
    return dict(n=len(ds), mean=round(m, 4),
                ci95=bootstrap_ci(ds), p_signflip=round(p, 5),
                caveat='n=60 likely underpowered for the interaction: '
                       'non-significant ⇒ NOT ESTABLISHED, never '
                       '"no interaction"')


def arm_summary(per, arm):
    rows = [v[arm] for v in per.values()]
    n = len(rows)
    return dict(n=n, Q=sum(r['Q'] for r in rows) / n,
                on_time_correct=sum(r['on_time'] for r in rows) / n,
                mean_C_inc=round(sum(r['C_inc'] for r in rows) / n, 1),
                mean_T=round(sum(r['T'] for r in rows) / n, 3),
                mean_R_cond=round(sum(r['R'] for r in rows) / n, 4),
                degrade_rate=sum(1 for r in rows if r['degraded']) / n)


def analyze(results_path):
    res, per = load_rows(results_path)
    return dict(
        version='JOINT_VERIFY_ANALYSIS_v1',
        primary=contrast(per, 'DD', 'SS'),
        secondary=dict(DD_vs_DS=contrast(per, 'DD', 'DS'),
                       DD_vs_SD=contrast(per, 'DD', 'SD')),
        interaction=interaction(per),
        arms={a: arm_summary(per, a)
              for a in ('SS', 'DS', 'SD', 'DD', 'NONE', 'MONO')
              if a in next(iter(per.values()))},
        conventions=dict(
            T='service-time (queue-free, switch-free); wall reference '
              'in rows', R='R_conditional primary; full-task cost view '
              'separate', MONO='descriptive baseline, outside the '
              'same-fault causal contrasts'),
        non_claims='non-significant = failed to demonstrate, never '
                   'equivalence; 60-task interaction caveat above')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('results_json')
    a = ap.parse_args()
    print(json.dumps(analyze(a.results_json), indent=1,
                     ensure_ascii=False))
