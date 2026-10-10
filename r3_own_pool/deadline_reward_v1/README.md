# deadline_reward_v1 — feedback-driven DAG dynamic recovery scheduling (rev B)

**Scope (operator ruling 2026-10-10):** the reward/penalty mechanism targets
the EXECUTION layer — dynamic recovery-action selection (NONE / LOCAL / FULL)
inside DAG task execution under quality–cost–latency constraints. The Formal
six-method configuration search keeps its independent research value and is
NOT this mechanism's object.

Hard boundaries (phases 1–3): zero real model calls; no modification of
Formal/net-benefit code, protocols, ledgers, or results; no fabricated
capabilities (detection = exactly the audited predicates D1–D6); **phase 2
NOT started — this revision awaits human review.**

## Document map (rev B; rev A preserved at commit 0d381a8 as review baseline)

| File | Content |
|---|---|
| `AUDIT_EXISTING_CODE.md` | Part I search layer (rev A evidence, §2.9 + §3 verbatim) · **Part II execution layer**: stage structure, detection predicates D1–D6, LOCAL event table, two FULL semantics, confound ladder, three time quantities, reuse list vs missing-interface list (§II.10), honesty ledger (§II.11) · corrections log (96→48; E1 formula) |
| `DESIGN_REWARD_FUNCTION.md` | R0 = task-level terminal reward; gold enters ONLY terminal scoring (§3.1); online score = Ê[R0\|H,a] at detection points (§3.2); corrected E1 (§3.3); time-ownership no-double-charge (§3.3a); R1 stays demoted |
| `DESIGN_DYNAMIC_SCHEDULER.md` | Architecture (§1), decision loop + policy–static equivalence (§2), SchedulerState full definition (§3), NONE/LOCAL/FULL action interface (§4), transition (§5), compensator unified accounting (§6), confound & ablation design (§7), failure matrix F1–F9 |
| `DESIGN_PREDICTOR_INTERFACE.md` | Per-action prediction contract (q̂, ΔC, μ/w_p90), corrected E1, action-event tables, PRIORS provenance, phase-2 class inventory |
| `VERIFICATION_PLAN.md` | Executable tests L/A/T/B/R-F/Z/P/C with coverage map to the instruction's ten items |

## Corrections carried from rev A (visible, with rationale)

1. Config count 96 → **48** (2⁴ X × 3 Z, evaluator.py:22-26); the search
   space is anyway retired as the test range.
2. Normal lateness expectation: correct form **σ[φ(z)+zΦ(z)]**, z=(μ−D)/σ
   (rev A had z(1−Φ(z)) — agrees only at z=0). Fixed in both docs; P3
   includes a regression tripwire asserting the old form fails.

## Consolidated open decisions (16; defaults proposed)

Reward: D3 (λ, C₀, B, P) · D5 (C₀ granularity) · D6 (E1 family) ·
D8 (q̂ within-episode feedback) · D9 (tie-break).
Scheduler: B1 (FULL semantics — default E-arm matched) · B2 (fb memory-rule
granularity) · B3 (D_task allocation) · B4 (cascade decision granularity) ·
S5 (stub-only exercise).
Predictor: P1/P3/P4 (carried defaults) · P6 (cross-task pooling — default
OFF) · P7 (PRIORS values at phase-2 freeze).

## Phase-2 admission recommendation (deliverable)

**Recommend: ADMIT phase 2 conditionally**, gated on the operator resolving
four decision points before coding starts, since they change module
structure or comparability: **B1** (FULL semantics), **B2** (memory-rule
granularity), **D3** (weights/C₀), **P7** (prior values + provenance notes
for PRIORS.json). All other OPENs may proceed on documented defaults and be
revisited at the phase-3 review.

Phase-2 scope if admitted: `scheduler_state.py`, `outcome_predictor.py`,
`deadline_compensator.py`, the stub execution engine (inside this package,
mirroring audited stage semantics), PRIORS.json freeze, and the full
VERIFICATION_PLAN suite — all zero-call, verified by T3 (policy–static
equivalence) as the engine-fidelity proof. Phase 4 (real models) remains
gated on Formal settlement audit + net-benefit gates + independent
authorization, unchanged.
