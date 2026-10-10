# deadline_reward_v1 — deadline-constrained feedback-driven DAG dynamic scheduling (rev C)

**Frozen research objective (operator, 2026-10-10, verbatim):**

> 提出一种面向截止时间约束的反馈驱动异构多智能体 DAG 动态调度方法。在执行异常发生后,系统依据 DAG 依赖关系、节点级模型能力、剩余时间及资源预算,联合优化故障恢复范围与后续节点模型分配,通过按时正确完成奖励、新增执行成本惩罚和超时惩罚,实现质量、成本与时延之间的动态权衡。

(EN gloss: a deadline-constrained, feedback-driven scheduling method for
heterogeneous multi-agent DAG execution; after an anomaly, jointly optimize
recovery scope and downstream model assignment under DAG dependencies,
node-level capability, remaining time and budget, via the on-time-correct
reward with new-cost and timeout penalties — the dynamic Q/C/L tradeoff.
Proposed as a core algorithm of the paper's "feedback-driven DAG dynamic
scheduling".)

**Core decision (rev C):** a_t = (Z_t, R_t, π_t) — two-stage choice:
constraint filter (Q_min, P̂(T≤D_remain)≥1−ε, ΔC≤B_remain) → argmax
Ê[R_task]; explicit degradation + violation recording when the feasible set
is empty (never a forced action).

Hard boundaries (phases 1–3): zero real model calls; no modification of
Formal/net-benefit code/protocols/ledgers/results; detection = exactly the
audited predicates D1–D6; no capability is claimed beyond AUDIT II §12;
**phase 2 NOT started — awaiting human review of rev C.**

## Document map (rev C; baseline history: rev A @0d381a8, rev B @fc201ae)

| File | Content |
|---|---|
| `AUDIT_EXISTING_CODE.md` | Part I search-layer evidence · Part II execution layer: stages, D1–D6, LOCAL table, two FULL semantics, confound ladder, three time quantities, reuse/missing lists, honesty ledger · **§II.12 runtime-interface checklist (pause/observation/closure/reassignment/recovery/timing — with the CLOSURE table + budget-gated skip+record precedents)** · corrections (96→48; E1) |
| `DESIGN_REWARD_FUNCTION.md` | R_task task-level terminal reward; gold only at settlement; **two-stage decision + C_new-vs-settlement separation (§3.2)**; corrected E1; time ownership |
| `DESIGN_DYNAMIC_SCHEDULER.md` | Architecture; **joint action space (Z,R,π) with audited node menus, reuse rule, closure consistency, degradation policy, A/B/C worked example (§2a, §4)**; SchedulerState; transition; compensator (D_remain/B_remain); confound/ablation; F1–F13 |
| `DESIGN_PREDICTOR_INTERFACE.md` | Per-joint-action prediction: **node-level quality chain under π**, ΔC with reuse, critical-path time aggregation, corrected E1, PRIORS provenance |
| `VERIFICATION_PLAN.md` | L/A/T/B/R-F/Z/P/C groups + **V group (V1 A/B/C golden, V2 filter incl. P90 trap, V3 degradation, V4 cost separation, V5 joint consistency, V6 equivalence)**; coverage map |

## Corrections carried (visible)

1. Config count 96 → 48 (evaluator.py:22-26); search space retired as test
   range anyway.
2. E1 lateness expectation fixed to σ[φ(z)+zΦ(z)], z=(μ−D)/σ (rev A form
   agreed only at z=0); P3 regression tripwire asserts the old form fails.

## Consolidated open decisions (22; defaults proposed)

Reward: D3 (λ,C₀,B,P) · D5 (C₀ granularity) · D6 (E1 family) · D8 (q̂
feedback) · D9 (tie-break) · **D10 (degradation policy)** · **D11 (Q_min,
ε, B_remain floors)**.
Scheduler: B1 (FULL semantics; default E-arm) · B2 (fb memory-rule
granularity) · B3 (D_task/token allocation) · B4 (cascade granularity) ·
S5 · **C1 (menu widening; default audited menus only)**.
Predictor: P1 · P3 · P4 · P6 (pooling OFF) · P7 (PRIORS values) · **P8
(quality-chain correlation)** · **P9 (observed-state belief rule)**.

## Phase-2 admission recommendation (rev C)

**Recommend: ADMIT phase 2 conditionally**, with the build order fixed by
the interface checklist (AUDIT II §12: items 1, 4, 6 missing, 2 partial) —
**minimal execution closed loop FIRST**, then the policy:

- **M1** stub execution engine: per-call event loop on injected clock,
  per-task real wall, first-class switch records (interfaces 1+6);
- **M2** node-state observation API = SchedulerState skeleton (interface 2);
- **M3** closure/reuse machinery from the CLOSURE constants + cache-identity
  semantics (interface 3, exists — wire it);
- **M4** recovery execution in the engine (LOCAL recipe semantics, FULL per
  OPEN-B1) (interface 5, exists — mirror it);
- **M5** reassignment capability: π application + menus (interface 4 — the
  new capability);
- **M6** policy stack: two-stage decision + predictor + compensator +
  reward settlement, with the full VERIFICATION_PLAN suite (T3/V6
  equivalence as the engine-fidelity gate).

Operator gates before coding: resolve **B1, B2, D3, P7** (as rev B) plus
**D10, D11** (degradation policy + threshold values). All others may run on
documented defaults. Phase 4 (real models) unchanged: Formal settlement
audit + net-benefit gates + independent authorization.
