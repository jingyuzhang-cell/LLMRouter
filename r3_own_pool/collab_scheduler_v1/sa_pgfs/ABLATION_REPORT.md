# ⚠️ V1 RESULTS INVALID — see ABLATION_STATE_V2 and corrected report below ⚠️

> **This v1 ablation used the broken `compute_hv` from `replay.py` (z-descending
> scan that skips z≤prev_z points) and per-state normalization. The numbers
> below are not valid evidence.** The corrected version
> (`ablation_state_v2.py` → `ABLATION_STATE_V2.json`) uses the
> regression-tested `sa_pgfs_v1.pareto.hypervolume`, unified normalization,
> a 3-arm design, and two-sided tests.

---

# Ablation: State-aware vs State-blind SA-PGFS (zero LLM calls, 2026-09-30) [V1 — INVALID]

Pre-frozen supplementary protocol; does NOT alter the main results.

## Design

Both arms use identical EHVI acquisition, identical structural features,
identical n_0=3 initial design per seed, same budget t=3..14, |G_collab|=14.
The ONLY difference:
- **State-aware**: surrogate trained on current-state observations only
- **State-blind**: surrogate trained on observations from BOTH states pooled
  (2× training data — the generous interpretation of "no state information")

200 paired replay seeds; paired sign-permutation test (10k permutations).

## Results

| state | arm | AUC-HV | N95 | paired test |
|---|---|---|---|---|
| s_clean | state-aware | **0.832** | 7.6 | — |
| s_clean | state-blind | 0.787 | 9.0 | **aware better, p=0.0001** |
| s_fault30 | state-aware | 0.887 | 6.3 | — |
| s_fault30 | state-blind | **0.899** | 5.9 | blind better (n.s., p=1.00) |

## Interpretation (honest, split result)

- **Under s_clean, state-conditioning significantly improves search**
  (+4.4pp AUC, p=0.0001). The clean-state surrogate benefits from NOT being
  polluted by fault-state observations — the objectives differ enough that
  cross-state transfer hurts.

- **Under s_fault30, state-blind is slightly better but NOT significantly**
  (−1.2pp, p=1.00). Pooling extra clean-state observations provides a mild
  data-volume benefit that offsets the state-mismatch cost, but the effect
  is not statistically distinguishable from zero.

- **Net reading**: state-conditioning helps where objectives are MOST
  state-sensitive (clean vs fault shifts Q by ~6-8pp), and is neutral where
  the extra data compensates. The claim should be scoped as:

  > State-aware surrogate training significantly improves search efficiency
  > under the clean state (where cross-state transfer is harmful); under the
  > fault state, the advantage is not statistically significant. State-
  > conditioning is beneficial overall but not uniformly across states.

## Paper positioning

This ablation provides moderate (not overwhelming) support for the
state-conditioning design choice. Report as a supplementary ablation, not
a headline finding. The stronger motivation for state-conditioning remains
the Reference Cube's demonstration that the collaborative Pareto front
changes across states (Fig F1), which is an outcome-level argument rather
than a search-efficiency argument.
