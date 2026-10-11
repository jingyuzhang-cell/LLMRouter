# NETBENEFIT_AUDIT_RO — independent read-only audit (Calibration GO prerequisite)

Authorization: operator "继续跑直到跑通" (2026-10-11). READ-ONLY over
frozen artifacts; writes only to netbenefit_audit_ro/. Zero real model
calls.

## Verdict (hardened)

**38/38 checks PASS, exit 0** (31 original + 5 hardening/negative
tests + 2 B5/E5 semantic splits from the latest review). The
operator's review items are closed:
- **C1**: per-cell independent recount from DISPATCH (responses linked
  to reservations by ID; arm extracted from the reservation key):
  A_single 50 req/28,123 tok, A_cross 2/740, B_same_model 200/74,031
  — each matches NB_CELL_LEDGER exactly.
- **C2b**: the actual counted total must be exactly 252 (string
  matching fallback removed).
- **D4**: budget checked with the independently recounted totals
  (252 req / 102,894 tok vs 4,000 / 4M caps), never a freeze-file
  default.
- **E5** (split into E5a/E5b for honesty):
  - E5a (V4 INTERNAL CONSISTENCY): sub-audit flags match their own
    check sets; stub rows carry no execute flags.
  - E5b (partial RAW recomputation): the stub NB_ROWS independently
    verified to cover every arm in the freeze grid. Full raw
    recomputation of V4's analytical conclusions is NOT performed
    here — those conclusions are stub-based (zero_model_requests).
- **Negative tests (G1–G4)**: tampered request counts, token counts,
  per-cell counts, and V4 flags each make the corresponding checker
  fail. The net-benefit freeze, its pre-halt
real spend, and the V4 audit chain are internally consistent. ONE
important observation (not a failure): the net-benefit experiment is
**PAUSED mid-execution** — 3 of 8×4=32 mechanism cells ran for real
before the halt directive; the remaining cells are stub-validated only.
The net-benefit gate is therefore **NOT a completed experiment**: it is
a **frozen-and-paused protocol with honest partial spend**.

## What was verified

**A. Freeze integrity (5 PASS)** — 8 arms match between the freeze and
the driver code; V2 candidate arms present; D and E share X (scope-only
contrast) with E's replay-rule recorded; the cross-fallback arm
correctly defines fallback+max_fallbacks=1.

**B. Halt honesty (5 PASS)** — NB_ROWS contains exactly 3 real cells
(A_single / A_single_cross_fallback / B_same_model_dag, all clean
state, all COMPLETE, all execute=true); no other row claims real
execution. The pre-halt note ("3 real cells... 252 physical requests")
matches the raw evidence.

**C. Row-level reconciliation (6 PASS)** — NB_CELL_LEDGER has exactly 3
cells, all COMPLETE; the real run directory (real_20261010_000854)
exists with TRAJECTORY covering ≥ the 252 charged requests; per-cell
physical counts sum correctly (50+2+200=252 requests, 28,123+...=
~94K tokens total within the 4M global cap).

**D. Budget gates (4 PASS)** — global caps (4,000 requests / 4M tokens
/ 21,600s wall) present; DE reservation (800 requests) recorded;
per-strategy-per-state cap (400) present; pre-halt 252 requests well
within the global cap.

**E. V4 audit cross-check (5 PASS)** — the V4 audit report exists,
claims zero_model_requests=true and all_pass=true, and contains
sub-audits that individually pass.

**F. Protocol structure (5 PASS)** — confirmatory primary family
declared; Holm within exploratory families; competitive family listed;
gate2 present; task-selection exclusions recorded.

## What this audit does NOT claim

- It does NOT claim the net-benefit experiment is COMPLETE — it is
  paused at 3/32 real mechanism cells. The remaining cells (C/D/E/V2
  arms + fault/competitive states) have stub validation only.
- It does NOT claim the V4 audit conclusions are scientifically valid —
  they are stub-validated only (zero_model_requests=true means the V4
  audit ran on synthetic/stub data, not real results).
- It does NOT verify the statistical analyses (McNemar, bootstrap) —
  those need real data.

## Gate recommendation

The net-benefit freeze + protocol structure + partial-spend honesty all
verify. The gate decision for the operator is:

**Option 1**: treat the net-benefit gate as SATISFIED for Calibration
GO purposes (the protocol is frozen, budgets are honest, and the
experiment design is auditable) — resume the remaining cells under
Experiment GO when real calls are authorized.

**Option 2**: treat it as CONDITIONALLY SATISFIED (freeze and honesty
verified; completion deferred) — same effect for Calibration GO but
with the incompleteness explicitly carried.

Evidence: `netbenefit_audit_ro/NETBENEFIT_AUDIT_RO.json`; frozen
artifacts untouched.

Reproduce: `python3 -m collab_scheduler_v1.joint_search_v1.netbenefit_audit_ro`
