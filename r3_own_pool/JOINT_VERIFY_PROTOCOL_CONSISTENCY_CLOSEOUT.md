# Protocol-consistency closeout (ruling on 4c941fc) — PASS/FAIL + final primary-endpoint definition

Zero calls, zero GPU; no P3 result inspection; weights/Q_min/faults untouched; no new audit rounds spawned.

## Item-by-item verdict

**Item 1 — decision/settlement time-objective correspondence: CONDITIONAL→RESOLVED (documented choice, option (b)).**
The decision layer remains switch-aware by design (mu_e2e = service + switch + contention; declared stub switch priors ~0.5–3 s); the SETTLEMENT objective is now explicitly the **service-latency** view (below), and the claim level is correspondingly downgraded: this is a **mechanism comparison under service latency**, NOT a real end-to-end wall-latency net-benefit claim. No real scheduling overhead was deleted to flatter rewards — the full wall and every switch remain recorded per task (`T_wall_reference`, `R_wall_deployment_view`, `switch_wall_s`, `switch_count`), reported, never hidden.

**Item 2 — cached base replay inside the recovery T: DEFECT FOUND & FIXED.**
`_per_task_service()` summed ALL call latencies INCLUDING cached shared-base replays (the pilot's SS rows carried ~4–5 s of replay time that is not recovery). Fixed: `_per_task_incremental_service()` sums **physical calls only** (the arm's own actions; cached replay excluded; FAILED retries are no_cache ⇒ physical by rule). Independently recomputable from the ledger's `physical` flags. T12 asserts T == Σ physical-call latencies per task (degraded tasks ⇒ 0).

**Item 3 — global physical cap vs per-arm decision budget: DEFECT FOUND & FIXED.**
`token_allocation` was `caps − budget.charged` — the GLOBAL charged-so-far, which grows with arm order ⇒ later arms (DD) saw strictly smaller decision budgets than earlier arms (SS): candidate feasibility depended on execution order. Fixed: every arm's SchedulerState receives the **same constant allocation** (= the confirmatory token cap); physical enforcement stays on the global Budget (shared cap unchanged). Deadlines: each arm episode sets D at its own release ⇒ identical d_remain = D across arms. Contention: run_cell's estimator structure is identical for every arm (same driver), so no arm-order term remains.

**Item 4 — objective declaration: RESOLVED per the ruling's dichotomy.**
Chosen: **(b) service-latency mechanism comparison.** The primary metric does NOT include real switch walls or queue, therefore the paper/experiment claims are capped at "mechanism comparison under service latency" and MUST NOT claim real end-to-end latency net benefit. The wall view (`R_wall_deployment_view`, T_wall, switch walls/counts) is reported as deployment-context reference — order-dependent (batching queue), explicitly not a per-arm causal metric.

## FINAL PRIMARY-ENDPOINT DEFINITION (frozen)

**R_conditional** = realized_rtask(q = terminal v2.1 correctness, C = the arm's own incremental physical tokens, **T = the arm's own incremental service time (Σ physical-call latencies in the arm episode; cached base replay, queue, and switch walls excluded)**, D = frozen tier multiplier × independent-FIT planned-path service mean).

- Secondary: R_full_task_cost_view (per-task base + incremental cost; same T).
- Deployment reference (not causal): R_wall_deployment_view (T = episode wall), T_wall_reference, switch_wall_s, switch_count — per task per arm, always reported.
- Analysis unchanged (ΔR_DD−SS primary; DD−DS/DD−SD secondary; interaction I with the n=60 caveat); claim ceiling: service-latency mechanism comparison, no E2E latency claim, no strategy superiority from the confirmatory run alone beyond its pre-registered contrasts.

## Verification

T12 extended and passing: incremental-T equality asserted; wall/deployment-view/switch fields present on every row; degraded tasks ⇒ T=0 physical (honest). Core suites green (joint-verification, supplementary smoke, M6, policy, admission-repairs). 13/13.

**Status: closed. Stopped — the confirmatory experiment still awaits explicit authorization (dual-hash GO).**
