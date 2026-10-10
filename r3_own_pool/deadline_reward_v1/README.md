# deadline_reward_v1 — deadline reward/penalty mechanism for the joint-search scheduler

Started 2026-10-10, developed in parallel with the Formal campaign (v2B,
now reporting 18/18 COMPLETE, pending its own settlement audit — separate
workstream, untouched by this one).

Hard boundary for phases 1–3: ZERO real model calls; NEVER import/modify/
write anything under `collab_scheduler_v1/joint_search_v1/formal_campaign_v2*`
or any other live campaign artifact. **Phase 2 is NOT started — blocked on
the operator's phase-1 admission decision (this directory is review-only).**

## Location decision (review finding #3 — the path change is deliberate)

Original plan: `collab_scheduler_v1/deadline_reward_v1/` with three docs.
Actual: top-level `r3_own_pool/deadline_reward_v1/` with six files. Reasons:

1. **Isolation from an audited, SHA-bound package.** The Formal launch
   admission binds specific files inside `collab_scheduler_v1/` by SHA
   (formal_launch.py `frozen_inputs()` + `bindings`). Developing new files
   inside that tree risks tripping those bindings and any future audit that
   walks the package. A top-level sibling (like `sa_pgfs_v1`, `static_dag_v0`)
   makes accidental interference structurally impossible.
2. **Phase-4 needs its own admission chain** (protocol/admission/bindings,
   AUDIT §2.8 style); every prior workstream that reached real execution has
   been a top-level package.
3. **No interface misalignment:** the three phase-2 module names are exactly
   as planned (`scheduler_state.py`, `outcome_predictor.py`,
   `deadline_compensator.py`); they import production code ONLY through the
   stable seams identified in the audit (SearchSession callback, Budget
   clock=, QSurrogate) and are exercised via stub replay — verified
   structurally by VERIFICATION_PLAN L5 (import-graph assertion), which also
   guards against duplicate re-implementations by pinning the allowed
   dependency set.

File count: the three planned design docs are unchanged in role; AUDIT and
README are additive context; VERIFICATION_PLAN.md was added in revision A as
the direct response to review finding #4 (executable test design).

## Files (revision A, 2026-10-10)

- `AUDIT_EXISTING_CODE.md` — audit incl. **§2.9 wall-clock reconstructability
  verdict with artifact evidence** and the double-gate (G1/G2) conclusion.
- `DESIGN_REWARD_FUNCTION.md` — **R0 primary** (finalized task-level formula,
  conditional expectation as the online score, §3), R1 demoted to
  candidate/ablation (§4), ablation arms (§5).
- `DESIGN_DYNAMIC_SCHEDULER.md` — scheduler_state + deadline_compensator;
  default score = Ê[R0|H,c]; failure-mode matrix F1–F7.
- `DESIGN_PREDICTOR_INTERFACE.md` — OutcomePredictor contract, E1 on-time
  estimator (§5.1), priors provenance rule, parity tests.
- `VERIFICATION_PLAN.md` — executable tests L1–L6 / R-F1–7 / B1–B5 / Z1–Z2 /
  P1–P3 / C1–C3, with the coverage map to the four review findings.
- `README.md` — this file.

## Phase gates

| Phase | Scope | Model calls | Status |
|---|---|---|---|
| 1 | Audit + design docs + verification plan | 0 | **rev A submitted for review; NOT accepted yet** |
| 2 | `scheduler_state.py`, `outcome_predictor.py`, `deadline_compensator.py` + tests | 0 | blocked on phase-1 admission |
| 3 | Verification: logic, budget, leakage, recovery | 0 | blocked on phase 2 |
| 4 | Real-model experiments | >0 | blocked on: Formal settlement audit + net-benefit gates + independent authorization |

## Reviewer checklist (rev A)

1. Reward: R0 formula instantiation table (§3), E1 estimator (§3.1), unit
   choice OPEN-D5; R1 consistency answers (§4).
2. Wall-clock: AUDIT §2.9 verdict table + double-gate resolution; B5 test.
3. Location: the section above; L5 import-graph test.
4. Leakage: VERIFICATION_PLAN L1–L6; extensible LEAK_PROBES.json.
5. OPEN decisions: D1–D7, S1–S5, P1–P5 (17 after rev A additions; v0.1's
   14 kept their numbering, D2 resolved by your ruling).
