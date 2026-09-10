# R3 v2 routing evaluation

Role: development; n_test=750.

| Method (quality preference) | Quality | Utility gain | GRR |
|---|---:|---:|---:|
| RandomExpected | 0.776567 | -0.072633 | -0.8336 |
| BestSingle | 0.849200 | +0.000000 | 0.0000 |
| ZeroMixture | 0.849200 | +0.000000 | 0.0000 |
| Oracle | 0.936333 | +0.087133 | 1.0000 |
| Ridge | 0.848933 | -0.000267 | -0.0031 |
| MLPReward | 0.817200 | -0.032000 | -0.3673 |
| KNN | 0.835067 | -0.014133 | -0.1622 |
| Hybrid_alpha0 | 0.815400 | -0.033800 | -0.3879 |
| NoModelEmbedding_alpha0 | 0.812533 | -0.036667 | -0.4208 |
| Hybrid | 0.814533 | -0.034667 | -0.3979 |
| NoModelEmbedding | 0.827733 | -0.021467 | -0.2464 |
| MLPWinner | 0.754067 | -0.095133 | -1.0918 |
| MLPWinnerTieAware | 0.831200 | -0.018000 | -0.2066 |
| RankingOnly | 0.846133 | -0.003067 | -0.0352 |

Constrained policies were selected on validation before test. See RESULTS.json for paired intervals, all preferences, and source strata.

- Finite grid, not complete Pareto frontier
- Fixed-seed conditional query bootstrap; not training variance or simultaneous intervals
- Transformer baseline not yet implemented; no claim of complete main-paper comparison
- Current features are fixed-model-pool; no unseen-model or held-out-source claim
- Conditional resource means, no latency SLO guarantee; encoder/dispatch overhead excluded
