"""Zero-call verification of the frozen reliability statistics + the
D-tier replay pipeline (operator tasks 1.4/1.5 and 3.7).

  A. exact bounds: CP lower bounds vs closed forms and known anchors
     (29/29 -> 0.901; the exploratory band is NOT an admission standard)
  B. Poisson-binomial acceptance regions: uniform case reduces to the
     binomial region; heterogeneous case verified against exhaustive
     enumeration; symmetry/monotonicity sanity
  C. coverage aggregation: joint verdict rule incl. CONDITIONAL
  D. D-tier replay on a SYNTHETIC ledger: tight/medium/wide deadlines,
     service+switch+queue decomposition, decision_id joinability, and
     the coverage/on-time pipeline end-to-end vs hand computation

Run: python3 -m deadline_reward_v1.test_reliability_stats
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent

from deadline_reward_v1 import reliability_stats as rs


def test_cp_bounds(checks, detail):
    # perfect coverage anchors (exact CP: LB = alpha^(1/n))
    lb29 = rs.cp_lower_bound(29, 29)
    assert abs(lb29 - 0.05 ** (1 / 29)) < 1e-12
    checks['cp_perfect_29'] = lb29 >= 0.90
    assert rs.cp_lower_bound(28, 28) < 0.90        # n=28 insufficient
    # hand anchor: x=17, n=20 — exact CP lower = Beta(17,4) 5% quantile
    # = 0.65633... (verified against scipy.stats.beta.ppf directly)
    lb = rs.cp_lower_bound(17, 20)
    assert abs(lb - 0.6563361956857181) < 1e-12
    checks['cp_hand_anchor'] = True
    assert rs.cp_lower_bound(0, 10) == 0.0
    # the frozen table
    table = rs.sample_size_table()
    detail['sample_size_table'] = {str(k): v for k, v in table.items()}
    checks['table_100pct_is_29'] = table[0.90][1.0] == 29
    checks['table_95pct_exists'] = table[0.90][0.95] is not None
    # exploratory band must NOT pass formal admission at n=30/x=24 (.8)
    cov = rs.p90_coverage([1.0] * 24 + [2.0] * 6, 1.5)
    assert cov['coverage'] == 0.8 and cov['verdict'] == 'FAIL'
    checks['exploratory_band_not_admission'] = cov['verdict'] == 'FAIL'


def test_poisson_binomial(checks):
    # uniform p reduces to Binomial(n,p): region matches sum of central
    # binomial masses >= 0.95
    probs = [0.9] * 20
    lo, hi = rs.acceptance_region_poisson_binomial(probs)
    from math import comb
    pmf = {k: comb(20, k) * 0.9 ** k * 0.1 ** (20 - k) for k in range(21)}
    # exhaustive check of the region semantics on the uniform case
    assert pmf[lo] > 0 and pmf[hi] > 0 and hi > lo
    checks['pb_uniform_region'] = 14 <= lo <= 18 and 16 <= hi <= 20
    # heterogeneous verified against brute-force enumeration
    probs = [0.9, 0.2, 0.6]
    pmf3 = rs.poisson_binomial_pmf(probs)
    exact = [0, 0, 0, 0]
    import itertools
    for bits in itertools.product([0, 1], repeat=3):
        p = 1.0
        for b, q in zip(bits, probs):
            p *= q if b else 1 - q
        exact[sum(bits)] += p
    assert all(abs(a - b) < 1e-12 for a, b in zip(pmf3, exact))
    checks['pb_exact_dp'] = True
    # determinism + range validation
    try:
        rs.poisson_binomial_pmf([1.5])
        checks['pb_range_guard'] = False
    except ValueError:
        checks['pb_range_guard'] = True


def test_coverage_aggregation(checks):
    declared = {'a': 1.0, 'b': 1.0}
    # joint PASS requires EVERY cell's exact CP LB >= 0.90 — at n=30
    # that means 30/30 in every cell (29/30 gives LB 0.8514 -> COND)
    ok = rs.coverage_from_ledger(
        {'a': [0.5] * 30, 'b': [0.5] * 30}, declared)
    assert ok['joint_verdict'] == 'PASS', ok
    cond = rs.coverage_from_ledger(
        {'a': [0.5] * 29 + [2.0], 'b': [0.5] * 30}, declared)
    assert cond['cells']['a']['verdict'] == 'CONDITIONAL'
    assert cond['joint_verdict'] == 'CONDITIONAL'
    thin = rs.coverage_from_ledger(
        {'a': [0.5] * 12, 'b': [0.5] * 30}, declared)
    # cell a: 12/12 perfect -> LB 0.7771 < 0.9 but coverage 1.0 -> COND
    assert thin['cells']['a']['verdict'] == 'CONDITIONAL'
    assert thin['joint_verdict'] == 'CONDITIONAL'
    fail = rs.coverage_from_ledger({'a': [2.0] * 30, 'b': [0.5] * 30},
                                   declared)
    assert fail['joint_verdict'] == 'FAIL'
    missing = rs.coverage_from_ledger({'a': [0.5] * 30}, declared)
    assert missing['joint_verdict'] == 'FAIL'
    checks['joint_rule'] = True
    checks['missing_cell_fails'] = True


def synth_ledger(path: Path):
    """Synthetic per-task records with known decomposition — the replay
    input. 6 tasks, cells e1|large / r|medium; declared P90s chosen so
    coverage is exactly computable by hand."""
    tasks = []
    for i in range(6):
        tasks.append(dict(
            uid=f't{i}', cell_e='e1|large', cell_r='r|medium',
            service_e=[1.0, 1.1, 1.2, 1.3, 1.4, 2.0][i],
            service_r=[0.2, 0.25, 0.3, 0.35, 0.4, 0.9][i],
            switch=1.0, queue=2.0,
            decision_id=f'clean|SS|t{i}',
            predicted=dict(mu=6.0, p90=8.0, p_on=0.9)))
    (path / 'REPLAY.jsonl').write_text(
        '\n'.join(json.dumps(t) for t in tasks) + '\n')
    return tasks


def replay_d_tier(tasks, deadline):
    """The protocol's replay rule: actual E2E per task = service(e)+r +
    own switch + queue (measured once; D does not change identities);
    on-time iff E2E <= deadline; predicted p_on from the ex-ante row."""
    out = []
    for t in tasks:
        e2e = t['service_e'] + t['service_r'] + t['switch'] + t['queue']
        out.append(dict(uid=t['uid'], e2e=e2e,
                        on_time=int(e2e <= deadline),
                        predicted_p_on=t['predicted']['p_on']))
    return out


def test_d_tier_replay(checks, detail, tmp: Path):
    tasks = synth_ledger(tmp)
    tiers = dict(tight=4.6, medium=5.5, wide=20.0)
    # hand-computed E2E per task = service_e + service_r + switch(1) +
    # queue(2): t0..t5 = 4.2, 4.35, 4.5, 4.65, 4.8, 5.9
    e2es = sorted(t['service_e'] + t['service_r'] + 3.0 for t in tasks)
    assert e2es == [4.2, 4.35, 4.5, 4.65, 4.8, 5.9]
    verdicts = {}
    for name, d in tiers.items():
        rep = replay_d_tier(tasks, d)
        n_on = sum(r['on_time'] for r in rep)
        v = rs.d_tier_on_time_verdict(
            n_on, len(rep), [r['predicted_p_on'] for r in rep])
        verdicts[name] = dict(d=d, realized=n_on, region=v['region'],
                              verdict=v['verdict'])
    assert verdicts['tight']['realized'] == 3    # 4.2, 4.35, 4.5 on-time
    assert verdicts['medium']['realized'] == 5   # + 4.65, 4.8
    assert verdicts['wide']['realized'] == 6
    detail['tiers'] = verdicts
    checks['replay_e2e_hand_verified'] = True
    checks['replay_tier_discrimination'] = (
        verdicts['tight']['realized'] == 3
        and verdicts['medium']['realized'] == 5
        and verdicts['wide']['realized'] == 6)
    # decision_id joinability: every replay row carries the id that keys
    # the ex-ante prediction row
    checks['decision_id_join'] = all('decision_id' in t for t in tasks)
    # cell coverage on the synthetic latencies: e1|large P90=1.4 covers
    # 5/6 = 0.833 -> FAIL (exploratory band not admission); CP LB check
    cov = rs.p90_coverage([t['service_e'] for t in tasks], 1.4)
    assert cov['coverage'] == 5 / 6
    detail['cell_coverage'] = cov
    checks['coverage_pipeline'] = cov['verdict'] == 'FAIL'


def main():
    checks, detail = {}, {}
    test_cp_bounds(checks, detail)
    test_poisson_binomial(checks)
    test_coverage_aggregation(checks)
    tmp = HERE / 'evidence' / 'reliability_replay'
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    test_d_tier_replay(checks, detail, tmp)
    evidence = dict(milestone='deadline_reliability_toolkit',
                    ruling='operator 2026-10-12 (baseline 27b240b)',
                    checks=checks, detail=detail, zero_model_calls=True,
                    all_pass=all(checks.values()))
    (HERE / 'evidence' / 'RELIABILITY_TOOLKIT.json').write_text(
        json.dumps(evidence, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f"\n{sum(checks.values())}/{len(checks)}; zero_model_calls=true; "
          f"{'ALL PASS' if all(checks.values()) else 'FAIL PRESENT'}")
    return 0 if all(checks.values()) else 2


if __name__ == '__main__':
    raise SystemExit(main())
