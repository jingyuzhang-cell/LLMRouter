# JOINT_VERIFY_OUTCOME_INTERPRETATION_PREREG — interpretation rules frozen BEFORE the confirmatory data exist

Written at `dc3c5a6` (pre-registration): the 60-task confirmatory run
has NOT executed; no P3 task results have been viewed. This file
pre-commits the interpretation of every outcome pattern so that no
post-hoc spin is possible regardless of what the data show. It
completes the pre-registration discipline (design frozen → analysis
frozen → INTERPRETATION frozen).

## Primary contrast: ΔR = R_DD − R_SS (R_conditional, service-latency T)

| outcome | committed interpretation |
|---|---|
| mean > 0, sign-flip p ≤ .05 | "Under injected D3_r faults and natural failures, the joint dynamic mechanism (DD) produced a statistically demonstrable conditional recovery net benefit over the fixed static recipe (SS) on this panel, under service-latency accounting." Scope: service-latency mechanism comparison; NO end-to-end wall claim; this panel/tier mix only. |
| mean > 0, p > .05 | "Directionally positive; failed to demonstrate superiority at n=60. No benefit claim. Reported with CI." |
| mean ≈ 0 (CI excludes practically meaningful ±δ, δ=0.05 pre-set) | "No detectable net difference. NOT equivalence (only failure to detect)." |
| mean < 0 | "The joint mechanism underperformed the static recipe on this panel — a NEGATIVE result, reported with the same prominence as a positive one, with the mechanism breakdown (§DegradeFunnel) as the primary explanation-seeking analysis." |

## Interaction I = DD − DS − SD + SS

- I > 0 significant: "the two dynamic dimensions compose more than
  additively on this panel" — scoped, not generalized.
- I not significant: **"interaction NOT ESTABLISHED at n=60"** — never
  "no interaction exists" (the design is underpowered for I; §power
  table: n≈71 needed at Δ=0.10).
- I < 0 significant: "dimensions substitute rather than complement"
  — reported as-is.

## Secondary contrasts

- DD−DS (value of dynamic π on top of dynamic Z) and DD−SD (value of
  dynamic Z on top of dynamic π): same verdict language as primary;
  each is a SINGLE-dimension claim, never pooled with the interaction.

## Mechanism breakdown (pre-committed, runs regardless of outcome)

- **Degrade funnel per arm**: degradation rate + binding constraint
  (q_min / on-time / budget) from the persisted decision rows. If
  DD/DS/SD degrade on most faulted tasks, the honest headline is
  "the mechanism mostly declines recovery under its declared beliefs;
  net-benefit contrasts then measure decline-vs-blind-retry, which is
  itself an answer to when NOT to recover."
- **Prediction–realization gap**: predicted q̂/p_on vs realized
  Q/T per executed action (ex-ante rows exist); quantifies the
  predictor-mismatch tax on the mechanism's decisions.
- **Cost anatomy**: incremental tokens by node/action type per arm;
  switch counts/walls (reported, outside the primary T).

## NONE and MONO (fixed roles)

- NONE: floor. If NONE ≥ some recovery arm on R_conditional, that is
  a finding ("recovery not worth it under these conditions"), stated
  as such.
- MONO: descriptive single-model baseline ONLY; excluded from the
  same-fault causal contrasts (no r-node; D3_r not equivalent).
  Any MONO comparison appears in a separate table, labeled.

## Forbidden interpretations (regardless of outcome)

1. Claiming end-to-end wall-latency net benefit (T is service-time by
   frozen convention).
2. Generalizing beyond this panel/domain/tier mix or to complex DAGs.
3. Reading non-significance as equivalence or as "no interaction".
4. Using the 3 micro-pilot tasks or any prior-round data to augment
   the confirmatory estimates.
5. Post-hoc weight/threshold/multiplier adjustment motivated by the
   observed direction (any such change = new frozen version + new
   authorization).
6. Selecting favorable subsets (faulted-only, tier-only) for the
   primary claim; subset analyses are exploratory and labeled.

## Pre-set analysis constants

δ (practical-zero half-width) = 0.05 R-units; sign-flip B=100,000
(seed 20261105); bootstrap B=10,000 (seed 20261106); α=0.05 one-sided
for directional contrasts; the six pre-registered contrasts (primary +
2 secondary + interaction + 2 vs-NONE) reported with NO multiplicity
adjustment for the primary, Holm across the secondary family
(family = {DD−DS, DD−SD, I}).

**Frozen before data. Any deviation discovered after unblinding is a
protocol violation to be reported, not corrected.**
