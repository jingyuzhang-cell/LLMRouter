# PHASE3_AUDIT_REPORT — zero-call prediction/execution/settlement consistency audit

Baseline: commit 7459698 (M5+M6). Authorization: operator phase-3
instruction (2026-10-11) — audit + targeted fixes + counterexample tests,
zero real model calls, no new research mechanisms. Status: **all four
audit issues REPRODUCED, all four FIXED, all acceptance gates GREEN —
141/141 checks across six suites.** No original assertion was modified to
mask a defect; the three test-side corrections made during this audit are
listed in §Deviations (each fixed a wrong EXPECTATION, not the code).

## Issue-by-issue verdict

### 1. FULL (E-arm) replay predicted as cache reuse — REPRODUCED & FIXED

Reproduction (from the committed V1 evidence, and live before the fix):
FULL candidates carried dcost == LOCAL's (900 == 900) and identical μ —
`state.judge()` marked the replayed e1/e2 as identity-unchanged cache
hits, and the predictor honored that, while the ACTUAL M4 execution
charges every replayed node (no cache substitution). Prediction
under-counted exactly the nodes the replay must pay for.

Fix: in `_score_and_pick`, a FULL candidate's execute set is forced to
`new_call=True` for every node before prediction (policy.py, phase-3
fix 1). New counterexample test `p3_1_*`: a constructed FULL-WINS
scenario (q_observed_done=0.70 makes every LOCAL variant quality-infeasible
while the all-fresh replay passes Q_min) in which:
- FULL is chosen and its predicted dcost (4 charged calls, 400 tokens)
  is STRICTLY above LOCAL's maximum (3 calls, 300) — the defect is
  structurally impossible to regress silently;
- **prediction↔execution reconciliation**: predicted physical requests
  (4) == actual post-decision physical calls (4: e1,e2,r in the plan
  stage + PENDING v in its planned V1 stage under the chosen π);
  predicted tokens (400) == actual metered tokens; predicted switch
  overhead (9.5 s) == actual Σ switch events; execution order matches the
  topological plan; recovery outcome settles q=1 with c_full = 3 planned
  + 4 replay calls.

### 2. Switch time absent from P90; quantile-sum assumption unbounded — REPRODUCED & FIXED

Reproduction: V10's tight case previously passed only through the
DEGENERATE path — μ_E2E (service+switch=23.5) exceeded the service-only
p90 (18), σ<0 collapsed E1 to a point mass. Exactly the reviewer's
anomaly.

Fixes (policy.py + predictor.py, phase-3 fix 2):
- Deterministic switch overhead now shifts mean AND p90 together
  (`p90_e2e = p90_service + switch`); σ is shift-invariant, so the
  anomaly cannot arise from the composition itself. Test
  `p3_2_p90_shifted_with_switch` asserts `p90 == service_p90 + switch`
  and `p90 ≥ μ_E2E` on a nonzero-switch run.
- p90 aggregation is now a DECLARED choice with two tested modes:
  `quantile_sum` (default; under the declared independence+normal family
  it OVERSTATES the true path p90 since sqrt(Σσ²) ≤ Σσ, so the derived
  on-time probability is a CONSERVATIVE LOWER bound — used for the
  operator's golden scenarios, whose tables assume quantile addition)
  and `variance` (exact independent-normal aggregation,
  p90 = μ + 1.2816·sqrt(Σσ²)). Test `p3_2_aggregation_modes` verifies
  both closed forms and that quantile_sum ≥ variance.
- A profile with p90 < mean degrades exactly to the point-mass semantics
  (P ∈ {0,1} exactly, no crash) — `p3_2_anomaly_point_mass`.
- V1/V8/V9/V10 goldens: **unchanged and passing** (the shift is zero in
  the golden world by construction; V10 now passes through the regular
  distributional path instead of the degenerate one).

### 3. Expected vs realized lateness normalization mismatch — REPRODUCED & FIXED

Expected used d_remain as the denominator; settlement uses the frozen
task duration D. Fixed: `expected_rtask` normalizes by `d_total`
(= deadline − release), with d_remain used ONLY for the on-time
feasibility comparison (reward.py + policy.py, phase-3 fix 3). Test
`p3_3_expected_uses_D_total` verifies the score against the closed form
with D_total and would fail under the old d_remain denominator.
C_new (decision) vs C_full (settlement) separation re-asserted.

### 4. Vacuous session-success condition — REPRODUCED & FIXED

`all(q >= 0)` was always true for 0/1 quality. Fixed to the frozen
definition: every task **correct AND on-time AND not degraded**
(reward.py, phase-3 fix 4). Tests: `p3_3_settlement_cases` (four cases:
correct+on-time → r_task +0.9375 & terminal +1; wrong completion →
negative; timeout completion → −2.1625 exactly (0 − cost − lateness −
timeout-flag); EARLY_STOP → q=0, degraded, negative) and
`p3_3_session_terminal_fixed` (+1 only for the all-good session; −2 for
wrong / late / degraded sessions).

### 5. Cross-task causality (instruction §四.4) — implemented & tested

- **Budget double-promise**: a COMMITMENT ledger was added — the chosen
  candidate's ΔC reserves immediately (`state.committed_tokens`), physical
  calls drain the reservation as they land, and `b_remain = allocation −
  spent − committed`. Test `p3_4_no_double_promise`: two faulted tasks,
  shared 1500-token budget — task 0's choice (900) leaves task 1 with
  b_remain 0 → task 1 degrades with recorded budget deficits; the
  commitment algebra (`committed == max(0, reserved − landed)`) is
  asserted in `p3_4_budget_reconciles`. Honest note: the reservation is
  the PREDICTED cost (node-profile token P90s), deliberately
  conservative when profiles exceed the engine's metered per-call cost.
- **Re-fault after recovery**: r recovered at post_R1, then v faults at
  V1 → the post_V1 decision round fires, recovers v on the alternative
  model, and settles q=1 with budget/state correctly updated
  (`p3_4_refault_redecides`).
- **E2E口径**: settlement T equals completion−release exactly on the
  multi-task run, and is strictly positive on the nonzero-latency run
  (`p3_4_e2e_from_release`).
- Future info / gold / fault-registry exclusion: unchanged M2/M3
  firewalls, re-covered by the regression suites.

## Ledger consistency (deliverable)

The FULL-wins reconciliation table (predicted vs actual: requests,
tokens, switch, order, outcome) is stored in
`evidence/P3_EVIDENCE.json::reconciliation`. All six suites' evidence
files carry `zero_model_calls: true`; every suite runs socket-blocked.

## Deviations during this audit (test-expectation corrections)

1. FULL reconciliation initially counted only `plan:FULL` calls — the
   predicted set correctly includes the PENDING node, which executes in
   its planned stage under the chosen π; the reconciliation window is now
   "all post-decision physical calls of the task".
2. The timeout-settlement golden used 0.125 (a 1000-token cost) while the
   crafted state spends 500 → 0.0625; the code was right.
3. The e2e assertion originally demanded T>0 on a zero-time profile run
   (where T==0 is correct); it now asserts the definitional identity
   there and T>0 on a nonzero-latency run.

## Still NOT supported (paper-claim boundaries)

- Everything runs on SYNTHETIC priors. The 141/141 result proves
  prediction/execution/settlement SEMANTIC CONSISTENCY and decision
  logic — it is NOT evidence of empirical quality/cost/latency gains on
  real models, and NOT evidence of superiority over static recovery
  (that requires the separately-gated real experiments with calibrated,
  pre-frozen weights).
- quantile_sum remains a conservative convention (declared, tested);
  choosing it vs `variance` (and P8 correlation modeling) is open for
  the calibration phase.
- OPEN items B3 (per-task allocation policy), P8, P9 values, P10
  (switch variance) remain open, unchanged.

**Status: phase-3 zero-call audit COMPLETE, all gates green (141/141).
Stopped per instruction — real-model experiments remain HOLD pending
their own authorization.**
