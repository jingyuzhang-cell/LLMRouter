# DEADLINE_RELIABILITY_PROTOCOL_V2 — revised plan (plan only; NOT started)

Revision of the §6 proposal in DEADLINE_RELIABILITY_READINESS.md per the
operator's 2026-10-12 ruling (eight required revisions). No measurement
is launched; every cap below is a PROPOSAL requiring explicit approval.

## 1. Scope: the FULL legal menu, not the planned combination

Cells measured (10 = the complete dag_closure menu): e1, e2 × {medium,
large, coder}; r × {medium, large}; v × {coder, large}. The M5-fixed
LOCAL family can reassign any closure node within its menu, so
reliability must hold for every assignable cell — measuring only the
planned r|medium / v|coder pair would validate the plan, not the action
space.

## 2. What is measured (per §2 of the ruling)

- **Service**: per-cell latency on REAL cascade prompts (upstream
  answers fed forward — e-prompt→facts→r-prompt→expr→v-prompt), not the
  node-isolated prompts of the 1200-call calibration.
- **Switches**: stop/start wall measured per ordered model pair during
  the run (append-only MODEL_SWITCH records; no extra calls).
- **Cross-task waits**: a controlled 2-task co-residency variant
  (shared serial executor) so queue time is measured, not estimated;
  task-level E2E = service + own switches + queue wait, reconciled per
  task-summary (the supplementary run showed median E2E 143 s with 125 s
  queue — deadline tiers set on service-only would ignore the dominant
  term).
- **Task-level E2E quantiles** drive this stage's D-tiers.

## 3. Fit / validation separation (hard)

Two DISJOINT frozen panels from the frozen200 remainder (excluding
evaluation, 1200-call calibration, supplementary, and any prior panels;
seeds + SHA-256 bound in a freeze file):
- **fit panel** — per-cell quantile derivation (the new latency prior);
- **validation panel** — used ONCE, exclusively for coverage evaluation;
  never consulted during fitting.
A per-cell family binding (lognormal/empirical per the frozen
distribution-protocol statistics) is derived on fit data only.

## 4. Statistical admission standard (revised per ruling §4)

- **Formal acceptance** for "declared P90 covers real P90": one-sided
  exact (Clopper–Pearson) test of H0: coverage < 0.90 at α = 0.05 —
  i.e., the 95% lower confidence bound of the empirical coverage must be
  ≥ 0.90. On-time-probability calibration analogously requires the
  realized on-time rate's lower bound to exceed the predicted p_on −
  tolerance (tolerance frozen in this protocol before any run).
- The **0.80–1.00 Wilson band is EXPLORATORY ONLY** — 80% coverage never
  certifies a 90% requirement; it flags cells for deeper sampling.
- Honest sample-size arithmetic (exact bounds): at perfect coverage
  (x=n), n = 29 certifies LB ≥ 0.90; at observed 0.95, n ≈ 110; at 0.93,
  n ≈ 200+. Therefore a **two-stage design**: screening (exploratory,
  n=30/cell) → confirmatory sizing derived from the observed screening
  coverage, executed ONLY on the validation panel.

## 5. Ex-ante predictions and the counterfactual prohibition

Every decision persists its full P0-B row set BEFORE execution
(decision_id correlation). Post-run validation compares predictions to
actuals **only for actions that actually executed**; unexecuted
candidates carry predictions and NO outcome — counterfactual outcomes
are never imputed from the chosen action's latencies.

## 6. This stage's D-tiers vs the frozen V2.3 deadlines

This protocol's D-tiers are derived from THIS measurement's own
task-level E2E quantiles (P40/P60/P80 of measured E2E, including queue)
for reliability calibration only. They are a SEPARATE object from the
frozen V2.3 confirmation D-tier rules; no tier definition, threshold, or
result transfers between the two, and neither is retrofitted to the
other.

## 7. Budget re-proposal (honest insufficiency report)

The earlier 400-request / 300K-token / 3600 s proposal is INSUFFICIENT
for full-menu + fit/validation separation + statistical admission:
- screening: 10 cells × 30 = 300 calls (fit panel) + 300 (validation
  screening overlap rules to be frozen) ≈ up to 600
- confirmatory stage: sized by screening (0 additional if screening
  fails early; up to 10 × 110 ≈ 1,100 if near-miss cells proceed)
- contention variant: 20 co-resident task pairs × 4 nodes ≈ 160
- switches: ~12 ordered-pair measurements (no model calls)
PROPOSED caps (require approval; NOT auto-raised): **1,200 requests /
600K tokens / 14,400 s**, with the confirmatory stage gated on a
separate zero-call review of screening results. If the operator caps
below this, the protocol degrades to exploratory-only status and says so
in every output.

## 8. Versioning

New artifacts only: `PRIORS_REAL_V2_latency_cascade.json` (+ its family
binding file) with independent SHA-256, derived exclusively from this
protocol's fit panel. PRIORS_REAL_V1*, the supplementary run artifacts,
and every frozen experiment file remain untouched.

## Prerequisites (admission conditions, zero-call verifiable)

1. P0-A/B/C landed (this commit series) and regression-green ✓
2. SS semantics frozen (STATIC_RECOVERY_UNAVAILABLE path verified) ✓
3. Freeze file for both panels + tiers + tolerances, hash-bound
4. Freeze-manifest extension over the tier/panel logic
5. Stub rehearsal incl. e-failure scenarios ✓ (test_m5_closure_fix)
6. PREFLIGHT_PASS at the final commit; explicit operator GO
