"""Deterministic eU regression (Task 2): frozen D=80 recompute must match the
corrected values stored in H1_UNIT1_RESULT.json; raw (D=350 bug) scores must
remain preserved verbatim."""
import json, sys
D, C0 = 80.0, 60000.0
d = json.loads(open('H1_UNIT1_RESULT.json').read())
fails = 0
for r in d['results']:
    if r.get('t_q') is None:
        continue
    late = r['clock'] > D
    eu = (r['t_q'] * (0 if late else 1) - 0.5 * r['tokens'] / C0
          - ((r['clock'] - D) / D if late else 0) - (2.0 if late else 0))
    ok = abs(round(eu, 4) - r['eU_D80']) < 1e-9
    raw_ok = 'eU' in r and r['eU'] != r['eU_D80']  # raw preserved & differs only where D mattered
    print(f"  {r['arm']:8s} eU_D80 stored={r['eU_D80']:+.4f} recomputed={eu:+.4f} "
          f"{'ok' if ok else 'FAIL'}; raw(D=350)={r['eU']:+.4f} preserved={'ok' if raw_ok or r['met'] else 'FAIL'}")
    fails += (not ok)
sys.exit(1 if fails else 0)
