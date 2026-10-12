# JOINT_VERIFY_EXEC_CLOSURE_STATUS — final execution-closure status (zero real calls)

Operator ruling on `d1353b1`: two remaining items only — the real
six-arm execution entry and shared-base metering attribution. Both are
closed at this commit; nothing else was touched. Zero real model
calls, zero GPU, named files only.

## Item 1 — real execution entry (DONE, fake-transport proven)

- `arm_engine_from_snapshot(real=True)` now builds the **RealEngine**
  (model load/stop/switch through the ModelManager, the audited
  stage-handoff inheritance included). The StubEngine path exists only
  for zero-call tests.
- `execute()` in `joint_verification_runner.py` is the complete
  controlled run: fresh run dir (no silent reuse), production Budget
  (micro-pilot worst-case caps 60 requests / 25K tokens / 1,800 s),
  shared-base phase (faults active) → snapshot copies → six per-arm
  episodes (SS/DS/SD/DD/NONE/MONO) with per-task frozen D-tiers →
  per-arm settlement → COMPLETE/INCOMPLETE results with the
  INCOMPLETE-permanence guard.
- **T12 (fake transport) proves the whole loop end-to-end**: all six
  arms + base COMPLETE; base-share attribution present on every row;
  model lifecycle actually driven through the manager (starts/stops
  observed); re-execution into the same run dir → PermissionError; an
  exploding transport → the exception propagates, ledgers preserved,
  no auto-restart; a run that wrote INCOMPLETE can never be marked
  COMPLETE.
- The execution env flag (`JOINT_VERIFY_EXECUTE`) **still does not
  exist** — `execute()` has no launcher; the pilot GO will add the
  gated CLI entry mirroring the audited reliability-runner pattern.

## Item 2 — shared-base cost/latency attribution (DONE, semantics frozen)

Frozen metering semantics (recorded in code and in every result row):
- `physical_total` = every settled response in the run's ledgers;
- `base_share` = shared-base physical tokens ÷ 6, attributed EQUALLY
  to each arm's **full-task cost** `C_full_task`;
- `arm_incremental` = the arm's own physical spend after the snapshot;
- **T (per arm)** = the arm's own episode release→completion (base
  replay = cache hits, ~0 service);
- **Primary endpoint = FULL-TASK realized R** with C = base_share +
  incremental — the DD−SS comparison is a full-task reward comparison
  under one shared deployment base;
- the recovery-CONDITIONAL contrast (incremental costs only) is
  reported SEPARATELY and is never presented as independent end-to-end
  deployment benefit.

## Additional confirmations per the ruling

- **Micro-pilot tasks cannot contaminate P3**: the pilot uses 3 tasks
  drawn from the REMAINING pool (never the frozen 60; the pilot draw
  will be recorded in its own freeze file at GO time). The P3 freeze
  (`JOINT_VERIFY_P3_FREEZE.json`, sha b04ffb29…) is untouched.
- **n=60 power caveat recorded**: at the E6-derived planning SD the
  interaction test needs n ≈ 71 at Δ=0.10 — n=60 is likely
  UNDERPOWERED for the interaction; a non-significant interaction at
  n=60 must be reported as "not established", never as "no
  interaction exists".

## Verification at this commit

T1–T12 all PASS (13/13 checks incl. both T4 directions); full M-suite
15 suites + admission check green. `execute()`'s only callers are
tests with fake transports.

**Status: closure complete. Real execution remains NO-GO; the next
decision is solely the 3-task micro-pilot GO/NO-GO.**
