# Offline Incremental-Cost Predictor Error Audit (DIAGNOSTIC EVIDENCE, v3 final)

2026-10-09. Zero GPU calls, zero production changes. Inputs are frozen COPIES
under `copy_inputs/`; TEST16 untouched; no active file read for any conclusion.

## Conventions

- **Error sign**: `error = prediction − actual` (negative = underestimate).
- **coverage_upper** = fraction of cells with `actual ≤ prediction` (bound
  direction), NOT an interval hit rate.
- **signed_mean alone is insufficient**: per-node errors of opposite sign can
  cancel. The cold-S1 decomposition below is the worked example; conclusions
  use MAE + relative_mae (MAE / mean actual) + coverage.
- Token scales: predictor emits a PER-TASK MEAN; ledger new_tokens is CELL
  TOTAL. Both reported (`*_per_task`, `*_cell_total`).
- Deployment C and search physical spend never merged.

## Erratum chain (both errors AUDIT-SIDE; production predictor unchanged)

- **v1**: compared per-task prediction against cell-total actual (8× scale
  artifact on campaign cells; mis-narrated as "constants overestimate").
- **v2**: registered signatures panel-wide on fullval SINGLE-TASK cells (the
  production predictor's register covers the whole panel because searcher
  cells evaluate all tasks; fullval cells contain one). This produced phantom
  "false hits" (22.7% / 66.7% in the model-changed bucket) that were replay
  artifacts, not predictor failures. v3 registers/estimates only the executed
  task's signatures for fullval cells; campaign cells keep panel semantics.

## Inputs (completed/terminated, versioned; sha256 in JSON)

fullval_authorized_1h_01 (11 cells, old gold) · fullval_cont1_01 (4, COMPLETE)
· campaign v1 proposed (8 completed cells, old gold, DIAGNOSTIC)
· campaign v2 scalarized (24, COMPLETE, GOLD_CONTRACT_V1).
Excluded: sessions without terminal records; all running sessions.

## Final findings (PREDICTOR_ERROR_AUDIT.json has every row)

1. **Node-level, corrected replay**: false-hit = **0 / 1,084** decisions
   (predicted hit ⇒ ledger hit on every audited row); overall accuracy 0.854 —
   all errors are the SAFE direction (predicted new, actually hit).
   model-changed buckets: accuracy 0.93–1.0, false-hit 0 (model changes are
   correctly charged as new). The earlier retraction of precision-1.0 was
   driven by the v2 audit artifact; on these four sources precision holds,
   but we register it as "supported on audited sources", not a guarantee.
2. **Token-level — heuristic only, no bound in either direction**:
   - cold-S1: signed +170.3 (run01) / +52 (cont1) LOOKS calibrated, but the
     per-node decomposition shows cancellation: e1 +389/+452 (over), e2
     +211/+229 (over), r −182/−281 (under), v −248/−348 (under). relative_mae
     10.3% / 2.9%.
   - LOCAL: relative_mae 59% (run01) / 305% (cont1), upper cover 33%/100% —
     the 0.3×overhead expectation is too coarse in both directions.
   - FULL: relative_mae 44–74%, under-estimates (replay spend exceeds the
     recovery expectation).
   - campaign: v2 signed +4.6 / MAE 135.8 (relative 31.2%) / upper cover 54.2%;
     v1 +11 / MAE 222 / 25%. Near-zero means do NOT establish calibration
     (cancellation); treat as a scoring heuristic only.
3. **Request-level**: campaign v1 exact 8/8; v2 upper cover 91.7% with
   relative_mae 50% (actual mean 10 req/cell-task, MAE 5.0); fullval S2/S3
   undercount by construction (node-derived view excludes recovery calls).

## Registrations (review directives, standing)

- **Resource safety**: predictor is ONLY an acquisition-function heuristic
  (sole consumer: candidate-score divisor, `review/track_b.py:247`). Hard
  budget and settlement are ledger-controlled: every dispatch passes
  `budget.check()` pre-call and `budget.reserve()` per request
  (`smoke_runner.py:106,127`). No prediction can bypass or relax charging.
- **Claims language**: no "guarantee"/"upper bound" wording for predictions;
  precision-1.0 phrased as "supported on audited sources" pending broader data.
- **Current campaign**: predictor version FROZEN; calibration/fixes from this
  audit must be separately versioned and validated on NEW trajectories.
- **Post-war judgment**: compare search curves on the COMMON MEASURED physical
  budget; failed and retried trajectories listed separately with additive
  costs, never spliced. Prediction error neither proves nor disproves
  algorithm advantage.
