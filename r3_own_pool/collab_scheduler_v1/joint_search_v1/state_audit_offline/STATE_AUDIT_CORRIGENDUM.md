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
