# JOINT_SCHED_VERIFICATION_ADMISSION — zero-call admission check + protocol draft for the joint-scheduling effectiveness experiment

Operator ruling 2026-10-12 (post `022bd0f`): the joint reward mechanism's
real effectiveness is the core UNVERIFIED claim; verification is a
future, separately authorized experiment; the reliability line stays
closed; no execution is started by this document. This delivers step 1
of the operator's sequence (zero-call admission check) and the draft
authorization packet for steps 2–3.

## A. Admission check results (all zero-call, at HEAD `022bd0f`)

| # | item | verdict | evidence |
|---|---|---|---|
| 1 | M5 enumeration defect fixed | **PASS** | `test_m5_closure_fix` 25/25 (six mandated e-failure scenarios + regressions); SS now recovers e-failures with the fixed LOCAL recipe — the E6 confound is gone IN CODE |
| 2 | Arm semantics match the intended ablation | **PASS** | `arm_entry.py` current code: SS = fixed LOCAL + planned π (static pick, STATIC_RECOVERY_UNAVAILABLE on genuine no-match); DS = policy over π==planned (scope dynamic, assignment fixed); SD = policy over LOCAL-only (scope fixed, π dynamic); DD = policy over all candidates; NONE = no recovery. Exactly the 2×2 + floor. A single-model baseline arm does NOT exist in the runner — gap G2 |
| 3 | Reward settlement uses TERMINAL correctness | **GAP G1** | `reward.settle` computes q via v1-close (`det.close(json_value(v), answer)`) — NOT the frozen v2.1 scorer; and the E6-line runner never settles per-task R at all (rows carry Q_v21/C/T components only). Fix required pre-pilot: settle must take terminal q from `score_v21` (+ contract gold), and the runner must persist per-task realized R. Zero-call implementable and testable |
| 4 | Switch & queue time really counted | **PASS (with design note)** | per-task switch_sum from attributed switch events; T = completion − release includes queue (E6 medians: 143 s E2E, 125 s queue). NOTE: in cell-batched execution T is dominated by cross-task queue — the protocol pre-freezes D-tiers from the MEASURED task-E2E distribution (incl. queue) so the deadline dimension is live without restructuring episodes (per the earlier operator ruling) |
| 5 | No gold / fault-registry in decisions | **PASS** | decisions consume only M2 legal views + declared priors (L2/L3 firewall suites green); gold enters only terminal scoring/settlement; fault registry only at the executor |
| 6 | Predictor accuracy precondition | **N/A by ruling** | mechanism effectiveness ≠ predictor precision; no P90 certification required first (both are separate experimental conclusions) |

**Pre-pilot fix list (zero-call, requires approval as part of the
admission package): G1** (v2.1 terminal-q settlement + per-task R
persistence), **G2** (single-model mono baseline arm inside the same
engine/budget: full-context single call + same-model retry policy),
**G3** (pre-freeze D-tiers, see §B.3 — derivable zero-call from E6's
measured E2E distribution).

## B. Draft protocol: joint-scheduling effectiveness verification (NOT authorized; awaits explicit GO)

### B.1 Arms (7)

SS / DS / SD / DD / NONE (frozen `arm_entry`, semantics verified above)
+ **MONO**: single-model full-context execution with same-model retry
(E1-style mono prompt; the single-model baseline the operator
mandated). Same tasks, same fault draws, same budget, same pre-frozen
deadlines per task.

### B.2 Panel (operator decision required — options with trade-offs)

| option | n ceiling | freshness | trade-off |
|---|---|---|---|
| P1: frozen200 spare only | 24 | pristine | confirmatory only for large effects (Δ≥0.17) |
| P2: reliability validate-90 reuse | 90 | seen by coverage diagnostics only (no arm/policy tuning ever touched them; partial DD episodes exist in the aborted run) | n=80+ achievable; disclose prior exposure; predictor FIT used a disjoint 24-task panel, so priors are not tuned on these tasks |
| P3: new benchmark draw (e.g., TAT-QA remainder outside frozen200 lineage) | large | pristine | new panel freeze + provenance work; different distribution from all existing evidence |

Recommendation: **P2 with disclosure** for the confirmatory run (the
priors were fit on the disjoint FIT panel; the validate tasks' exposure
was measurement-only), P1 reserved as a fully-pristine sanity subset.

### B.3 Conditions & deadlines (pre-frozen, zero-call derivable)

- Fault condition: D3_r on the planned r model at 30% of tasks
  (frozen seed; same draws across ALL arms — pairing requirement).
- Clean reference subset (optional, n=20) for context only.
- **D-tiers pre-frozen from E6's measured task-E2E distribution
  (including queue)**: tight = P40, medium = P60, wide = P80 of the
  observed E2E CDF; assigned per task by frozen seed. The deadline
  dimension is thereby live and identical across arms.

### B.4 Metrics (realized, per task per arm)

Q (terminal v2.1 correctness), C (physical tokens; logical calls
reported alongside), T (real E2E incl. own switches + queue),
on-time-correct (Q ∧ T≤D), **realized R_task** (frozen λ, c0; terminal
v2.1 q — G1), plus per-decision ex-ante rows (P0-B) for the
prediction-error breakdown the operator specified (why DD loses when
it loses: quality over-optimism / switch time / wrong recovery /
cost).

### B.5 Primary contrasts & power (indicative variance from E6, confounded but variance-estimable)

- **ΔR = R_DD − R_SS** (primary): paired sd ≈ 0.283 (fault condition)
  → one-sided α=.05, 80% power: **n = 49 @ Δ=0.10; 77 @ Δ=0.08; 197 @
  Δ=0.05**.
- **Interaction I = R_DD − R_DS − R_SD + R_SS**: sd ≈ 0.340 → **n =
  71 @ 0.10; 112 @ 0.08; 286 @ 0.05**.
- Secondary: DD vs DS, DD vs SD, each vs MONO and NONE; paired
  exact/sign tests + task-cluster bootstrap CIs; non-significant =
  "failed to demonstrate", never equivalence.
- E6's observed point estimates (ΔR_DD−SS = −0.05 fault / +0.16 clean)
  are CONFOUNDED and carry no design weight — only their variance does.

### B.6 Budget estimate (from E6 actuals: 124 req / 40.3K tok / 2735 s for 20 tasks × 5 arms × 2 conditions)

n=80 fault-only × 7 arms ≈ 80 × (4 shared-base + ~1.5 arm-distinct) +
80 MONO + 20 clean×4 ≈ **~700 physical requests / ~280K tokens /
~7,000–9,000 s** (stage-batched cells, switch-dominated wall).
Proposed caps: **900 requests / 400K tokens / 14,400 s** (PROPOSAL —
requires approval; not auto-raised).

### B.7 Staged admission & fail-stop (binding)

1. **Admission package**: G1–G3 landed, all suites green, freeze files
   (panel/fault/D-tier/params) hashed, preflight + rehearsal PASS.
2. **Micro-pilot (authorized separately)**: 3 tasks × 7 arms, sole
   purpose = complete execution + correct recording (Q/C/T/R, decision
   rows); results NEVER quoted as effectiveness. Any failure → STOP,
   report, no in-round repair relaunch.
3. **Confirmatory run**: single authorization, the caps above,
   INCOMPLETE-on-any-cap semantics, paired analysis per B.5.

## C. Status

Zero calls, zero GPU. Nothing launched. This document + the G1–G3 fix
list constitute the step-1 deliverable; steps 2–3 wait for explicit,
separately-worded authorizations.

---

## v2 REVISIONS (operator ruling 2026-10-12 on 83ea096; zero-call round complete)

1. **SIX arms, not seven** (operator correction): SS, DS, SD, DD, NONE,
   MONO. All workload/sample/budget arithmetic below is superseded by
   the six-arm figures in §B.6-rev.
2. **MONO fault semantics ruled**: MONO has no r node — the D3_r
   injection is NOT an equivalent fault for MONO. MONO = descriptive
   baseline OUTSIDE the same-fault causal contrasts (ΔR, I computed
   over the five DAG arms under identical draws). An optional
   mono-side corruption condition exists for sensitivity only,
   labeled non-equivalent.
3. **Panel**: P3 fresh-frozen tasks = the CONFIRMATORY panel
   (per the exposure audit: reliability-validate-90 tasks entered
   reliability executions and DD exploratory episodes and had
   prediction errors viewed — usable only as exploratory/sensitivity,
   and only with a per-use independence argument, never by FIT-disjoint
   alone). P2 demoted accordingly.
4. **G3 outcome (analysis only, nothing frozen)**: E6 absolute E2E
   quantiles (P40/60/80 = 142/204/217 s) are batch-saturated — position
   sensitivity ≈ 0 (first vs last in cell both ~148 s median) — they
   would measure batch position, not scheduling. A workable rule anchors
   D on per-task QUEUE-FREE work (service+own-switch: median 46.8 s,
   P90 377 s) with pre-registered multipliers; freeze deferred to pilot
   authorization with a discrimination check (evidence
   G3_FEASIBILITY.json).
5. **Power redesign on divergent-task fraction**: E6 fault30 has
   dR(DD−SS)≠0 on only 45% of tasks and I≠0 on 45% — the effective
   paired denominator is n×0.45. Combined with the earlier paired sd
   (0.283 / 0.340), nominal panel sizes for 80% power at one-sided
   α=.05 become approximately: **Δ=0.10 → ~109 tasks; Δ=0.08 → ~171;
   Δ=0.15 → ~49** for the primary; the interaction needs
   **~158 / ~249 / ~71** respectively. (E6-derived variance is
   M5-confounded — treat as resource-planning bounds, re-estimated at
   pilot.)
6. **Six-arm budget re-estimate** (per-task physical, from E6 actuals
   + MONO): base 4 (shared via identity cache across arms) + arm
   extras (SS ~1.7, DS ~0.6, SD ~1.2, DD ~1.5, NONE ~1.0, MONO ~1.3
   incl. fallback) ≈ **11.3/task**; n=60 → ~680 requests, ~270K
   tokens; wall: 6 cells stage-batched ≈ 6×(10–14 switches ×65 s +
   calls) ≈ **6,000–8,000 s**. Cumulative-context: this experiment
   line's real spend to date = 0 (global historical lines: calibration
   1,200; supplementary 124+80 quarantined; reliability 1,257 closed).
   PROPOSED caps: **800 requests / 350K tokens / 10,800 s** (approval
   required).
7. **Zero-call build landed this round**: joint_verification_runner.py
   (G1 v2.1 settlement + G2 MONO, six arms) with 6/6 tests
   (JOINT_VERIFY_ZERO_CALL.json) and G3 evidence; see
   JOINT_SCHED_ZERO_CALL_READINESS.md for blockers B1–B4 and the
   approvable micro-pilot conditions. Real execution remains
   UNAUTHORIZED.
