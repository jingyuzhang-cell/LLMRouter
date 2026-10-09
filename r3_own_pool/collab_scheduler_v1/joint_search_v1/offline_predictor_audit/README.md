# Offline Incremental-Cost Predictor Error Audit (DIAGNOSTIC EVIDENCE)

2026-10-09. Zero GPU calls, zero production changes. Inputs are frozen COPIES
under `copy_inputs/` (no active file read for any conclusion); TEST16 untouched.

## Conventions (explicit, per review)

- **Error sign**: everywhere `error = prediction − actual` (negative = underestimate).
- **coverage_upper** = fraction of cells with `actual ≤ prediction` (prediction
  treated as a CANDIDATE upper bound). **coverage_lower** = `actual ≥ prediction`.
  These are bound-direction rates, NOT interval hit rates.
- **Token scale**: the predictor outputs a PER-TASK MEAN; ledger `new_tokens` is
  the CELL TOTAL over n tasks. Both scales are reported (`*_per_task`,
  `*_cell_total`).
- Deployment C and search physical spend are never merged.

## ERRATUM (v1 of this audit)

v1 compared the per-task prediction against the cell-total actual on campaign
cells — an 8× scale artifact that masqueraded as systematic underestimation
(signed_mean ≈ −3,044) and was mis-narrated as "constants overestimate".
Corrected numbers below. The v1 conclusion "token estimates are not a bound"
STANDS, with the corrected magnitudes.

## Inputs (completed/terminated runs with explicit versions)

| source | kind | version manifest | cells |
|---|---|---|---|
| fullval_runs_fullval_authorized_1h_01 | calibration | FULLVAL_AUTHORIZED_1H.json (old gold) | 11 (terminated, VALIDATION_INCOMPLETE) |
| fullval_runs_fullval_cont1_01 | calibration | FULLVAL_CONTINUATION_1.json | 4 (COMPLETE) |
| formal_campaign_proposed_state_incremental_20261009 | campaign | FORMAL_LAUNCH_V1.json (old gold, DIAGNOSTIC) | 8 completed cells |
| formal_campaign_v2_scalarized_bo_20261009 | campaign | FORMAL_LAUNCH_V2.json (GOLD_CONTRACT_V1) | 24 (COMPLETE) |

Excluded: sessions without a terminal record (random_20261009), all running
sessions. Manifest sha256 per source recorded in the JSON.

## Method

Production `CacheIdentityPredictor` imported UNMODIFIED, replayed
chronologically per cell exactly as the searcher uses it (predict → register,
clean/fault30 scopes). Actuals from the copies' ledgers: per-node hit/new from
TRAJECTORY alias records; cell spend from search_spend; deployment C separate.
Oracle-scope variant (same identity rules, one shared scope per run) isolates
scope-split conservatism from identity-rule error.

## Corrected findings (PREDICTOR_ERROR_AUDIT.json has every row)

1. **Node-level: the stub-era "precision = 1.0" claim is WITHDRAWN for real
   executions.** Cross-source accuracy 0.877; false-hit rate (predicted hit,
   ledger shows a NEW request — unsafe direction) 1.3% overall, 22.7% on
   fullval run01, **66.7% in the model-changed bucket** there (FULL replay
   swaps models; recovery-path prompts diverge). All 14 false-hit rows are
   itemized (`predictor_mismatches`).
2. **Request-level**: campaign v1 proposed exact on 8/8 cells; v2 scalarized
   MAE 4.5 requests, upper cover 83% — useful heuristic, **no guarantee**.
   fullval S2/S3 undercount by construction (node-derived view excludes
   recovery/replay calls: −2..−3 per cell).
3. **Token-level (scale-corrected, per-task)**: campaign v2 signed mean +4.1
   (near-unbiased) with MAE 135 and **upper cover 54.2%** — a calibrated-on-
   average heuristic, NOT an upper bound. Campaign v1: +11 / MAE 222 / upper
   25%. fullval: cold-S1 UNDER-estimates (−976: per-node constants exceed real
   cold usage), LOCAL mixed (−1,010 run01 / +1,404 cont1: the 0.3×overhead
   recovery expectation is both too small and too coarse), S4 +100 floor vs 0.
4. **Deployment vs search physical**: side-by-side per cell, never merged.

## Registrations (review directives, accepted)

- **Resource safety**: the predictor is ONLY a heuristic penalty inside the
  acquisition function (sole consumer: the divisor in candidate scores,
  `review/track_b.py:247`). Hard budgets and settlement are controlled by the
  real ledger: every dispatch passes `budget.check()` before the call and
  `budget.reserve()` per request (`smoke_runner.py:106,127`) — a false
  "predicted hit" can shape WHICH candidate is picked but can NEVER bypass or
  relax the pre-dispatch quota check or the charging path.
- **Algorithm claims**: "precision = 1.0" and "conservative upper-bound
  guarantee" are retracted for real executions; 83% request / 54% token upper
  coverage supports no guarantee.
- **Current campaign**: predictor version FROZEN for the running campaign (no
  mid-campaign change to the selection mechanism). Any calibration or fix from
  this audit must be separately versioned and validated on NEW trajectories —
  current trajectories cannot be used to both tune and confirm.
- **Post-war judgment criterion**: whether Proposed achieves better search
  curves at LOWER ACTUAL physical spend (ledger-measured). Prediction error
  neither proves nor disproves algorithm advantage.

Diagnostic evidence only. No method comparison, no TEST16 access, no
modification to production code, caches, quotas, or run configuration.
