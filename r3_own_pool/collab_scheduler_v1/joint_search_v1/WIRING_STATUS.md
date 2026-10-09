# WIRING_STATUS.md — Unified Acceptance Report (2026-10-09, v2.2)

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

## PASS: Cost Predictor Counter-example Fix (Track B, 2026-10-09)

**Evidence**: `review/track_b.py` → `review/TRACK_B_EVIDENCE.json` (20/20)

**Counter-examples found (METERING_AUDIT.json smoke actuals)**:
- HET-LOCAL: old est 1280 vs actual 371/task (+245% — cache hits ignored)
- QUAL-LOCAL: old est 1430 vs actual 0/task (fully cached)
- HET-NONE: old est 1130 vs cold 1686/task (−49% — per-model constants too low)

**Fix — two separated costs with two roles**:
1. `deployment_cost(config)`: cold-run estimate, data-informed per-node tokens
   (e1/e2≈700, r≈200, v≈100 × model multiplier, + recovery overhead). Used for
   the deployment C/L objective normalization. Range over 48 configs: 1540–3070.
2. `incremental_cost(config, revealed)`: acquisition-time NEW-token estimate —
   subtracts cache overlap with already-revealed configs (same node+model ⇒
   prompt-identical ⇒ cached), floor 100. Used ONLY as the acquisition divisor.
   A fully-overlapped config now estimates 100, not its full deployment cost
   (fixes the QUAL-LOCAL 1430-vs-0 failure class).

**Calibration** (closed-loop actuals from JointEvaluator, 9 unique configs):
Spearman(est, actual C) = 0.767, MAPE = 4.5%. Note: stub dispatch usage was
shaped to realistic model-dependent costs, so MAPE measures consistency of the
estimator with a realistic cost field; the rank correlation is the wiring-level
claim (predictor orders configs by actual cost correctly).

## PASS: Production Closed-Loop, 100% Evaluator Observations (Track B)

**Evidence**: `review/track_b.py` → `review/TRACK_B_EVIDENCE.json` (20/20)

Upgrades the earlier DIAGNOSTIC score-distribution result to closed-loop:
- All 6 methods ran 5/5 selections through SearchSession→JointEvaluator→
  MeteredExecutor→Budget with **zero synthetic injection** — every Q/C/L in the
  searchers' observation stores came from `EVALUATIONS.jsonl` returns ✅
- All Q=1.0 (positive-control responses scored through the formal path) ✅
- GP + cost predictor called in every acquisition round for non-random methods ✅
- Non-degenerate last-round scores from pure evaluator data: qNEHVI 14 distinct /
  13 nonzero of 44 candidates (31 dominated candidates score exactly 0 — expected
  HV-improvement behavior, not degeneracy); scalarized 29 distinct / 44 nonzero ✅
- Known limitation (registered, not hidden): this closed loop runs the clean
  state only, so `use_state` ablations cannot diverge here; state-ablation
  divergence remains covered by `unified_test.py` Part B/C on the fault30 panel.

## PASS (DIAGNOSTIC): Per-Round Candidate Score Distribution

**Evidence**: `review/Q_CONTROLS_AND_SCORES.json`
- 40 candidates, 30 distinct @10dp, 31 nonzero, 1 tied@max (2.5%)
- Range [0, 0.0022], std 0.0006, non-degenerate, all finite
- **Scope**: mixed observations (superseded for closed-loop claims by Track B
  above; retained as acquisition-function diagnostics)

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
| Cost predictor counter-example fix (Track B) | ✅ PASS (20/20) | TRACK_B_EVIDENCE.json |
| Closed-loop non-degenerate scores, evaluator-only obs | ✅ PASS (Track B) | TRACK_B_EVIDENCE.json |
| Official BoTorch qNEHVI alignment | ❌ BLOCKING (Track A) | — |
| FULL real validation | ❌ BLOCKING | — |
| Formal experiment freeze | ❌ NOT STARTED (Track C) | — |

## Next Steps

**Track A — Baseline alignment** (now primary): Install/import BoTorch qNEHVI;
numerical alignment test with same GP, data, noise, objectives, reference point.
Self-built version retained as diagnostic method; official version replaces
`official_qnehvi_same_state`.

**Track B — DONE** (2026-10-09). Residual for formal experiment: rerun the
closed loop on the fault30 state panel once state-feature interface is admitted
(current closed loop is clean-state-only; state ablation covered separately).

**Track C — Data preparation** (parallel): Task splits, sample size rationale,
budget specification for formal experiment.
