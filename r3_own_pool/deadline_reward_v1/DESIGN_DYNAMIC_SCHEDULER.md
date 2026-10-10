# DESIGN_DYNAMIC_SCHEDULER — Phase 1 deliverable 3/4 (deadline_reward_v1)

Status: DRAFT v0.2 (revision A) for phase-1 review. Governs phase-2 files
`scheduler_state.py` and `deadline_compensator.py`. Zero model calls in all
phases through 3. Never imports or modifies `collab_scheduler_v1` runtime
files; runs beside the Formal campaign only in stub replay. Executable test
specs for §6 live in `VERIFICATION_PLAN.md` (F1–F7 mirrored there as
recovery tests R-F1…R-F7).

## 1. Positioning

The production loop (AUDIT §2.2) is `SearchSession.step(select, states)` with
a pure selector callback. The dynamic scheduler therefore wraps, not patches:

```
deadline_reward_v1 scheduler (new)                existing production seam
┌──────────────────────────────┐   select(candidates, observations)
│ SchedulerState               │ ───────────────────────────────────► SearchSession
│  + deadline_compensator      │ ◄───────────────────────────────────
│  + outcome_predictor         │            observations (legal view)
│  + reward                    │
└──────────────────────────────┘
```

Phase 2 drives this against the REAL `SearchSession` + `MeteredExecutor`
classes with a stub `dispatch` (the proven `selectors.run_closed_loop`
pattern, AUDIT §2.7) — no edit to any running file.

## 2. `scheduler_state.py` — responsibilities

1. **Decision state**: selected set, per-round rewards (per
   DESIGN_REWARD_FUNCTION), budget snapshot trail, current model, switch
   history, rounds remaining vs `max_configurations`.
2. **Deadline-aware selection policy** (rev A; per the reviewer's ruling the
   R0 conditional expectation is the primary score — DESIGN_REWARD_FUNCTION §3.1):
   ```
   feasible(c)   := W_p90(c) ≤ D̂(c)                    # hard gate first (G1)
   score(c)      := Ê[R0 | H, c]                        # primary (rev A)
                    = P̂(T≤D)·q̂ − λ_c·Ĉ/C₀ − λ_t·Ê[(T−D)₊]/D − λ_f·(1−P̂(T≤D))
   choose        := argmax over feasible of score; if none feasible,
                    choose argmin W_predicted (graceful wind-down)
   ```
   The v0.1 default score `EI/(1+α·cost)` (the existing proposed form,
   AUDIT §2.2) is retained ONLY as ablation baseline arm A2
   (DESIGN_REWARD_FUNCTION §5); `random` is arm A3. Selector arms are chosen
   at construction, mirroring the campaign's per-method session style.
   **Double gate (AUDIT §2.9):** G1 = the per-cell feasibility gate and R0
   deadline terms against the compensator-allocated D̂; G2 = the production
   `Budget.wall_seconds` + SIGALRM backstop (unchanged, runtime.py:133-138).
   G1 ⊂ G2 by construction (D̂ is allocated inside the work window), so the
   scheduler can never authorize work the hard cap would kill; wind-down that
   finishes inside the window is COMPLETE, not an R0 violation.
3. **Event hooks** (called by the phase-2 stub driver):
   `on_round_start`, `on_switch(model, wall_s)`, `on_reveal(observation)`,
   `on_stop(reason)` → terminal reward, `snapshot()`.
4. **Own ledger** `SCHEDULER_STATE.jsonl`: append-only, fsync, one event per
   hook + per decision (terms, features, hashes of legal inputs). Resume
   policy mirrors Budget/CampaignQuota: existing ledger ⇒ refuse to start a
   second state over it; explicit reconciliation tool only (OPEN-S3: whether
   a `--reconcile` subcommand is in phase-2 scope; default: error out only).
5. **Crash honesty**: any exception path appends a terminal INCOMPLETE event
   before re-raising; reward charges `−P_incomplete` exactly once.

## 3. `deadline_compensator.py` — responsibilities

Converts raw wall budget into an honest per-candidate usable deadline.

```
inputs : wall_cap, cleanup_reserve (default 60 s, matches runtime.py:136),
         switch history of THIS session [(from_model, to_model, wall_s)],
         per-model E[start_s], E[stop_s] estimators (see §4)
output : D̂(c | current_model) = wall_cap − cleanup_reserve − elapsed
                       − Σ_{m ∈ models(c), m ≠ current_model}
                             (E[stop_cur_share] + E[start_m])
         − safety_margin
```

- `models(c)`: distinct model slots in candidate c's X.
- Safety margin (OPEN-S4): default `max(0, q90(switch_overhead_history))`
  once ≥3 switches observed, else a frozen prior of 45 s (justified from
  MODEL_SWITCH data only AFTER phase-3 provenance review; frozen constant
  until then).
- Estimator update rule: running mean + count per (from,to) pair; priors
  seeded from frozen constants, never from other sessions' files.
- `remaining_rounds_budget()`: maps `D̂` into "how many more expected rounds
  fit" — used by the wind-down path and the reward's DeadlineDebt.

## 4. Where estimator priors may come from (provenance rule)

Phase 2/3: frozen constants in a versioned `PRIORS.json` inside
`deadline_reward_v1/` (values chosen manually, documented). Reading the
Formal campaign's MODEL_SWITCH.jsonl to fit priors is a data-provenance
decision reserved for the phase-4 gate (AUDIT §3); until admitted, tests use
stub switch latencies via the injected clock.

## 5. Determinism and testability

- All time reads via injected clock (`clock=` convention, AUDIT §2.7).
- No RNG except seeded `random.Random(seed)`; seeds recorded per run.
- Scheduler never holds references to evaluator/ledger/tasks/faults; the
  driver hands it only the legal view (reward doc §2 table).
- Module import must have zero side effects (no model startup, no GPU locks —
  mirroring runtime.py's import-time guarantees).

## 6. Failure-mode matrix (each row = one phase-3 test)

| # | Scenario | Expected behavior |
|---|---|---|
| F1 | Stub clock jumps past work window mid-round | StopRun propagates; terminal INCOMPLETE event + `−P` exactly once; ledger closed |
| F2 | Every candidate infeasible under D̂ | Wind-down pick (argmin W), never a silent random choice; event logged `mode=winddown` |
| F3 | Switch estimator sees pathological 600 s start | Next D̂ drops by ≥ that estimate; candidate needing that model gated out |
| F4 | Crash (SIGTERM simulation) between events | Ledger shows no settle-after-crash; restart refuses (no silent resume) |
| F5 | Predictor returns NaN/inf | Decision skipped this round, candidate treated infeasible, error event logged; no crash |
| F6 | Duplicate selection attempt | Rejected exactly like SearchSession does (illegal selection guard) |
| F7 | Reward trajectory fault-blindness | Same seeds ± hidden faults ⇒ identical decisions & rewards |

## 7. Acceptance criteria (phase-3 review)

1. All F1–F7 pass with `zero_model_calls: true`.
2. Selection respects feasibility gate: no chosen candidate with
   `W_predicted > D̂` unless in wind-down mode (assert over full replay).
3. Ledger reconciliation: event counts, fsync'd appends, no mid-file rewrites;
   SCHEDULER_STATE.jsonl survives kill -9 mid-write without a torn final line
   being interpreted as complete (length-prefixed or line-atomic appends).
4. Budget double-check: scheduler's own accounting of new_tokens equals the
   stub Budget's `actual_tokens` at every round boundary (two independent
   ledgers must agree — mirrors evaluator's physical-ledger assertion).
5. No import of torch/botorch anywhere in scheduler_state/compensator.

## 8. Open decisions (finalize at phase-1 review)

- OPEN-S1 hard gate vs multiplicative penalty (default: hard gate).
- OPEN-S2 wind-down policy: argmin predicted demand vs stop-early-and-settle
  (default: argmin; stopping early wastes reserved-but-unspent budget).
- OPEN-S3 reconcile subcommand scope (default: out of phase-2 scope).
- OPEN-S4 safety margin form (default: q90 after 3 switches, frozen prior
  before).
- OPEN-S5 whether SchedulerState also emits the `select` callback directly
  for run_session compatibility, or stays driver-mediated (default:
  driver-mediated; keeps production seam untouched).
