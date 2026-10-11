# M1_REPORT — stub execution engine, phase-2 milestone M1

Authorization: operator 2026-10-11 — "先完成 M1 的零真实调用 Stub 开发,
完成后暂停审查". Scope held to M1 exactly; M2+ NOT started. Zero real model
calls (sentinel + stdlib-only AST + socket-blocked suite, evidence below).

## Delivered (all under `deadline_reward_v1/`)

| File | Content |
|---|---|
| `stub_engine.py` | `InjectedClock` (sole time authority) · `StubModelServer` (scripted answers + declared synthetic PRIORS draws, invocation sentinel) · `StubEngine`: planned stages A→R1→V1 for the 4-node DYNAMICDAG with production-mirrored `run_stage` sorted-model batching (fault30_run.py:159-164), first-class switch records (incl. cold start), per-task wall tracking, append-only fsynced `TASK_LEDGER.jsonl`, refuse-on-existing-ledger (no silent resume), torn-line-safe loader. Stdlib-only imports (asserted). |
| `PRIORS_STUB_V1.json` | Synthetic profiles (normal family with declared mean/std; deterministic v3_compat reference-parity entry), switch costs, all entries `synthetic: true`, `class: stub_test_only`, version + source + sha256 in evidence (rulings P7/D3). |
| `test_stub_engine.py` | 19 acceptance checks; evidence → `evidence/M1_EVIDENCE.json`; run ledgers preserved under `evidence/m1_runs/`. |
| `__init__.py` | package marker, import-safe. |

## Test results — 19/19 ALL PASS, zero_model_calls=true

Highlights (full list in evidence):
- **T3-lite production-reference equivalence (NONE arm)**: the M1 engine
  reproduces the independently generated reference trajectory — production
  `fault30_run.eval_config` driven through `predictor_v3.V3Executor`
  (read-only imports) on `DYNAMICDAG__HETEROGENEOUS__NONE__FRESH`, 3-task
  panel — with IDENTICAL global call order, per-task order, and (node,
  kind, model) assignment (12 planned calls). This is the first slice of
  the T3a/T3b phase gate; LOCAL/FULL arms land with M4.
- **Batching regrouping**: per-task model assignment (the shape M5's π will
  produce) regrouped exactly per the sorted-model rule — a later-listed
  large-model job correctly jumps ahead of earlier medium jobs.
- **Wall semantics (B7 slice)**: single-task panel ⇒ wall == Σ service +
  Σ attributed switches EXACTLY (cold start included once); interleaved
  panel ⇒ wall ≥ Σ service per task.
- Determinism (bitwise-identical ledgers, seed-sensitive), torn-line
  loader, ledger-integrity replay, resume refusal, PRIORS hygiene.

## Semantic decisions made in M1 (flagged for review)

1. **Cold start is a first-class switch** (from null), charged at start
   cost only (no stop overhead) — attributed to the first task served.
2. **Per-task `wall_inclusive_s`** = first attributed event (incl. its
   preceding switch) → last call end on the mission clock. Under batched
   panels it includes interleaved other-task work. The POLICY-grade T for
   R_task (M6) will need the serial-episode semantics choice — recorded as
   an open point tied to OPEN-B3 (per-task deadline allocation).
   `service_sum_s` + `switch_sum_s` are recorded alongside, so all three
   time quantities of AUDIT II §6 stay separated.
3. `v3_compat` deterministic profile matches V3Executor's new-call metering
   (100 tokens / 0.2 s) purely for reference parity — not a latency claim.

## Explicitly NOT in M1 (awaiting authorization)

SchedulerState API (M2), closure/reuse machinery (M3), LOCAL/FULL recovery
execution + detection predicate wiring (M4), model reassignment (M5,
V10's target), two-stage policy + reward settlement (M6). No production,
Formal, or net-benefit file was touched; production imports exist ONLY in
the test file for reference generation (the sanctioned T3 pattern).

**Status: M1 complete; paused for operator review.**
