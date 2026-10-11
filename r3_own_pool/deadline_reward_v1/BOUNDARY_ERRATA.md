# BOUNDARY_ERRATA — T3 evidence fixes + report alignment (zero calls)

Baseline: commit 697d656. Authorization: operator errata instruction
(2026-10-11) — fix the two T3 test flaws, tighten the contention claim,
align the audit number. No real model calls; no goldens touched. Result:
**both flaws reproduced & fixed; the fixes exposed TWO REAL estimator
gaps (both fixed); seven suites 156/156 green.**

## Issue 1 — flip counterexample used the wrong remaining time: FIXED

Reproduction (exactly as the reviewer stated): the old test computed
solo_p against the INITIAL deadline D=26, while the ledger's decision
moment had d_remain=19.3 — B was infeasible even solo, so "contention
flipped it" was a false conclusion.

Fix: the counterexample now runs at D=32.7 so the decision-time
`d_remain = 26.0` (verified from the decision event, tolerance 0.2), and
BOTH probabilities are computed AT THAT SAME moment:
- P_solo (μ=23.5, p90=24.5) at d_remain 26.0 → **0.9993 ≥ 0.90**;
- P_contention (μ=33.5, p90=34.5, contention=10.0) at d_remain 26.0 →
  **≈ 4e-9 < 0.90**, row infeasible with an `on_time` deficit.
The ONLY difference between the two predictions is the contention
addend, and its value is asserted traceable to decision-observable state
+ frozen priors (v|coder mean 7.0 + full switch allowance 3.0 for the
co-task's planned binding). Had the window failed to exist, the test
would fail rather than relax.

## Issue 2 — coverage test could pass vacuously: FIXED

Reproduction: the old `t3_prediction_covers_actual` only checked
decisions with `chosen != None`; the committed t3 run was degraded
(chosen=null), so `ok_cover` stayed at its initial True — a PASS that
proved nothing.

Fix: coverage now runs THREE deterministic scripted samples (fault on
task 0 / task 1 / per-node latencies equal to the priors' means) and
REQUIRES in each: ≥1 chosen cross-task decision, the task really
completes (completion recorded), decision clock + predicted μ/p90 +
actual elapsed reconciled, and ≥1 OTHER-task physical call observed
inside the decision→completion window (interleaving is real, not
assumed). **The tight sample immediately caught two genuine estimator
gaps**:

1. the contention estimate omitted the CO-TASK's switch cost (estimated
   7.0 vs actual 7.0+3.0), pushing actual past predicted p90;
   → fixed: the co-task baseline estimate is now v mean + a FULL switch
   allowance (stop+start for its planned binding; observable, priors-
   derived, covers the observed gap);
2. cross-task interleaving can force a RE-SWITCH before EVERY ONE of my
   own calls (the sequential own-switch estimate 3.5 badly under-counted
   the actual 7.0 when the co-task's v ran between my r and v);
   → fixed: own switch cost is now a PROVABLE per-call bound — on the
   shared serial executor each of my new calls needs at most one
   stop+start — replacing the non-bound sequential estimate (kept in the
   row as `switch_seq` for audit).

Claim discipline: the coverage checks are named and recorded as
**deterministic-sample coverage**, explicitly NOT a general P90
probability guarantee (asserted in the evidence file's `claim` field).

## Issue 3 — contention claim tightened: DONE

`remaining_work_est` is an ESTIMATE (priors-derived means + switch
allowances), correctly described now as a DECLARED heuristic penalty; it
is a provable upper bound on a co-task's remaining work only when that
work (its service + its switches) stays within its estimate. Code
comments, the decision-row schema, and BOUNDARY_AUDIT_REPORT.md now all
state the estimate nature and the conditions; finite-sample coverage is
never generalized.

## Issue 4 — number alignment: DONE

The reported "−20 tokens" overspend was my arithmetic slip; the
replayable ledger (`BOUNDARY_EVIDENCE.json::detail.t1.overspend_b_remain`)
records **−50**, and BOUNDARY_AUDIT_REPORT.md now cites the ledger value.
(Mechanism unaffected: reservation 100 vs real metering 200 → spent 500
on a 450 allocation → b_remain = −50, post_V1 decision budget-deficient.)

## Downstream updates (documented, not silent)

- `p3_1_switch_reconcile` now asserts the row's switch is a proven UPPER
  bound over the actual switch sum plus the internal identity
  p90 = service_p90 + switch — replacing the exact-equality assertion
  that encoded the old non-bound semantics (single-task run: tokens and
  requests still reconcile exactly).
- V1/V8/V9/V10 goldens: untouched and passing (zero-switch / single-task
  worlds; V10's per-call bound equals its sequential estimate since each
  call changes model).

## Regression

Seven suites, socket-blocked, `zero_model_calls: true` everywhere:
21+24+35+25+18+19+14 = **156/156**. Evidence:
`evidence/BOUNDARY_EVIDENCE.json` (flip arithmetic at d_remain,
coverage-sample details with the claim field, T1 ledger numbers).

**Status: errata complete. Real-model experiments remain HOLD pending
the Formal settlement audit, net-benefit gates, and a separately
authorized calibration plan.**
