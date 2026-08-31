# Stable Routability and Response-Aware Cascade Audit

## Evidence status

- C3 is exploratory and leakage-contaminated because its implementation reads `gold_answer` despite the frozen schema prohibiting it. C3 metrics are not confirmatory evidence.
- v3 remains the one-time C3 confirmation and failed. It is not used to train or select C5/C6.
- C4 is the clean task-only development result and recovered only 0.95% of the oracle gap.
- C5 and C6 are development analyses on the 419-task pool. Neither is an independent confirmation.

## C5: stable routability exists

Cross-repeat selection shows an observed oracle gap of 6.36pp and a replicable oracle gap of 4.84pp. The stable component is 76.1% of the observed gap; the remaining 1.52pp is noise-induced headroom. The stable-gap 95% task-bootstrap interval is 3.87–5.87pp.

Winner labels are nevertheless noisy: 63.5% of tasks have the same winner in all three repeats, while 33.9% have top1/top2 margin-to-noise SNR below one.

The training-only reduced-pool audit selects Qwen-plus as anchor and DeepSeek plus Gemini as the strongest two-specialist pool, with 3.95pp cross-repeat stable gain. GLM contributes the weakest single-specialist gain and also has known provider failures, but C5 does not remove it from any prior experiment.

## C6: failure detection is not sufficient for escalation

The first response-aware cascade predicts whether a Qwen-plus answer fails, then escalates to a fold-local specialist. It uses 1,257 existing anchor responses, keeps all repeats of a task in one OOF fold, uses no gold/evidence annotations, and makes no API calls.

It fails all development gates: Utility decreases by 1.34pp, overall Failure increases from 19.49% to 31.26%, and high-risk Failure increases from 27.81% to 56.76%. Verifier failure recall is 56.7%, but escalation precision is only 32.9%.

The scientific conclusion is narrower than “response-aware routing fails”: the label `Anchor Failure` is not aligned with the action `switch to this specialist`. Future work must estimate specialist-specific improvement and catastrophic-switch risk from response evidence. No C6 threshold is retuned after seeing these results, and no v4 confirmation is collected for the failed method.
