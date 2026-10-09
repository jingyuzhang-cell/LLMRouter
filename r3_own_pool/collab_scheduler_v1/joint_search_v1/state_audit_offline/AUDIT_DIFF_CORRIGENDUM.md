# Audit v1 vs v2 Differences: Corrigendum & Final Close-out (2026-10-09)

## 1. Check item count difference (10 vs 9): different categories, not omissions

v1 checked **mechanism properties** (does state change predictions? are features different?):
  v1_state_changes_predictions, v1_features_differ, v1_state_bit_present,
  v2_with_state_sensitive, v2_without_state_stable,
  v3_same_kernel, v3_same_seed, v3_same_candidates,
  v4_v21_canonical_present, v4_v1_reference_present

v2 checked **isolation properties** (are both arms identical except state bit?):
  isolation_same_candidates_in_order, isolation_same_costs_same_function,
  isolation_feat_dims_match_6v6, isolation_only_diff_is_state_bit_all_candidates,
  isolation_training_rows_bit_only, isolation_same_norm_scales,
  isolation_shared_acquisition_path, isolation_no_mc_sampling,
  isolation_same_gp_settings_recorded

The two sets are **complementary, not contradictory**. v2 replaced v1's coarse
"same kernel/seed" with finer-grained per-candidate isolation checks.

## 2. Top-1 change attribution: my summary was wrong, not the data

Raw JSON shows:
- **qNEHVI session**: top-1 SAME in both v1 (rank 0=0) and v2 (top1_same=True)
- **proposed_without_state session**: top-1 DIFFERENT in v2 (top1_same=False)
  - with_state top-1: `medium__large__medium__coder__`
  - without_state top-1: `medium__large__large__coder__LOCAL`
- **scalarized_bo session**: top-1 SAME in both versions

My earlier summary incorrectly attributed the without_state session's top-1
change to the qNEHVI session. The JSON data is consistent between v1 and v2
for all three sessions.

## 3. Units: 0.033 prediction difference = 3.3 percentage points on Q∈[0,1] scale

Not "3.3% improvement" — this is an absolute prediction difference, not a
relative change. Similarly, Spearman p-value measures within-session rank
correlation, not cross-task statistical significance.

## 4. Supported conclusion (final wording)

"Across independently re-trained surrogate models on frozen observation data,
the state input feature changes GP predictions by up to 7.9 percentage points
and can alter the top-ranked candidate for some observation sets. Ablation
isolation is verified: both arms share identical candidates, costs, feature
dimensions, normalization, and GP settings; the only difference is the state
bit value."

This does NOT prove:
- Production selectors used the mechanism as designed
- State-awareness improves search efficiency (that is the running campaign)
- The effect generalizes across tasks or panels

## Close-out

Both v1 and v2 audit reports are retained as-is (no overwriting).
STATE_ABLATION_AUDIT.json = mechanism diagnostic (v1 framing).
STATE_AUDIT_V2.json = quantified sensitivity + isolation (v2 framing).
This corrigendum reconciles the two. No further diagnostic versions needed.
