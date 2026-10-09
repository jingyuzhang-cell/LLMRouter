# WIRING_STATUS.md — Unified Acceptance Report (2026-10-09, v2)

Single source of truth for all pipeline wiring evidence. Supersedes all previous
partial reports and the v1 of this file. Items grouped by status.

## PASS: Production Pipeline

**Path**: `ProductionSelector.select()` → `SearchSession.step()` → `JointEvaluator.evaluate()` → `MeteredExecutor.call()` → `Budget` → `observe_evaluator_result()` → next `select()`

**Evidence**: `review/unified_test.py` → `review/UNIFIED_PIPELINE_EVIDENCE.json` (12/12)
- All 6 methods run through SearchSession→JointEvaluator→Budget ✅
- Incremental cost predictor called BEFORE each selection ✅
- Both clean and fault30 states evaluated ✅
- Budget tracked actual token usage ✅
- Methods produce different selection sets ✅

**qNEHVI implementation used in the 6-method pipeline**: self-built `JointPosteriorGP` + `exact_qnehvi_score()` (joint posterior Cholesky sampling). This is a SELF-BUILT baseline, distinct from the OFFICIAL BoTorch qNEHVI which is separately BLOCKING. The 6-method pipeline currently runs the self-built version under the name `official_qnehvi_same_state`; this label is misleading and should be `self_built_qnehvi_joint_posterior` until BoTorch alignment is complete.

## PASS: Ablation Isolation

**Evidence**: `review/unified_test.py` (Part B/C) + `review/acquisition_evidence.py`
- State-blind picks identical across clean/fault30 (insensitive) ✅
- Feature dimensions differ (state bit present vs absent) ✅
- use_state/use_cost flags correctly set per method ✅
- Cost divisor removal exactly recovers base scores ✅
- Ranking changes with cost toggle (corr=0.994≠1.0) ✅
- Both ablations share SAME JointPosteriorGP + exact_qnehvi_score ✅

## PASS: Q Scoring Controls

**Evidence**: `review/Q_CONTROLS_AND_SCORES.json` (9/9)
- Q=1 positive control: facts(1.5,2.5), expr(v0+v1), v={"value":4.0}, gold=4.0 → **Stub Q=1.0 via formal scoring path** ✅
- Q=0 negative control (wrong value): v returns 999 → Q=0.0 ✅
- Q=0 negative control (unparseable): v returns {} → Q=0.0 ✅
- Previous Q=0 root cause: gold=4.0 (make_task default, not 200); stub {} → None → Q=0 ✅
- Note: "Q=1.0" here means through the formal JointEvaluator→eval_config→scoring path with Stub dispatch, NOT a real LLM result.

## PASS (DIAGNOSTIC): Per-Round Candidate Score Distribution

**Evidence**: `review/Q_CONTROLS_AND_SCORES.json`
- 40 candidates, 30 distinct @10dp, 31 nonzero, 1 tied@max (2.5%)
- Range [0, 0.0022], std 0.0006, non-degenerate, all finite
- **Scope**: mixed observations — 4 Stub Q=1.0 from JointEvaluator + 4 hand-set synthetic Q=0.3–0.5. This proves the acquisition function produces non-degenerate scores on varied input, but does NOT prove the full production loop generates non-degenerate scores from evaluator-only observations. Next closed-loop test should use 100% JointEvaluator-returned Q/C/L.

## PASS: FULL Reachability

**Evidence**: `review/exact_qnehvi_test.py` (8/8) + `review/wiring_test.py` (13/13)
- FULL present in 48-config space (16 FULL configs) ✅
- Random search selects FULL with sufficient budget ✅
- Acquisition selects FULL when FULL Pareto-dominates ✅
- Cost-aware EHVI correctly avoids FULL when cost high (documented behavior) ✅

## PASS: Prior Unit Tests (not superseded)

- `test_evaluator.py`: 8/8 (48 configs execute, FULL=8 calls, cache, fault cost, detector) ✅
- `test_runtime.py`: 10/10 (campaign quotas, GPU lock, crash recovery, fail-closed) ✅
- `review/wiring_test.py`: 13/13 (features, C/L estimates, 6 methods through stub) ✅

## BLOCKING: qNEHVI BoTorch Alignment

Self-built joint posterior is mathematically correct (Cholesky from full
posterior covariance). NOT verified against BoTorch `qExpectedImprovement`
or Ax Platform qNEHVI. Required: numerical alignment with same GP, data,
noise, objectives, reference point; MC sampling-error bounds.

Without alignment, "official_qnehvi_same_state" is a self-built baseline,
not the strong qNEHVI baseline the experiment design promised.

## BLOCKING: Incremental Cost Predictor Counter-example Fix

Identified in prior review. Not yet fixed.

## BLOCKING: FULL + New Fault Billing Real Validation

Stub-verified (8 logical calls, swapped models, both charged). Requires
small-scale real LLM validation before formal experiment.

## NOT STARTED: Formal Experiment Protocol Freeze

Data splits, sample size, budget, stopping rules — awaiting blocking items.

## Summary

| Item | Status | Evidence |
|---|---|---|
| Production pipeline 6 methods (self-built qNEHVI) | ✅ PASS | UNIFIED_PIPELINE_EVIDENCE.json |
| Ablation isolation | ✅ PASS | UNIFIED_PIPELINE_EVIDENCE.json |
| Q scoring controls (Stub via formal path) | ✅ PASS | Q_CONTROLS_AND_SCORES.json |
| Score distribution (mixed obs, diagnostic) | ✅ DIAGNOSTIC PASS | Q_CONTROLS_AND_SCORES.json |
| FULL reachability | ✅ PASS | EXACT_QNEHVI_TESTS.json |
| Evaluator (48 configs) | ✅ PASS | test_evaluator.py 8/8 |
| Runtime (quota, GPU, crash) | ✅ PASS | test_runtime.py 10/10 |
| Production-loop non-degenerate scores (evaluator-only obs) | ❌ NOT TESTED | — |
| Official BoTorch qNEHVI alignment | ❌ BLOCKING | — |
| Cost predictor counter-example fix | ❌ BLOCKING | — |
| FULL real validation | ❌ BLOCKING | — |
| Formal experiment freeze | ❌ NOT STARTED | — |

## Next Steps (two parallel tracks)

**Track A — Baseline alignment**: Install/import BoTorch qNEHVI; numerical alignment
test with same GP, data, noise, objectives, reference point. Self-built version
retained as diagnostic method; official version replaces `official_qnehvi_same_state`.

**Track B — Production closed-loop**: Fix incremental cost predictor counter-example;
run 6-method closed-loop with 100% JointEvaluator-returned observations (no synthetic
Q injection); verify non-degenerate scores from pure evaluator data.

**Track C — Data preparation** (parallel): Task splits, sample size rationale,
budget specification for formal experiment.
