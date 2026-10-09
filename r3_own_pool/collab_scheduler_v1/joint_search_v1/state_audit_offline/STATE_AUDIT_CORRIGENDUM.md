# Corrigendum: State-Feature Audit Report Clarifications (2026-10-09)

Supersedes interpretive claims in STATE_ABLATION_AUDIT.json. Raw computational results unchanged.

## 1. Session names are OBSERVATION DATA SOURCES, not mechanism provenance

The three audited sessions (official_qnehvi_same_state, scalarized_bo, proposed_without_state)
provided **frozen observations** (config/state/Q tuples). The with_state/without_state
comparison was constructed by this audit using those observations — it does NOT prove
that the original sessions' production selectors used the corresponding mechanism.
The original sessions ran their own selector logic; this audit re-trains independent
GPs on their observation data.

## 2. V1 check for without_state column: clarification

The V1 checks (state_changes_predictions, features_differ, state_bit_present) verify
that **when a state feature is present in the input, it enters the GP and changes
predictions**. They do NOT verify the production without_state selector's internals.
The audit's without_state arm masks the state bit to 0 — this is the audit's
construction, not a verified property of the original without_state session.

**Correct framing**: "an independently trained GP with a 6th-dim state bit
produces different predictions than one with the bit masked to 0" — mechanism
diagnostic only.

## 3. Ablation isolation: additional consistency checks needed

Sharing kernel/seed/candidates is necessary but not sufficient. The following
must also be confirmed identical between arms (not yet verified in v1 audit):
- Cost prediction function (incremental cost divisor)
- Normalization scales (Q/C/L frozen ranges)
- Acquisition function (EHVI vs EI — same formula)
- MC sampling settings (n_samples, sampler type)
- Reference point for HV computation

Current audit uses only GP posterior means (no acquisition function), so
acquisition/MC/ref-point consistency is UNTESTED.

## 4. "State-sensitive" should report magnitudes, not just PASS

Should report: score change distribution (mean/std/range), Spearman rank
correlation between with/without state rankings, and whether the top-1
candidate changes. Current report only shows prediction_diff_range.

## Classification

This audit remains a **mechanism diagnostic**. It answers:
  "Can a GP with a state feature produce different predictions than one without?"
    → Yes (verified with quantified prediction differences)

It does NOT answer:
  "Did the production selectors use the state feature as designed?"
    → Not verified (would need runtime logging of actual feature vectors)
  "Does state-awareness improve search efficiency?"
    → That is the running campaign's job
  "Is the production without_state selector truly state-blind?"
    → Not verified (would need code inspection or runtime feature dumps)

## 4. Closure — v2 audit run with programmatic isolation (final)

`STATE_AUDIT_V2.json` supersedes the v1 PASS-list framing. All four review
points are implemented in the machine-readable report:

- Every session is labeled "(OBSERVATION DATA SOURCE — not mechanism
  provenance)" and carries `produces_no_claim_about: production selector
  internals or mechanism use`. The with/without-state comparison is an
  independent re-training on frozen observations.
- `without_state_bit_semantics` recorded explicitly: the state bit exists in
  the public input but is masked to a CONSTANT 0.0 column in the without_state
  proxy — no state information enters it; this masking is the audit's
  construction.
- Isolation is runtime-verified, not asserted: same candidates in order, same
  cost function (audit-local identical-for-both-arms table, explicitly NOT the
  production predictor), 6-vs-6 feature dims, bit-only difference across ALL
  candidates and ALL training rows, identical recorded GP settings (kernel /
  normalize_y / restarts / seed via a single shared code path), identical
  normalization scales, shared posterior-mean acquisition, no MC sampling.
- Sensitivity is quantified per source: prediction-diff mean/max, Spearman
  rho (+p), top-1 identity change, top-5 overlap. Headline numbers:
  proposed_without_state obs rho=0.827 with top-1 CHANGE (most state-sensitive);
  official_qnehvi rho=0.992 top-1 same; wo_incremental_cost rho=1.000;
  scalarized rho=0.937.

Positioning unchanged: mechanism diagnostic only; algorithm-efficiency claims
await the campaign's measured comparison on common physical budget.

## 5. Final naming and interpretation guards (review)

- Final name: **冻结观测上的状态输入敏感性诊断** (state-input sensitivity
  diagnostic on frozen observations) — not production algorithm acceptance.
- A top-1 change on a source means the audit's re-trained STATE-AWARE proxy
  differs from the masked proxy; it is NOT state leakage in the state-removed
  arm (the bit is constant-0 there by construction).
- rho=1.000 means ranking unchanged only, never identical predictions; read
  with pred_diff (wo_incremental_cost: rho=1.000, pred_diff mean 0.0098 /
  max 0.0884).
- Scope guard: audit-local cost table + posterior-mean acquisition CANNOT
  replace production EHVI/cost-predictor ablation evidence. Auxiliary
  diagnostic; efficiency conclusions rest on post-campaign reconciled curves
  on the common measured physical budget.

## 6. Erratum — the "qNEHVI top-1 changed" discrepancy (final entry; diagnostic closed)

Commit 2c7f8fc's MESSAGE claimed "top1 changes in qNEHVI session
(medium_large_medium_coder vs medium_large_large_coder_LOCAL)". Both committed
JSON versions (2c7f8fc and 2107963) are byte-identical on this point and were
all along:

- official_qnehvi_same_state_20261009: top1_same = TRUE, rho = 0.9917,
  input_sha256 = d10eb6d7ab2432ac, n_obs = 24.
- The quoted top-1 pair (medium__large__medium__coder vs
  medium__large__large__coder__LOCAL) belongs to the
  proposed_without_state_20261009 observation source
  (input_sha256 = a9e050cee4203ce2, n_obs = 24, top1_same = FALSE,
  rho = 0.8274).

The discrepancy was a commit-message misattribution, not a data or code
change: no input hash or comparison basis differed between versions. The
diagnostic is closed with this entry; no further versions.
