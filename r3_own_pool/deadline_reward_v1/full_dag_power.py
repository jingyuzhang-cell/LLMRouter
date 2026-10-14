"""Pre-experiment statistical power analysis for the full-DAG paired
comparisons (zero calls; follows the Phase 0.4-0.5 exact-McNemar
power-simulation precedent).

Test: per-task paired dU, two-sided sign-flip permutation (10k,
frozen seed) — exactly what full_dag_scoring.paired_analysis runs
post-experiment.

Design facts: 15 tasks; 10 F_TRUNCATED tasks carry in-run recovery
decisions (DD can differ from Fixed there); the 5 F_JSON tasks are
terminal-evaluation regime in the fake world (often ties across
arms). Ties carry no information for the sign test — effective n is
the number of NON-ZERO pairs.

Scenarios simulated for DD-vs-Fixed:
  d = per-task dU on decision tasks drawn N(mean=delta, sd=0.05)
  (truncated to ±0.3); other tasks tie (dU=0). Power(delta) over
  2000 replications. Also the observed demo effect for DD-vs-SS
  (mean dU=0.163, 10+/0-/5 ties) as a realism anchor.

Settlement robustness (silver incompleteness): recompute the demo
arm ranking under atom-subset silver (dates-only, dates+amounts,
all) — checks whether conclusions flip when the candidate-silver
over/under-counts.

Run: python3 -m deadline_reward_v1.full_dag_power
"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20261014
B = 10000     # permutation draws
R = 2000      # replications per delta


def signflip_p(diffs, nrng):
    import numpy as np
    d = np.asarray(diffs, dtype=float)
    obs = abs(d.sum())
    signs = nrng.choice((-1.0, 1.0), size=(B, len(d)))
    sums = signs @ d
    cnt = int((np.abs(sums) >= obs - 1e-12).sum())
    return (1 + cnt) / (B + 1)


def power_at(delta, n_decision=10, n_tie=5, sd=0.05, alpha=0.05):
    import numpy as np
    nrng = np.random.default_rng(SEED)
    hits = 0
    for _ in range(R):
        raw = nrng.normal(delta, sd, n_decision)
        diffs = [round(float(max(-0.3, min(0.3, x))), 6) for x in raw]
        diffs += [0.0] * n_tie
        if signflip_p(diffs, nrng) <= alpha:
            hits += 1
    return hits / R


def main():
    deltas = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.16, 0.20]
    power = {f'd={d:.2f}': round(power_at(d), 3) for d in deltas}
    # minimum detectable mean dU at 80% power (linear interpolation)
    mde = None
    for a, b in zip(deltas, deltas[1:]):
        pa, pb = power[f'd={a:.2f}'], power[f'd={b:.2f}']
        if pa < 0.8 <= pb:
            mde = round(a + (0.8 - pa) / (pb - pa) * (b - a), 3)
            break

    # realism anchor: the fake-demo DD-vs-SS effect
    demo = json.loads((HERE / 'FULL_DAG_FAKE_SCORING_DEMO.json')
                      .read_text())
    anchor = demo['paired']['DD-Online_vs_SS-Tuned']
    anchor_power = power_at(anchor['mean_dU'],
                            n_decision=anchor['pos']
                            + anchor['neg'], n_tie=anchor['zero'])

    # settlement robustness under silver subsets
    from deadline_reward_v1.full_dag_scoring import run_fake_scoring  # noqa
    robust = json.loads(
        (HERE / 'FULL_DAG_FAKE_SCORING_DEMO.json').read_text())
    ranking = {}
    for arm, rows in robust['arms'].items():
        q = [r['terminal_q'] for r in rows]
        ranking[arm] = round(sum(q) / len(q), 4)
    # silver-subset rerank: recompute fe/tl/er coverage on dates-only
    # atoms from the settled node details is not stored per-atom, so
    # the robustness check records the design + the ranking under the
    # current silver and flags the check as post-run mandatory
    report = dict(
        version='FULL_DAG_POWER_v1', zero_model_calls=True,
        test='two-sided sign-flip permutation, 10k draws, alpha=0.05',
        design=dict(n_tasks=15, n_decision_tasks=10, n_tie_tasks=5,
                    note='F_JSON tasks are terminal-evaluation '
                         'regime; ties uninformative for the sign '
                         'test — effective n = non-zero pairs'),
        power_curve=power,
        min_detectable_dU_at_80pct=mde,
        anchor=dict(
            source='fake-demo DD-vs-SS (mechanism anchor, not '
                   'evidence)',
            mean_dU=anchor['mean_dU'],
            pos_neg_zero=[anchor['pos'], anchor['neg'],
                          anchor['zero']],
            power_at_anchor=round(anchor_power, 3)),
        demo_ranking_current_silver=ranking,
        silver_robustness=dict(
            mandatory_post_run='recompute arm ranking under '
                               'dates-only and dates+amounts atom '
                               'subsets; a ranking flip means the '
                               'conclusion is silver-sensitive',
            status='designed, post-run mandatory'),
        reading=dict(
            below_mde=f'true mean dU below {mde} is likely '
                      f'undetectable at n=15 — report as '
                      f'inconclusive, NOT as no-effect',
            above_mde=f'delta >= {mde} detectable with ~80% power'))
    (HERE / 'FULL_DAG_POWER.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    print('power curve (DD-vs-Fixed, per-task dU ~ N(d, 0.05)):')
    for k, v in power.items():
        print(f'  {k}: {v}')
    print(f'MDE @80% power: mean dU = {mde}')
    print(f'anchor (demo DD-vs-SS mean {anchor["mean_dU"]}): '
          f'power {anchor_power:.2f}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
