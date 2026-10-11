# BOUNDARY_AUDIT_REPORT — phase-3 final boundary audit (zero calls)

Baseline: commit b14c8fb. Authorization: operator boundary instruction
(2026-10-11) — four tasks only, zero real model calls, no changes to the
frozen mainline / V1/V8/V9/V10 goldens / Formal evidence. Result: **both
residual defects reproduced & fixed; both pre-experiment conditions
implemented & tested. Seven suites 156/156 ALL PASS.**

## Task 1 — budget-reservation ownership: REPRODUCED & FIXED

Reproduction (arithmetic of the old global scalar, b14c8fb
`scheduler_state._on_call`): task A reserves 900; task B's unreserved
100-token call executed
`committed_tokens = max(0, committed_tokens − 100)` → 800 — B's call
WRONGLY released A's reservation; conversely a 900-reservation of which
only 300 landed stayed occupied forever (no plan-end settlement).

Fix: a per-task, per-decision FIFO reservation ledger
(`state.reservations = {uid: [(seq, amount), …]}`):
- `reserve(uid, amount)` at each feasible decision (own task only);
- `_on_call` drains **only the calling task's** reservations, FIFO;
- `release_reservations(uid)` at plan end / degradation / pre-settlement
  returns unused residuals to the pool;
- overspend beyond the reservation honestly eats the global pool:
  `b_remain` may go NEGATIVE — never silently topped up — and subsequent
  decisions see budget deficits.

Tests (`t1_*`): foreign call leaves committed identical across the
snapshot pair; own plan call drains own reservation exactly; conservation
invariant
(spent + committed + available == allocation) holds at EVERY mid-run
snapshot; residuals released at settlement (committed == 0); the
overspend counterexample (cheap reservations vs real metering) drives
`b_remain` to **−50** (replayable ledger:
`evidence/BOUNDARY_EVIDENCE.json::detail.t1.overspend_b_remain`;
reservation 100 vs 200 real metering on a 450 allocation) and the
post_V1 re-decision degrades with recorded budget deficits.

## Task 2 — probability-conservatism applicability: IMPLEMENTED & TESTED

The reviewer's distinction is now explicit in code, docs, and every
decision row:

| Claim | Conditions |
|---|---|
| path-p90 UPPER bound (quantile_sum ≥ true path p90) | declared per-node normal profiles + independence (σ_qs = Σσᵢ ≥ √Σσᵢ²) |
| on-time-probability LOWER bound | the above **AND D ≥ μ** — below the mean, the inflated σ RAISES P(T≤D) |

Tests: the reviewer's exact counterexample (μ=20, D=18: σ=2 → 15.9% vs
σ=3 → 25.2%, `t2_d_below_mu_counterexample`); every decision row now
carries `p_conservative` — asserted True on feasible rows when D ≥ μ,
False on all D < μ rows (`t2_annotation_*`), True for the exact
`variance` mode. Formal experiments: prefer a distribution-aggregation
method validated for the data, and calibrate predicted probabilities
(both modes now auditable per row).

## Task 3 — cross-task time contention: IMPLEMENTED & TESTED

The predictor now includes a DECLARED contention penalty:
`contention = Σ_{other tasks} remaining_work_est` — each co-task's
remaining planned/recovery work (initialized before any decision from
the priors' v mean PLUS a full switch allowance, replaced by that task's
chosen-plan estimate once it decides, cleared as its stages land). It is
an ESTIMATE, not an unconditional bound: it upper-bounds the co-task's
real remaining work only when that work (service + its switches) stays
within the estimate. The row records it explicitly; nothing is silent.
(See BOUNDARY_ERRATA.md — the tight deterministic sample exposed and
fixed two real estimator gaps.)

Counterexample test (`t3_bound_flips_approval`, real switch costs, two
tasks sharing the timeline; numbers ALIGNED to the post-errata evidence,
commit 83ec860): **D_total = 32.7 s, decision-time d_remain = 26.0 s**
(read from the decision event — never the initial deadline). At that
SAME moment, candidate B SOLO (μ=23.5, p90=24.5) has **P = 0.9993 ≥
0.90** (approvable), while WITH the **10.0 s** contention addend (v mean
7.0 + full switch allowance 3.0 for the co-task's planned binding,
frozen priors) it is **P ≈ 4e-9 < 0.90** — correctly infeasible on
`on_time`, exactly the "预计按时、实际因交错超时" failure the reviewer
demanded prevented. (The pre-errata text here said D=26 / 7.0 s — it
mixed the initial deadline with the pre-allowance estimate; the
replayable values are those above and in
`evidence/BOUNDARY_EVIDENCE.json::detail.t3`.)

Coverage: across THREE deterministic scripted samples (different fault
positions, different latency regimes incl. per-node latencies equal to
the priors' means), every CHOSEN cross-task plan's ACTUAL elapsed time
(real interleaved clock, with the co-task's calls and switches verified
inside the window) falls within its predicted p90.

**Three-way claim discipline (binding for the paper):**
1. **Per-call switch overhead — STRUCTURAL bound**: on the shared serial
   executor each of my new calls needs at most one stop+start. Provable
   from the executor model; prior-independent.
2. **Cross-task contention — HEURISTIC ESTIMATE from synthetic priors**
   (v mean + full switch allowance, or the co-task's chosen-plan
   estimate): upper-bounds the co-task's real remaining work only when
   that work stays within the estimate. Declared per decision row;
   never presented as a bound.
3. **On-time probability under REAL distributions — NOT ESTABLISHED**:
   the 156 passing checks are deterministic-sample coverage plus
   declared-family arithmetic; they do NOT constitute a probability
   guarantee for real model latencies. Establishing it requires the
   separately gated calibration (phase 4) with validated aggregation
   and calibrated probabilities. No paper text may claim otherwise.

## Task 4 — latency-profile legality: IMPLEMENTED & TESTED

`validate_node_profiles` (run at episode start): a declared NORMAL
profile with p90 < mean is statistically contradictory and is REJECTED
by name — never silently coerced to the point-mass model for formal
feasibility (the b14c8fb behavior). p90 == mean remains the legal
zero-variance limit; family = deterministic is an explicit point mass.
Tests: illegal profile (v|large mean 9 > p90 8) raises with the profile
named (`t4_illegal_profile_rejected`); legal sets pass; the phase-3
suite's former "anomaly → point-mass" check was updated to the mandated
semantics (rejection) and a legal zero-variance point-mass check was
added — a behavior change REQUIRED by this instruction, not a relaxed
assertation.

## Evidence & regression

Seven suites, all socket-blocked, `zero_model_calls: true` in every
evidence file: M1 21/21 · M2 24/24 · M3 35/35 · M4 25/25 · M5+M6 18/18 ·
phase-3 19/19 · boundary 14/14 = **156/156**. The V1/V8/V9/V10 goldens
are untouched and passing (single-task scenarios: contention = 0). Two
phase-3-suite checks were updated where THIS instruction changed the
required behavior (profile rejection; reservation release semantics) —
both tighten, neither relaxes. Per-task snapshots with the conservation
invariant and the FULL/prediction reconciliation tables are in
`evidence/BOUNDARY_EVIDENCE.json` / `P3_EVIDENCE.json`.

## Still NOT supported (paper/claim boundaries — unchanged)

- All priors remain synthetic: these 156 checks prove accounting and
  probability-semantics correctness, NOT empirical performance.
- quantile_sum conservatism is conditional (D ≥ μ) and now labeled as
  such; formal experiments must validate/calibrate the aggregation.
- The contention penalty is a DECLARED HEURISTIC ESTIMATE from synthetic
  priors (see the three-way claim discipline in Task 3), not a general
  queueing model and not an unconditional bound.
- Real-model experiments, production integration, Formal/net-benefit
  evidence: untouched, still gated.

**Status: boundary audit complete, all four tasks closed, 156/156.
Stopped per instruction — real-model experiments remain HOLD pending the
Formal settlement audit, net-benefit gates, and a separately authorized
calibration plan.**
