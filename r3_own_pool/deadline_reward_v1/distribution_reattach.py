"""Calibration re-audit: REAL Shapiro-Wilk + P90 coverage + contention
relabeling. Zero real calls; reads only the frozen calibration ledger.

Uses scipy.stats.shapiro (not the broken approximation that returned
W=1, p=1 for all 40 cells). Outputs per-cell W, p, std, skewness,
kurtosis, normal verdict, and P90 empirical coverage.

Run: python3 -m deadline_reward_v1.distribution_reattach
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from scipy import stats as sps
import numpy as np

HERE = Path(__file__).resolve().parent
LEDGER = HERE / 'calibration_runs' / 'CALIBRATION_LEDGER.jsonl'
OUT = HERE / 'evidence' / 'DISTRIBUTION_TESTS_V2.json'

ALPHA = 0.01  # frozen in CALIBRATION_FREEZE_PREREQUISITES.json


def main():
    ledger = [json.loads(l) for l in LEDGER.read_text().splitlines()
              if l.strip()]
    calls = [e for e in ledger if e.get('event') == 'call']
    cells = defaultdict(list)
    for c in calls:
        cells[c['cell']].append(c['lat_s'])

    results = {}
    anomalies = []
    for cell in sorted(cells.keys()):
        lats = np.array(cells[cell])
        n = len(lats)
        mean = float(np.mean(lats))
        std = float(np.std(lats, ddof=1))
        skew = float(sps.skew(lats))
        kurt = float(sps.kurtosis(lats))

        # REAL Shapiro-Wilk from scipy
        W, p = sps.shapiro(lats)
        W = round(float(W), 6)
        p = round(float(p), 6)
        normal_pass = p >= ALPHA

        # P90 empirical coverage: fraction of samples <= the P90
        # reported in PRIORS_REAL_V1
        priors = json.loads(
            (HERE / 'PRIORS_REAL_V1.json').read_text())
        p90_reported = priors['profiles'].get(cell, {}).get('lat_p90')
        if p90_reported is not None:
            coverage = float(np.mean(lats <= p90_reported))
        else:
            coverage = None

        # flag anomalies
        notes = []
        if std == 0:
            notes.append('zero_variance')
        if abs(skew) > 1.0:
            notes.append(f'high_skew({skew:.2f})')
        if not normal_pass:
            notes.append(f'normality_rejected(p={p:.4f})')
        if coverage is not None and (coverage < 0.80 or coverage > 1.0):
            notes.append(f'p90_coverage_anomaly({coverage:.2f})')

        results[cell] = dict(
            n=n, mean=round(mean, 4), std=round(std, 4),
            skew=round(skew, 4), kurtosis=round(kurt, 4),
            W=W, p=p, normal_pass=normal_pass,
            p90_reported=p90_reported,
            p90_empirical_coverage=(round(coverage, 4)
                                    if coverage is not None else None),
            notes=notes)

        if notes:
            anomalies.append((cell, notes))

    n_pass = sum(1 for v in results.values() if v['normal_pass'])
    n_fail = sum(1 for v in results.values() if not v['normal_pass'])
    n_anom = len(anomalies)

    report = dict(
        test='scipy.stats.shapiro (REAL, replacing broken approximation)',
        scipy_version=sps.__name__ + ' ' + str(sps.__doc__ or '')[:0] or
        'scipy installed',
        alpha=ALPHA,
        n_cells=len(results), n_pass=n_pass, n_fail=n_fail,
        n_anomalies=n_anom,
        results=results,
        anomalies=[dict(cell=c, notes=n) for c, n in anomalies],
        p90_coverage_summary=dict(
            min=min(v['p90_empirical_coverage'] for v in results.values()
                    if v['p90_empirical_coverage'] is not None),
            max=max(v['p90_empirical_coverage'] for v in results.values()
                    if v['p90_empirical_coverage'] is not None),
            note='Empirical fraction of samples <= reported P90; '
                 'expected ~0.90 if P90 is accurate'),
        contention_relabeling=dict(
            old_label='conservative_upper_bound',
            new_label='stub_simulation_only',
            scope='Valid ONLY for the stub-based simulation with real '
                   'measured service latencies as inputs. NOT a '
                   'production-environment contention bound. Real '
                   'queueing/scheduling latency requires production '
                   'measurement.',
            original_value=0.0304),
        zero_model_calls=True,
        note='Computed from the frozen calibration ledger (SHA '
             'bb202e2e...); no data modified; no additional calls.')
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False))

    print(f'Shapiro-Wilk (scipy, alpha={ALPHA}):')
    print(f'  Normal pass: {n_pass}/{len(results)}')
    print(f'  Normal fail: {n_fail}/{len(results)}')
    print(f'  Anomalies: {n_anom}')
    print()
    for cell in sorted(results.keys()):
        v = results[cell]
        status = 'PASS' if v['normal_pass'] else 'FAIL'
        notes_s = '; '.join(v['notes']) if v['notes'] else ''
        cov = v['p90_empirical_coverage']
        print(f"  {cell:32s} W={v['W']:.4f} p={v['p']:.4f} "
              f"std={v['std']:.3f} skew={v['skew']:.2f} "
              f"cov90={cov} {status} {notes_s}")
    print()
    print(f'P90 coverage range: '
          f"{report['p90_coverage_summary']['min']:.3f} – "
          f"{report['p90_coverage_summary']['max']:.3f} "
          "(expected ~0.90)")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
