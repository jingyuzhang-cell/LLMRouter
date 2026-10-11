# P3_B_REPORT — targeted fixes per the P3-A audit findings

Operator authorization: phase-3 P3-B (2026-10-11, baseline cc9e80d).
Exactly the three approved items; no reward-function, profile,
candidate-generation, or filter changes; no real-model/production/
Formal/net-benefit work. Zero real model calls.

## Fix 1 — `session_summary.calls` double-count (APPROVED item)

`stub_engine.write_session_summary`: `calls` now
`requests_total + cached_calls` (corruption-after-metering calls are
already inside `requests_total`). New conservation regression
(`p3b_calls_field_conservation`, boundary suite): on a run containing
injected + cached + physical calls, `calls` == the number of call
EVENTS, events == requests + cached, injected ⊆ requests, and
requests/tokens_total/settlement unchanged (their values were never
wrong — asserted now explicitly).

## Fix 2 — `expected_tag` unified with the frozen rule (APPROVED item)

`test_m6.py`: the helper is now EXACTLY the product rule —
`quantile_sum`: conservative IFF `d_remain ≥ mu_e2E` (a p_on_time of
exactly 0/1 no longer implies conservatism); `variance`: exact under
the declared independent-normal family (product tags True).
Mandated boundary counterexample added: a D<μ row with p_on_time
EXACTLY 0 (μ=30, p90=31, D=20) is NOT conservative — and its reverse
test (`m6_reverse_boundary_tag_detected`) fails when wrongly tagged.
The two prior reverse tests remain.

## Fix 3 — M6_ACCEPTANCE §6 refresh (APPROVED item)

Section 6 now records the historical 199 → 207 transition (M6 suite
14→22 at 0f7cb46: +3 calibre-independence, +2 reverse-tag, +2
structural-whitelist, +3 counterfactual, −1 vacuous; net +8) and the
current live total. Original evidence files untouched; no results
rewritten.

## Verification (mandated acceptance items)

**Full regression — live count (all nine suites, ALL PASS):**
M1 21/21 · M2 24/24 · M3 37/37 · M4 28/28 · M5 24/24 · M6 **24/24**
· M5+M6 18/18 · phase-3 19/19 · boundary **15/15** =
**210/210** (was 207; +3 new: 2 M6 boundary/counterexample checks, 1
calls-conservation check — listed above; no prior check removed or
relaxed).

**Independent decision re-verification:** the P3-A audit script re-runs
its independent golden math and live-count reconciliation against the
post-fix tree — **PASS 17 · CONDITIONAL 2 · FAIL 0**, with all three
P3-B findings now RESOLVED in-place (R2 doc, B3 helper, E1 calls).
Decisions unchanged: V1-S1 choose-B score +0.737328, V1-S2
EARLY_STOP at P̂=0.831774, V8 flips +0.0625/−0.0500, V10 model switch
by deadline — all identical to the signed-off values (fixes touched a
convenience ledger field and test helpers only).

**Event-level accounting:** requests/tokens/calls/cached/injected and
the settlement reconcile per event (asserted by the new conservation
check and re-confirmed by the audit's E1/E2).

## Remaining CONDITIONAL items (unchanged, binding)

- **B4 family conditionality**: E1 exactness holds only under the
  declared normal family; synthetic validation is NOT real-model
  calibration.
- **T1 time calibre**: quantities reconcile and are recorded
  separately; no untested upper-bound claims are made.

## Status

P3-B complete; the three approved items are fixed, pinned, and
independently re-verified. **Ready for phase-3 final acceptance
review.** Real-model experiments, production integration, and
Formal/net-benefit work remain HOLD — P3-B completion does not
authorize any of them.
