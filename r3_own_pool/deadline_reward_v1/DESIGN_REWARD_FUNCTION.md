# DESIGN_REWARD_FUNCTION — deadline_reward_v1 (rev B)

Status: DRAFT v0.3 (rev B) — restructured to the execution layer per the
operator ruling of 2026-10-10 (feedback-driven DAG dynamic recovery
scheduling). The R0 formula itself is unchanged from the finalized scheme;
its instantiation moves from "search reveal" to "task execution episode".
Zero model calls in phases 1–3.

Buddy docs: `AUDIT_EXISTING_CODE.md` Part II (execution-layer audit, cited as
II §n), `DESIGN_DYNAMIC_SCHEDULER.md` (state/actions/transition),
`DESIGN_PREDICTOR_INTERFACE.md`, `VERIFICATION_PLAN.md`.

## 1. Purpose

Define the reward for ONE task's execution episode under a dynamic recovery
policy: a task-level terminal reward R0 with deadline terms, and an online
decision score equal to its conditional expectation under legally observed
history, used at every recovery decision point (anomaly detected → choose
action).

## 2. Decision points and legal information

**Decision point** = any moment the executor's real detection predicates
(AUDIT II §2, D1–D6) fire for a task mid-episode, plus the terminal point.
At each, the policy chooses one legal recovery action (NONE / LOCAL / FULL;
scheduler doc §4).

**Legal inputs** (what the policy and its predictor may see; executable
firewall in VERIFICATION_PLAN L1–L6):

| Signal | Source | Legal for policy? |
|---|---|---|
| Node status, dependency state, current model per node, recovery counts | SchedulerState (scheduler doc §3) | YES |
| Detection outcomes D1–D6 (parse failures, mismatches, changed-outputs) | AUDIT II §2 predicates | YES |
| Per-call usage/latency of THIS task's executed calls | stub executor records | YES |
| Budget/time state: tokens spent, elapsed, D remaining (compensator) | driver-side | YES |
| **Task gold / correct answer** | — | **NO — terminal scoring only** (see §3.1) |
| Fault registry / which node was faulted / fault content | — | **NO — leakage** |
| Other tasks' gold; future outputs; other sessions | — | **NO** |

## 3. R0 — task-level terminal reward (finalized formula)

```
R0 = 1(T ≤ D)·q − λ_c·(C/C₀) − λ_t·(T−D)₊/D − λ_f·1(T > D)
```

Instantiation at the execution layer (each row pinned to a real, existing
measurement or a phase-2 stub obligation):

| Symbol | Meaning | Instantiation | Status |
|---|---|---|---|
| q | task quality | final-answer correctness under the frozen scoring contract (v2.1 Q semantics, task-level) | scorer-side [EXISTS]; per-task q in campaign rows (`ok`/Q_v21) |
| C | physical cost of the episode | Σ new_tokens over ALL the task's calls incl. every recovery call (physical_accounting, AUDIT II §10) | [EXISTS] |
| C₀ | normalization | frozen constant (default: per-task token allocation = session `new_total_tokens` / n_tasks) | OPEN-D3 |
| T | task completion time | **real per-task E2E wall** on the injected clock, including model switches and recovery re-execution | [MISSING in production — phase-2 stub engine obligation, AUDIT II §6.3] |
| D | task deadline | allocated by DeadlineCompensator from the session envelope (scheduler doc §6) | phase-2 |
| λ_c, λ_t, λ_f | weights | frozen constants in PRIORS.json | OPEN-D3 |

### 3.1 Gold enters ONLY the terminal reward — never a decision

q is computed by the SCORER after the episode ends, exactly as campaign
scoring does today. The policy, its predictor, and every intermediate signal
never receive q or gold (firewall §2; test L2). This is the standard
RL separation: realized reward may depend on gold; the policy's information
may not. Ablation note: because q is revealed only post-hoc, online learning
of q̂ inside one episode is impossible by construction — the predictor
estimates from priors + within-episode observable feedback (e.g., parse
success after recovery), never from this task's gold.

### 3.2 Online decision score = conditional expectation of the FINAL R0

At a decision point with legal history H and candidate action a:

```
score(a) = Ê[R0 | H, a] = P̂(T≤D | a)·q̂(a) − λ_c·ΔĈ(a)/C₀
                             − λ_t·Ê[(T−D)₊ | a]/D − λ_f·(1 − P̂(T≤D | a))
decision rule:  a* = argmax_{a ∈ legal(H)} score(a)
```

- `q̂(a)` — predicted post-recovery task quality (predictor doc §3): prior
  success rates by (fault family, action, models) + within-episode observed
  feedback; never this task's gold.
- `ΔĈ(a)` — incremental physical token bound of executing a (event
  enumeration × profiles; predictor doc §4). Note the −λ_c·C/C₀ term in the
  FINAL R0 charges the whole episode; at decision time the already-spent
  part is constant across actions, so only ΔC discriminates — the two are
  consistent by telescoping (spent-so-far is added back identically to every
  score; assert in test C4).
- `P̂(T≤D|a)`, `Ê[(T−D)₊|a]` — from the action's completion-time estimate
  (predictor doc §5) via estimator E1 (§3.3 below).

### 3.3 Estimator E1 (corrected in rev B — see AUDIT corrections §2)

With completion-time belief (μ, σ) for action a (μ = remaining service mean,
σ from p90: σ = (w_p90 − μ)/1.2816; degenerate σ≤0 → point mass):

```
P̂(T≤D)   = Φ((D−μ)/σ)
Ê[(T−D)₊] = σ·[φ(z) + z·Φ(z)],   z = (μ−D)/σ        (CORRECTED)
```

Check values: D=μ → 0.399σ; D=μ+σ → 0.0833σ; D≪μ → → μ−D. The rev A form
`σ[φ(z)+z(1−Φ(z))]` was wrong off the boundary and is retired; golden tests
regenerated (VERIFICATION_PLAN P3). Distribution form beyond normal is
OPEN-D6 (log-normal / empirical variants behind the same interface).

### 3.3a Time-accounting ownership (no double charge)

The predictor's (μ, w_p90) cover PURE service demand of the remaining calls
incl. action re-execution. Model-switch overhead is added ONCE by the
compensator when it forms the effective deadline/margin (scheduler doc §6),
and idle/gap time is tracked by the stub clock. Test B6 asserts switch cost
appears in exactly one of {predictor time estimate, compensator margin} per
decision — never both, never neither.

## 4. R1 — candidate incremental accounting reward (unchanged ruling)

R1 (the v0.1 per-step form) stays DEMOTED to diagnostics/ablation; excluded
from decision paths structurally (import-graph test L5). The rev A answers
stand: ΔQ* uses only already-revealed quality outcomes of COMPLETED tasks
(legal; no future estimation), and per-step/final consistency is behavioral
(C-tests), not algebraic.

## 5. Session-level aggregation

Session value = mean of realized task R0 over the task panel + one terminal
term (+B if all tasks completed within the envelope without StopRun; −P on
wall-budget StopRun or crash; charged once — crash honesty per
CampaignQuota convention). A task that terminates via action NONE with an
unfixed detected anomaly receives its R0 as-is (q reflects the failure) —
NONE is never "free".

## 6. Acceptance criteria (executable specs in VERIFICATION_PLAN)

1. Golden table: R0 exact-match on a scripted (q, C, T, D) grid incl.
   boundary T=D; monotonicity ∂R0/∂T≤0 (T>D), ∂R0/∂q≥0, ∂R0/∂C≤0.
2. E1 goldens on the corrected closed form (P3), incl. degenerate σ→0.
3. Telescoping check C4: adding a constant spent-so-far to all actions
   leaves argmax unchanged, and final R0 − Σ score-components reconcile.
4. Fault-blindness L1: fault-primed vs fault-free replays (same seeds)
   produce bitwise-identical decisions; gold-blindness L2: gold injections
   rejected everywhere in the policy path.
5. NONE never escapes charging (scripted accept-the-failure episode yields
   R0 < same episode under a successful LOCAL by the q gap — sanity).
6. `zero_model_calls: true` on every evidence file.

## 7. Open decisions

- OPEN-D3 (carried): λ_c, λ_t, λ_f, C₀, B, P values + calibration on stub
  replay before any real-data fit.
- OPEN-D5 (revised by rev B): the reward UNIT is now fixed = one task
  episode; remaining choice is C₀ granularity (per-task allocation vs
  mission-wide constant; default per-task allocation).
- OPEN-D6 (carried): E1 distribution family (default: corrected normal).
- OPEN-D8 (new): whether q̂ may condition on WITHIN-episode post-recovery
  observable feedback (parse success) — default YES (it is legal signal;
  ablation arm with q̂ feedback-off included).
- OPEN-D9 (new): tie-breaking rule when scores are equal (default: smallest
  ΔC, then action order NONE<LOCAL<FULL).
