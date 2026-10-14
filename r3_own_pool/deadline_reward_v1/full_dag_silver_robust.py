"""Settlement robustness: does the arm ranking flip when the
candidate-silver atom set is perturbed (dates-only / dates+amounts /
all)? A flip means conclusions are silver-sensitive and must be
reported as such. Zero calls; runs the fake-transport demo under
each silver subset.

Run: python3 -m deadline_reward_v1.full_dag_silver_robust
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from deadline_reward_v1.full_dag_scoring import run_fake_scoring

HERE = Path(__file__).resolve().parent


def subset_silver(silver, keep):
    s = copy.deepcopy(silver)
    for t in s.values():
        t['fe']['atom_dates'] = (t['fe']['atom_dates']
                                 if 'dates' in keep else [])
        t['fe']['atom_amounts'] = (t['fe']['atom_amounts']
                                   if 'amounts' in keep else [])
        t['fe']['atom_penalties'] = (t['fe']['atom_penalties']
                                     if 'penalties' in keep else [])
        t['tl']['ordered_dates'] = (t['tl']['ordered_dates']
                                    if 'dates' in keep else [])
    return s


def main():
    base = {s['task_id']: s for s in json.loads(
        (HERE / 'FULL_DAG_SILVER_V1.json').read_text())['tasks']}
    variants = {
        'dates_only': subset_silver(base, {'dates'}),
        'dates_amounts': subset_silver(base, {'dates', 'amounts'}),
        'all_atoms': base,
    }
    out = {}
    for name, silver in variants.items():
        results, paired = run_fake_scoring(silver_override=silver,
                                           quiet=True)
        out[name] = dict(
            mean_q={arm: round(sum(r['terminal_q'] for r in rows)
                               / len(rows), 4)
                    for arm, rows in results.items()},
            mean_U={arm: round(sum(r['utility_U'] for r in rows
                                   if r['utility_U'] is not None)
                               / max(1, sum(1 for r in rows
                                            if r['utility_U']
                                            is not None)), 4)
                    for arm, rows in results.items()},
            paired_dU={k: v['mean_dU'] for k, v in paired.items()})
        print(name, json.dumps(out[name]['mean_q'],
                                ensure_ascii=False))
    rankings = {name: sorted(v['mean_q'], key=v['mean_q'].get,
                             reverse=True)
                for name, v in out.items()}
    stable = len({tuple(r) for r in rankings.values()}) == 1
    report = dict(
        version='FULL_DAG_SILVER_ROBUSTNESS_v1',
        zero_model_calls=True, variants=out, rankings=rankings,
        ranking_stable=stable,
        note='fake-transport demo — mechanism-level robustness; the '
             'same check is MANDATORY on the real run before any '
             'conclusion is drawn')
    (HERE / 'FULL_DAG_SILVER_ROBUSTNESS.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    print('ranking stable across silver subsets:', stable)
    for n, r in rankings.items():
        print(f'  {n}: {" > ".join(r)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
