# M3_ERRATA — four boundary fixes per operator review (M4 remains HOLD)

Baseline: commit e113a4e (M3). Review verdict: direction correct, 23/23
evidence confirmed, but four boundary problems must be fixed before M4.
This errata implements exactly those fixes + the on_incomplete hardening +
targeted regression tests. Zero real model calls; M4–M6 not started.

## Fix 1 — FAILED results are never successful cache reuse (blocking)

`dag_closure.evaluate_plan`: a node with status FAILED that re-executes is
now ALWAYS a real new attempt — `new_call=True`, `changed=True` (so cached
downstream results that consumed the failed output are invalidated), with
reason `failed_retry_new_call:<node>`; the same-model/same-input case can
never return a success cache-hit. `reuse` now admits **DONE nodes only**.
A FAILED node left out of R is flagged `failed_node_not_recovered:<node>`
(an audit note — accept-the-failure plans remain adjudicable; the POLICY
decides, M6).
Tests: `f1_failed_retry_not_cache_hit`,
`f1_failed_retry_invalidates_downstream` (retry invalidates r,v),
`f2_failed_r_not_reused` (r's failed output never reused; r ∉ reuse).

## Fix 2 — upstream change invalidating a RUNNING downstream ⇒ reject (blocking)

After change propagation, any RUNNING node whose parents changed makes the
WHOLE candidate illegal: reason `running_downstream_invalidated:<nodes>`.
No silent continuation, no automatic cancel/restart (none authorized).
Tests: `f3_running_r_invalidated_rejected` (e1 model change while r runs),
`f4_running_v_invalidated_rejected` (r model change while v runs), plus
positive control `f3_control_unrelated_plan_legal` (an unrelated plan on
the same state stays legal).

## Fix 3 — frozen per-node model menus (blocking)

`MENUS`: e1/e2 ∈ {medium, large, coder}; r ∈ {medium, large};
v ∈ {coder, large} (from audited production paths). π is rejected AT
ADJUDICATION with `model_off_menu:<node>:<model>` — not at execution time.
Tests: `f5_r_coder_off_menu`, `f6_v_medium_off_menu`.

## Fix 4 — input signature covers the real static context (blocking)

`dag_closure.ctx_signatures(task)` → per-node static-context sha
(e1 ← ctx_table, e2 ← ctx_text; r/v consume parent outputs only).
`dag_closure.input_signature(uid, node, ctx_sha, parent_answers)` now
includes the node's ctx sha alongside uid/node/parent outputs — same uid
no longer implies same identity. The ENGINE computes `input_sha` at call
time over exactly what the call consumes (no future information) and
records it in `call_start`/`call` events; SchedulerState stores
`(model, input_sha)` from the event (single source of truth — replay,
snapshots and live state share one口径). `judge()` passes the task's
CURRENT ctx sha + cached answers so the adjudicator compares the frozen
identity against the current one: static-context drift ⇒
`input_identity_changed:<node>` ⇒ new call + downstream invalidation.
Tests: `f7_ctx_change_breaks_identity` (same uid, ctx A→B: identity
changes, r/v invalidated; complete-mode executes e1 as a NEW call),
`f7_same_ctx_cache_hit` (same ctx ⇒ genuine cache hit),
`f8_signature_deterministic`.

## Hardening — on_incomplete entry validation

`evaluate_plan` rejects any `on_incomplete` other than reject|complete AT
ENTRY — before candidate evaluation — so an illegal value can no longer
pass unnoticed on plans without invalidations. Test:
`f9_on_incomplete_entry_validated`.

## Code diff summary (e113a4e → this commit)

- `dag_closure.py`: MENUS + menu check; FAILED-retry semantics; reuse =
  DONE only; RUNNING-downstream rejection; entry validation of
  on_incomplete; `ctx_signatures` + new `input_signature` (ctx-aware);
  ctx-drift comparison in the cache-hit path (`input_identity_changed`).
- `stub_engine.py`: computes ctx sha + input_sha at call time; `input_sha`
  recorded in call_start/call events; `ctx_sha` in panel_start (per-task);
  imports sibling `dag_closure` (single signature formula — see note).
- `scheduler_state.py`: exec_identity from engine event `input_sha`;
  stores per-task ctx_sha; `judge()` passes uid + current ctx + cached
  answers.
- `test_stub_engine.py`: engine import whitelist gains the sibling
  `dag_closure` (still stdlib+sibling only; no production/network imports;
  no behavioral assertion relaxed — all 21 original checks unchanged).
- `test_dag_closure.py`: +12 errata checks (35/35 total).

## Test results

M1 21/21 · M2 24/24 · M3 35/35 — all suites idempotent re-runs, zero real
model calls (`zero_model_calls: true` in every evidence file), socket
disabled. No previously-passing assertion was modified or relaxed; the two
test-expectation corrections during development (e2 branch reusable in
S1/S2; ctx-change default-reject semantics in F7) fixed WRONG EXPECTATIONS
against correct adjudicator behavior and are recorded above.

**Status: M3 errata complete; paused for operator review. M4/M5/M6 and any
real-model work remain unauthorized.**
