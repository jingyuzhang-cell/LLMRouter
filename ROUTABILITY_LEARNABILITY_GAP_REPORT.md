# Routability–Learnability Gap: C3 → v3 → C4

This report is generated after the frozen v3 confirmatory experiment was opened. It is a research conclusion and stopping decision, not a new confirmatory claim.

## Outcome

The five-model pool remains meaningfully routable in hindsight, but neither tested request-time router learns enough of that gap to improve reliably over the fold-local best single model.

| Stage | Role | Gap recovery | P(ΔUtility > 0) | Router failure | Best-single failure | Decision |
|---|---|---:|---:|---:|---:|---|
| C3 selective advantage | 419-task nested-OOF development | 18.59% | see frozen C3 result | 18.62% | 19.57% | Development signal only |
| Frozen C3 on v3 | 120-task independent confirmation | -19.85% | 17.28% | 19.17% | 16.67% | Confirmatory fail |
| C4 capability × requirement | 419-task nested-OOF development | 0.95% | 56.38% | 20.53% | 19.57% | Development fail |

The development oracle gap is about 0.0603 Utility and the v3 oracle gap is about 0.0450, so model complementarity exists. The failure is learnability and transportability, not absence of oracle headroom.

## Integrity qualifications

1. Response recovery continued through round 8 without a retry cap frozen in advance. Four GLM repeat keys still returned empty answers and were retained as real provider failures. They must not be replaced after unblinding.
2. The C3 feature schema forbids gold-answer access, but the implementation reads `gold_answer` to construct answer-type features. This makes C3 non-deployable as written and is a material protocol-implementation discrepancy.
3. C4 uses only request-time question, context, and table content. It does not use gold answers, derivations, evidence annotations, model outcomes, dataset IDs, task-type IDs, or v3 outcomes.
4. All uncertainty resampling in v3 and C4 uses task as the sampling unit, keeping model and repeat outcomes paired within a task.

## Stopping decision

Do not tune Pairwise, Safety Veto, λ, LCB thresholds, embeddings, or add a sixth model on these outcomes. C4 has now tested the predeclared response to a v3 Utility failure and did not pass its development gate.

The defensible next research claim is a Routability–Learnability Gap: oracle complementarity exists, but the available sample size and observable task features do not support a transportable switching policy. Any future router should begin with new development data and must be confirmed on a new, untouched v4 holdout. The existing v3 set may be used only for labeled diagnostics, never again as a confirmatory set.
