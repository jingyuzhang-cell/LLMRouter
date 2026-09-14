# E1 capability upper bound (utility-400 frozen folds, zero generation)

Oracle EQ 0.8100; BestSingle EQ 0.7240; gap 8.60pp

| method | EQ | gap recovery % | regret pp | selection |
|---|---|---|---|---|
| BestSingle | 0.7240 | 0.0 | 8.60 | reasoning:400
| QueryOnlyRidge | 0.7350 | 12.8 | 7.50 | medium:1, large:53, reasoning:346
| CapabilityLookupPure | 0.7080 | -18.6 | 10.20 | large:105, reasoning:295
| CapabilityLookupShrunk | 0.7170 | -8.1 | 9.30 | large:54, reasoning:346
| PairwiseRidge | 0.7350 | 12.8 | 7.50 | medium:1, large:53, reasoning:346
| TwoStageResidualGate | 0.7190 | -5.8 | 9.10 | large:56, reasoning:344
| RepeatPairwiseMA_3seed | 0.7235 | -0.6 | 8.65 | medium:1, large:24, reasoning:375

CapabilityLookupShrunk vs QueryOnlyRidge: -1.80pp pooled (switched 60, rescued 8, harmed 21, CI95 [-3.2, -0.5])

Verdict: {'beats_queryonly_point': False, 'beats_queryonly_ci': False, 'beats_bestsingle_point': False}

Development panel (opportunity-enriched); no population-level MMLU-Pro claim. Subjects from frozen prompts; capability estimated on development folds only.
