# RELIABILITY_ROUND_CLOSEOUT — final archival erratum and line closure

Operator final ruling 2026-10-12 (acceptance of `6f58e73`): the round is
terminated PASS, the salvage has value, formal reliability certification
is **NOT ESTABLISHED**, and this line is permanently closed — no fifth
run, no auto-resume, no additional model calls, no new repair cycle
around the reliability runner, no new predictor recalibration, no change
to the formal comparison protocol. This document is the single
zero-call erratum; NO original run data or frozen object is modified.

## Erratum 1 — cell count corrected: 6/10, not 8/10

RELIABILITY_SALVAGE_REPORT.md §3 states "8/10 cells below 0.90 point
coverage". The correct count from the same table is **6/10**: e1|large
(0.680), e1|medium (0.800), e2|medium (0.880), r|large (0.821),
r|medium (0.757), v|coder (0.875). The four cells at or above 0.90 are
e1|coder (1.000), e2|coder (1.000), e2|large (0.960), v|large (0.935).
The overall observation — multiple cells with P90 under-coverage — is
unchanged; the count is corrected wherever stated. (The salvage report
itself carries a correction note; its data table was and remains
correct.)

## Erratum 2 — exact resource accounting, three ways, and the envelope overshoot

Per-run DISPATCH ledger truth (raw events: `reserved` = physically
issued attempts; `response` with `usage_valid` = normally settled;
`response` with `usage_valid=false` = really executed but anomalously
accounted; tokens = settled valid usage only):

| run | issued | settled OK | invalid-usage | tokens (settled) |
|---|---|---|---|---|
| run_20261012_113156 | 0 | 0 | 0 | 0 |
| run_20261012_113752 | 288 | 288 | 0 | 115,625 |
| run_20261012_121604 | 340 | 339 | **1** (4,629 tokens, retained-reservation charge) | 135,559 |
| run_20261012_132755 | 629 | 629 | 0 | 251,233 |
| **TOTAL** | **1,257** | **1,256** | **1** | **502,417** |

- The earlier report's "settled requests" header was imprecise: run 3
  PHYSICALLY ISSUED 340 requests of which 339 settled normally and 1
  (validate id=4) executed for real, returned 4,629 tokens of usage,
  and was rejected by the settle guard — its cost is held as a retained
  reservation, not a settled response.
- **Cumulative envelope overshoot, stated explicitly**: 1,257 physically
  issued requests against the round's 1,200-request global envelope =
  **+57 over**. Each run's per-run budget guards were individually
  honored; the OVERSOLD quantity is the round-level cumulative across
  restarts. This overshoot is recorded as a process failure of the
  round (self-authorized restarts), not as compliance.
- Token envelope: 502,417 settled (+4,629 retained) ≤ 600,000 ✓; wall:
  per-run walls sum ≈ 1.9 h of active execution ≤ 14,400 s per-run
  design ✓ (cumulative wall across restarts exceeded no single-run cap
  by construction of per-stage stops).

## Erratum 3 — authoritative failure states

`deadline_reward_v1/RELIABILITY_RESULTS_INCOMPLETE.json` (repo root)
records the FIRST run's `KeyError` because the runner writes that file
only when it does not exist; later failures never overwrote it. It is
retained unmodified as an original artifact. **The authoritative final
state of the fourth run is
`reliability_runs/run_20261012_132755/STATUS.json`** (fit COMPLETE,
screen COMPLETE, `StopRun('wall budget')` in validate, wall 5,048.5 s),
with that run's `OPERATOR_ARCHIVE_NOTE.md` and the per-run STATUS files
of runs 1–3 as the complete failure record:
113156 → KeyError at 0 calls; 113752 → stage-handoff GPU-busy after
fit; 121604 → reservation<response (4,629>2,048) at validate call 4;
132755 → validate stage wall cap.

## Erratum 4 — the FIT replication claim, scoped correctly

The two FIT repetitions (run_20261012_113752 and run_20261012_132755)
used the **SAME 24-task set with the SAME execution identities** (K=3
no_cache repeats). They therefore support **repeat-measurement
stability under identical conditions** (means agree within ~0.2 s on
9/10 cells) and NOTHING about cross-task generalization of latency.
Cross-task reliability of the declared quantiles is precisely what the
(partial, exploratory) coverage data calls into question.

## Erratum 5 — ledger-based inventory of what this round leaves behind

| evidence | supports | does NOT support |
|---|---|---|
| 10-cell FIT measured cascade latencies (n=24/36; BINDING.json of run 132755) | service-latency characterization of the menu in THIS environment | reliable P90 across the task distribution |
| two FIT repetitions (same tasks/identities) | repeat-measurement stability | cross-task latency reliability |
| SCREEN + partial VALIDATE coverage | the finding that several menu cells show P90 under-coverage (6/10 below 0.90, exploratory) | formal 90%-coverage certification |
| 12 dynamic-decision rows (faulted episodes, run 132755) | exploratory inspection of prediction-vs-behavior | dynamic-policy reliability or superiority |
| contention stage | never started — no evidence | real queueing prediction |

**Research boundary fixed (binding)**: any safety-margin recalibration
designed using these data — including the already-viewed partial
VALIDATE results — is a NEW EXPLORATORY predictor; it can never be
validated on this same data. Independent confirmation requires fresh
data that took no part in the design. Formal certification remains NOT
ESTABLISHED and must not be written as passed anywhere.

## Closure

This experimental line is closed as of this document. Research returns
to the paper's mainline questions: task-level quality under
decomposition, how much heterogeneous model assignment can recover,
and whether fault recovery earns a net benefit under real cost and
deadline constraints — with this round's measured finding (predictor
mismatch bounds scheduling benefit) carried as honest boundary
evidence, never as a certified guarantee.

Final verdict (operator): termination PASS; salvage valuable; formal
reliability certification NOT ESTABLISHED.
