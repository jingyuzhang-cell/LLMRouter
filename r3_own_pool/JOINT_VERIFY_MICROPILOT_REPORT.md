# JOINT_VERIFY_MICROPILOT_REPORT — the ONE authorized real micro-pilot run

Operator GO 2026-10-12 (baseline 98ecc81 → run at e13c2e6). One run,
3 tasks × 6 arms, purpose = execution-chain validation ONLY. This
report contains NO effectiveness claims: the 3 tasks are never used to
assert DD>SS, to adjust weights, strategies, or tier multipliers.

## 1. Verdict: **PASS** (all six arms executed, settled, and accounted)

| stage/arm | status |
|---|---|
| base / SS / DS / SD / DD / NONE / MONO | **COMPLETE** (7/7) |

Disclosure: a first launch attempt misfired at the directory gate
BEFORE any spend (0 requests / 0 tokens / 0 GPU) — launcher pre-created
the run dir; execute()'s no-reuse guard fired. Documented as
ATTEMPT0_NOTE.md in `pilot_20261012_170251/`; wiring fixed (execute()
owns dir creation); the one authorized run then executed cleanly.

## 2. Resource consumption (GO caps: 60 / 25,000 / 1,800 s)

- **29 real requests / 10,449 tokens** (48% / 42% of the caps);
  wall ≈ 7.5 min including 19 switches (1 cold start) ≪ 1,800 s.
- DISPATCH ledger exact: 29 reserved = 29 settled, 0 attempt-failed.
- 46 cache hits (base replay + within-arm reuse), 29 physical, 7 fault
  injections (D3_r on the planned r model, cache+corruption — base 1 +
  6 arm replays), server stopped and GPU freed after the run (verified:
  0 GPU processes).

## 3. Six-arm settlement table (real outputs)

| arm | task(tier) | Q | C_inc | C_base | T(s) | D(s) | on-time | R_cond | R_full |
|---|---|---|---|---|---|---|---|---|---|
| SS | t1(tight) | **1** | 1034 | 1306 | 359.5 | 68.0 | 0 | −6.41 | −6.58 |
| SS | t2(medium) | 0 | 846 | 1399 | 359.8 | 113.4 | 0 | −4.28 | −4.45 |
| SS | t3(wide) | **1** | 752 | 972 | 360.0 | 226.8 | 0 | −2.68 | −2.80 |
| DS | t1/t2/t3 | 0/0/0 | 0/0/745* | — | 138/138/278 | — | 0 | −3.03/−2.22/−0.09 | — |
| SD | t1/t2/t3 | 0/0/0 | 0/0/745 | — | 137/137/278 | — | 0 | −3.01/−2.21/−2.32 | — |
| DD | t1/t2/t3 | 0/0/0 | 0/0/745 | — | 76/76/218 | — | 0 | −2.12/0.00/−0.09 | — |
| NONE | t1/t2/t3 | **1**/0/**1** | 215/268/235 | — | 125/126/126 | — | 0/0/**1** | −2.87/−2.14/**+0.97** | — |
| MONO | t1/t2/t3 | 0/**1**/0 | 836/739/357 | — | 78/78/79 | — | 0/**1**/0 | −2.25/**+0.91**/−0.05 | — |

(*DS t3 shows C_inc 745 with Q 0; arms with C_inc 0 = policy
degradation — honest D10 EARLY_STOP with zero further calls.)

## 4. Integrity checks (the GO's mandated list)

| check | result |
|---|---|
| B1 reward consistency (independent recomputation, both metrics, all 18 rows) | **0 mismatches** |
| B2 per-task base attribution | 1306/1399/972 per task; Σ = base total ✓ |
| Terminal v2.1 Q recorded per task/arm | ✓ (18 rows) |
| Physical tokens / recovery E2E / frozen D / on-time-correct / dual R | ✓ all columns present |
| Recovery scope, re-executed nodes, model assignment | ✓ in arm ledgers (retry jobs + decisions) |
| Predictions vs realized separation | ✓ 15 decision rows persisted pre-execution; oracle keys in decisions: NONE |
| Physical/cache/injection/switch ledger | ✓ 29/46/7/19, all reconciled |
| Reward computation errors / wrong-model calls / cache leakage | none found (B1 recheck 0; cache fairness design held — per-arm engines) |
| Fail-stop / INCOMPLETE protection | not triggered (clean run); machinery verified in T12 |

## 5. Ready for the confirmatory experiment?

**Execution conditions: YES** — the chain (freeze-gated launch → real
models → shared base → six arms → dual settlement → ledgers → cleanup)
ran end-to-end within less than half the GO budget, with consistent
rewards and complete records. Observed calibration notes for the
confirmatory design (not defects): (a) SS episode times include large
switch walls (≈360 s for 3 serial tasks in one cell) making tight/medium
tiers unreachable for cell-batched SS — the confirmatory design must
either run per-task episodes or treat T consistently; (b) the stub-prior
q̂ beliefs still cause DS/SD/DD to degrade on natural e-failures — the
confirmatory analysis must use REAL terminal outcomes (which it does)
and report the degradation rates as part of the mechanism's behavior.

**Per the GO: stopped. No further real execution; awaiting the next
explicit ruling on the confirmatory experiment.**
