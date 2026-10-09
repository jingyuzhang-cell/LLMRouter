# Formal Pipeline Wiring Status (2026-10-09)

## What EXISTS and PASSES (18 unit tests)
- `evaluator.py:space()` — 48 configs (4-node independent X × 3 Z)
- `evaluator.py:JointEvaluator` — evaluates via MeteredExecutor, ledger-based costs
- `evaluator.py:SearchSession` — callback interface: `step(select, states)`
- `runtime.py:run_session()` — wires campaign/quota/evaluator/session
- `smoke_runner.py:Budget` — attempts/tokens caps with pending/settle
- 8 evaluator tests + 10 runtime tests ALL PASS

## What DOES NOT EXIST yet (the gap)
SearchSession docstring says "six algorithm implementations are external."
No selector callbacks have been written for the six METHODS:
1. proposed_state_incremental — NOT IMPLEMENTED
2. random — trivially implementable
3. scalarized_bo — NOT IMPLEMENTED
4. official_qnehvi_same_state — NOT IMPLEMENTED (mark BLOCKED: no official BoTorch)
5. proposed_without_state — NOT IMPLEMENTED (ablation)
6. proposed_without_incremental_cost — NOT IMPLEMENTED (ablation)

Incremental cost predictor not yet called by any selector on this pipeline.

## Next window's single deliverable
Write the six `select(candidates, observations) -> config_id` callbacks for
SearchSession.step(), wire the incremental cost predictor into the proposed
selector's scoring, drive with independent Stub responses, and verify:
- At least one model update → re-selection round (not just init)
- Non-degenerate acquisition scores (not all zero)
- wo_state and wo_incr_cost correctly disable their respective mechanisms
- Costs from ledger, not from predictor values
- Official qNEHVI marked BLOCKED if BoTorch unavailable

The `select` callback receives (candidates_list, observations_list) and must
return a config_id string. It CANNOT see states/faults (correct isolation).
