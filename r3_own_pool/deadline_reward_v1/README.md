# deadline_reward_v1 — deadline-constrained feedback-driven DAG dynamic scheduling (rev D)

**Frozen research objective (operator, verbatim):**

> 提出一种面向截止时间约束的反馈驱动异构多智能体 DAG 动态调度方法。在执行异常发生后,系统依据 DAG 依赖关系、节点级模型能力、剩余时间及资源预算,联合优化故障恢复范围与后续节点模型分配,通过按时正确完成奖励、新增执行成本惩罚和超时惩罚,实现质量、成本与时延之间的动态权衡。

Core decision: a_t = (Z_t, R_t, π_t); two-stage filter (Q_min,
P̂(T≤D_remain)≥1−ε, ΔC≤B_remain) → argmax Ê[R_task]; explicit degradation +
violation recording when nothing is feasible.

Version history: rev A @0d381a8 (search-layer draft) → rev B @fc201ae
(execution-layer pivot; **review baseline**) → interim rev C @57f2553
(joint-action anticipation) → **rev D (this revision): review rulings
applied**. Phase 2 remains HOLD pending review of rev D.

## Operator rulings (2026-10-10 review, recorded verbatim)

- **B1 (FULL semantics)**: net-benefit E-arm matched semantics is the
  STATIC baseline; DYNAMIC FULL may specify its own model assignment, but
  scope effects and model effects must be recorded separately.
  → scheduler doc §4 (Z variants), predictor doc §8.
- **B2 (feedback memory rule)**: static-equivalence tests keep PANEL
  DETECTION ORDER; the dynamic policy must not exploit cross-task detection
  results that have not yet occurred.
  → scheduler doc §4a causality constraint; test L4b.
- **D3 (weights & C₀)**: scientific experiment weights are NOT frozen now;
  stub phases may use parameters ONLY when explicitly labeled
  `stub_test_only`; **C₀ must be strictly > 0**; formal weights must be
  independently calibrated and pre-frozen before real runs.
  → reward doc §7; test V7.
- **P7 (PRIORS.json)**: synthetic stub priors allowed WITH provenance
  notes; never labeled real-model calibration; no reverse-tuning from
  confirmation-test outcomes.
  → predictor doc §8; test V7.

**Parameter separation rule:** every parameter file entry carries a class
tag — `stub_test_only` (phases 2–3) vs `formal_experiment` (empty until the
phase-4 calibration+freeze process). V7 enforces the tags, C₀>0, and
read-only PRIORS during confirmation tests.

## Issue → fix → test mapping (review's four must-fix items + rulings)

| # | Review issue | Fix (file/§) | Test |
|---|---|---|---|
| 1 | Actions must include model reassignment | scheduler §4 (Z static/dynamic variants; π domain = R ∪ unexec, DONE-immutable; audited menus) | V5, V6, T3 |
| 2 | Q_min + deadline + budget constraints; retire OPEN-P3 | reward §3.2 (filter verbatim); predictor §5 (quality gates on whole-DAG q̂) | V1, V2, V3 |
| 3 | Unified E2E口径 (service + switches, whole remaining DAG) | reward §3.3a; predictor §5 (composition once) | B6, B7 |
| 4a | L1/L4: same-legal-history, not always-identical traces | VERIFICATION §L (pinned-observable counterfactual worlds; streaming prefix form) | L1, L4, L4b |
| 4b | C5: no performance threshold in correctness | VERIFICATION §C5 → experimental metrics | V2/C2/C3 remain correctness |
| 4c | T3: independent production references (batching semantics!) | VERIFICATION §T3 (eval_config/JointEvaluator + stub executors as reference generators; checks model-batched order, cascades, accounting) | T3, V6 |
| R10 | Full A/B/C scenario + uncertainty variant | VERIFICATION §V1 (two variants with exact arithmetic) | V1 |
| R9 | README rulings + parameter separation | this file §Rulings, §Parameter separation | V7 |

## Document map

| File | Content |
|---|---|
| `AUDIT_EXISTING_CODE.md` | Part I search-layer evidence · Part II execution layer (stages, D1–D6, LOCAL table, two FULL semantics, confound ladder, three time quantities, reuse/missing lists, §II.12 runtime-interface checklist, honesty ledger) · corrections (96→48; E1) |
| `DESIGN_REWARD_FUNCTION.md` | R_task task-level terminal reward; two-stage decision + C_new/settlement separation (§3.2); corrected E1; **E2E composition口径 (§3.3a)**; D3 ruling (§7) |
| `DESIGN_DYNAMIC_SCHEDULER.md` | Joint action (Z,R,π) with **static/dynamic Z variants (B1)**, π domain restriction, causality constraint (B2), reuse rule, closure consistency, degradation policy, A/B/C example, compensator, confound/ablation, F1–F13 |
| `DESIGN_PREDICTOR_INTERFACE.md` | Per-joint-action prediction; node-level quality chain; ΔC with reuse; critical-path service time; **E2E composition; quality gating (P3 retired)**; B1/P7 rulings |
| `VERIFICATION_PLAN.md` | L (redesigned L1/L4/L4b) / A / T (**production-reference T3**) / B / R-F / Z / P / C (performance→metrics) / V (full V1 scenario, V7 hygiene); coverage map |

## Corrections carried (visible)

1. Config count 96 → 48 (evaluator.py:22-26); search space retired as test
   range.
2. E1 lateness expectation fixed to σ[φ(z)+zΦ(z)], z=(μ−D)/σ (rev A form
   agreed only at z=0); P3-goldens regenerated; regression tripwire.

## Remaining open decisions (17)

D5 (C₀ granularity) · D6 (E1 family) · D8 (q̂ feedback) · D9 (tie-break) ·
D10 (degradation policy) · D11 (Q_min/ε/B_remain values — stub-test values
allowed under D3 labeling) · B3 (D_task/token allocation) · B4 (cascade
granularity) · S5 (stub-only exercise) · C1 (menu widening) · P2
(cache-aware cost) · P4 (profile granularity) · P6 (pooling, default OFF) ·
P7-values (stub prior numbers) · P8 (quality-chain correlation) · P9
(observed-state belief rule) · P10 (switch variance in σ). (P1/P3-RETIRED/
B1/B2/D3/P7-policy are RULED; values where noted remain open.)

## Phase-2 minimal scope & admission recommendation

Build order fixed by AUDIT II §12 (interfaces 1, 4, 6 missing; 2 partial) —
**minimal execution closed loop first**:

- **M1** stub engine: per-call event loop, injected clock, per-task real
  wall, first-class switch records;
- **M2** SchedulerState observation API;
- **M3** closure/reuse machinery (CLOSURE constants + cache identity);
- **M4** recovery execution in-engine (LOCAL recipe; FULL per B1 static
  baseline semantics first, dynamic FULL behind the same interface);
- **M5** π application + menus (the new capability);
- **M6** policy stack: two-stage filter + predictor + compensator +
  settlement, with the full VERIFICATION_PLAN suite — T3/V6
  production-reference equivalence as the engine-fidelity gate.

**Admission recommendation: HOLD stands until rev D review passes.** On
pass, phase 2 may start on M1–M6 with the remaining OPENs running on
documented defaults (D10/D11 defaults need operator confirmation since they
shape the degradation behavior). Phase 4 (real models) unchanged: Formal
settlement audit + net-benefit gates + independent authorization +
independently calibrated pre-frozen weights (D3).
