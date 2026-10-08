# Corrected Ablation v2: State-aware vs State-blind SA-PGFS (zero LLM calls)

Fixes over v1: regression-tested `sa_pgfs_v1.pareto.hypervolume`; unified
normalization across both states (pre-determined); three arms; two-sided
paired permutation tests. 200 paired seeds, shared n_0=3, budget t=3..14.

## Three-arm design

| arm | surrogate training data | state label? | data volume |
|---|---|---|---|
| state_aware | current-state observations only | implicit (by construction) | n |
| state_blind_equal | half current-state, half other-state (shuffled, no label) | no | n (matched) |
| state_blind_pooled | ALL observations from both states | no | 2n |

## Results (corrected HV, unified normalization)

| state | arm | AUC-HV | N95 | vs state_aware |
|---|---|---|---|---|
| s_clean | **state_aware** | **0.968** | **4.2** | — |
| s_clean | state_blind_pooled | 0.957 | 4.9 | aware better, p<1e-4 |
| s_clean | state_blind_equal | 0.938 | 6.3 | aware better, p<1e-4 |
| s_fault30 | state_blind_equal | **0.943** | **4.1** | — |
| s_fault30 | state_blind_pooled | 0.932 | 4.5 | blind_equal better, p<1e-4 |
| s_fault30 | state_aware | 0.897 | 5.9 | aware WORSE, p<1e-4 |

All pairwise tests two-sided, p<1e-4 (10,000 permutations).

## Honest interpretation (split result, cleanly resolved by the fix)

- **Under s_clean, state-aware wins**: clean-state Q values are
  systematically higher than fault-state values, so mixing in fault-state
  observations biases the surrogate downward. State-conditioning protects
  the surrogate from cross-state pollution.

- **Under s_fault30, state-blind wins**: fault-state Q values are noisier
  and harder to learn from few observations. The clean-state observations
  provide a useful structural prior (which configs are intrinsically
  better) that the fault-state-only data cannot capture in 3-11
  observations. Extra data volume beats state purity here.

- **Net conclusion (paper-ready)**: state-conditioning improves search
  efficiency under the clean state but degrades it under the fault state.
  The asymmetry arises because clean-state observations are informative
  for fault-state search (structural prior), but fault-state observations
  are harmful for clean-state search (downward-biased Q). This is a
  data-asymmetry property of the current benchmark, not a general
  argument against state-conditioning — but it must be reported honestly.

- **For the paper**: report as a supplementary ablation with the split.
  The outcome-level motivation for state-conditioning (Reference Cube's
  Fig F1: collaborative fronts change across states) remains the stronger
  and unambiguous argument. This ablation shows the SEARCH-layer benefit
  is state-asymmetric and does not universally justify state-aware
  surrogate training.

## Invalid v1 note

The v1 ablation (`ablation_state.py` → `ABLATION_STATE_AWARE.json`) used
a broken hypervolume function and per-state normalization; all v1 numbers
are invalid and superseded by this corrected version.
