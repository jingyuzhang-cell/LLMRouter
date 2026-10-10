# AUDIT_EXISTING_CODE — Phase 1 deliverable 1/4 (deadline_reward_v1)

Date: 2026-10-10. Method: read-only source review. Model calls: **0**.
Files written by this phase: only under `r3_own_pool/deadline_reward_v1/`.
No file used by the running Formal campaign was modified (verified: Formal
driver PID 4815 writes only under `joint_search_v1/formal_campaign_v2*`).

## 1. What was audited

Core (read in full):
- `collab_scheduler_v1/joint_search_v1/evaluator.py` (201 L) — space(), MeteredExecutor, JointEvaluator, SearchSession
- `collab_scheduler_v1/joint_search_v1/runtime.py` (190 L) — CampaignQuota, require_admission, run_session
- `collab_scheduler_v1/joint_search_v1/formal_launch.py` (329 L) — the RUNNING driver (read-only)
- `collab_scheduler_v1/joint_search_v1/selectors.py` (357 L) — six selector callbacks
- `collab_scheduler_v1/joint_search_smoke/proposal_v2/smoke_runner.py` (266 L) — Budget, StopRun, SmokeExecutor
- `collab_scheduler_v1/predictor_v3.py` (348 L) — incremental-cost event enumeration predictor

Referenced (symbols used above): `fault30_protocol.py` (Ledger, planned_models,
build_faults), `fault30_run.py` (eval_config, physical_accounting),
`sa_pgfs_v1/surrogate.py` (QSurrogate), `static_dag_v0/run.py` (engine:
start_model/stop_model/call_model), `static_dag_v0/multidag_dynamic.py`
(value_of, json_value, close).

## 2. System snapshot (facts the reward/penalty design must build on)

### 2.1 Workflow and search space
- Fixed 4-node DAG: `e1, e2, r, v`. Config = `X` (per-node model in
  {medium, large} for e1/e2/r, {coder, large} for v) × `Z` (recovery policy:
  NONE | LOCAL | FULL). 96 configs total (`evaluator.space()`).
- Deployment objectives per (config, state): `Q` (v2.1 contract correctness,
  mean over task panel), `C` (cold logical workflow tokens, mean),
  `L` (SERIAL service-demand reconstruction = Σ per-call latency_s, mean —
  explicitly *not* an end-to-end wall claim).
- Search spend (physical) tracked separately in `search_spend`:
  `new_requests`, `new_tokens`, `new_latency_s`, plus `observed_wall_s`.

### 2.2 Scheduling loop (what "dynamic scheduling" plugs into)
- `SearchSession.step(select, states)`: selector is a pure callback
  `select(candidates, observations) -> config_id`. It receives **deep copies**.
  Constraints: no repeated/illegal selection; max_configurations budget.
- Information boundary (enforced in code): `states` and the fault registry are
  NEVER passed to `select`; selectors see only candidates + accumulated
  `observations` (each with `objectives` and `search_spend`). Gold answers are
  never exposed to the selector path (`detected_failure` reads observable
  outputs only; Q_v1/Q_v21 computed after the reveal, stored in observations).
- Production selectors live in `joint_search_v1/review/track_b.py`
  (`ProductionSearcher` + `SyncedSelector` bridge, formal_launch.py:168-183).
  The audited `selectors.py` variants: `proposed` = QSurrogate GP + EI, score
  divided by `(1 + alpha * incremental_cost_upper_bound)` (alpha=0.5);
  two single-mechanism ablations; `scalarized_bo`; `random`; official BoTorch
  qNEHVI (fail-closed, raises on BoTorch error — no silent degradation).

### 2.3 Budget and stop rules (current state — no anticipatory control)
`smoke_runner.Budget` (per session):
- Caps: `new_request_attempts`, `new_total_tokens`,
  `request_token_reservation` (pre-charged per call, settled to actual),
  `max_output_tokens`, `wall_seconds`,
  `logical_calls_per_task_config_state`.
- Semantics: reserve→settle ledger in `DISPATCH.jsonl` (append-only, fsync);
  crash ⇒ reservation stays charged. A new Budget on an existing
  DISPATCH.jsonl is an ERROR ("explicit reconciliation required") — no silent
  resume.
- `check()` is **passive**: raises StopRun when already over the wall cap;
  called before each dispatch, in `prepare()`, and after each settle. There is
  no prediction of "will the NEXT config fit in remaining budget".

### 2.4 Deadline handling today (the gap deadline_compensator addresses)
- `runtime.run_session`: work window = `per_session_caps.wall_seconds − 60`
  (60 s reserved for backend shutdown ≤ 40 s), enforced by
  `signal.setitimer(ITIMER_REAL, ...)`; SIGALRM/SIGTERM raise StopRun →
  session settles INCOMPLETE. (runtime.py:133-138)
- Model switches are IN the work window: `prepare(model)` stops the current
  model, starts the new one, appends cost to `MODEL_SWITCH.jsonl`
  (wall_s per switch). Switch latency is measured but **never used
  predictively** — a config whose model set guarantees a switch can silently
  consume a large fraction of the remaining wall budget.
- Campaign level: `CampaignQuota` (flock + append-only CAMPAIGN.jsonl;
  reserve at session start, settle with actual charge; overrun is recorded,
  never hidden). Formal driver additionally enforces a campaign headroom rule
  (7,200 − 299 prior requests) across all campaign roots before each session.

### 2.5 Predictor landscape (what outcome_predictor must interoperate with)
- `predictor_v3.predict_v3(config, task, cache_shas, led)` →
  `{lower, upper, certain[], conditional[], total_events}`: enumerates call
  events (planned e/r/v; under Z=LOCAL also e_fb×2, r_fbd, r_esc, v_fbd,
  v_esc), exact SHA cache check only for deterministic e-node prompts.
- `selectors._predict_incr_cost(cfg)`: static upper bound table
  (NONE=4, LOCAL=10, FULL=8 events) — no cache awareness in the search loop.
- `sa_pgfs_v1.surrogate.QSurrogate`: `fit(X, y)`, `predict(X, return_std=True)`
  — the existing quality surrogate used inside EI. Features: 5-dim
  `[e1, e2, r, v, Z]` ordinal encoding (`selectors._feat`).
- **Missing**: no explicit outcome (Q) predictor interface; no latency
  predictor; no feasibility/completion predictor; nothing reads
  MODEL_SWITCH history.

### 2.6 Faults and recovery (reward must stay blind to these)
- Fault panel: 30% of task uids, node uniform over e1/e2/r/v, typed
  corruption (empty facts / unparseable r / null v), frozen at build time
  (FAULT_SEED 20261009), hidden from selectors by construction.
- Z=LOCAL recovery: fb (first→coder, rest→medium), fbd refresh, esc
  escalation events, all enumerated by predictor_v3.
- Z=FULL: exactly one full-graph replay with frozen alternative models
  (large↔coder swap), all logical nodes re-charged in C/L.
- MeteredExecutor: corruption is injected AFTER a metered valid response —
  faulted calls keep real deployment cost; ledger/trajectory unchanged.

### 2.7 Stub/simulation infrastructure (phase 2/3 test bed)
- `predictor_v3.V3Executor`: answers-map executor with fault injection,
  running cache, full call_log — a proven zero-call executor pattern.
- `selectors.run_closed_loop()`: drives the REAL SearchSession +
  MeteredExecutor + real Budget with a stub `dispatch(model, prompt)` —
  the exact pattern phase 2 should reuse (zero_model_calls=True convention).
- `Budget.__init__(..., clock=time.monotonic)` already accepts an injectable
  clock — controlled-time tests for deadline logic need no monkeypatching.
- Existing per-module test files (`test_runtime.py` 10/10, `test_evaluator.py`,
  `test_fast_backend.py`) set the expected style: real assertions, JSON
  evidence files, `all_pass` flags.

### 2.8 Authorization style (phase 4 will need the same)
- `require_admission`: protocol SHA binding + admission JSON gates
  (selector_review, independent_splits, new_semantics_real_validation,
  runtime_tests) + `JOINT_SEARCH_EXECUTE=1` env + frozen input bindings
  (per-file SHA). Fail-closed everywhere; no silent rebinding
  (`FileExistsError` on existing launch/admission files).

### 2.9 Wall-clock reconstructability verdict (added in revision A — evidence, not gap analysis)

Question put by the phase-1 reviewer: are historical task-level latencies
RECONSTRUCTABLE / PARTIALLY_RECONSTRUCTABLE / NOT_RECONSTRUCTABLE, and are
the observation fields needed for future task/node/recovery/scheduling
overhead prediction complete? Evidence below is a READ-ONLY schema
inspection of one COMPLETE finished session
(`formal_campaign_v2/official_qnehvi_same_state_20261009/`, 2026-10-10;
nothing was written). Code-level facts cited from the audited sources.

**Verdict table:**

| Quantity | Verdict | Evidence |
|---|---|---|
| Per-call service latency (physical + faulted) | **RECONSTRUCTABLE** | `TRAJECTORY.jsonl`/`WORKFLOW.jsonl`: every logical call has `response.start_unix`, `end_unix`, `latency_s` (930 records in the inspected session). Faulted calls keep the real metered latency (MeteredExecutor replaces only the answer; AUDIT §2.6). |
| Per-task serial service demand (L semantics) | **RECONSTRUCTABLE** | Recorded directly per task in `EVALUATIONS.jsonl → tasks[].L_serial_service_reconstructed_s`; independently recomputable from WORKFLOW by summing `latency_s` over the task's keys (cold/alias semantics by design, evaluator docstring). |
| Per-cell (config×state) evaluation wall | **RECONSTRUCTABLE** | `EVALUATIONS.jsonl → search_spend.observed_wall_s` per reveal. |
| Per-session wall | **RECONSTRUCTABLE** | `STATUS.jsonl → observed_wall_s`; bracketed by first/last `DISPATCH.jsonl → unix`. |
| Per-task E2E wall | **PARTIALLY_RECONSTRUCTABLE** | (a) cache hits carry the SOURCE call's timestamps (alias reuses the cached response object), and the TRAJECTORY append itself is untimestamped — a hit's instant is only bracketed by the surrounding physical calls' unix times (execution is serial, so the bracket is tight but not exact); (b) `MODEL_SWITCH.jsonl` (26 switches inspected) has `wall_s` but no cell/task attribution. |
| Per-(node, model) latency samples for priors | **FIELDS PRESENT** | node is embedded in every `key` (4th colon field); recovery events (fb/fbd/esc) appear as ordinary calls when they fire (`search_spend.injected_calls`, `dry_calls` counters exist). Usable for PRIORS only after the phase-4 provenance gate (§4 of the scheduler doc). |

**Completeness for the future predictor (question's second half):** node-level
service samples, recovery-event samples, and switch-cost samples all exist as
fields. What does NOT exist anywhere: per-hit timestamps, per-switch→cell
attribution, and any inter-call scheduling-gap record beyond the unix
brackets. Consequently the R0 deadline terms must be defined on serial service
demand + recorded wall brackets, NOT on a claim of exact E2E per-task wall.

**Double wall-clock gate (explicit conclusion):** two independent gates exist
and must stay consistent in the design: (G1) the R0 task/cell deadline D vs
realized T (reward-level), and (G2) the production hard caps —
`Budget.wall_seconds` + `run_session`'s SIGALRM at `wall_seconds − 60`
(audit §2.4). Resolution adopted by the design docs (rev A): D for the next
cell is ALLOCATED by `deadline_compensator` inside the G2 work window
(`D̂ = wall_cap − 60 − elapsed − predicted_switch_overhead − safety_margin`);
G2 remains the unconditional backstop. A cell that violates its allocated D
triggers the R0 over-deadline terms; a session that hits G2 settles INCOMPLETE
exactly as today. The two gates therefore never conflict: G1 ⊂ G2 by
construction, and G1 violations are observable strictly before G2 can fire.

## 3. Running Formal campaign — files this project must not touch

- Driver: PID 4815, `formal_launch --run --launch FORMAL_LAUNCH_V2.json
  --admission FORMAL_ADMISSION_V2B.json --only <7 sessions>`, plus a vLLM
  server (Qwen2.5-7B, port 8128) and GPU lock `collect/logs/local_gpu.lock`.
- HOT directories (append-only, owned by the driver):
  `joint_search_v1/formal_campaign_v2*` (incl. retry1..7), i.e.
  `CAMPAIGN.jsonl`, `CAMPAIGN_LOG.jsonl`, per-session `*/` trees
  (DISPATCH/TRAJECTORY/EVALUATIONS/WORKFLOW/STATUS/MODEL_SWITCH jsonl).
- Read-only consumption of finished artifacts for calibration is a phase-3/4
  question (data provenance review), not something phase 1 does.

## 4. Gap analysis (why deadline_reward_v1 exists)

| Need | Current state | Gap |
|---|---|---|
| Per-decision reward/penalty signal | Q/C/L aggregated per (config, state) reveal | No reward defined over scheduling decisions; no deadline term |
| Deadline awareness in selection | Selector sees candidates+observations only; Budget never passed in | No remaining-time feasibility gating; switch cost ignored prospectively |
| Deadline compensation | Fixed −60 s cleanup reserve; MODEL_SWITCH.jsonl recorded, unused | No compensator predicting switch/startup overhead against remaining wall |
| Outcome prediction | Implicit GP-EI inside selectors; explicit cost-bound predictor_v3 (offline tooling) | No uniform predictor interface (Q̂, Ĉ, L̂, feasibility) usable by both scheduler and reward |
| Failure recovery in new code | CampaignQuota crash-safe; Budget no-resume | Phase-2 scheduler_state must replicate crash-honest semantics in its own ledger |
| Information boundaries | Enforced at SearchSession; faults/states hidden | Reward features must be derived from legal observations only — needs explicit test |

## 5. Design constraints extracted for the three design docs

1. Reward signals must be computable from `observations` entries
   (`objectives.Q/C/L`, `search_spend.*`) + Budget state that run_session
   already holds — anything else (faults, gold, task labels) is leakage.
2. A deadline-aware selector cannot be dropped into the running Formal: it
   changes selection behavior. Phase 2/3 code must therefore live in
   `deadline_reward_v1/` and be exercised on stub replay only; any future
   real run is a separately admitted campaign (phase 4).
3. Wall-clock semantics differ by surface: search wall (Budget.wall_seconds,
   hard SIGALRM) vs deployment L (serial service demand). The reward function
   must not conflate them.
4. Crash semantics: any scheduler_state ledger must be append-only,
   reserve-before-spend, and must refuse silent resume — mirroring Budget /
   CampaignQuota conventions.
5. Stub tests must inject the clock (Budget already supports `clock=`), inject
   model-switch latencies, and assert zero real model calls
   (`zero_model_calls: true` evidence keys, existing convention).
6. Predictor interface must compose with predictor_v3's event enumeration
   (cost side) and QSurrogate (quality side) rather than duplicate them.

## 6. Verdict

The codebase provides everything phase 2 needs to build against WITHOUT
touching the Formal campaign: pure-callback selector seam
(`SearchSession.step`), injectable-clock Budget, an executor whose dispatch is
a callable (stub-friendly), measured-but-unused switch latencies, and an
established zero-call test convention. The main design work is (a) defining
the reward without oracle access, (b) deadline compensation that is honest
about the −60 s reserve and switch overhead, (c) a predictor interface that
unifies cost bounds and quality surrogates.
