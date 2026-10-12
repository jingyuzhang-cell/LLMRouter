# DEADLINE_RELIABILITY_READINESS — E2E prediction-reliability preparation report

Zero real model calls. Data basis: the completed supplementary run
(`run_20261012_092146`) ledgers ONLY, plus the 1200-call calibration and
formal trajectories for context. Nothing below adjusts frozen
parameters; no measurement is started.

## 1. Is the timing record complete? — **PASS**

| record | present | check |
|---|---|---|
| per-call t_start/t_end/latency_s/usage | 702/702 | no missing fields |
| call_start events (queue-entry marks) | 702 | 1:1 with calls |
| switch events incl. wall_s, from/to, task attribution | 37/37 | cold-start vs switch distinguished |
| task summaries (t_first/t_last/wall/service/switch) | 200/200 = 10 cells × 20 | per cell |
| panel_start t_release | 10/10 | per-cell release anchor |
| DISPATCH reserve/settle unix timestamps | 124/124 | per-attempt accounting |

Service reconciliation: per-task Σ(latency) vs recorded service_sum —
0 mismatches in the checked sample. Actual per-task E2E is fully
reconstructable; under the shared serial executor the median task E2E
is 143 s of which the median cross-task wait is 125 s (service ~5 s;
switch attribution per task) — queueing dominates and is reconstructable
from the interleaved timestamps, so the E2E ledger is auditable end to
end.

## 2. Predicted-vs-actual E2E audit — **CONDITIONAL (persistence gap)**

What was persisted per decision: mode, degraded, pool_size, chosen
(arm, π), violations (constraint deficits). What was NOT: the scored
rows' `mu_e2e`, `p90`, `p_on_time`, `estimator`, `estimator_claim`
(trimmed when writing CELL_RECORDS/arm_decision). Therefore the
decision-time predicted E2E cannot be compared 1:1 against realized
times from the artifacts alone — recomputation would be an offline
reconstruction, not an audit of what the policy actually saw. No
double-counting was found in anything recorded (per-call latency ==
t_end − t_start; switch wall measured around real stop/start; service
and switch sums reconcile). All decisions in this run had d_remain ≫
mu_e2e (D=3600 scaffolding) so on-time coverage at THIS deadline is
vacuous (100% trivially) — uninformative for tight deadlines by design.

## 3. Claim separation — **PASS (in code), CONDITIONAL (in artifacts)**

The estimator/claim split (normal = declared parametric estimate;
lognormal = Fenton–Wilkinson approximation; empirical = declared-model
lower bound via staircase + Markov) is enforced in `policy._score_and_`
`pick` rows — but those fields were among the trimmed ones (§2), so the
run artifacts do not carry per-decision claim labels. Fix = the same
persistence repair.

## 4. Preliminary zero-call coverage audit (with caveats)

Declared per-cell P90s (from the 1200-call calibration, node-isolated
prompts) vs THIS run's physical cascade latencies:

| cell | n | coverage of declared P90 | verdict |
|---|---|---|---|
| e1\|large | 28 | 1.000 | conservative ✓ |
| e2\|large | 30 | 0.900 | on target |
| r\|medium | 31 | **0.774** | UNDER-covers |
| v\|coder | 32 | **0.625** | badly under-covers |
| r\|large | 3 | 0.667 | n too small |

Caveats: different prompt distribution (cascade vs calibration), one
run, small n. Finding (provisional): **the fast nodes' declared
quantiles are optimistic under real cascade prompts** — r and v prompts
embed real facts/expressions and run longer than the calibration's
synthetic inputs. Any tight-deadline experiment run on the current
latency priors would inherit this under-coverage.

## 5. Sufficiency for real-deadline coverage evaluation — **FAIL (insufficient)**

Reasons: (1) only 5 of 10 menu cells have cascade-prompt samples, with
n = 28–32 (r|large n = 3); (2) no deadline variation — every task ran
under the same relaxed scaffolding, so no (D-tier → on-time outcome)
pairs exist; (3) no independent repeats (cache dedup means one sample
per identity); (4) contention observed only in the incidental
stage-batched interleaving, not under a controlled co-residency design;
(5) the predicted-side quantities were not persisted (§2).

## 6. Next-stage independent measurement PROPOSAL (not started; requires authorization)

**Purpose (calibration, not strategy proof):** measure realized service
+ switch + queue times per (node, model) under REAL cascade prompts,
and realized on-time outcomes under controlled D-tiers, to evaluate
predicted-mu/P90/p_on COVERAGE — no arm selection, no superiority
claims, frozen parameters untouched.

**Design sketch:**
- Panel: fresh disjoint 20–30 tasks from the frozen200 remainder
  (isolation rules as before: exclude evaluation + calibration +
  supplementary panels; seeds frozen; hashes bound).
- Arms: planned-path execution only (X fixed), single-task episodes
  (no cross-task contention) + one controlled 2-task co-residency
  variant to calibrate the contention estimate; the D3 fault condition
  optional for path-mix variety.
- D-tiers: 3 tiers bracketing the planned path's empirical P50/P90/P99
  (derived from THIS run's measured service+switch sums), frozen
  before the run.
- Persistence prerequisite (gate): full decision rows persisted
  (mu_e2e, p90, p_on_time, estimator, estimator_claim) — the §2 repair.
- Optional prerequisite (operator decision): the M5 LOCAL fix + SS
  no-match semantics ruling — otherwise recovery decisions stay
  e-failure-blind and the deadline experiment would test a crippled
  action space.
- Latency re-derivation: r/v cells re-quantiled from cascade-prompt
  samples (this proposal's own output), replacing the node-isolated
  calibration quantiles FOR PREDICTION ONLY (new frozen version with
  rationale; PRIORS_REAL_V1 untouched).

**Budget proposal (upper bounds):** ~30 tasks × 4 nodes ≈ 120 base
calls + D-tier repeats (service re-measured per tier only where cache
identities differ — deadline changes do NOT change call identities, so
physical calls ≈ base 120 + retry variance ≈ 200 total; the D-tier
manipulation reuses cached service times and recomputes deadlines
zero-call for tiers within the same execution) → caps: 400 requests /
300K tokens / 3,600 s wall. Coverage reporting: per-cell empirical
coverage with Wilson CIs; declared-quantile coverage target 0.90 with
acceptance band [0.80, 1.00] at n ≥ 25 per cell.

**Admission conditions (all zero-call verifiable):** freeze file with
panel/fault/tier definitions + hashes; freeze-manifest extension over
the tier logic; full-row persistence repair landed and regression-green;
stub rehearsal incl. e-failure scenarios; preflight PREFLIGHT_PASS;
explicit operator GO.

## 7. Verdict table

| item | verdict |
|---|---|
| Timing-record completeness | **PASS** |
| No double-counting in recorded quantities | **PASS** |
| Predicted-vs-actual 1:1 audit from artifacts | **CONDITIONAL** (decision-row persistence gap) |
| Claim labels in artifacts | **CONDITIONAL** (same gap) |
| Preliminary quantile coverage | **CONDITIONAL/FAIL** (r|medium 0.774, v|coder 0.625 — declared quantiles optimistic on cascade prompts) |
| Sufficiency for real-deadline coverage claims | **FAIL** (5/10 cells, no D variation, no repeats) |
| Next-stage plan drafted, nothing launched | **PASS** |

**Stopped per instruction. No real deadline experiment is started, no
frozen protocol changed; all findings and the proposal await operator
review.**
