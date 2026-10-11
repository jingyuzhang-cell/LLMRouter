# M3_REPORT — DAG dependency closure & cache reuse, phase-2 milestone M3

Authorization: operator M2 review (2026-10-11) — "M3 GO,仅授权 DAG 闭包与
复用"。Scope held to M3; M4–M6 NOT started; zero real model calls.
Suites: M1 21/21 · M2 24/24 · M3 23/23 (all now idempotent re-runs; no old
assertion was relaxed).

## Delivered

| File | Content |
|---|---|
| `dag_closure.py` | Explicit DAG (PARENTS/CLOSURE/TOPO — **parity-tested against production `multidag_dynamic.CLOSURE`**), transitive `descendants()`, and the core **`evaluate_plan(R, π)`** adjudicator: returns `PlanJudgment(legal, execute[(node, new_call)], reuse, invalidated, reasons)`. Semantics follow the FROZEN production cache identity (model, prompt-sha, task, node, scope): reuse ⇔ model unchanged AND every parent's output identity unchanged; **answer-text equality is never a reuse criterion**; identity-unchanged re-executions are flagged `cache_hit` (new_call=False); incomplete closures are REJECTED (`on_incomplete='reject'`, default) or completed BY RULE with an explicit reason (never silently). RUNNING nodes are immutable (no R, no π); DONE/FAILED nodes are immutable unless in R. |
| `scheduler_state.py` (M3 additions) | Per-node **exec_identity** = (model, input_signature) frozen at call time (input signature mirrors the audited prompt-dependency structure: e←static ctx, r←e1+e2 outputs, v←r output); `judge(uid, R, π, on_incomplete)` — the M5-facing entry point. |
| Hardening 1 (ruling) | `StubModelServer` override lookup is now KEY-EXISTENCE based — an explicit override, **including the empty string `''`**, is never replaced by the default answer. Tests: `''`→D1, `not json`→D3, `{"value": null}`→D5, end-to-end through engine+state. |
| Hardening 2 (ruling) | `make_legal_view` deep validation: recursive forbidden-key blacklist at ANY nesting depth (gold/answers/faults/future_outputs/…) + shape-exact structural validation for `observations` (keys exactly {code,node,t}, code ∈ registered D-codes), `session` (key set), `node_status`/`node_model` (node sets, status enums). Injection probes in `observations`/`session`/`budget` all rejected; well-formed views still accepted. |

## Judgment samples (closure/reuse 判定样例)

Clean 4-node completed state (e1,e2:large · r:medium · v:coder, all DONE):

| Candidate (R, π) | Judgment |
|---|---|
| `R={e1}, π={e1:coder}` | **reject** — invalidated (r, v): `incomplete_closure_missing:r,v` |
| same, `on_incomplete=complete` | **legal** — execute [(e1,new),(r,new),(v,new)], reuse (e2), reasons `model_change:e1; closure_completed:r,v` |
| `R={e1}, π={}` | **legal** — execute [(e1, **cache-hit**)], reuse (e2, r, v) — frozen identity unchanged |
| `R={r}, π={r:large}` | **reject** — invalidated (v) |
| `R=[], π={v:large}` (v PENDING) | **legal** — execute [(v,new)], reuse (e1, e2, r) |
| `R=[], π={e1:coder}` (e1 DONE) | **reject** — `done_node_model_change_without_reexec:e1` |
| r RUNNING, `R={r}` / `π={r:large}` | **reject** — `running_in_R:r` / `running_node_immutable:r` |
| `R={e1}, π={e1:medium}` (answer text would be identical) | **reject** — invalidated (r, v), `model_change:e1`: text-sameness does not restore identity |

## The eight operator acceptance scenarios → tests

S1 e1-change invalidation (reject + complete) · S2 identity-unchanged reuse
(cache hit) · S3 r-change → v invalidation (+ transitive e1→r→v) · S4
v-only reassignment reuses e1/e2/r · S5 DONE-model-change rejection · S6
RUNNING immutability (both R and π) · S7 text≠identity · S8 determinism
(judgment equality on repeated calls). Plus: production CLOSURE parity,
topo validity, descendants transitivity, unknown node/model rejection,
hardening groups, zero-call sentinel + socket-blocked suites.

## Recorded deviation found & fixed during M3

Initial propagation set `changed=False` for non-re-executed DONE nodes,
which stopped invalidation from propagating past one hop (e1 change would
invalidate r but not v). Fixed: for reused nodes, `changed` means CACHE
STALENESS (any parent changed) — the corrected semantics is what S1/S3
transitivity now pin.

## Not in M3 (awaiting authorization)

M4 recovery execution (LOCAL/FULL arms → full T3a/T3b references) · M5
model reassignment on top of `judge()` (V10 decisive test) · M6 two-stage
policy + reward settlement. No production/Formal/net-benefit file touched;
production imports only inside test files (parity/reference generation).

**Status: M3 complete; paused for operator review.**
