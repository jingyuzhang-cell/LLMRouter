# M4_REPORT — static recovery execution + production equivalence (T3a/T3b)

Authorization: operator M3-errata review (2026-10-11) — "M4 GO". Scope held
to M4 (recovery execution + static equivalence); M5/M6 NOT started; zero
real model calls. Suites: M1 21/21 · M2 24/24 · M3 35/35 · M4 25/25
(105 checks total, idempotent, socket-blocked, no old assertion relaxed).

## Headline result

**All three static arms — NONE, LOCAL, and FULL (frozen E-arm MATCHED
semantics) — reproduce the independently generated production reference
BITWISE on T3a (per-task call semantics) and T3b (global order, batching,
fault cascades, physical request/token accounting).** The reference is the
production path the net-benefit campaign actually ran: `evaluator.
_evaluate` (recovery=True for the D-arm LOCAL machinery) + `netbenefit_
runner.recovery_plans` + the grouped replay loop for the E arm, driven
through the REAL campaign executor — `MeteredExecutor` with a `Budget` and
a stub `dispatch` (read-only imports; zero real calls). No arm is BLOCKED.

## Delivered

| File | Content |
|---|---|
| `recovery.py` | `run_arm(engine, state, tasks, node_models, arm)` for NONE / LOCAL / FULL. LOCAL mirrors `eval_config` LOCAL_REROUTE stage-for-stage (ER memory rule by panel detection order; R2 on facts-changed; R3 ungated escalation to large; V2 with the FINAL-state original-vs-last comparison rule; V3 on latest-v fail). FULL mirrors `eval_dag_arm`'s Z=FULL branch: base pass (Z=NONE), `recovery_plans`-style per-task plans, tasks grouped by identical plan (sorted), groups in sorted order, full-graph replay where trigger nodes run on D-matched alternative models and every other node re-executes on its PLANNED model — **no cache substitution, all replayed calls charged**. All triggers computed from already-occurred observable outputs only. |
| `stub_engine.py` (M4) | **Fault semantics rewritten to the campaign's corruption-AFTER-metering** (MeteredExecutor): the underlying call is a normal charged/cacheable call; corruption replaces the answer on a copy afterwards (`answer_replaced_after_call`, faults retain deployment cost). `(model, input_sha)` cache mirrors the production alias. `no_cache` per job. Task-static-context FROZEN assertion (mid-episode mutation is an engine error). Public orchestration entry points (`start_panel`/`run_jobs`/`planned_jobs`/`write_task_summaries`/`write_session_summary`). Server: `(uid,node,model)` fault registry (V3Executor/Metered keying — faults never fire on alternative models in replays) + explicit-None override now an ERROR. |
| `dag_closure.py` (M4 pre-checks) | `SIG_INPUTS`: the input signature now follows the PROMPT-dependency structure — v consumes e1+e2+r (grandparents included; the FULL-arm parity caught the gap). Non-executing DONE nodes also compare their CURRENT input identity — an R=[] plan can never reuse a ctx-drifted stale cache (invalidation propagates e1→r→v). |
| `scheduler_state.py` (M4) | Physical spend excludes cache aliases; recovery-kind counting (e_fb/r_fbd/r_esc/v_fbd/v_esc/replay). |

## Boundary tests (operator §四) — all pass

1. ctx frozen: mid-episode mutation raises (b1); judge: R=[] + drifted ctx
   ⇒ invalidated (e1, r, v), never reused (b1b).
2. Explicit `None` answer override raises — no silent fallback (b2).
3. Same-model FAILED retry (dedicated panel, planned e1=medium, memory
   rule returns medium for the second-detected task): a REAL charged call
   (`physical=True`, 100 tokens) that is re-corrupted — the fault
   persists, the node honestly stays FAILED, D1 observed twice; never a
   success cache-hit (b3).
4. No stale-input consumption: e1-fault cascade executes fb→r_fbd as new
   calls (changed input identity, not aliases) (b4); V2 correctly does NOT
   fire when the r answer text is identical (production final-state rule —
   parity-proven, not assumed).
5. RUNNING nodes never rewritten mid-flight: call_start/call strictly
   alternate; M3 judge already rejects R/π on them (b5).
6. Cold start + switch costs counted exactly once (session references by
   index, never re-summed) (b6).
7. Task E2E = release → actual termination, spanning recovery calls (b7).
8. Determinism (bitwise ledgers) + zero-call sentinel (server invoked only
   for physical calls) + socket-blocked suite (b8).

## Deviations found & fixed during M4 (recorded, in order)

1. **v input signature missed the grandparents** — v's prompt consumes the
   merged facts (e1+e2) AND the r expression; the graph-edge-only
   signature wrongly aliased a replay v call. Fixed via `SIG_INPUTS`;
   caught by FULL-arm T3b parity.
2. **Reference generation, attempt 1 (V3Executor)** — label colons shift
   V3Executor's positional key parsing, silently routing replay answers
   to a `'{}'` default: an ARTIFACT, not E-arm semantics. Replaced by the
   faithful campaign path: MeteredExecutor + Budget + stub dispatch (with
   template-marker routing — VPROMPT also contains the word "arithmetic",
   which initially mis-routed v prompts; fixed with distinctive markers).
3. **Fault semantics** — the engine initially used V3-style
   inject-shortcut (usage=1, cache bypass); the campaign's semantics are
   corruption-after-metering (real charge, cache-aware). Rewritten; this
   is what "faults retain the deployment cost" (AUDIT §2.6) means.
4. **no_cache scope** — blanket no-cache on all recovery jobs broke V2
   alias parity (a refresh of a healthy node may legally alias when its
   input identity is unchanged, e.g. after R3 already updated r before
   V1). Narrowed to FAILED-node retries only — exactly the operator's
   retry-charging rule — while refreshes keep production alias semantics.

## Honest caveats for review

- Production identity vs my signature: production prompts embed the task
  question and template text; my `input_signature` covers uid + node +
  static-ctx sha + consumed upstream answers — the STRUCTURE matches
  (what each prompt depends on), and within-episode ctx is frozen by
  assertion, but the two are not byte-identical formulas. Equivalence
  claims in M4 are therefore about BEHAVIOR (parity tests), not about
  claiming the identical hash function. Full-hash parity would require
  importing production prompt builders into the engine (an L5 exception
  not currently authorized).
- Injected usage is metered at the real call's usage (corruption-after-
  metering); production's stub-side conventions for cached-usage values
  differ from alias-reuse conventions — comparisons use physical counts
  and flags, not cached usage values.
- The same-model-retry corner is deliberately charged in my engine
  (operator rule) where production MeteredExecutor would alias-and-
  re-corrupt for free; in campaign-parity scenarios this corner never
  occurs (recipes change models), and both behaviors agree the recovery
  FAILS — only the accounting differs, and ours is the mandated one.

**Status: M4 complete; paused for operator review. M5 (dynamic model
reassignment — V10), M6 (two-stage reward policy), phase 3, and any
real-model work remain unauthorized.**
