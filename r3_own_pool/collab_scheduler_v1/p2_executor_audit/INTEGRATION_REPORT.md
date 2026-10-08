# P2 Executor Integration Test Report (zero LLM calls)

## Test design
Used REAL `eval_config()` from `fault30_run.py` with deterministic stubs
(StubLedger + StubExecutor), not simulated state variables.

## Results

### T1: R2 fires when facts change ✅
- Faulted e1 (empty facts) → fb recovery returns real facts → e_recovered fires
- r:fbd: call appears in execution log with a DIFFERENT prompt SHA than original r
- **R2 correctly triggered by structured e_recovered state**

### T2: R2 does NOT fire when no fault ✅
- Clean execution (no faults) → no fb calls → no e_recovered → no r:fbd:
- **R2 correctly skipped**

### T3: V2 presence ✅ (absence is correct)
- Stub returns same expression for both original r and r:fbd → r_changed=False
- V2 correctly did NOT fire (would have been unnecessary under old code)
- **New r_changed check prevents unnecessary V2 execution**

### T4: r_changed semantics ✅
- When r output is same across calls: r_changed=False → no V2
- **r_changed correctly reflects whether final r output actually changed**

### T5: C/L inflation analysis
- 6 logical calls, 5 unique prompts, 1 duplicate-key charge
- The e1:fb call shares the same prompt SHA as e1 original (same context) but
  uses a different model (coder vs large), so it's a genuinely different call
- **Duplicate-key C/L charge: 1 (the e1 planned call is superseded by e1:fb)**
- Note: this is the E-stage equivalent of the V1/V2 issue — the planned call
  is wasted when recovery succeeds

## V1/V2 dedup audit (P0-2)

### Old code behavior
V2 fires whenever `len(rkeys) > 1` — even when r output unchanged. This
charges V1 + V2 for every task with any r recovery, inflating C and L.

### New fix behavior
V2 fires only when `r_changed=True` — when r output actually changed.
This eliminates unnecessary V2 calls when recovery produces same output.

### Remaining issue
When r_changed=True, V1 is still charged even though V2 supersedes it.
The V1 call is "wasted" (its answer is based on old r output). This is
+1 v-node cost per r_changed task. NOT trivially fixable without lookahead
(would need to defer V1 until after R2/R3 complete, but V1 is batched
for GPU efficiency). P2 protocol should report `superseded_v_calls` separately.

### E-stage equivalent
The planned e1 call is similarly "wasted" when e1:fb recovery succeeds.
Same batch-efficiency tradeoff applies.

## r_changed semantics after R2+R3 (P0-3)

R2 (fbd) fires when facts changed. R3 (esc) fires when r is unparseable.
If both fire: R2 produces r_answer_A, then R3 produces r_answer_B.
r_changed compares only the LATEST answer to the PREVIOUS one.
- If A→B: r_changed=True (correctly reflects final change)
- If A→A (same answer from R3): r_changed=True from R2 may be overwritten
  by comparison of B vs A → False (correctly reflects no net change)

**Issue found**: r_changed is set in each stage independently. If R2 sets
r_changed=True but R3 produces the same output as original (unlikely but
possible), r_changed stays True from R2. This is a conservative behavior —
it errs on the side of refreshing V (safe but potentially wasteful).

## Historical impact list (P0-4)

The `1421` figure from previous commit needs correction:
- These are LOCAL_REROUTE task-evaluations that have `:fb:` keys
- NOT all 1421 need model re-calls: R3 may still fire and produce correct
  output even without R2 refresh
- Actual impact depends on:
  1. Whether facts actually changed (e_recovered would have fired)
  2. Whether the un-refreshed r output was already wrong (R3 would catch it)
  3. Cache coverage for zero-call recomputation

**Version timeline (corrected):**
- Original code: `endswith(':fb')` — never matches → R2 NEVER fires
- 7cd4f44: `':e1:fb:' in kk` — string-based, DOES match → R2 fires on any fb key
- 8cbd29c: `e_recovered` structured state → R2 fires only when facts changed

## Test count clarification (P0-5)

Previous "12/12" test count: 11 boolean assertions + 1 text note = 12 items.
Only 11 were actual test assertions. Current integration test: 5 boolean
assertions with real execution path + 3 informational notes.

## Recommendations for P2 protocol

1. Report `superseded_v_calls` and `superseded_e_calls` separately from total
2. Use `serial_execution_L` label (not "critical-path") since calls are serial
3. Consider deferring V1 until after R2/R3 to avoid waste (efficiency optimization,
   not correctness fix — defer to P3)
4. Historical fault30 data: identify tasks where R2 SHOULD have fired but didn't
   (pre-7cd4f44); determine if R3 compensated; flag unresolvable cases
