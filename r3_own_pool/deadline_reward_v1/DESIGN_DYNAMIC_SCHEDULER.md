# DESIGN_DYNAMIC_SCHEDULER — deadline_reward_v1 (rev D)

Status: DRAFT v0.5 (rev D) — applies the review rulings of 2026-10-10:
fixed-model NONE/LOCAL/FULL retained as production-equivalence baselines,
dynamic versions carry their own π (B1); π's domain restricted to still-
executable nodes; B2 causality constraint on the dynamic policy; E2E口径
pointer to reward doc §3.3a. Zero model calls, phases 1–3; no production
file modified.

Frozen research objective (operator, verbatim): 面向截止时间约束的反馈驱动
异构多智能体 DAG 动态调度方法 — after an execution anomaly, jointly optimize
recovery scope and downstream model assignment using DAG dependencies,
node-level model capability, remaining time and resource budget, via the
on-time-correct completion reward, new-cost penalty and timeout penalty —
i.e., the dynamic Q/C/L tradeoff. (EN gloss in README.)

## 1. Architecture (unchanged from rev B; interfaces per AUDIT II §12)

```
StubExecutionEngine (in-package; mirrors audited stage semantics)
   │ per-call events on INJECTED CLOCK; switch events first-class;
   │ per-task real wall tracked  [interfaces 1,2,6 of II §12 — built here]
   ▼
SchedulerState (§3) ── CLOSURE constants (multidag_dynamic.py:59)  [3 EXISTS]
   │ detection events D1–D6                                       [5 EXISTS]
   ▼
Two-stage policy (§2):  A_feasible filter  →  argmax Ê[R_task | s_t, a]
   ├─ OutcomePredictor: q̂(a), ΔC(a), (μ, w_p90)(a)      [4 = the new capability]
   └─ DeadlineCompensator: D_remain, B_remain, margins   [§6]
▼ apply a → transition (§5) → next detection / terminal → realized R_task
```

## 2. Decision loop — constraint filtering + reward optimization

At every decision point (detection event e for task τ, or pre-node
scheduling point for unexecuted nodes):

```
Stage 1 (feasibility filter — removes clearly infeasible actions):
  A_feasible(s_t) = { a = (Z, R, π) ∈ legal(s_t) :
       q̂(a | s_t) ≥ Q_min,                       # quality floor
       P̂(T_a ≤ D_remain | s_t) ≥ 1 − ε,           # on-time confidence (E1)
       ΔC(a) ≤ B_remain }                         # budget bound
Stage 2 (reward optimization over survivors):
  a*_t = argmax_{a ∈ A_feasible(s_t)} Ê[R_task | s_t, a]
No survivor ⇒ explicit degradation policy (§4c) + violation recording —
NEVER force a seemingly-feasible action.
```

R_task and the C_new/settlement separation are defined in
DESIGN_REWARD_FUNCTION §3 (formula unchanged; decision-time comparison uses
incremental C_new, settlement records full episode cost).

### 2a. Worked example (operator's A/B/C, pinned as golden test V1)

Remaining time D_remain = 20 s, Q_min = 0.80, ε = 0.10. Candidate joint
actions at an r-node anomaly (same R_t, different π_t for {r-repair, v}):

| Action | mean time | q̂ | verdict |
|---|---|---|---|
| A: original models | 24 s | 0.95 | infeasible: P̂(T≤20)<0.9 (time) |
| B: faster models | 17 s | 0.85 | feasible if P90 ≤ ~20 s → P̂ ≥ 0.9 |
| C: fastest models | 12 s | 0.60 | infeasible: q̂ < Q_min (quality) |

Chosen: B. **Uncertainty is decisive, not optional**: with B's P90 at 21 s,
P̂(T≤20) < 0.9 ⇒ B leaves the feasible set — the filter must use the
distribution (E1), never the mean alone. The 95/85/60 are PREDICTED
correctness from state (predictor doc §3), never future truth.

### 2b. Policy–static equivalence (test T3, carried)

Constant joint policies reproduce the static arms: π≡(NONE,∅,·) ≡ Z=NONE;
π≡(LOCAL, trigger-closure, production-substitution) ≡ D-arm;
π≡(FULL, all, E-arm-rule) ≡ E-arm. The dynamic policy is a strict
generalization; T3 remains the engine-fidelity proof.

## 3. SchedulerState — complete definition (rev C additions in bold)

Per task episode (session envelope alongside):

```
node_status  : {e1,e2,r,v → PENDING | RUNNING | DONE | FAILED(detected)}
node_model   : {node → model}          # current binding; π_t may rewrite PENDING nodes
recovery_cnt : {e_fb,r_fbd,r_esc,v_fbd,v_esc,replay → int}    # production caps
observed     : per-node latest detection outcome + repair feedback (D1–D6, II §2)
**reuse_set  : {node → CACHED_FRESH | STALE}**                # completed nodes whose
               # outputs remain valid under the pending π_t (§4b reuse rule)
**unexec_set : {PENDING nodes}**                              # π_t's assignment targets
calls/budget/time/history : as rev B (§3)                     # + D_remain, B_remain views
**violations : [(constraint, deficit, decision_id)]**         # degradation ledger
```

Excludes (firewall L2/L3): gold, fault registry, unexecuted-node outputs.

## 4. Joint action space a_t = (Z_t, R_t, π_t) — complete definition

### 4a. Components

**Z_t ∈ {NONE, LOCAL, FULL}** — two registered variants per Z (review
ruling B1):

- **Static fixed-model variant** (production-equivalence baseline): the
  rev B §4 substitution rules verbatim (LOCAL: fb memory rule / esc→large /
  refresh keeps planned model; FULL: E-arm matched replay). Constant joint
  policies over these reproduce Z=NONE / D-arm / E-arm bitwise (T3/V6).
  The memory rule keeps PANEL DETECTION ORDER here (ruling B2), because it
  is mirroring production batch semantics.
- **Dynamic variant**: same recovery SCOPE semantics, but π_t may carry its
  own model assignment (within menus, §4a) — e.g. time-rich → higher-quality
  models for r-repair/v; time-tight → faster models that still clear Q_min.
  Every applied dynamic FULL is recorded with (scope, model-delta) separated
  so scope and model effects remain individually attributable (B1).

**R_t ⊆ legal re-execution set** — nodes to re-execute under Z_t:
- Z=NONE ⇒ R=∅; Z=FULL ⇒ R={all four} (+ completed-output reuse per 4b where
  the chosen FULL semantic allows); Z=LOCAL ⇒ R from the trigger's causal
  chain: trigger node ∪ CLOSURE nodes whose inputs actually change (the
  production cascade, generalized: e.g. D3 on r ⇒ R may be {r} or {r,v}).
- Legality: R must be closure-consistent — if π_t changes the model of node
  n ∈ DONE, then CLOSURE(n) ∩ (DONE ∪ RUNNING) must be in R or their cached
  outputs must be provably invariant (4b). Assert in test V5.

**π_t : nodes → models** — assignment whose DOMAIN is exactly the
still-executable set: `R_t ∪ unexec_set` (PENDING nodes, or nodes being
re-executed). A DONE node NOT in R_t is IMMUTABLE under π_t (its binding and
cached output stand — review ruling 1); changing it would require adding it
to R_t via the closure rule (4b). Per-node model menus FROM AUDITED
PRODUCTION PATHS (not invented): e1/e2 ∈ {medium, large, coder} (coder
occurs via fb); r ∈ {medium, large}; v ∈ {coder, large}. Menu widening =
OPEN-C1.

**Causality constraint (ruling B2):** the dynamic policy may use only
information available AT THE DECISION INSTANT. Cross-task detection results
that production would only obtain in LATER batched stages are future
information — SchedulerState exposes per-task state only for tasks whose
stage the engine has actually reached, and the fb memory rule's panel-order
dependence is a property of the STATIC baseline only; the dynamic variant
must not read other tasks' not-yet-occurred detections (test L4b).

### 4b. Completed-node reuse rule (operator: "e1/e2 输出是否仍可复用?")

A DONE node's output is reusable iff (i) its own (model, prompt-identity) is
unchanged under a_t — cache-identity semantics already exist in production
((model, sha, task, node, scope), smoke_runner.py:114) — and (ii) no
ancestor in R_t changed an input it consumed. Violating (ii) ⇒ node enters
R_t via CLOSURE. The selective-update precedent ("re-executed set ==
descendant closure on every event", multidag_dynamic.py:30) is the audit
pattern; test V5 asserts closure-consistency of every applied action.

### 4c. No-feasible-action rule (degradation; operator directive)

If A_feasible(s_t) = ∅ the system MUST NOT force a seemingly feasible
action. It enters an explicit degraded mode — default policy (OPEN-D10):
**BEST_EFFORT_QUALITY**: among legal actions, take argmax q̂ subject only to
the hard safety rule "never START a call that cannot finish before the
mission wall" (call atomicity); alternatives: EARLY_STOP (settle episode
now) / FORCED_NONE. Every degradation records the full violation vector
(constraint, deficit: Q_min−q̂, 1−ε−P̂, ΔC−B_remain) into
SCHEDULER_STATE.jsonl + REWARDS.jsonl. Direct precedent: budget-gated
skip+record (multidag_dynamic.py:319,365). Degraded episodes are flagged in
all downstream analyses (never silently mixed with feasible completions).

### 4d. Decision granularity

Decision points: every detection event AND every pre-execution point of a
PENDING node (so π_t genuinely schedules unexecuted nodes, not only
repairs). Recipe-internal cascades stay automatic (OPEN-B4 carried: default
no separate decisions, preserving D-arm comparability).

## 5. Transition (rev B §5 carries over; additions)

Applying a_t = (Z,R,π): engine rewrites node_model per π for R ∪ unexec_set;
re-executes R in dependency order (stage batching preserved); reuses
4b-valid DONE outputs (cache hit, zero new cost — stub engine mirrors
production cache semantics); budget/clock/ledger update per call; predicates
re-run on new outputs; recovery_cnt increments per production event;
violations appended when degraded. Deterministic given the scripted server.

## 6. DeadlineCompensator (rev B §6 carries; rev C inputs)

Adds to the rev B table: **D_remain(t) = D_task − t_now** and
**B_remain(t) = per-task token allocation − tokens_spent** exposed as
first-class decision inputs; switch overhead now must consider π_t's model
SET (number of distinct models in R ∪ unexec under π vs current — batched
by the engine, so overhead = switches between model-groups in execution
order, still compensator-owned, single-counted — B6 audit extended to π_t).

Allocation of D_task / token allocation per task: OPEN-B3 carried
(default rolling split).

## 7. Confound control & ablation (rev C update)

Static ladder B/C/D/E stays (as constrained constant policies, §2b). New
decomposition arms enabled by the joint space:
- **scope-vs-assignment**: π-dynamic-with-frozen-π (optimize Z,R only) vs
  full (Z,R,π) — isolates the VALUE of joint reassignment (the paper's core
  claim);
- **feedback**: live detections vs frozen-at-start (carried);
- **term ablation**: λ-off one at a time (carried).
Action logs per (trigger family, scope size, model delta) feed the C5
confound audit.

## 8. Failure-mode matrix (carried F1–F9; rev C additions)

| # | Scenario | Expected |
|---|---|---|
| F10 | A_feasible = ∅ | degradation mode entered, violation vector recorded, flag on episode; no forced feasible-looking action |
| F11 | π_t proposes model outside node menu | action illegal at construction (V5) |
| F12 | closure violation (R excludes a node whose input changed) | rejected at construction; engine never executes an inconsistent R |
| F13 | reuse check wrong (stale output consumed) | V5's closure-consistency assert fails loudly — treated as engine bug, not policy behavior |

## 9. Acceptance criteria (carried) + rev C

Carried: T3 equivalence, legality asserts, ledger/budget reconciliation,
determinism, import graph. Added: V1 golden (2a example), V5 closure/menu
consistency on every applied action, degradation recording (F10), C_new vs
settlement separation (V4).

## 10. Open decisions & rulings (rev D)

**RULED by operator review 2026-10-10 (recorded verbatim in README §Rulings):**
- **B1**: FULL — E-arm matched semantics as the STATIC baseline; dynamic
  FULL may specify its own model assignment, with scope and model effects
  recorded separately. (Implemented §4 Z variants.)
- **B2**: static-equivalence tests keep panel detection order; the dynamic
  policy must not exploit cross-task detection results that have not yet
  occurred. (Implemented §4a causality constraint; test L4b.)

Still open: B3 (D_task/token allocation; default rolling split), B4
(cascade granularity; default automatic), S5 (stub-only exercise), **C1**
(menu widening beyond audited paths; default audited menus only), **D10**
(degradation policy; default BEST_EFFORT_QUALITY), **D11** (Q_min/ε/
B_remain values — stub-test values allowed under the D3 labeling rule).
