# PHASE_P0_REPAIR_AUDIT — M5 closure fix, decision-log hardening, SS semantics

Operator ruling 2026-10-12 (baseline f0b3e5e). Zero real model calls; no
GPU; frozen reward function / Q_min / eps / lambdas / panels / raw run
artifacts untouched; no strategy experiment started.

## P0-A — M5 LOCAL enumeration fix: DONE, PASS

`reassign.enumerate_candidates` now constructs **R_eff = failed ∪
closure** explicitly (closure = DONE nodes the M3 change-propagation
invalidates and re-executes; PENDING nodes are first executions, never
re-executions) and enumerates π jointly over **R_eff ∪ PENDING**:
- every π-assigned node is inside R — no illegal rebinding of finished
  nodes (`done_node_model_change_without_reexec` can no longer fire for
  LOCAL);
- closure nodes stay dynamically reassignable within their menus — the
  fix does NOT freeze closure models (the workaround the ruling
  rejected);
- M3 core cache-identity rules untouched (`dag_closure.py` unmodified).

Behavioral compatibility:
- **r-only failures: bit-identical** to pre-fix behavior (closure empty
  → R_eff = failed; π domain {r, v}; 4 LOCAL candidates) — asserted in
  `test_m5_closure_fix.py` (REG_r_only_*);
- **e-failures: LOCAL now REACHABLE** — closure nodes execute with kind
  `fbd` (aligning with M4's R2 refresh semantics; previously they ran
  'plain');
- **M4 static reference**: test_recovery (T3a/T3b equivalence vs the
  production evaluator semantics) passes 28/28; M5/M6 suites and the
  V1/V8/V9/V10 goldens (test_m6, test_policy) pass unchanged — the
  explicit-R completion does not alter any previously-reachable
  execution trajectory (those scenarios were r-only).

Six mandated stub scenarios + regressions — `test_m5_closure_fix.py`
**25/25** (evidence `M5_CLOSURE_FIX.json`):
S1 e-FAILED/r-DONE/v-PENDING: LOCAL exists, closure {e2,r} inside the
execution set, v pending-only, SS static pick EXISTS (the previously
missing recipe). S2 e-FAILED with r AND v DONE: full closure {e2,r,v}.
S3 e+ r both FAILED: kinds fb/esc correct. S4 applied recipe REALLY
re-executes e2 (fb, no_cache) and refreshes r (fbd) — the actual call
sequence is asserted. S5 RUNNING downstream → zero LOCAL candidates and
SS records STATIC_RECOVERY_UNAVAILABLE (never a silent NONE). S6
fixed-model vs dynamic LOCAL: both legal, and the executed call
sequences differ (models + refreshed inputs). REG: r-only unchanged.

## P0-B — full decision-row persistence: DONE, PASS

- `policy._score_and_pick` rows now freeze the joint action's
  adjudicated identity at decision time: `execute` (node, new_call)
  list, `reuse`, `judgment_reasons`, per-node `families` — alongside
  q̂, ΔĈ, μ̂_E2E, P̂90, P̂_on, Ê_late, estimator + claim, violations,
  Ê[R_task] (=score).
- `arm_entry.decide_arm` passes rows through UNTRIMMED.
- `run_cell` appends the complete `arm_decision` event with
  decision_id / decision_unix / d_remain / b_remain_tokens / chosen
  (incl. E_R_task) / violations / full table — **before any execution**
  of the task's plan (ordering asserted: decision event index <
  plan-stage call index).
- Oracle prohibitions asserted: no gold / fault / actual / future keys
  in any decision row (P0B_no_oracle_fields).
- Counterfactual boundary honored by design: unexecuted candidates keep
  predictions only; the correlation id joins ex-ante rows to the
  subsequent executed calls (task + condition|arm|uid + stage names).

## P0-C — SS exception semantics: DONE, PASS

SS remains exactly "fixed LOCAL recovery + fixed planned models" — no
implicit NONE fallback anywhere. With P0-A, an ordinary legal e-node
failure ALWAYS yields the fixed recipe (P0C_ss_executes_fixed_recipe:
chosen LOCAL planned π, not degraded, v exactly once, 6 logical calls =
e1, e2, r, e2-retry, r-fbd-refresh, v). Genuinely illegal states (S5
RUNNING downstream) record `STATIC_RECOVERY_UNAVAILABLE` with the
degradation and settlement kept honest — implementation defects can no
longer masquerade as strategy behavior.

## P1 — deadline-reliability plan revision: DONE (plan only)

`DEADLINE_RELIABILITY_PROTOCOL_V2.md` implements all eight required
revisions: full 10-cell menu; cascade prompts + switches + measured
cross-task waits + task-level E2E; hard fit/validation panel separation;
formal statistical standard = exact one-sided Clopper–Pearson LB ≥ 0.90
(the 0.80–1.00 band demoted to exploratory-only) with honest n-arithmetic
(n=29 at perfect, ≈110 at 0.95, ≈200+ at 0.93 → two-stage design);
ex-ante predictions with the counterfactual prohibition; this stage's
E2E-derived D-tiers kept strictly separate from V2.3's frozen P40/P60/P80
rules; honest budget insufficiency report (400/300K/3600 inadequate →
PROPOSED 1,200 requests / 600K tokens / 14,400 s, confirmatory stage
gated on a separate zero-call review — nothing auto-raised); new
versioned artifacts with independent hashes, originals untouched.

## Verdict table

| item | verdict | evidence |
|---|---|---|
| P0-A code fix (R_eff explicit, π over R_eff∪PENDING) | **PASS** | reassign.py; REG r-only identical |
| P0-A six mandated scenarios | **PASS** | test_m5_closure_fix 25/25; M5_CLOSURE_FIX.json |
| M4 static-reference compatibility (T3a/T3b) | **PASS** | test_recovery 28/28 |
| M5/M6 + goldens regression | **PASS** | test_m5, test_m6 24/24 (whitelist +4 P0-B fields), test_policy, V1/V8/V9/V10 green |
| P0-B fields + pre-execution persistence + no-oracle | **PASS** | P0B_* checks; arm_decision ledger ordering |
| P0-C SS semantics | **PASS** | P0C_* + S5 reason checks |
| P1 protocol revised (8 rulings) | **PASS** | DEADLINE_RELIABILITY_PROTOCOL_V2.md |
| Full-suite regression | **PASS** | M1–M6, phase-3, boundary, smoke 42/42, repairs 8/8, admission ALL GATES PASS |
| Real-model reliability measurement | **NOT STARTED** | awaiting separate GO |

## Research note recorded (per ruling §7)

The diagnostic distinction — node-anomaly OBSERVATION → execution-
CONTRACT determination → impact analysis → recovery & reassignment — is
now explicit in the audit trail; D5 compares v against r (not gold), so
"detected inconsistency" ≠ "localized the faulty node" (3 concrete
cases in run_20261012_092146). No detector was modified; the distinction
is binding for all future analysis and paper text.

**Stopped per instruction: engineering acceptance complete; no real
calibration, deadline experiment, or strategy comparison is started
without a new explicit GO.**
