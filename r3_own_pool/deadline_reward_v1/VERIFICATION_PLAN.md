# VERIFICATION_PLAN — executable test design, phases 2–3 (deadline_reward_v1, rev C)

Status: DRAFT v0.3 (rev C) — adds group V (two-stage decision, degradation,
cost separation, joint-action consistency). All prior groups carried.
Phase-2 code is not admissible to phase 3 without these tests. Zero real
model calls; seeded RNG, injected clock, socket disabled (Z2).

## L — information-leakage firewall

Decision-time property under test: the policy and predictor can obtain
neither task gold, nor the hidden fault registry/labels, nor outputs of
nodes not executed in this episode.

- **L1 differential fault-blindness.** Same seeds/task panel/scripted
  server; hidden fault panel redrawn (same rate) or removed ⇒ identical
  decision sequences, scores, and action traces (bitwise). ≥3 seeds × 3
  panels. (Fault content reaches the policy only through detection events +
  outcomes — both legal.)
- **L2 gold-blindness matrix.** Every ingestion point (DecisionContext,
  ActionView, EpisodeFeedback, SchedulerState constructor, scorer-to-policy
  channel) rejects an enumerated probe list (`gold`, `answer`,
  `derivation`, `faults`, `fault_panel`, `states`, future outputs, nested
  and callable smuggles). Probes live in `LEAK_PROBES.json` (extensible by
  the reviewer without writing code). The scorer's own terminal use of gold
  is asserted to be the ONLY read path (static + runtime check).
- **L3 unexecuted-node-output probe.** No legal construction exposes node
  outputs absent from this episode's TASK_LEDGER; synthetic "future"
  payloads injected through every channel are rejected.
- **L4 hidden-assignment blindness.** Shuffling fault ASSIGNMENTS within
  the same detection families leaves decisions identical (complements L1:
  no inference of WHICH node/task is faulted beyond observable predicates).
- **L5 import-graph assertion.** AST-level: the three modules import only
  {stdlib, numpy, PRIORS.json, sibling modules}; no production
  execution-path import (fault30_run/evaluator/runtime/engine); no
  torch/botorch; R1 absent from the decision path (OPEN-D7 carried).
- **L6 provenance hashing.** Every recorded decision carries SHA-256 of its
  legal-input snapshot; replayer recomputes and asserts 100% match.

## A — recovery-action legality

- **A1** cap enforcement: no LOCAL recipe event exceeds its production cap;
  no second FULL replay ever executes (exactly-one rule).
- **A2** legality under exhaustion: with caps exhausted, exhausted actions
  are absent from legal_actions; policy cannot select them (attempt → F6
  rejection path).
- **A3** NONE always legal: including at every detection family and at
  budget-exhausted states.

## T — state, transition, engine fidelity

- **T1** state update: after each applied action, node_status/recovery_cnt/
  observed match hand-specified expected states on scripted scenarios
  (one per action × trigger family).
- **T2** transition determinism: same seeds + server script ⇒ identical
  episode traces (two runs, bitwise).
- **T3 policy–static equivalence** (scheduler doc §2): π≡NONE ≡ Z=NONE
  trace; π≡LOCAL ≡ D-arm recipe; π≡FULL-on-D6 ≡ E-arm replay — bitwise call
  sequences on the scripted panel. This is the fidelity proof of the stub
  engine against the audited production semantics (AUDIT II §1–§4).
- **T4** cascade semantics: LOCAL cascades (fb→fbd→refresh) follow
  production trigger rules; final-state comparison rule (D4) reproduced
  incl. the R2=B,R3=A ⇒ r_changed=False case (fault30_run.py:354-366).

## B — budget & time accounting

- **B1** dual-ledger agreement: TASK_LEDGER vs stub Budget reconcile at
  every decision (tokens, requests).
- **B2** crash honesty: mid-episode kill ⇒ spent-so-far charged, no
  fabricated settle, restart refuses.
- **B3** wall-cap: injected clock past mission window ⇒ next check raises
  StopRun before any new reserve.
- **B4** malformed/oversized usage ⇒ settle raises, infra failure recorded,
  no silent retry.
- **B5** G1⊂G2 containment: every D_task and every margin ≤ mission work
  window at all times (assert from ledgers).
- **B6 double-charge audit**: for every decision, switch cost appears in
  exactly one of {predictor time estimate, compensator margin} — never
  both, never neither; safety margin likewise single-counted.
- **B7 three-quantity separation** (AUDIT II §6): recorded per-task wall T ≥
  Σ service latency (equality when zero gaps/switches scripted); critical-
  path L (production formula) recomputed and distinct from both; no test
  may assert T == Σ service when switches/gaps > 0 are scripted.

## R-F — failure recovery

F1 clock jump past D_task mid-episode → atomic call finishes, no new
action, (T−D)₊/1(T>D) charged in R0.
F2 all actions infeasible → forced NONE logged, no crash.
F3 pathological 600 s switch → estimate rises, that model gated next
decision.
F4 crash mid-episode → ledger INCOMPLETE, charged, restart refused.
F5 predictor NaN/inf → action infeasible this decision, error event, no
propagation.
F6 illegal action attempt → rejected with reason, next-best legal chosen.
F7 kill −9 during append → partial line never parsed as complete.
F8 FULL replay still fails D6 → terminal, q as-is.
F9 cascade hits cap mid-LOCAL → stops at cap, state consistent.

## Z — zero-call

- **Z1** sentinel counter + L5: only the stub scripted server is ever
  invoked; engine functions unreachable.
- **Z2** socket disabled during all tests.

## P — predictor parity & estimators

- **P1** action-event parity: enumeration per (action × trigger family)
  matches the frozen golden table (production-derived; search-space sizing
  retired — see AUDIT corrections §1).
- **P2** profile monotonicity + feasibility boundary flip at margin=w_p90.
- **P3 E1 goldens (CORRECTED formula)**: P̂/Ê on a golden grid incl. D=μ
  (0.399σ), D=μ+σ (0.0833σ), D≪μ (→μ−D), σ→0 point mass. The rev A
  formula is asserted WRONG on off-boundary points (negative/absurd values)
  as a regression tripwire.

## C — reward consistency & ablations

- **C1** R0 golden grid incl. T=D boundary; monotonicity (T>D: ∂R0/∂T≤0;
  ∂R0/∂q≥0; ∂R0/∂C≤0).
- **C2** E[R0] closed-form agreement with scripted predictor outputs
  (1e-9).
- **C3** telescoping: adding constant spent-so-far to all actions leaves
  argmax unchanged; final R0 reconciles with score components.
- **C4** NONE-never-free: scripted accept-the-failure episode scores below
  successful LOCAL by the q gap.
- **C5** ablation sanity (stub world only): π_R0 ≥ π_random-legal on ≥4/5
  adversarial scenarios; feedback-blind π_R0 variant strictly differs on
  ≥1 scenario (i.e., the feedback channel is live); action distributions
  logged per fault family for the confound audit (scheduler doc §7).

## V — two-stage decision, joint actions, degradation (rev C)

- **V1 worked-example golden (operator's A/B/C).** Scripted decision point:
  D_remain=20 s, Q_min=0.80, ε=0.10; three joint actions with (μ, w_p90, q̂)
  = A(24,–,0.95), B(17,21,0.85), C(12,–,0.60). PASSES iff A excluded on
  P̂<0.9 (time), C excluded on q̂<Q_min (quality), B chosen; AND in the
  variant where B's P90 pushes P̂ below 0.9, the feasible set is EMPTY and
  the degradation path fires (never a forced B).
- **V2 filter correctness incl. the uncertainty trap.** Across a scripted
  grid: no action with mean ≤ D but P̂ < 1−ε is ever admitted; no action
  with q̂ < Q_min admitted; ΔC > B_remain excluded; boundary equalities
  (q̂=Q_min, P̂=1−ε) admitted exactly (≥ semantics pinned).
- **V3 degradation & violation recording.** A_feasible=∅ scenarios: the
  chosen degraded action, violation vector (Q_min−q̂, 1−ε−P̂, ΔC−B_remain),
  and episode `degraded` flag all recorded; realized R_task settles from
  realized quantities; no forced feasible-looking action in any trace
  (assert over full replays).
- **V4 cost-record separation.** Every decision record carries C_new
  (incremental) only; settlement records C_full; schema assert prevents
  cross-contamination; C_full reconciles with Σ realized increments +
  pre-decision spend.
- **V5 joint-action consistency.** For every applied a=(Z,R,π): π within
  audited node menus (F11); R closure-consistent — every DONE/absent node
  whose input changed is in R or provably invariant (F12); reused nodes
  contribute zero ΔC (P-companion); engine never executes an inconsistent R.
- **V6 policy–static equivalence under the joint space** (extends T3):
  constant joint policies reproduce Z=NONE / D-arm / E-arm bitwise.

## Coverage map to the rev B/C instructions

| Instruction item | Covered by |
|---|---|
| execution-layer audit | AUDIT Part II |
| R_task task-level + conditional expectation | reward doc §3; C2–C3 |
| SchedulerState | scheduler doc §3; T1 |
| recovery action interface → **joint (Z,R,π)** | scheduler doc §4; A1–A3, V5, V6 |
| OutcomePredictor → action outcomes | predictor doc §3–5; P1–P3 |
| compensator unified, no double charge | scheduler doc §6; B5–B7 |
| wall vs serial separation | AUDIT II §6; B7 |
| verification plan retarget | this file |
| 96→48 + E1 corrections | AUDIT corrections; P3 tripwire |
| confound + ablation | AUDIT II §5; scheduler doc §7; C5 |
| **two-stage filter + no-forced-action (rev C)** | reward doc §3.2; V1–V3 |
| **C_new vs settlement (rev C)** | reward doc §3.2; V4 |
| **runtime-interface checklist (rev C)** | AUDIT II §12; M1–M6 build order |
