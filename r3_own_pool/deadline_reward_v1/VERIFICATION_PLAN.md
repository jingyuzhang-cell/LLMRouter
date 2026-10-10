# VERIFICATION_PLAN — executable test design for phases 2–3 (deadline_reward_v1)

Status: DRAFT v0.1, added in revision A (2026-10-10) as the direct answer to
review finding #4 ("验收需要看到可执行测试设计"). This file consolidates every
executable test the three modules must ship with; phase-2 code without these
tests is not admissible to phase 3. All tests run with ZERO real model calls.

Run convention (matches codebase style): one JSON evidence file per group
(e.g. `LEAKAGE_TESTS.json`) with per-test PASS/FAIL, an `all_pass` flag, and
`zero_model_calls: true`; exit code 0 iff all_pass. Deterministic: seeded
RNG, injected clock (`Budget(clock=)` convention, AUDIT §2.7).

## L — information-leakage firewall (finding #4)

The property under test: **at decision time, nothing can obtain task gold,
hidden fault assignments/labels, or outputs of nodes that were not executed
in this session.**

- **L1 differential fault-blindness (the decisive test).**
  GIVEN the same seed, task panel, and observation stream; WHEN the hidden
  fault panel is redrawn (different uid→node assignment, same rate) or
  removed entirely; THEN the decision sequence, all Ê[R0|H,a] scores, and the
  realized R0 trajectory are BITWISE identical. Runs across ≥3 seeds ×
  {none, redraw-1, redraw-2} panels. PASSES iff every pairwise diff is empty.
  (Faults influence answers only through evaluation results, which the legal
  view already prices in — decisions must not move when only the hidden panel
  moves.)
- **L2 illegal-key rejection matrix.** For EVERY entry point that ingests
  data (`OutcomePredictor.observe`, `state_view` factory, `ConfigView`
  constructor, `DeadlineContext` constructor): feed a enumerated probe list —
  `gold`, `answer`, `derivation`, `faults`, `fault_panel`, `states`,
  `task_labels`, `ok_internals`, plus nested probes (`objectives.__gold__`,
  `search_spend.fault_map`) and non-scalar smuggles (callable, object with
  `__getitem__`). PASSES iff each raises ValueError naming the rejected key,
  and the whitelist accept-list still works. The probe list lives in this
  repo as `LEAK_PROBES.json` so reviewers can extend it without writing code.
- **L3 unexecuted-node-output probe.** `ConfigView` is structurally limited
  to (id, X: node→model, Z) — it cannot carry node outputs. Runtime probe:
  construct ConfigView with extra fields → TypeError/ValueError; then, for a
  scripted history, append synthetic "future" node outputs through every
  legal channel (observe/state_view) in mutated payloads → all rejected by
  L2's whitelist. PASSES iff no legal construction path exposes node outputs
  of calls not present in this session's own TRAJECTORY-equivalent stub log.
- **L4 hidden-state blindness vs public state labels.** The state NAME in
  observations (`clean`/`fault30`) is public protocol knowledge; the fault
  ASSIGNMENT is not. GIVEN identical seeds; WHEN fault assignments are
  shuffled within the same state label (L1's redraw restricted to keep labels
  fixed); THEN decisions are identical. (Complements L1: proves the scheduler
  cannot infer WHICH tasks are faulted, only react to revealed results.)
- **L5 import-graph assertion.** Static check over the three modules' ASTs:
  no import of `fault30_run`, `fault30_protocol`, evaluator internals, ledger
  objects, tasks, or any `static_dag_v0` engine symbol; no import of
  torch/botorch; and — enforcing OPEN-D7 — the scheduler's selection path
  must not reference the R1 symbol (`import`/attribute graph assertion).
  PASSES iff the dependency graph is exactly: {stdlib, numpy, PRIORS.json,
  the three sibling modules, QSurrogate (predictor quality side only)}.
- **L6 state_view provenance hashing.** Every reward/score evaluation appends
  the SHA-256 of its legal-input snapshot; a replayer recomputes hashes from
  the stub logs and asserts equality. PASSES iff replayed hashes match 100% —
  proves no off-ledger data influenced any recorded decision.

## R-F — failure recovery (mirrors DESIGN_DYNAMIC_SCHEDULER §6)

R-F1 clock jump past work window mid-round → StopRun propagates, terminal
INCOMPLETE + `−P` exactly once, ledger closed.
R-F2 all candidates infeasible → wind-down pick `argmin W_predicted`,
`mode=winddown` logged, never a silent random choice.
R-F3 pathological 600 s startup recorded → next D̂ drops by ≥ the estimate;
that model's candidates gated out.
R-F4 SIGTERM/crash between events → no settle-after-crash; restart refuses
existing SCHEDULER_STATE.jsonl (no silent resume).
R-F5 predictor returns NaN/inf → round skipped for that candidate, treated
infeasible, error event logged, no crash.
R-F6 duplicate/illegal selection attempt → rejected exactly like
SearchSession's guard.
R-F7 torn-final-line robustness → kill -9 during append; loader treats a
partial last line as absent-but-flagged, never as complete.

## B — budget constraints

- **B1 dual-ledger agreement.** Scheduler's own per-round token accounting ==
  stub `Budget.actual_tokens` at every round boundary (independent ledgers
  must agree; mirrors the evaluator's physical-ledger assertion, AUDIT §2.3).
- **B2 crash-honest reservation.** Kill mid-round → the round's reservation
  stays charged in both ledgers; STATUS-equivalent shows pending ≠ 0 and no
  fabricated settle.
- **B3 wall-cap under adversarial clock.** Injected clock fast-forwards past
  `wall_seconds` → next `check()` raises StopRun BEFORE any new dispatch is
  reserved (assert: attempts did not increase after the raise point).
- **B4 token-cap rejection.** Stub dispatch returns usage exceeding
  reservation caps / malformed usage → settle raises (production semantics),
  scheduler records infra failure, does not retry silently.
- **B5 D̂-window containment.** For every round, allocated D ≤
  `wall_cap − 60 − elapsed_at_allocation` − safety margin (assert from
  SCHEDULER_STATE.jsonl; G1 ⊂ G2, AUDIT §2.9).

## Z — zero-call

- **Z1 dispatch isolation.** Import-graph (L5) + runtime: the only callable
  ever invoked is the stub `dispatch` passed by the test driver; a sentinel
  counter asserts engine functions are never reached. Evidence keys
  `zero_model_calls: true`.
- **Z2 network-proof execution.** All L/B/R-F tests run under a context
  manager that patches `socket.socket` to raise; PASSES iff no test touches
  the network (catches accidental real-API usage, including imports with
  lazy network side effects).

## P — parity & predictor

- **P1 event-table parity.** All 96 configs enumerate 4/10/8 events by
  Z=NONE/LOCAL/FULL vs a frozen golden file (generated once, zero calls) —
  parity with predictor_v3's published table (AUDIT §2.5).
- **P2 profile monotonicity.** Scaling any p90 latency profile by k scales
  `w_p90_s` by k; feasibility flips exactly at `D̂ = w_p90_s`.
- **P3 E1 estimator goldens.** `P_on_time`/`E_late` match closed-form values
  to 1e-9 on a golden grid incl. boundary D = w_mean and the σ→0 degenerate
  branch (DESIGN_PREDICTOR_INTERFACE §5.1).

## C — R0 consistency & ablation (DESIGN_REWARD_FUNCTION §4–5)

- **C1 policy dominance.** On ≥5 scripted stub scenarios (adversarial mix:
  heavy-switch, tight-deadline, cheap-quality, degenerate-prior), session
  return of arm A1 (R0-greedy) ≥ A2 (EI/cost) ≥ A3 (random) in ≥4/5
  scenarios, and never below random anywhere (one-sided scripted-world check,
  not a statistical claim).
- **C2 R1 explanatory power.** Sign agreement between R1 trajectory and
  realized R0 outcome ≥80% of rounds per scenario (gate for any future
  promotion of R1, per the reviewer's ruling).
- **C3 R0 golden table.** Scripted (q, C, T, D) grid incl. boundary T=D →
  exact-match vs hand-computed values; monotonicity ∂R0/∂T≤0 (T>D), ∂R0/∂q≥0,
  ∂R0/∂C≤0.

## Coverage map to the reviewer's four findings

| Finding | Covered by |
|---|---|
| 1. R0 primary / R1 candidate + consistency | reward doc rev A §3–5; C1–C3 |
| 2. wall-clock verdict + double gate | AUDIT §2.9 (evidence table); B5; P2 |
| 3. path/file-count change | README rev A §"Location decision" |
| 4. executable leakage tests | L1–L6 (+L2's extensible LEAK_PROBES.json) |
