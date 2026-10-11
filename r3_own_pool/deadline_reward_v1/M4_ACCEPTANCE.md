# M4_ACCEPTANCE — formal acceptance of recovery execution & static equivalence

Operator authorization: M3 PASS / **M4 GO** (2026-10-11 dual-line review).
Scope held to reviewing, correcting where necessary, and independently
reference-verifying the EXISTING zero-call M4 implementation. **M5/M6
and phase-3 code exists in the repository but is NOT counted toward M4
acceptance** (§Process below). Zero real model calls; frozen Formal
data untouched. The two small Formal-audit hardening notes from the
review (crash-session response-count check; 18/18→23/23 comment) are
deferred to the next read-only audit pass per the operator's wording.

## 1. M4 inventory & commit lineage (mandated item 1)

| Artifact | Delivered at | Role |
|---|---|---|
| `recovery.py` | de09efe | static arms: NONE / LOCAL (eval_config mirror: ER memory rule, R2 on facts-changed, R3 ungated escalation, V2 final-state rule, V3) / FULL (eval_dag_arm mirror: recovery_plans-style per-task plans, group-by-identical-plan sorted, full-graph replay, trigger nodes on D-matched alternative models, others on PLANNED models, no cache substitution) |
| `stub_engine.py` (M4 semantics) | de09efe | corruption-AFTER-metering fault layer (campaign MeteredExecutor semantics), (model, input_sha) cache mirroring the production alias, task-ctx frozen assertion, per-job `no_cache`, orchestration entry points |
| `dag_closure.py` (M4 pre-checks) | de09efe | `SIG_INPUTS` prompt-material signature (v consumes e1+e2+r); reuse-candidate ctx-drift check |
| `scheduler_state.py` (M4 bits) | de09efe | exec_identity from engine events; recovery-kind counting; physical spend excludes aliases |
| `test_recovery.py` | de09efe + this round | T3a/T3b × 3 arms + 8 boundary tests; THIS round adds the literal single-task-panel T3a checks (28 checks total) |
| `evidence/m4_runs/*`, `M4_REPORT.md` | de09efe | run ledgers + delivery report |

**Process note (honest):** M4–M6 and phase-3 code was developed in an
earlier instruction round ("继续跑实验直到跑通") whose authorization is
superseded by the gate discipline now in force. M4 acceptance verifies
ONLY the artifacts above. Shared modules (scheduler_state, dag_closure,
stub_engine) gained later-milestone additions (reservation ledger,
contention hooks) in commits 7459698/b14c8fb/697d656/83ec860; the M4
suite passing AT HEAD (this round) demonstrates the M4 behaviors remain
intact; the strictly-pure-M4 snapshot is de09efe.

**Isolation proof:** `recovery.py` imports stdlib + `detection` only;
`stub_engine.py` stdlib + `dag_closure`; `scheduler_state.py` stdlib +
`dag_closure`/`detection`; `test_recovery.py` adds ONLY read-only
production reference imports (`fault30_protocol`,
`smoke_runner.Budget`, `evaluator.MeteredExecutor/_evaluate`,
`netbenefit_runner.recovery_plans`). **No imports of policy / predictor
/ compensator / reward anywhere in the M4 scope.**

## 2. Independent-reference equivalence (mandated items 2–4) — ALL PASS

Reference = PRODUCTION CODE driven through the real campaign executor:
`evaluator._evaluate` over `MeteredExecutor` + `Budget` + stub dispatch
(read-only imports, zero calls). For FULL, the reference is the
**E-arm-matched** path — `netbenefit_runner.recovery_plans` + the
grouped replay loop (`eval_dag_arm`'s Z=FULL branch) — **explicitly NOT
`JointEvaluator`'s all-model-swap FULL** (test_recovery.py:36-38,
production_reference).

**28/28 checks (25 delivered at de09efe + 3 added this round):**

- **T3a single-task (literal)**: `t3a_single_panel_{NONE,LOCAL,FULL}` —
  one-task panel per arm: identical (node, kind, model, cached,
  injected, task) sequences AND identical physical request/token
  counts vs the production reference.
- **T3a per-task** (multi-task panels): identical per-task sequences.
- **T3b multi-task**: `t3b_{arm}_global_order` (global call order incl.
  cross-task model-batched stage regrouping), physical requests and
  tokens equal for all three arms; not-torn ledgers.
- **Model switching**: parity of cached/injected flags across arms
  implies identical switch points; the engine's switch events carry the
  cost once (b6).

## 3. Mandated verification items (item 5) — M4-scoped mapping

| Requirement | M4-scoped evidence |
|---|---|
| FAILED retry charged | b3: same-model retry is a real metered call, re-corrupted (fault persists), node stays FAILED, never a success cache-hit |
| Legal cache hits not double-charged | engine cache mirrors the production alias; parity of cached flags + physical request/token equality across arms (cache hits excluded from physical on both sides); V2-alias case preserved (M4_REPORT deviation 4) |
| Context drift | b1: mid-episode ctx mutation is an engine error; b1b: judge R=[] rejects stale DONE caches |
| Downstream invalidation | b4 cascade: fb→facts changed→r_fbd executes as a NEW call (changed input identity, not an alias); LOCAL parity covers the final-state V2 rule |
| Budget conservation | M4-scoped: session physical accounting parity (session_summary == budget == ledger, all arms) + M2 dual-ledger. NOTE: the full reservation conservation invariant belongs to phase-3 code and is deliberately NOT counted here |

## 4. Internal unit tests vs independent reference — the distinction

- INDEPENDENT-REFERENCE equivalence: everything in §2 (production code
  generated the expectations; the engine matched bitwise).
- INTERNAL unit/behavior tests: §3's b1–b8 (engine invariants:
  alternation, switch-once, determinism, zero-call sentinel, socket
  block) — they verify OUR engine, not parity with production.
- NOT COVERED by M4 (boundaries): any dynamic policy (M5), constraint
  filter/reward (M6), cross-task contention (phase-3), multi-EPISODE
  cache persistence, cache-usage VALUE parity (both stubs' cached-usage
  conventions differ from alias-reuse conventions — physical counts and
  flags are what parity covers; documented in M4_REPORT caveats), and
  any latency-profile realism.

## 5. Regression & evidence

M4 suite 28/28 at HEAD; full repo regression (this round):
M1 21/21 · M2 24/24 · M3 37/37 · **M4 28/28** · M5+M6 18/18 · phase-3
19/19 · boundary 14/14 = 161/161 — but per the gate discipline ONLY the
M1–M4 rows count toward M4 acceptance; the M5+M6/phase-3/boundary rows
are reported as repository status, NOT as accepted milestones.
Evidence: `evidence/M4_EVIDENCE.json` (28 checks), run ledgers under
`evidence/m4_runs/` (incl. the new `single_*` runs).

**Status: M4 acceptance submitted. M5/M6 await separate review
authorization; net-benefit and real-model experiments remain HOLD.**
