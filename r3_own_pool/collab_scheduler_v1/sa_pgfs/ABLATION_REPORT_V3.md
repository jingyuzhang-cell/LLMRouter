# Ablation v3: State-specific vs cross-state training (zero LLM calls)

Fixes v2's critical feature-label misalignment bug; uses regression-tested
HV, unified normalization, separate RNGs, exact two-sided p-values with
Holm-Bonferroni correction. 200 paired seeds.

## Protocol boundary (MUST be stated in paper)

This is a SUPPLEMENTARY experiment using the old RBF GP (ls=1.0), n0=3,
budget=14 (full space) — NOT the replay v2 main protocol (sklearn GP,
n0=2, budget=8). It tests training-data-source effects, not state-feature
on/off effects. Normalization uses offline full-cube ranges (not deployable).

## Results (v3, feature-label alignment verified by unit test)

| state | arm | AUC-HV | 95% CI |
|---|---|---|---|
| s_clean | **state_aware** | **0.9682** | [0.919, 1.000] |
| s_clean | blind_equal | 0.9581 | [0.851, 1.000] |
| s_clean | blind_pooled | 0.9571 | [0.832, 1.000] |
| s_fault30 | state_aware | 0.8974 | [0.723, 0.989] |
| s_fault30 | **blind_equal** | **0.9294** | [0.779, 0.989] |
| s_fault30 | blind_pooled | 0.9319 | [0.797, 0.985] |

## Pairwise tests (two-sided, 10k permutations, Holm-corrected)

| comparison | diff | p_raw | p_Holm |
|---|---|---|---|
| clean: aware vs equal | +0.0101 | 0.0002 | **0.0012** |
| clean: aware vs pooled | +0.0111 | 0.0002 | **0.0012** |
| clean: equal vs pooled | +0.0010 | 0.6822 | 0.7676 |
| fault: aware vs equal | −0.0320 | 0.0002 | **0.0012** |
| fault: aware vs pooled | −0.0345 | 0.0002 | **0.0012** |
| fault: equal vs pooled | −0.0025 | 0.3838 | 0.7676 |

## Definitive conclusion (after bug fix, split persists)

- **s_clean: state-specific training significantly better** (+1.0-1.1pp,
  p_Holm=0.0012). Cross-state Q observations bias the surrogate downward
  under clean (fault Q values are systematically lower).

- **s_fault30: cross-state training significantly better** (+3.2-3.5pp,
  p_Holm=0.0012). Clean-state observations provide structural prior
  (config-quality ordering) that few fault-only observations cannot.

- **blind_equal ≈ blind_pooled in both states** (n.s.): the volume
  difference (n vs 2n) doesn't matter; what matters is WHICH state's
  labels dominate the training mix.

## v2 bug impact (documented)

v2's blind_equal had feature-label misalignment: indices were shuffled
for labels but not features, so the GP learned wrong config→Q mappings.
The fix narrowed the clean-state gap (+3.1pp → +1.0pp) and reversed the
fault-state blind_equal ranking (0.943 → 0.929), but the directional
split persists. v2 numbers are invalid; v3 is authoritative.

## Paper-ready statement

> State-specific surrogate training significantly improves search efficiency
> under the clean state (p_Holm=0.001) but significantly degrades it under
> the fault state (p_Holm=0.001). The asymmetry arises from data properties
> of this benchmark: clean-state Q observations carry structural prior useful
> for fault-state search, while fault-state Q observations are downward-biased
> noise for clean-state search. State-conditioned training is beneficial when
> cross-state observations would pollute the surrogate, but cross-state
> pooling is preferable when the other state's observations are informative
> despite the state mismatch. The outcome-level motivation for state-
> conditioned scheduling (collaborative fronts change across states, Fig F1)
> remains unambiguous and is the stronger argument.
