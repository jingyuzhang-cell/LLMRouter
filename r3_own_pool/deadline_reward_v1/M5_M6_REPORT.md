# M5_M6_REPORT — dynamic model reassignment + two-stage reward policy

Authorization: operator directive "继续跑实验直到跑通" (2026-10-11), read
as completing the zero-call stub pipeline M5+M6 (the real-model gate is
unchanged and requires its own authorization). Result: **the frozen
mainline decision loop is now executable end-to-end and every operator
acceptance scenario passes.** Suites: M1 21/21 · M2 24/24 · M3 35/35 ·
M4 25/25 · M5+M6 18/18 — **123/123 checks, zero real model calls.**

## The closed loop (MAINLINE_FREEZE, now executable)

detection (occurred D-observations only) → legal info (SchedulerState view
+ LIVE D_remain / B_remain) → joint candidates a=(Z, R, π) (recovery
recipe × model assignment over the frozen per-node menus, M3-adjudicated
for dependency legality) → **filter** (q̂≥Q_min, P̂(T≤D_remain)≥1−ε via
E1 on the composed E2E belief, ΔC≤B_remain) → **argmax Ê[R_task]** →
execute through the M1 engine (M4 recovery semantics) → feedback →
settlement (gold at settlement ONLY; C_new at decisions, C_full at
settlement, never mixed). Empty feasible set ⇒ **EARLY_STOP** with the
full violation vector and ZERO further calls for the task.

## New modules

| File | Content |
|---|---|
| `predictor.py` | Per-joint-action prediction: whole-DAG q̂ (weakest-link composition over the final answer path, `q_observed_done` boost for reused DONE nodes, failure floor for unrecovered FAILED; product mode also implemented), ΔC = Σ p90-tokens over new calls, critical-path service (μ, p90). `e1_on_time`: the CORRECTED closed form + degenerate point-mass. All synthetic PRIORS, no calibration claim. |
| `compensator.py` | D_remain (clock + task deadline, live), B_remain (real spend, never constant), switch-overhead ownership (cold start = start-only), composed ONCE into μ_E2E at the policy (B6). |
| `reward.py` | Realized R_task (frozen formula; gold only at settlement) + Ê[R_task] (C_new semantics) + `settle()` → REWARDS.jsonl (per-task q/C_full/T/D/degraded + one session terminal term). C₀>0 enforced. |
| `policy.py` | Candidate enumeration (NONE: π over pending; LOCAL: retry failed nodes + closure-completed + **π free over execute∪pending — the M5 capability**; FULL: E-arm replay semantics with trigger-node menu variants), two-stage scoring with full audit table in the ledger (`decision` events: every candidate's q/μ/p90/P̂/ΔC/score/feasible/deficits), D9 tie-break, D10 EARLY_STOP + violations, `apply_decision` (PENDING nodes run in their planned stage under the chosen π — never duplicated), `run_episode` driver (planned stages → decision rounds post-R1/post-V1 → settlement). |

PRIORS: `policy` section (Q_min/ε/λ/C₀/composition — all
`stub_test_only`, formal weights await independent calibration per D3),
`node_profiles` (synthetic per-(node,model) q/lat/tokens),
`golden_zero` engine profile (zero-time, metered tokens — makes the golden
scenarios' d_remain exact).

## The operator's four acceptance classes — all pass

**V1 time-tight golden (A/B/C), two scenarios.** D_remain=20, Q_min=0.80,
ε=0.10. Predictions land exactly on the operator's table — A(24s, q̂.95,
excluded on_time), B(17s, p90 18, q̂.85), C(12s, q̂.60, excluded q_min) —
and **B is chosen** (LOCAL, π={r:large, v:coder}), executed for real
(r re-escalated on large; v ran on coder), settled with q=1. Scenario 2
(B p90=21): P̂=0.832<0.90 → B EXCLUDED; feasible set empty → **EARLY_STOP**,
every candidate's violation vector recorded, **zero further model calls**
for the task, settlement flagged degraded. Never a forced B — the
uncertainty trap is pinned.
**V8 time-rich tradeoff.** D=60: A and B both feasible; λ_c=0.5 → A
(higher quality wins), λ_c=2.0 → B (cheaper wins) — BOTH regimes pinned,
score difference matches the Ê[R_task] arithmetic exactly (no fixed
preference).
**V9 budget-insufficient.** Allocation 1000: every quality-passing
candidate over budget → EARLY_STOP with budget deficits recorded.
Allocation 1350: A unaffordable (deficit recorded), B affordable → chosen.
**V10 M5 decisive test.** SAME fault, real PRIORS (nonzero switch costs),
D=60 vs D=32: chosen arm identical (LOCAL), R identical ({r}), **π differs
exactly on v** (large when time-rich, coder when tight) — the system
changes downstream node MODELS by remaining time; a recovery-mode-only
implementation cannot pass this.

Also passing: E1 closed-form goldens (incl. degenerate σ→0 and the
p90=21 boundary), settlement goldens (T=D boundary; timeout decomposition;
C_new=900-at-decision vs C_full=500-at-settlement separation), bitwise
determinism, zero-call sentinel, socket-blocked suite.

## Honest notes

- Quality composition 'min' (weakest link) is the stub-golden convention
  frozen in PRIORS; the product mode exists; choosing between them (and
  P8 correlation modeling) is a phase-3 question. Priors are SYNTHETIC —
  passing V1/V8/V9/V10 proves the DECISION LOGIC and the mainline loop,
  not any empirical superiority (per the operator's paper-claims ruling).
- Per M5 scope: policy π touches only R ∪ PENDING nodes (DONE nodes
  immutable unless re-executed — M3 judge enforces); menus are the frozen
  audited per-node menus.
- Remaining OPEN items (B3 allocation granularity, P8 correlation, P9
  observed-state rule values, P10 switch variance) are unchanged and do
  not block phase-3 review.

**Status: the phase-2 stub pipeline M1–M6 is complete and fully green
(123/123, zero real calls). Next gates, per standing authorizations:
phase-3 verification review → real-model experiments (separate
authorization + Formal/net-benefit gates).**
