# E2.2-A0 Expert Summary

Status: **RETROSPECTIVE_DEVELOPMENT**  
Decision: **STOP_E2_2**  
New provider/API calls: **0**

E2.1-A remains a confirmatory failure. This analysis is retrospective development only.

## Leakage-controlled OOF result

- Anchor: `deepseek`
- Grouping: company (258 groups; 5 outer folds)
- Selective gain: 0.0001
- Grouped bootstrap 95% CI: [-0.0098, 0.0103]
- Coverage: 0.153 (55 switches)
- Harmful-switch rate: 0.21818181818181817
- Harmful-switch 95% Wilson UCB: 0.3437028664047817
- Opportunity prevalence: 0.233
- Opportunity AUPRC: 0.297
- Advantage Spearman: 0.016
- Oracle-gap recovery: 0.0010656041512231375
- Matched-random mean gain: -0.0019
- Mean cost delta: $0.003181 per task
- Mean latency delta: 0.344s per task

## Interpretation

The frozen A0 GO rule was applied once to fully out-of-fold predictions. A GO result only authorizes prospective design; it is not confirmatory evidence. A STOP result ends E2.2 without retrospective threshold rescue.
