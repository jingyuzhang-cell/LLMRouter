# SUPPLEMENTARY_MEASUREMENT_REPORT — the DAG-quality calibration run

Run `run_20261012_092146` (2026-10-12), executed under the operator's
continuation of the GO-day procedure (MEASUREMENT_GO_RUNBOOK.md):
preflight PREFLIGHT_PASS → entry-point rehearsal REHEARSAL_PASS (16
bound files clean at commit 6f9cc5d) → execution with the approved
panel-freeze SHA. STATUS **COMPLETE**: 10/10 cells, **124 requests /
40,327 tokens / 2,734.9 s** (10.3% / 5.0% / 38.0% of the hard caps);
DISPATCH arithmetic exact (124 reserved = 124 settled, 0 failed
attempts); physical requests within the structural cache-plan range.

## Results (P(task correct), v2.1 scoring, Wilson 95% CI)

| cell | P | CI | new/cache/inj |
|---|---|---|---|
| clean\|SS | 0.10 (2/20) | [.028, .301] | 74/0/0 |
| clean\|DS | 0.10 (2/20) | [.028, .301] | 0/62/0 |
| clean\|SD | 0.10 (2/20) | [.028, .301] | 0/62/0 |
| clean\|DD | 0.10 (2/20) | [.028, .301] | 3/63/0 |
| clean\|NONE | 0.45 (9/20) | [.258, .658] | 17/63/0 |
| fault\|SS | 0.20 (4/20) | [.081, .416] | 25/62/12 |
| fault\|DS | 0.05 (1/20) | [.009, .236] | 0/61/6 |
| fault\|SD | 0.10 (2/20) | [.028, .301] | 1/62/6 |
| fault\|DD | 0.10 (2/20) | [.028, .301] | 2/65/6 |
| fault\|NONE | 0.45 (9/20) | [.258, .658] | 2/78/6 |

Per protocol scope (gate 5): **calibration only** — all CIs overlap at
n=20; NOTHING here supports strategy selection, arm ordering, or
superiority claims. D=3600 throughout (deadlines inert by design).

## Calibration findings

1. **Q_min=0.80 is not a reasonable bar for this stack as configured.**
   Realized terminal correctness is ≤ 0.45 in EVERY cell — far below
   0.80. A q_min filter at 0.80 therefore rejects (nearly) everything;
   if the mainline keeps 0.80, the feasibility gate is vacuously strict
   on this cascade; if it is ever revisited, that is a NEW frozen
   version with explicit rationale, NOT an adjustment from these data.
2. **Natural failures dominate the panel; the D3 injection is nearly
   invisible at the terminal.** clean|NONE per-node natural failures:
   e2 17/20, v 8/20, e1 4/20, r 3/20; 19/20 tasks had ≥1 FAILED node.
   fault|NONE == clean|NONE exactly (9/20): the 6 injected r-faults
   changed no NONE outcome (those tasks were already failing, or v
   overcame the corrupted r).
3. **The recovery arms as configured do not help on THIS panel** —
   clean|SS/DS/SD/DD all 0.10 vs NONE 0.45 (CIs overlap at the margin:
   [.258,.658] vs [.028,.301] overlap in [.258,.301] — not separable at
   n=20, recorded as a phenomenon, not a conclusion). Mechanisms
   observed: DS refused recovery wherever planned-π candidates were
   q̂-infeasible (0 new calls in both conditions — the strict-belief
   proxy in action); SS blindly retried (fault cell: 6 R1 + 6 re-faulted
   retries = 12 injections, exactly as designed); SD/DD executed few
   recoveries (3/1/2 new calls) — most naturally-failed tasks had e2 in
   scope and e-recovery is q̂-infeasible under min-composition with
   strict e2 beliefs (0.25–0.375).
4. **The parse-rate proxy gap is empirically confirmed** (standing
   boundary 3): q̂ beliefs implied composed feasibility ≈ 0.78–1.0;
   realized task correctness is 0.05–0.45. Parse success is nowhere
   near terminal correctness on this panel.
5. **8 of the 9 correct clean|NONE tasks were correct DESPITE ≥1
   detected node failure** — the v stage frequently answers correctly
   from partial facts; terminal v2.1 correctness is not implied by
   intermediate D-observations.

## Standing scope (unchanged, binding)

Initial quality calibration ONLY. No strategy selection, no DD>SS
reading, no weight adjustments, no time-pressure claims (D inert).
Next gates per the operator's sequence: real-deadline prediction
reliability, then the frozen V2.3 dynamic-vs-static comparison.

Artifacts: `PRIORS_REAL_V1_quality.json` (official, COMPLETE-guarded),
`supplementary_runs/run_20261012_092146/` (TASK_LEDGER 702 logical
calls, DISPATCH, CELL_RECORDS with per-cell metering + execution-order
audits, STATUS, verbatim freeze/protocol/beliefs copies).
