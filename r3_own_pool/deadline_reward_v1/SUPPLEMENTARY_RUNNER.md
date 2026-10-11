# SUPPLEMENTARY_RUNNER — the ~1000-call DAG-quality measurement (prepared, HOLD)

`supplementary_runner.py` executes DAG_QUALITY_CALIBRATION_PROTOCOL_v1:
5 configs (SS/DS/SD/DD/NONE through the frozen `arm_entry.py`) × 2
conditions (clean; fault30_D3 on the frozen 6-task set) × 20 frozen tasks,
full real 4-node cascade, **v2.1 terminal scoring only**. Default
invocation is a ZERO-CALL preflight; execution requires the operator's
measurement GO (`SUPPLEMENTARY_EXECUTE=1` + the approved
SUPPLEMENTARY_PANEL_FREEZE.json SHA-256 + GPU lock + production Budget).

## Two production-parity defects found and fixed while building it

Both were latent in `deadline_reward_v1/detection.py` (the M2 mirror of
the production detection predicates) and only manifest on REAL model
answers — the stub fixtures never exercise them:

1. **Fence handling.** Real answers wrap JSON in ``` fences (all 18,066
   formal-campaign trajectory records). The mirror's bare `json.loads`
   misfired D1/D3/D5 on every fenced answer. `_decode` now mirrors
   `tool_aware_v1.decode`; `json_value` mirrors production's
   strict-first-then-decode dual path.
2. **Expression family.** Production `exec_calc` evaluates a full AST
   whitelist (+ - * /, rational constants, unary ±, vN refs, exact
   Fractions). The mirror only split on '+' — it misfired D3 on naturally
   legitimate expressions like `v1 - v0` or `(v0 + v1) / 2` (observed in
   real r answers). The mirror now implements the identical AST semantics.

After the fixes the mirror agrees with production on **every** evaluated
real trajectory record (0 divergences; asserted again at every preflight
and before execution). The remaining documented divergence — the mirror's
facts validation is looser (no 1..12/evidence checks) — biases toward
under-detecting D1 and affects only recovery triggering, not the terminal
v2.1 score. Full M-suite regression green (M1-M6, phase-3, boundary;
M2 whitelist extended with the stdlib modules the mirror now needs).

## Decision beliefs (frozen at preflight, hash-bound)

PRIORS_REAL_V1's q_success is INVALID (strict-parse artifact; operator
ruling) — using it would make every candidate infeasible (e≈0, v|coder=0).
Instead the DS/SD/DD decision priors use **production-parity parse rates
over the deduped real formal-campaign records** (zero new calls):

| cell | q_parse | n | | cell | q_parse | n |
|---|---|---|---|---|---|---|
| e1|* | 1.000 | 8 | | r|large | 0.838 | 37 |
| e2|large | 0.875 | 8 | | r|medium | 0.783 | 23 |
| e2|coder/medium | 0.750 | 8 | | v|coder | 1.000 | 65 |
| | | | | v|large | 0.813 | 64 |

Latency/tokens come from the 1200-call calibration (clean cells); switch
costs are the REAL measured ones (~59-71 s/start). Notable consequence,
visible before spending anything: r|medium q̂=0.783 < q_min=0.80, so under
real beliefs DS's planned-π pool is infeasible and DS will degrade —
exactly the designed contrast (SS retries blind, SD/DD can escape via π).

Parse rates are a declared PROXY (parse-success ≠ correctness); they feed
only the arms' in-flight decisions, never the measured P(correct).

## Declared scaffolding (not measured quantities)

- **D = 3600 s per task.** Real switch costs under the frozen per-call
  switch bound make any smaller D infeasible for every multi-call plan;
  deadlines are inert by design and timeliness is outside this
  measurement's scope (ADMISSION_CHECK gate 5).
- **One engine + one identity cache for the whole run.** Cross-cell reuse
  of DONE outputs under unchanged (model, input_sha) identity is the M3
  deployment semantics; physical requests will be well under the 800
  logical base (cache hits), all metered.
- **Batched plan application** mirrors `reassign.apply_whole_plan` job
  construction exactly (per-task job tuples recorded per row for audit);
  only the batching granularity differs because real model switches cost
  ~60 s each.
- Faults are metered-corruption events (answer replaced AFTER the charged
  call), bound to (uid, r, planned-model) — the production evaluator's
  set_fault semantics; they never leak across cells.

## Verification status

- `evidence/SUPPLEMENTARY_PREFLIGHT.json`: PREFLIGHT_PASS — freeze/panel/
  protocol/arm_entry/detection/priors/beliefs hashes all bound; beliefs
  rebuilt from 21 trajectory files with 0 divergences.
- `evidence/SUPP_RUNNER_SMOKE.json` (36/36): the full cell driver —
  decision round, batched application, V stage, v2.1 scoring — exercised
  end-to-end on the stub engine, including the NONE-arm V-stage bug the
  smoke caught and fixed (NONE previously degraded instead of completing
  the DAG). Real-hardware paths (RealServer/RealEngine/ModelManager) are
  not covered by the smoke; they mirror calibrate_real/evaluator patterns.
- Budget caps (1200 requests / 800K tokens / 7200 s) via the production
  Budget class; drill evidence in ADMISSION_CHECK gate 4.

**Status: prepared and preflighted. Real execution remains HOLD pending
the operator's measurement GO.**
