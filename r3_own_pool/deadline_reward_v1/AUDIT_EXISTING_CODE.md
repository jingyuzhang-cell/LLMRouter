# AUDIT_EXISTING_CODE — deadline_reward_v1 (rev B)

Date: 2026-10-10. Method: read-only source review. Model calls: **0**.
Files written by this phase: only under `r3_own_pool/deadline_reward_v1/`.

**Rev B scope change (operator ruling, 2026-10-10):** the research target is
the EXECUTION layer — feedback-driven DAG dynamic recovery scheduling — not
the Formal configuration search. Part I (search-layer facts, rev A, commit
0d381a8) is retained as review evidence and context; **Part II is the new
execution-layer audit that rev B designs build on.** Every claim carries a
code citation; implementation status is marked [EXISTS] / [MISSING].

## Corrections to rev A (kept visible, per review policy)

1. **Config count**: rev A said "96 configs". `evaluator.space()`
   (evaluator.py:22-26) = product of four 2-slot model choices (2⁴=16 X)
   × 3 Z = **48**, not 96. Corrected everywhere in rev B. The execution
   layer anyway does not use the search space as its test range (it operates
   on one DAG at a time; see Part II).
2. **Normal lateness expectation (E1)**: rev A wrote
   Ê[(T−D)₊] = σ[φ(z) + z(1−Φ(z))] with z=(μ−D)/σ. The correct identity is
   **σ[φ(z) + zΦ(z)]** (equivalent to σ[φ(α) − α(1−Φ(α))] with α=(D−μ)/σ);
   the two agree only at z=0. Verified at D=μ (0.399σ), D=μ+σ (0.0833σ),
   D→−∞ (→μ−D). Fixed in DESIGN_PREDICTOR_INTERFACE §5.1 and
   DESIGN_REWARD_FUNCTION §3.1; VERIFICATION_PLAN P3 goldens regenerated
   from the corrected closed form.

---

# Part I — search layer (rev A, retained; superseded as design target)

§2.1–§2.8 (system snapshot: scheduling loop, Budget, deadline handling,
predictor landscape, faults, stub infra, authorization style) and §4–§6
(gap analysis, constraints, verdict) are unchanged at commit **0d381a8** —
the review baseline — except the config-count correction above (96→48).
§2.9 and §3 are reproduced verbatim below because rev B still builds on
them.

### §2.9 Wall-clock reconstructability verdict (rev A, verbatim — superseded
### for design purposes by Part II §II.6, kept as evidence)

| Quantity | Verdict | Evidence |
|---|---|---|
| Per-call service latency (physical + faulted) | **RECONSTRUCTABLE** | `TRAJECTORY.jsonl`/`WORKFLOW.jsonl`: every logical call has `response.start_unix`, `end_unix`, `latency_s` (930 records, inspected session official_qnehvi_same_state_20261009, read-only). Faulted calls keep real metered latency. |
| Per-task serial service demand (L semantics) | **RECONSTRUCTABLE** | `EVALUATIONS.jsonl → tasks[].L_serial_service_reconstructed_s`; recomputable from WORKFLOW. |
| Per-cell evaluation wall | **RECONSTRUCTABLE** | `EVALUATIONS.jsonl → search_spend.observed_wall_s`. |
| Per-session wall | **RECONSTRUCTABLE** | `STATUS.jsonl → observed_wall_s`; DISPATCH unix brackets. |
| Per-task E2E wall | **PARTIALLY_RECONSTRUCTABLE** | cache hits carry source timestamps (append untimestamped); MODEL_SWITCH has wall_s but no cell/task attribution. |
| Per-(node, model) latency samples for priors | **FIELDS PRESENT** | node embedded in every key; recovery events appear as ordinary calls. Usable for PRIORS only after the phase-4 provenance gate. |

Double gate (G1 per-cell deadline D̂ ⊂ G2 session wall cap + SIGALRM at
wall_seconds − 60, runtime.py:133-138) — carried over into rev B's
compensator design with per-task granularity.

### §3 Running Formal campaign — keep-out list (rev A, verbatim)

Driver + vLLM + GPU lock own: `joint_search_v1/formal_campaign_v2*` (incl.
retry roots) — CAMPAIGN/CAMPAIGN_LOG/PROTOCOL_SNAPSHOT/MODEL_BINDINGS/
TASK_PANEL/STATE_PANELS/DISPATCH/TRAJECTORY/EVALUATIONS/WORKFLOW/STATUS/
MODEL_SWITCH jsonl and per-session trees. Read-only schema inspection is the
only permitted contact (§2.9 evidence). Net-benefit runs/ledgers are under
the same rule. Phases 1–3 of this project write ONLY under
`deadline_reward_v1/`.

---

# Part II — execution layer audit (rev B, new)

## II.1 The real DAG executor and its stage structure [EXISTS]

`collab_scheduler_v1/fault30_run.py::eval_config` (fault30_run.py:215-474)
is the production execution path for the 4-node DYNAMICDAG
(e1, e2, r, v). Stage order (fault30_run.py:218, 234-422):

```
A  planned extraction    e1(ctx_table), e2(ctx_text)          L234-258
R1 planned reasoning     r(facts)                             L265-277
[LOCAL_REROUTE only:]
ER  e-recovery (fb)      trigger: empty facts                 L292-317
R2  r-refresh (fbd)      trigger: e facts actually changed    L318-335
R3  r-escalation (esc)   trigger: r unparseable               L336-353
V1  planned verification v(facts, expr)                       L368-382
V2  v-refresh (fbd)      trigger: r output changed (final)    L385-401
V3  v-escalation (esc)   trigger: v None or v-vs-r mismatch   L402-422
scoring                  ok / physical accounting / L         L424-473
```

Which recovery stages run is fixed STATICALLY by the config's Z
(fault30_run.py:220: `is_lr = z == 'LOCAL_REROUTE'`). There is **no runtime
branch point where a policy could choose an action** — [MISSING: online
decision hook].

## II.2 Detection predicates (the feedback that genuinely exists) [EXISTS]

| # | Signal | Predicate | Code | Used today as trigger for |
|---|---|---|---|---|
| D1 | e-node failure | `parse_facts_safe(answer)` → empty `facts` list | fault30_run.py:246,255; 293-295 | ER fb |
| D2 | e-repair changed facts | new facts ≠ old facts | fault30_run.py:313-315 | R2 fbd (descendant closure) |
| D3 | r failure | `value_of(r_answer, facts)` error / UNPARSEABLE expr | fault30_run.py:282-289, 337 | R3 esc |
| D4 | r output changed (final-state rule: last vs ORIGINAL r answer; process flag kept separately) | answer diff | fault30_run.py:354-366 | V2 fbd |
| D5 | v failure | `json_value(v)` None, or not `close(vv, rv)` vs r value | fault30_run.py:403-409 | V3 esc |
| D6 | task-level terminal failure | same three families over final outputs | evaluator.py:74-84 `detected_failure` | FULL replay gate (search layer) |

All predicates are observable-output-only (no gold, no fault registry). This
is the complete, real feedback interface — anything finer (per-node
confidence, token-level signals, latency anomalies) **does not exist**
[MISSING; not assumed by rev B designs].

## II.3 LOCAL recovery events — exact semantics [EXISTS, static]

| Event | Trigger (from II.2) | Re-execution scope | Model rule | Cap |
|---|---|---|---|---|
| `e_fb` | D1 on e1/e2 | only the empty e-node | **memory rule by panel detection order**: first detected task → coder, rest → medium (fault30_run.py:296) | one pass per node |
| `r_fbd` | D2 | r node only | **planned r model unchanged** (fault30_run.py:327) | once |
| `r_esc` | D3 | r node only | **hardcoded large** (fault30_run.py:345) | once |
| `v_fbd` | D4 | v node only | planned v model unchanged (fault30_run.py:395) | once |
| `v_esc` | D5 | v node only | **hardcoded large** (fault30_run.py:416) | once |

Note the scope×model coupling baked into these rules (see II.6).

## II.4 FULL replay — two DIFFERENT semantics coexist [EXISTS, ambiguous]

1. **Search-layer FULL** (evaluator.py:118-129): on D6, exactly one replay
   with X′ = {n: coder if m==large else large} — **every node's model
   swapped**; all logical calls re-charged.
2. **Net-benefit E-arm FULL** (NET_BENEFIT_FREEZE.json `arms.E_dynamic_full`):
   SAME detection predicate and SAME per-task alternative models as D
   (e: memory rule coder/medium; r→large; v→large); **every other node
   re-executes on its PLANNED model**; "D and E differ ONLY in re-execution
   scope (local subtree vs full graph)".

Rev B treats "FULL" as one decision with two candidate execution semantics —
pinned as OPEN-B1 (default: E-arm semantics, because it is the one that
supports scope-only attribution).

## II.5 Confound: recovery actions change scope AND models simultaneously

Every existing recovery rule substitutes models at the same time as it
changes re-execution scope (II.3: fb→coder/medium, esc→large; II.4.1:
full-swap). A reward-driven policy choosing between them therefore confounds
"how much to re-run" with "who re-runs it". Existing decomposition precedent
(NET_BENEFIT_FREEZE.json, arms B/C/D/E):

- B (all-large, NONE) vs C (hetero X, NONE): static model-assignment effect.
- C vs D (same X + LOCAL): adds local recovery.
- D vs E (same X, same detection, same alternative models; scope-only
  differs): recovery-SCOPE effect, model effect held fixed.

The dynamic scheduler's evaluation must inherit exactly this ladder
(DESIGN_DYNAMIC_SCHEDULER §7); single-factor switches are already proven
implementable in this codebase.

## II.6 Time semantics at the execution layer — three distinct quantities

1. **Per-call service latency** `latency_s` [EXISTS]: recorded per call
   (real: engine-measured + start/end_unix in campaign artifacts; stub:
   scripted value).
2. **Critical-path reconstructed L** [EXISTS]: fault30_run.py:451-463 —
   L = max(e-chain incl. serial fb) + Σ r-keys + Σ v-keys. A RECONSTRUCTION
   of serial service demand on the critical path. It is **not** wall time:
   no cache-lookup overhead, no model switch time, no scheduling gaps
   (physical_accounting docstring: "Cache lookup overhead belongs to wall
   time, not model service time", fault30_run.py:187-189).
3. **Real per-task E2E wall** [MISSING in executors]: no executor tracks
   task-level wall (start→finish). Only session/cell walls exist
   (`observed_wall_s`, Part I §2.9). The stub engine of phase 2 MUST add
   per-task wall on the injected clock; nothing in production records it
   today.

Design consequence (feeds all rev B docs): reward deadlines and predictor
time estimates must be explicit about which of the three they mean; serial
service demand may never be silently used as E2E.

## II.7 Model switch overhead at execution layer [PARTIALLY EXISTS]

- `Executor.call` switches models inline (stop + start) when the next call's
  model differs (fault30_run.py:131-135) — cost lands in wall time, NOT in
  any recorded field of the call.
- `run_stage` batches jobs by model to reduce switches (fault30_run.py:159-164)
  — a REAL scheduling lever already in production.
- MODEL_SWITCH.jsonl wall_s exists only in the campaign/session runtime
  (Part I §2.4), not inside eval_config.
- [MISSING] per-switch records inside a task's execution; attribution of
  switch time to tasks. Phase-2 stub engine must make switch events
  first-class records.

## II.8 Budget semantics at execution layer [EXISTS at session level only]

Budget caps (requests/tokens/wall, Part I §2.3) bind the SESSION, enforced
passively via `check()` before each dispatch. Per-TASK budget/deadline
allocation does not exist [MISSING]. The rev B DeadlineCompensator therefore
allocates per-task deadlines D from the session envelope — a new, additive
layer, not a modification of Budget.

## II.9 Planning helpers reusable without execution [EXISTS]

`fault30_protocol.py::plan_none` (L199) and `plan_reroute` (L253) enumerate
planned calls WITHOUT executing — the same pattern predictor_v3 uses for
cost bounds. Reusable as the action-enumeration core (task 4 of the
instruction): enumerate(action, state) → call-event list → cost/time bounds.
Also `predictor_v3.enumerate_call_events` (predictor_v3.py:41-81) hard-codes
the same table for the 4-node DAG.

## II.10 Reuse list vs missing-interface list (deliverable)

**Reuse as-is (import or re-derive, zero modification to owners):**
| Capability | Source |
|---|---|
| Prompt builders (e/r/v prompts, parse_facts_safe) | fault30_protocol.Ledger L147-166 |
| Detection predicates D1–D6 | fault30_run.py / evaluator.py:74-84 |
| Stage/recovery semantics reference | fault30_run.eval_config L215-474 |
| Event-planning without execution | plan_none/plan_reroute; predictor_v3.enumerate_call_events |
| Physical accounting (8-layer) | fault30_run.physical_accounting L184-212 |
| Metered fault injection (corruption after metered call) | evaluator.MeteredExecutor L29-60 |
| Budget with injectable clock | smoke_runner.Budget L32-81 (`clock=` param) |
| Stub executor pattern (answers-map + faults + cache) | predictor_v3.V3Executor L124-193 |
| **Dependency-closure constant table** | static_dag_v0/multidag_dynamic.py:59 `CLOSURE={'e1':['r','v'],'e2':['r','v'],'r':['v'],'v':[]}` |
| **Selective-update precedent + audit** ("re-executed set == descendant closure on every event") | multidag_dynamic.py:15-32 (pre-registered) |
| **Budget-gated skip+record precedent** (escalation skipped and RECORDED when B_rem<200) | multidag_dynamic.py:124, 319, 365 |
| **Frozen adaptation-rule arms (static fallback vs dynamic memory/escalation)** | multidag_dynamic.py:123-124 |
| Scope/model decomposition ladder | NET_BENEFIT_FREEZE.json arms B/C/D/E |
| Crash-honest append-only ledger conventions | CampaignQuota, Budget, DISPATCH.jsonl |

**Missing (must be built in deadline_reward_v1/ phases 2–3; none exists
anywhere in production):**
1. Online decision hook between detection and recovery (policy injection
   point) — eval_config has none.
2. Execution-layer SchedulerState (node status/dependency/model/recovery
   counts per task).
3. Recovery-action interface with legality enumeration (NONE/LOCAL/FULL as
   runtime choices).
4. OutcomePredictor over (decision point, action) outcomes.
5. DeadlineCompensator: per-task D allocation, switch-overhead accounting,
   unified with predictor to avoid double-charging.
6. Per-task real wall tracking (stub first; production later).
7. Per-switch records inside task execution (stub first).
8. Task-level terminal reward R0 wiring (scoring exists; reward does not).

## II.12 Runtime-interface checklist (rev C, per operator instruction §五)

Question: does the codebase already possess the six runtime interfaces the
joint dynamic scheduler needs? Verdict per interface (grep + source review,
2026-10-10):

| # | Interface | Status | Evidence |
|---|---|---|---|
| 1 | Runtime pause / decision suspension | **MISSING** | no pause/resume/preempt anywhere (grep over static_dag_v0, fault30, collab); execution is straight-line staged scripts. Not needed as OS primitive: a per-call event-driven engine suspends naturally between calls — the phase-2 stub engine's native mode. |
| 2 | Node-state observation | **PARTIAL** | in-memory `st[uid]` inside eval_config (fault30_run.py:222-229) — never exposed as an interface; simulator emits per-node event records (multidag_dynamic). SchedulerState (phase 2) is the proper interface. |
| 3 | Post-fault dependency-closure computation | **EXISTS (constant table)** | `CLOSURE` (multidag_dynamic.py:59) + pre-registered selective-update audit. Fixed 4-node DAG ⇒ constants are the honest implementation, not a limitation. |
| 4 | Remaining-node model reassignment (π_t) | **MISSING as a decision** | substitution RULES exist (fb memory rule; esc→large; static fallback table multidag_dynamic.py:123) but are frozen per event; no joint assignment of unexecuted nodes is optimized anywhere. This is precisely the new capability. |
| 5 | Recovery execution | **EXISTS** | LOCAL recipe (fault30_run.py:292-422), FULL replay (evaluator.py:118-129, E-arm variant in NET_BENEFIT_FREEZE), simulator fb/esc with closures (multidag_dynamic.py:291-365). |
| 6 | Real wall-clock timing (per task / per decision) | **MISSING** | per-call latency + unix exist in campaign artifacts (Part I §2.9); per-task E2E absent everywhere; simulator uses service latencies. Phase-2 stub engine obligation (II §6.3). |

Additional precedent found (rev C): budget-gated escalation with skip+record
(multidag_dynamic.py:319,365 — escalation skipped and RECORDED when
B_rem<200) is a direct ancestor of the rev C no-feasible-action degradation
rule. Caveat carried: that experiment's failure detection was IDEAL
("evaluation answer", multidag_dynamic.py:24) — deployable detection is
exactly predicates D1–D6 (II §2), which rev C uses instead.

**Conclusion (operator instruction §五):** interfaces 1, 4, 6 are missing
and 2 is partial ⇒ **phase 2 must build the minimal execution closed loop
first** (M1–M6 build order in README), not reuse Formal search selectors.
The joint scheduler (Z_t, R_t, π_t) exists NOWHERE in the codebase —
frozen-rule simulators (multidag_dynamic) and static-Z recovery
(fault30/evaluator) are its correct ancestors, not its implementations.

## II.11 What rev B/C must NOT claim (honesty ledger)

- No online recovery interface exists to "plug into" — phase 2 builds a
  stub execution engine INSIDE deadline_reward_v1/ that mirrors eval_config's
  stage semantics (the V3Executor precedent), driven by the new policy. Any
  future production integration is a separately admitted change.
- Detection capability is exactly D1–D6; nothing finer.
- The Formal campaign (search layer) keeps its independent research value;
  nothing in rev B redefines or reuses its ledgers as training signal
  (provenance gate unchanged, Part I §3).
