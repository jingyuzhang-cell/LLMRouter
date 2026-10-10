# deadline_reward_v1 — deadline-constrained feedback-driven DAG dynamic scheduling (rev E)

**Frozen research objective (operator, verbatim):**

> 提出一种面向截止时间约束的反馈驱动异构多智能体 DAG 动态调度方法。在执行异常发生后,系统依据 DAG 依赖关系、节点级模型能力、剩余时间及资源预算,联合优化故障恢复范围与后续节点模型分配,通过按时正确完成奖励、新增执行成本惩罚和超时惩罚,实现质量、成本与时延之间的动态权衡。

Core decision: a_t = (Z_t, R_t, π_t); two-stage filter (Q_min,
P̂(T≤D_remain)≥1−ε, ΔC≤B_remain) → argmax Ê[R_task]; A_feasible=∅ ⇒
**EARLY_STOP** degradation + violation recording.

Version history: rev A @0d381a8 (search-layer draft) → rev B @fc201ae
(execution-layer pivot) → interim rev C @57f2553 (joint-action; review
baseline for the final errata) → rev D @09d6b4d (rev-B review rulings:
P3 retired, E2E口径, L1/L4/C5/T3-references, B1/B2/D3/P7) → **rev E (this,
final errata): D10/D11 rulings, V1 scenario split, T3a/T3b gates,
synthetic-distribution statistical assumptions.** Phase 2 remains HOLD
pending admission confirmation of rev E.

## Operator rulings (2026-10-10 review; SIX, all frozen)

- **B1 (FULL semantics)**: E-arm matched semantics = fixed-policy baseline;
  dynamic model assignment controlled separately, (scope, model-delta)
  recorded separately. → scheduler §4.
- **B2 (memory rule)**: static-equivalence tests keep the ORIGINAL panel
  detection order; the dynamic policy reads only legal observations that
  have ALREADY occurred. → scheduler §4a; test L4b.
- **D3 (reward weights)**: synthetic test constants allowed (labeled);
  formal weights and C₀ frozen only after independent calibration — no
  optimality claim now. C₀ > 0 strictly. → reward §7; V7.
- **P7 (priors)**: synthetic stub priors with recorded source, version,
  and hash; never presented as real calibration. → predictor §5/§8; V7.
- **D10 (no-feasible-action default)**: **EARLY_STOP** — no further calls
  once nothing satisfies the quality/time/budget constraints;
  BEST_EFFORT_QUALITY kept only as a testable ablation under hard budget
  and task-wall constraints. → scheduler §4c; tests F2/F10/V1-Scenario2.
- **D11 (thresholds)**: stub goldens use Q_min=0.80, ε=0.10;
  formal-experiment thresholds await an independently frozen protocol;
  **B_remain is computed from actual budget state**, never a constant.
  → reward §7, predictor §8; V7.

## Errata diff summary (57f2553/09d6b4d → rev E)

| Fix | File(s) |
|---|---|
| V1 contradiction resolved: TWO independent golden scenarios — B(p90=18s≤20) chosen; B(p90=21s) excluded → EARLY_STOP fires, zero further calls | VERIFICATION §V1 |
| OPEN-P3 retired (already in rev D): quality gates feasibility via Q_min on whole-DAG q̂ | predictor §5/§8 |
| L1/L4 same-legal-history redesign (already in rev D) + F2 rewritten: explicit degradation, no "forced NONE" | VERIFICATION §L, §R-F F2 |
| C5 performance thresholds removed from correctness (already in rev D) | VERIFICATION §C5 |
| T3 split: T3a single-task call-semantics + T3b cross-task batching — separate gates, both required; phase-2 FIRST acceptance gate = T3a+T3b under fixed policies | VERIFICATION §T; README §Phase-2 |
| Statistical assumptions explicit: μ = declared distribution mean (never generic p50); path-p90 = conservative upper bound; z=1.2816 exact only for declared normal family; no real-latency calibration implied; new P4 distribution-integrity test | predictor §5; VERIFICATION §P4 |
| D10/D11 rulings frozen; EARLY_STOP default; B_remain computed | scheduler §4c/§10; reward §7; predictor §8; VERIFICATION V7/F2 |

## Document map

| File | Content |
|---|---|
| `AUDIT_EXISTING_CODE.md` | Part I search-layer evidence · Part II execution layer (stages, D1–D6, LOCAL table, two FULL semantics, confound ladder, three time quantities, reuse/missing lists, §II.12 runtime-interface checklist, honesty ledger) · corrections (96→48; E1) |
| `DESIGN_REWARD_FUNCTION.md` | R_task task-level terminal reward; two-stage decision + C_new/settlement separation; corrected E1; E2E口径 §3.3a; D3/D10/D11 ruled |
| `DESIGN_DYNAMIC_SCHEDULER.md` | Joint action (Z,R,π): static/dynamic Z variants (B1), π domain restriction, causality (B2), reuse rule, closure consistency, **EARLY_STOP degradation (D10)**, A/B/C example, compensator, confound/ablation, F-matrix |
| `DESIGN_PREDICTOR_INTERFACE.md` | Per-joint-action prediction; node-level quality chain; ΔC with reuse; critical-path service time; **synthetic-distribution statistical assumptions**; quality gating; B1/P7/D10/D11 ruled |
| `VERIFICATION_PLAN.md` | L (same-legal-history) / A / T (**T3a+T3b production-reference gates**) / B / R-F (F2=degradation) / Z / P (**P4 distribution integrity**) / C (descriptive metrics) / V (two-scenario V1, V7 hygiene) |

## Corrections carried (visible)

1. Config count 96 → 48 (evaluator.py:22-26); search space retired as test
   range.
2. E1 lateness expectation fixed to σ[φ(z)+zΦ(z)], z=(μ−D)/σ; P3 goldens;
   regression tripwire.
3. rev C V1 contradiction (B selected despite P90=21>D_remain=20) — split
   into two scenarios (rev E).

## Remaining open decisions (15)

D5 (C₀ granularity) · D6 (E1 family) · D8 (q̂ feedback) · D9 (tie-break) ·
B3 (D_task/token allocation) · B4 (cascade granularity) · S5 (stub-only
exercise) · C1 (menu widening) · P2 (cache-aware cost) · P4 (profile
granularity) · P6 (pooling, default OFF) · P7-values (synthetic prior
numbers) · P8 (quality-chain correlation) · P9 (observed-state belief
rule) · P10 (switch variance in σ). All have documented defaults; none
blocks phase 2.

## Phase-2 minimal scope & admission

**First acceptance gate (operator order):** fixed policies reproduce the
INDEPENDENT production reference execution semantics — T3a (single-task
call semantics) AND T3b (cross-task model-batched stage order) — BEFORE any
joint reallocation, constraint filtering, reward selection, or recovery
dynamics are exercised.

Build order (AUDIT II §12; interfaces 1, 4, 6 missing, 2 partial):
**M1** stub engine (per-call loop, injected clock, per-task wall, switch
records) → **M2** SchedulerState API → **M3** closure/reuse → **M4**
recovery execution (static variants first) → **M5** π application + menus
→ **M6** two-stage policy + predictor + compensator + settlement, with the
full VERIFICATION_PLAN suite.

**Admission status: phase-2 architecture ACCEPTED (rev C review); coding
awaiting the operator's admission confirmation of this rev E errata.**
Phase-2 completion does NOT authorize production-executor integration or
real-model experiments — both need separate approval (unchanged).
