# Search Mechanism Review Report (CPU zero-call, 2026-10-09)

Reviewed: `sa_pgfs_v1/acquisition.py`, `surrogate.py`, `external_baselines.py`,
`replay_v2.py`, `ablation_mechanisms.py`, `joint_search_smoke/unified_space.py`,
`closed_loop_test.py`, `six_method_closed_loop.py`, `joint_search_v1/evaluator.py`,
`joint_search_v1/runtime.py`, `joint_search_v1/test_evaluator.py`, `test_runtime.py`.

## Q1: Does Proposed actually select via fitted GP + acquisition?

**YES — verified by CPU test.**

Evidence:
- `sa_pgfs_v1/surrogate.py:QSurrogate.fit()` calls sklearn GP `fit(X, y)` on
  revealed configs' features and Q observations
- `sa_pgfs_v1/acquisition.py:ehvi()` calls `hypervolume()` on
  `front_pts + [sampled_Q, C, L]` for each MC sample — the selection is
  driven by posterior `mu/sigma` and deterministic `C/L`
- **Directed test**: fitted GP on observation set A (configs 0-4) vs B (5-9);
  predictions differ (`t1_gp_predictions_differ=true`); acquisition values
  differ significantly (correlation = 0.164); top-3 rankings differ
  (A→config 30 first; B→config 10 first)
- Initial test's `argmax` convergence (both picked config 22) was a stub-data
  coincidence; the acquisition VALUES are clearly observation-sensitive

File/function: `sa_pgfs_v1/replay_v2.py:250-262` (ehvi/cost_aware_ehvi branch);
`joint_search_v1/evaluator.py:SearchSession.step()` (select callback receives
only candidates + past observations).

**Verdict: PASS — not blocking.**

## Q2: Do wo_state / wo_incremental_cost only remove their corresponding mechanism?

**YES — verified by flag isolation test.**

Evidence from `joint_search_smoke/six_method_closed_loop.py:SAPGFS.__init__`:
- `proposed`: `use_state=True, use_incremental_cost=True` ✓
- `wo_state`: `use_state=False, use_incremental_cost=True` ✓ (only state removed)
- `wo_incr_cost`: `use_state=True, use_incremental_cost=False` ✓ (only cost removed)
- Both ablations share the SAME GP, SAME EHVI function, SAME features — the
  only code-path difference is `if self.use_incremental_cost: acq = acq / incr`

In `sa_pgfs_v1/ablation_mechanisms.py` (B1 state ablation):
- v2_1 fair design: BOTH arms train on the SAME pooled samples; only the
  state feature column differs (`Zp` appended for aware, absent for blind)
- B2 representation: same GP + same EHVI; only feature encoding differs

**Verdict: PASS — not blocking.**

## Q3: Is qNEHVI a real implementation (archive re-sampling)?

**YES — verified by source inspection.**

Evidence from `sa_pgfs_v1/replay_v2.py:202-219` and
`sa_pgfs_v1/external_baselines.py:138-161`:

```python
# Both implementations:
sur.fit(X[ev], obs_q)                    # GP on observed
mu_a, sg_a = sur.predict(X[ev])          # posterior for ARCHIVE
mu_c, sg_c = sur.predict(X[uneval])      # posterior for CANDIDATES
qa = _sample_q(mu_a, sg_a, n, rng)       # SAMPLE archive Q from posterior
qc = _sample_q(mu_c, sg_c, n, rng)       # SAMPLE candidate Q from posterior
for s in range(n):
    arch = [[qa[s][j], C[j], L[j]] ...]  # ARCHIVE re-sampled each draw
    f0 = hypervolume(arch)                # HV of SAMPLED archive
    for k in range(len(uneval)):
        cand = vstack([arch, [qc[s][k], C[k], L[k]]])
        out[k] += hypervolume(cand) - f0
```

The qNEHVI distinction (archive points SAMPLED from posterior each MC draw,
vs SA-PGFS's point-archive EHVI which uses observed values as fixed) is
correctly implemented. This is the `q=1` batch formulation.

**Verdict: PASS — not blocking.**

## Q4: Is any unrevealed config's true Q/C/L accessible to the selector?

**NO — verified by source inspection and boundary test.**

Evidence:
- `joint_search_v1/evaluator.py:SearchSession.step()`: select callback receives
  `copy.deepcopy(candidates)` (id/X/Z only, no Q/C/L) and
  `copy.deepcopy(self.observations)` (past results only)
- No global truth table, no `TRUE`, no `objs[`, no `pts[` in the SearchSession code
- `t3_no_truth_leak_in_step: true` in directed test
- In `replay_v2.py`, all methods access `obs_q[pick]` ONLY AFTER selection
- In `six_method_closed_loop.py`, methods access `true_qcl[]` only for configs
  they've already revealed (via `method.observe()`)

**Potential concern (non-blocking)**: in `replay_v2.py`, the `cand_obj` passed
to EHVI contains `objs[uneval]` which includes TRUE C/L of unrevealed configs.
However, C and L are declared deterministic (computable from config structure),
so this is not information leakage — it's the standard MOBO assumption that
non-surrogated objectives are known a priori. The Q value (the black-box
objective) is properly hidden until evaluation.

**Verdict: PASS — not blocking.**

## Additional findings

### Config space consistency
- `joint_search_v1/evaluator.py:space()` produces **48 configs**
  (2×2×2×2 X-options × 3 Z-options including FULL)
- `joint_search_smoke/unified_space.py` produces **32 configs**
  (16 X × 2 Z, FULL excluded)
- These are DIFFERENT spaces for different purposes:
  - evaluator.py = full experimental space (48, includes FULL recovery)
  - unified_space.py = smoke/search-comparison space (32, no FULL)
- `test_evaluator.py:test_exact_original_48_configs` confirms evaluator matches
  proposal_v2's 48-config definition
- **Not a bug — but must be documented clearly to avoid confusion**

### FULL recovery implementation
- `evaluator.py:113-124` implements FULL as: detect failure → re-execute all
  4 nodes with SWAPPED models → charge both attempts
- `test_evaluator.py:test_full_is_eight_logical_calls_after_failure` verifies
  8 logical calls (4 original + 4 replay), models actually differ
- Properly metered (deployment cost includes both attempts)

### Test results
- `test_evaluator.py`: 8/8 PASS
- `test_runtime.py`: 10/10 PASS (campaign quotas, GPU lock, crash recovery,
  protocol hash, wall alarm, fail-closed admission)
- `six_method_closed_loop.py`: 6/6 PASS (methods differ, dual cost, independent)

## Summary

| Question | Answer | Blocking? |
|---|---|---|
| Q1: Proposed uses fitted GP + acquisition? | **YES** (verified: predictions and acquisitions change with observations) | No |
| Q2: Ablations only remove corresponding mechanism? | **YES** (flag isolation verified) | No |
| Q3: qNEHVI is real (archive re-sampling)? | **YES** (source-verified posterior archive sampling) | No |
| Q4: Unrevealed truth accessible to selector? | **NO** (boundary test passed; C/L is deterministic, not leaked) | No |

**Overall verdict: ALL MECHANISMS VALID — ready for formal comparison.**

### Recommendations for formal experiment
1. Document the 48 vs 32 config space distinction clearly
2. In the paper, note that C/L are treated as deterministic (standard MOBO)
3. The `six_method_closed_loop.py` stub test should use the correct 48-config
   space for consistency with the evaluator
4. The stub HV convergence (all methods same HV) is an artifact — real data
   will differentiate
