# CALIBRATION_GO_PACKAGE — readiness summary for the operator's Calibration GO decision

Date: 2026-10-11. Zero real model calls. This document summarizes the
state of ALL Calibration-GO prerequisites and proposes the calibration
scope for the operator's review. It authorizes nothing by itself.

## 1. Prerequisite status

| Prerequisite | Status | Evidence |
|---|---|---|
| Phase 1 design (MAINLINE_FREEZE) | FROZEN | 42187e9 / V2.3 rev3 |
| Phase 2 M1–M6 stub implementation | SIGNED OFF | b50bbde chain |
| Phase 3 zero-call verification | SIGNED OFF | b50bbde chain |
| Formal settlement audit | **Conditional PASS** | 23/23; a6524ae + report; 8,192-token crash reservation carried |
| Net-benefit independent audit | **46/46 PASS** (awaiting operator's final gate decision) | 5da76e2; E5b final-effective grid + B5 traceable boundary |
| Experiment protocol (V2.3 rev3) | **FROZEN** | 42187e9; five arms, H1–H4/S1, unified six-contrast method rule, stop conditions |

**Both Calibration-GO prerequisites are now complete.** The Formal gate
carries two reservations (crash-reservation liability; STATUS/wall
absence) that the operator has accepted as Conditional PASS. The NB gate
at 46/46 is the operator's decision.

## 2. What Calibration GO would authorize (proposed scope)

Per protocol V2.3 rev3 §6, Calibration GO authorizes **profile
measurement ONLY** (no policy comparisons):

### 2.1 Measurement targets

For each (node × model × detection-family) combination:
- **quality success rate** (binary correctness per call)
- **token distribution** (P50/P90/P95)
- **service latency distribution** (P50/P90/P95)
- **model startup/switch wall time** (separate from service)

Node set: {e1, e2, r, v} × Model set: {medium, large, coder} ×
Detection families: {D1_e_empty, D3_r_unparseable, D5_v_fail} plus
clean → approximately 4×3×4 = 48 cells × ≥30 calls each ≈ **1,440
measurement calls minimum**.

### 2.2 Budget envelope (proposed)

| Cap | Proposed value |
|---|---|
| Max measurement requests | 2,000 (≈1.4× the minimum for CI convergence) |
| Max measurement tokens | 2,000,000 (conservative; actual ≈ 1,440 × P95_tokens) |
| Max wall time | 14,400 s (4 hours; startup dominant) |
| Caps are CEILINGS, not completion guarantees | sessions incomplete if exceeded, reported as-is |

### 2.3 Data-access boundaries

- **Calibration panel**: tasks drawn from the same source as the
  evaluation panels but **disjoint** from them (task-selection rule
  frozen before any measurement); SHA-bound and versioned.
- **No policy execution**: no arm comparisons, no reward decisions,
  no scheduling logic is run during calibration.
- **PRIORS_REAL_V1.json**: output artifact with per-entry real
  measurement provenance (source, count, timestamp, SHA), tagged
  `calibrated: true`.

### 2.4 Distribution-family validation (B4 landing)

After measurement, per (node × model):
- Fit normal / lognormal / empirical distributions to latency samples
- KS/AD goodness-of-fit tests (significance level frozen before
  viewing calibration results)
- E1 estimator family selection per cell → frozen in PRIORS_REAL_V1
- Cross-task contention: measured on a dedicated co-execution probe
  (2 tasks sharing the executor, ≥20 co-execution trials) → contention
  calibration value frozen

### 2.5 Applicability-standard freezing order (protocol §5)

**BEFORE any calibration data is viewed**: freeze the symmetry
diagnostic metric + threshold, outlier-influence criterion, minimum
sample size, and missing-data rule for the six-contrast method-choice
rule. Data-access log maintained.

## 3. What Calibration GO does NOT authorize

- No Experiment GO (pilot, confirmation, or any arm comparison)
- No production executor integration
- No net-benefit cell resumption
- No Formal campaign modification
- No real-model scheduling decisions (the policy is not run on real
  data during calibration)

## 4. Estimated cost comparison

| Item | Requests | Tokens |
|---|---|---|
| Calibration (proposed cap) | ≤ 2,000 | ≤ 2,000,000 |
| Formal campaign (completed) | 4,871 | 1,743,814 |
| Net-benefit pre-halt (3 cells) | 252 | 102,894 |
| Net-benefit full (if resumed) | ~3,750 est. | ~1,500,000 est. |

Calibration is the smallest real-call budget item and is a prerequisite
for everything downstream.

## 5. Decision requested

The operator is asked to:
1. Accept the NB audit at 46/46 as the final gate decision
   (Conditional PASS or Conditional PASS with the freeze-paused
   incompleteness carried — both are workable).
2. Approve Calibration GO with the scope and budget in §2.
3. Confirm the data-access boundaries in §2.3 and the freezing order
   in §2.5.

Upon approval, the first action would be to freeze the calibration
panel + applicability standards + budget envelope (a zero-call
freezing step), then execute measurements under the authorized budget.
