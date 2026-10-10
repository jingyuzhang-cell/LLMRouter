# DESIGN_DYNAMIC_SCHEDULER — deadline_reward_v1 (rev B)

Status: DRAFT v0.3 (rev B) — execution-layer redesign per the operator
ruling. Governs phase-2 files `scheduler_state.py` and
`deadline_compensator.py` plus the stub execution engine. Zero model calls
in phases 1–3; no modification to any production file. This document is the
single source for the architecture and the complete
state/action/reward/transition definitions (reward definition itself:
DESIGN_REWARD_FUNCTION §3).

## 1. Architecture (deliverable: 执行层架构)

```
deadline_reward_v1/ (all NEW code, phases 2–3)
┌─────────────────────────────────────────────────────────────────┐
│  StubExecutionEngine   mirrors fault30_run.eval_config stages    │
│  (A → R1 → [decision] → ER/R2/R3 → V1 → [decision] → V2/V3)      │
│    calls ──► StubModelServer (scripted answers + injected        │
│               faults + per-model token/latency profiles +        │
│               switch costs), all on an INJECTED CLOCK            │
│    emits ──► per-call records (usage, latency, switch events,    │
│               wall stamps) → TASK_LEDGER.jsonl (append-only)     │
└──────────────┬──────────────────────────────────────────────────┘
               │ detection events D1–D6 (real predicates, AUDIT II §2)
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  SchedulerState (§3)  +  Policy π = argmax_a Ê[R0|H,a]           │
│      │legal_actions(state) (§4)                                  │
│      ├─► OutcomePredictor  per-action q̂, ΔĈ, (μ,w_p90) (doc §3–5)│
│      └─► DeadlineCompensator  D_task, margins M(a,t) (§6)        │
└──────────────┬──────────────────────────────────────────────────┘
               │ chosen action a
               ▼
          engine.apply(a) → transition (§5) → next detection / terminal
Terminal: scorer computes realized R0 (gold used HERE only) → REWARDS.jsonl
```

Positioning vs production (honesty, AUDIT II §11): there is no online
decision hook in `eval_config` today. Phase 2 builds the stub engine INSIDE
this package, mirroring the audited stage semantics (II §1–§3) — the
V3Executor precedent. Production integration, if ever, is a separately
admitted change under the authorization style of AUDIT Part I §2.8.

## 2. The decision loop

```
for each task in panel (serial; engine batching by model preserved):
    D_task ← compensator.allocate(state)                    # §6
    execute planned stages A, R1 (evaluator semantics)
    at each detection event e ∈ {D1..D6} for this task:
        A ← legal_actions(task_state, e)                    # §4
        for a in A: score(a) ← Ê[R0|H,a]                    # reward doc §3.2
        a* ← argmax (tie-break OPEN-D9)
        if a* ≠ NONE: engine.apply(a*)                      # transition §5
        re-evaluate predicates on new outputs (same rules as production)
    terminal: score task → realized R0; update session aggregates
```

Policy–static equivalence property (testable, T3): a constant policy
π≡NONE reproduces Z=NONE behavior; π≡LOCAL (where legal) reproduces the
D-arm LOCAL recipe; π≡FULL-on-D6 reproduces the E-arm replay. This pins the
stub engine's fidelity to the audited semantics and defines the dynamic
policy as a strict generalization of the static arms.

## 3. SchedulerState — complete definition (deliverable)

Per task (one SchedulerState instance per task episode; session-level
envelope held alongside):

```
node_status   : {node ∈ {e1,e2,r,v} → PENDING | RUNNING | DONE | FAILED(detected)}
                FAILED = a detection predicate fired on its latest output
node_model    : {node → model id}          # current binding; changes on substitution
recovery_cnt  : {event ∈ {e_fb,r_fbd,r_esc,v_fbd,v_esc,replay} → int}   # caps in §4
observed      : per-node latest detection outcome (D1–D6 enum) + repair
                feedback (facts_changed, answer_changed_final) — exactly the
                signals of AUDIT II §2, nothing finer
calls         : this task's call records (key, model, usage, latency, switch)
budget        : {tokens_spent, requests_spent} (physical, reserve/settle)
time          : {t_now (injected clock), D_task, mission_deadline}
history       : ordered (detection, action, score-vector, outcome) tuples
```

Update rules are part of the transition (§5). The state EXCLUDES gold, the
fault registry, and any unexecuted-node output (firewall tests L2/L3).

## 4. Recovery action interface (deliverable: NONE/LOCAL/FULL 语义)

| | NONE | LOCAL | FULL |
|---|---|---|---|
| Semantics | accept current state; continue/terminate without repair | apply the production LOCAL recipe for the triggering detection (AUDIT II §3) | one full-graph replay from scratch (see model rule) |
| Trigger | any decision point | decision points D1–D5 | any decision point (incl. D6 terminal-check) |
| Legality | always legal | legal iff every event in the recipe's causal chain has remaining capacity: e_fb<1 per empty e-node, r_fbd<1, r_esc<1, v_fbd<1, v_esc<1 (production caps, II §3) AND its ΔC lower bound fits the remaining budget | legal iff replay_cnt==0 (exactly-one rule, evaluator.py:118-129) AND budget/time lower bound fits |
| Affected set | ∅ | trigger node ∪ descendant closure per production rules (fb→{e}; facts_changed→+r; r_changed→+v; esc→node) | all four nodes (re-scheduled from A) |
| Model substitution | — | production rules verbatim: fb memory rule (coder/medium), r_esc/v_esc → large, refreshes keep planned model | **OPEN-B1**: (a) E-arm matched — alternatives only on trigger nodes (e: memory rule; r,v: large), others on planned models [DEFAULT, scope-only attribution]; (b) search-layer all-swap (evaluator.py:124-126) |
| Extra cost | 0 new calls | enumerated events × profiles | 4-node replay × profiles (+switches to its model set) |

Additional constraints: actions are chosen BETWEEN calls (calls are atomic);
legality and feasibility are re-checked after every applied action; the
recipe's internal cascades (e.g., fb → facts changed → r_fbd) follow
production trigger rules automatically, not by extra decisions (decision
granularity = the initial trigger; OPEN-B4 whether cascades become
decisions too — default: no, to preserve D-arm comparability).

## 5. Transition (deliverable)

`s' = τ(s, a; stub responses)` — deterministic given the scripted server:

1. NONE: node_status unchanged (FAILED stays FAILED); if at terminal point →
   episode ends, scorer computes R0.
2. LOCAL: engine executes the recipe's events in production order
   (ER→R2→R3 / V2→V3); each call: budget reserve→settle, clock advances by
   service latency (+ switch cost iff model changes); predicates re-run on
   new outputs; recovery_cnt increments; observed updated
   (facts_changed/answer_changed_final per II §2 D2/D4 rules).
3. FULL: recovery_cnt[replay]=1; the task's schedule restarts at stage A
   with the substituted model set (per OPEN-B1); all replay calls charged;
   previous calls REMAIN charged (physical honesty — matches campaign
   semantics where the failed attempt is real spend); predicates re-run.
4. Every applied action appends one line to TASK_LEDGER.jsonl
   (action, scores, legal set, chosen, outcome) — append-only, fsync.
5. Episode ends at: terminal point with no legal/necessary action, or
   mission wall reached (StopRun → session terminal −P per reward doc §5).

## 6. DeadlineCompensator — unified accounting (deliverable; no double charge)

One component owns each time ingredient; the others must not re-count it:

| Ingredient | Owner |
|---|---|
| Absolute mission deadline (wall cap − cleanup reserve, G2) | frozen session envelope |
| Per-task deadline D_task | compensator.allocate: rolling split `D_task = min(mission_end, t_now + remaining_wall/remaining_tasks)` (OPEN-B3 alternatives: equal static split, Q-aware split) |
| Service demand of remaining/replay calls (μ, w_p90) | OutcomePredictor (pure service, NO switch time) |
| Model-switch overhead at decision time | compensator.switch_overhead(models(a) vs current, from switch history + PRIORS) |
| Safety margin | compensator: max(q90 observed switch error, frozen floor) |
| Idle/scheduling gaps | stub clock (recorded, not estimated) |

```
margin(a, t) = D_task − t − switch_overhead(a) − safety_margin
feasible(a)  := w_p90(a) ≤ margin(a, t)          # hard gate G1 (per task)
```

G1 ⊂ G2 by construction (D_task ≤ mission work window); test B5 asserts
containment every decision; test B6 asserts each ingredient is counted in
exactly one place (double-charge audit).

## 7. Confound control & ablation design (deliverable; AUDIT II §5)

Static baselines (exactly the net-benefit ladder, re-run in stub):
B (all-large, NONE) · C (hetero X, NONE) · D (same X, LOCAL) · E (same X,
FULL matched). Effects: B→C = model assignment; C→D = local recovery;
D→E = recovery SCOPE with models held fixed.

Dynamic policy arms (the contribution): π_R0 (argmax Ê[R0], primary) ·
π_random-legal (floor) · π_cheapest (min ΔC, cost-only) · π_eager (always
strongest legal action, no deadline term). Decomposition claims supported:
(i) dynamic vs best static (D, E): value of ADAPTIVITY;
(ii) π_R0 vs π_cheapest/π_eager: value of the FULL R0 structure (deadline
+ quality terms, ablated one at a time — λ-terms off);
(iii) feedback value: π_R0 with detection inputs frozen at episode start
(feedback-blind) vs live — isolates the feedback channel.
Scope×model deconfounding is inherited from D/E matched design; the policy's
chosen actions are additionally logged per (trigger family, model delta) so
post-hoc analysis can verify the policy is not merely re-discovering a fixed
model preference (test C5: action distribution shift across fault families).

## 8. Failure-mode matrix (phase-3 tests R-F1…)

| # | Scenario | Expected |
|---|---|---|
| F1 | injected clock jumps past D_task mid-episode | current call finishes (atomic), no new action admitted; episode settles; (T−D)₊/1(T>D) charged in R0 |
| F2 | all recovery actions infeasible (margin < 0) | NONE forced (always legal); logged mode=forced-none; no crash |
| F3 | pathological switch (600 s) observed | switch_overhead estimate rises ≥ observation; actions needing that model gated out next decision |
| F4 | crash mid-episode (SIGTERM sim) | TASK_LEDGER closed INCOMPLETE, spent-so-far charged, restart refuses existing ledger |
| F5 | predictor NaN/inf for an action | that action infeasible this decision; error event; no propagation |
| F6 | illegal action attempted (cap/exactly-one violated) | rejected with reason; falls back to next-best legal |
| F7 | kill −9 during ledger append | partial last line never parsed as complete |
| F8 | FULL replay finishes but D6 still fails | episode terminal (replay once); R0 reflects q as-is |
| F9 | recipe cascade hits internal cap mid-LOCAL | cascade stops at cap (production semantics); state consistent |

## 9. Acceptance criteria

1. T3 policy–static equivalence (§2) passes bitwise on scripted panels.
2. Legality: no executed action ever violates §4 constraints (assert over
   full replays; test A1–A3).
3. Ledger/budget: TASK_LEDGER reconciles with stub Budget counts every
   decision (B1); crash honesty (B2/F4); G1⊂G2 containment (B5);
   double-charge audit (B6).
4. Determinism: same seeds + scripted server ⇒ identical episode trace.
5. Import-graph (L5): no production execution-path import; stdlib+numpy+
   PRIORS only; R1 absent from decision path.

## 10. Open decisions

- OPEN-B1 FULL semantics (default: E-arm matched; alternative: all-swap).
- OPEN-B2 fb memory-rule granularity under per-task decisions (default:
  panel-detection-order, D/E comparable).
- OPEN-B3 D_task allocation (default: rolling split).
- OPEN-B4 decision granularity: cascades as separate decisions (default: no).
- OPEN-S5 (carried, revised): the policy is exercised ONLY inside this
  package's stub engine in phases 2–3; no run_session integration.
