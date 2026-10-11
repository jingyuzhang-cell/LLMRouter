# ADMISSION_REPAIR_REPORT — final admission repairs (operator mandate 2026-10-11)

Review baseline: `9b296726a91f1b3921123a08690c51940f9fe9b2`.
Repair commits (jingyuzhang-cell/LLMRouter, `main`):

- `7db5d33` — all six must-fix items + the eight zero-call test groups
- `380103f` — preflight re-bound at the repair commit (freeze manifest
  over the final code state), `PREFLIGHT_PASS`
- evidence-regeneration commit (timestamps only) on top
- **blocking-review round 2** (operator review of the above): the
  empirical-estimator Cantelli direction error and the non-covering FULL
  test — both fixed, see the addendum at the bottom; preflight re-bound
  at the fix commit.

Real measurement remains HOLD. No `SUPPLEMENTARY_EXECUTE=1`, no
background real calls, no GPU inference were performed for this round.

## Must-fix items — what changed (file → change)

1. **Per-attempt physical budgeting** (`supplementary_runner.py
   RealServer.draw`): every real `call_model` attempt now gets its OWN
   `budget.reserve()`; a failed attempt (returned
   `infrastructure_failure`/missing usage, or a dispatch exception)
   writes an `attempt_failed` event into the budget's append-only
   DISPATCH ledger (id, error, whatever usage existed) and its
   reservation stays CHARGED (never settled, never silently released).
   One reserve never covers two attempts. Budget-stop exceptions
   propagate immediately: the retry loop catches `Exception` only —
   `StopRun` inherits `BaseException` and passes through; a settle
   rejection (invalid usage) never retries.
2. **V double-scheduling** — the execution-level bug was fixed in
   `f0d9772` (apply_decision rule: first executions run exactly once, in
   their planned stage, under the chosen π; plan batches never execute
   PENDING nodes). This round adds the missing scenario coverage: test
   group 4 asserts v-call counts across SS/DS/SD/DD/NONE **and** a
   FULL-plan episode (v still exactly once), plus the cache-hit episode.
   "Old cache overwriting new results" is structurally impossible: the
   cache key is (model, input_sha) and a changed upstream answer is a
   different key; no_cache retries never write the cache.
3. **Complete freeze manifest** (`freeze_manifest`/`verify_manifest`):
   binds the panel freeze, protocol, calibration prerequisites,
   PRIORS_REAL_V1 + families binding, beliefs hash, ELEVEN code files
   (arm_entry, detection, dag_closure, scheduler_state, policy,
   reassign, predictor, compensator, reward, stub_engine, the runner
   itself), PARAMS/CAPS/PLANNED/D_SCAFFOLD, and records git HEAD.
   `execute()` re-derives all of it and refuses on ANY drift — including
   uncommitted modifications to any bound file (live git-status check
   over the bound paths). The enforced objects are the file hashes and
   values (they capture every behavior-relevant byte); HEAD is
   provenance — approving a commit that changes any bound file requires
   re-approval because its hash changes.
4. **Distribution-family alignment** (`predictor.py`, `policy.py`,
   `build_priors`): profiles now carry their audited family from
   `PRIORS_REAL_V1_families.json` (0/40 normal, 12/40 lognormal, 28/40
   empirical). Means are family-true — lognormal `exp(mu_log +
   sigma_log²/2)` and empirical sample means from the audit's saved
   statistics — never p50-by-default. `e1_on_time` is family-aware:
   all-lognormal paths use the Fenton–Wilkinson moment-matched path
   lognormal (closed-form on-time CDF and partial expectation E[(T−d)₊],
   deterministic switch/contention shift included); any empirical node
   switches to the one-sided Cantelli LOWER bound on P(T≤d) with the
   distribution-free σ_LB = (p90−μ)/3 (valid for ANY distribution). Every
   scored decision row records `estimator`. Default behavior for declared
   normal profiles (the stub/golden world) is bit-identical — full M-suite
   regression green.
5. **INCOMPLETE protection** (`write_quality_output`): the official
   `PRIORS_REAL_V1_quality.json` is written ONLY for a COMPLETE run (10/10
   cells + status COMPLETE); everything else goes to
   `PRIORS_REAL_V1_quality_INCOMPLETE.json` with status/reason. Neither
   file is ever silently overwritten (PermissionError).
6. **No reuse of quarantined state**: fresh run directory enforced
   (existing dir → PermissionError naming the no-reuse rule); the engine
   and its identity cache are per-process in-memory (nothing persists
   across runs); the production Budget refuses any pre-existing DISPATCH
   ledger inside the fresh dir. The quarantined run's dir
   (`run_20261011_223149`) is untouched and untraversable by the runner.

## Zero-call test evidence — `evidence/ADMISSION_REPAIRS.json`
(`test_admission_repairs.py`, all groups pass)

| Group | Asserts |
|---|---|
| g1 two-attempt budgeting | 2 dispatches → 2 reservations (1 settled, 1 `attempt_failed` with usage=None), failed reservation retained in `pending`, charged ≥ 2048+150 |
| g2 cap-before-dispatch | request cap exactly reached → next draw refused with `request budget` BEFORE any dispatch (call count 0) |
| g3 stop-no-retry | invalid usage at settle → StopRun, 1 call (no retry); a StopRun-family exception from dispatch propagates intact, 1 call |
| g4 V counts | v exactly once per non-degraded task in SS/SD/DD/NONE, zero for degraded DS; plan batches never contain v; FULL-plan episode v still once |
| g5 manifest drift | tampered file hash → refused naming `file:detection.py`; tampered PARAMS → refused naming `value:params` |
| g6 family estimators | lognormal mean = exp(μ+σ²/2) ≠ p50; Fenton–Wilkinson p_on equals independent recomputation to 1e-12; Cantelli bound ≠ unconditional normal; predictor composes families (all-lognormal → lognormal params, any-empirical → empirical); policy rows carry `estimator` |
| g7 INCOMPLETE protection | interrupted run → official file ABSENT, INCOMPLETE file present with reason; overwrite refused; complete 10/10 → official file |
| g8 cache order audit | two cells on one engine: cell1 4 new / 0 hits, cell2 0 new / 4 hits, invariant logical == new + cache_hits; per-cell metering recorded |

## Regression status

M1 21/21 · M2 24/24 · M3 35/35 · M4 25/25 · M5+M6 18/18 + M6 24/24 ·
phase-3 19/19 · boundary 14/14 · runner smoke 42/42 · admission repairs
8/8 groups · admission check ALL GATES PASS re-verified. M6's row
whitelist gained the `estimator` audit key (documented in-test).
Preflight: **PREFLIGHT_PASS** at `380103f` with the full freeze manifest.

## Budget & cache reconciliation recap

Per-attempt DISPATCH accounting (g1/g2/g3); quarantined run spend
80/1200 requests, 26,462/800K tokens (unchanged, diagnostic-only);
per-cell metering `{new_requests, cache_hits, injected_faults,
physical_tokens, logical_calls}` + `execution_order` +
`cache_order_audit` in every cell record; structural cache plan in
VERIFICATION_GUIDE.md §3 (expected total 150–250 physical requests).

**Status: repairs complete; paused. Real measurement HOLD until the
operator's explicit GO.**

## Addendum — blocking-review round 2 (two fixes)

**1. Empirical estimator: Cantelli direction error (INVALID form removed).**
The previous empirical branch computed Cantelli's lateness bound at a
sigma LOWER bound — but the bound is INCREASING in sigma, so the result
was an over-optimistic number, not a valid lower bound on P(T<=d). The
operator's counterexample (two-point law {0 w.p. .5, 100 w.p. .5}: mu=50,
p90=100, d=90; true on-time 0.5) produced 0.852 — a plan with 50%
on-time could pass a 90% gate. The revised branch uses ONLY
distribution-free statements valid for any law:
- quantile: d >= p90_sum ⇒ P(T<=d) >= 0.90 (inherits the frozen
  independence caveat of quantile_sum);
- Markov (T >= 0): P(T>d) <= mu/d ⇒ P(T<=d) >= 1 − mu/d;
- reported p_on = max of applicable bounds; 0.0 when d <= mu.
The counterexample now yields 0.4444 ≤ 0.5 (valid). e_late for the
empirical family is the valid UPPER bound E[(T−d)+] ≤ mu (T >= 0) —
mu−d is only a lower bound and is never reported as an estimate. The
counterexample is pinned in test group g6; the empirical estimator is
now marked bound-valid, not "statistically accepted" — the normal and
lognormal branches remain labeled parametric estimates/approximations.

**2. FULL test now DETERMINISTICALLY covers the FULL execution branch.**
The previous g4 "FULL" case silently fell back to a note when the policy
picked non-FULL (no coverage). Rebuilt with q_observed_done=0.5 (DONE
e-nodes distrusted ⇒ every LOCAL-scope candidate q-infeasible) and menu
quality tuned so the best FULL_DYNAMIC variant is exactly the static-FULL
assignment — the ARMS tie-break then deterministically selects
arm='FULL'. The test now asserts the execution trace: chosen = FULL with
pi {e1: large, e2: large, r: large, v: coder}; v executed exactly once
(V stage); the plan batch replays e1/e2/r with no_cache=True on every
replay node; PENDING v never enters the plan batch. Evidence in
ADMISSION_REPAIRS.json g4_v_counts.FULL.

Regression after both fixes: full M-suite + runner smoke + admission
checks green; g1–g8 all pass. Zero real model calls.

## Addendum — round 3 (final math fixes, operator mandate)

**1. Quantile-sum on-time guarantee REMOVED (was invalid).** Per-node
P90s do not bound the path P90 for general laws. Operator counterexample
(two independent nodes, each 0 s w.p. .9 / 100 s w.p. .1: per-node
P90 = 0, so p90_sum = 0; deadline 1 s; true path on-time = .81): the old
`d >= p90_sum ⇒ p_on >= 0.90` reported an unfounded 0.90. The empirical
branch now returns

    p_on = max( staircase(ladders, d_eff),  1 − mu_service/d_eff )

where the STAIRCASE bound is max over per-node thresholds t_i of
Π F_i(t_i) subject to Σt_i ≤ d_eff — strictly valid CONDITIONAL ON the
declared per-node empirical distributions (saved 30-sample staircases)
plus independence, because {X_i ≤ t_i ∀i} ⇒ ΣX_i ≤ Σt_i ≤ d_eff; and
MARKOV (T_service ≥ 0, P(T_service > d_eff) ≤ mu_service/d_eff) is valid
conditional on the declared mean. No unconditional 0.90 anywhere; with
insufficient statistics and no ladders, only Markov applies (and 0 when
it gives nothing). The counterexample now returns exactly **0.81**;
four such nodes return 0.9⁴ = 0.6561; a single node at its atom returns
0.9. All pinned in test group g6 (`round3` block in
ADMISSION_REPAIRS.json).

**2. Unified E2E shift interface (no double-counting).** Policy passes
SERVICE-side (mu, p90) plus `shift` (switch + contention) exactly once;
`e1_on_time` applies the deterministic addends internally. The normal
branch is bit-identical to the legacy totals convention (asserted:
e1_on_time(5,7,20,shift=3) == e1_on_time(8,10,20)); the empirical Markov
term uses mu_service against d_eff = d − shift (1−5/7, never the
double-counted 1−8/7).

**3. e_late upper-bound validity at boundaries.** Empirical:
E[(T−d)+] ≤ mu_service for d_eff ≥ 0 ((x−d)+ ≤ x on x ≥ 0) and
= mu_service − d_eff for d_eff < 0 (lateness certain; T ≥ 0 ≥ d_eff);
d_eff = 0 flows through the ≥0 form. Lognormal: dd ≤ 0 returns the
exact certain-lateness value tot_m + shift − d. All boundary cases
tested.

**4. Independent accuracy claims (never approximation-as-bound).** Every
decision row carries `estimator_claim`:
- normal → `declared_normal_parametric_estimate`
- lognormal → `fenton_wilkinson_approximation`
- empirical → `declared_model_lower_bound(staircase+markov)`
`p_conservative` is per-family (empirical True; lognormal False; normal
conditional on D ≥ mu as before).

Regression: full M-suite, runner smoke 42/42, admission repairs 8/8,
admission check ALL GATES PASS; preflight re-bound (PREFLIGHT_PASS).
Commits: `e26c856` (fixes) + `1ae5363` (preflight rebind). Zero real
model calls, zero GPU inference, Formal/net-benefit evidence untouched.
