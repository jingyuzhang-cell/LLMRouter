# E2 cross-repeat stable oracle (utility-400, leave-one-repeat-out, zero generation)

| quantity | EQ |
|---|---|
| BestSingle | 0.7240 |
| QueryOnlyRidge | 0.7350 |
| Hindsight Oracle (5-repeat mean max) | 0.8100 |
| **CrossRepeatStableOracle** | **0.7745** |
| StableOracle (fractional ties) | 0.7530 |

Hindsight gap 8.60pp; stable gap 5.05pp (59% of hindsight; 41% is generation noise).

Stable vs BestSingle: +5.05pp, CI95 [3.05, 7.15]
Stable vs QueryOnlyRidge: +3.95pp, CI95 [2.15, 5.9]

Winner consistency: 5/5 on 339 queries, 4/5 on 52, <=3/5 on 9. Ties at the top 4-repeat mean occurred in 59% of rotations.

Answers: A=58.7% stable; B=stable heterogeneity; C=True

Selection never sees its judged repeat; bootstrap unit is the query. Development panel; no population claim.
