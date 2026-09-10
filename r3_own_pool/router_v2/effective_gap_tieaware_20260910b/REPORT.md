# Effective Gap and Tie-Aware Decision

Scope: frozen original-train objective subset only. Validation and test labels were not loaded.

## Effective Gap

Baseline is dataset-best on the same frozen OOF folds.

| delta | opportunity n | opportunity rate | conditional oracle gap |
|---:|---:|---:|---:|
| 0.0 | 224 | 7.53% | 100.00 pp |
| 0.05 | 224 | 7.53% | 100.00 pp |
| 0.1 | 224 | 7.53% | 100.00 pp |

## Tie-Aware Grid

| policy | quality | quality delta | cost saving | latency delta | routing small/medium/large/reasoning |
|---|---:|---:|---:|---:|---|
| query_ridge_argmax | 84.739% | +0.000 pp | -0.61% | +1012.5 ms | 0.0/0.2/56.9/43.0 |
| tieaware_eps0.0 | 84.739% | +0.000 pp | -0.61% | +1012.5 ms | 0.0/0.2/56.9/43.0 |
| tieaware_eps0.005 | 84.840% | +0.101 pp | 2.25% | -699.6 ms | 0.0/1.0/62.1/36.9 |
| tieaware_eps0.01 | 84.739% | +0.000 pp | 4.57% | -1677.1 ms | 0.0/2.5/65.1/32.4 |
| tieaware_eps0.02 | 84.639% | -0.101 pp | 9.27% | -3823.7 ms | 0.0/9.8/62.3/27.9 |
| tieaware_eps0.05 | 83.361% | -1.378 pp | 26.90% | -11640.0 ms | 1.6/46.5/30.1/21.8 |
| tieaware_eps0.1 | 78.588% | -6.151 pp | 69.70% | -45105.3 ms | 32.2/42.1/22.0/3.7 |
| tieaware_eps0.2 | 75.059% | -9.681 pp | 87.66% | -56140.8 ms | 52.5/47.1/0.4/0.0 |

Selected exploratory policy under max quality loss 0.50 pp: `tieaware_eps0.02`.

## Large vs Reasoning Effective Pair Gap

| delta | stable n | stable rate | reasoning win rate when stable | pair oracle gain vs cheaper | near tie rate |
|---:|---:|---:|---:|---:|---:|
| 0.0 | 458 | 15.39% | 50.22% | 49.78 pp | 84.61% |
| 0.05 | 458 | 15.39% | 50.22% | 49.78 pp | 84.61% |
| 0.1 | 458 | 15.39% | 50.22% | 49.78 pp | 84.61% |

Interpretation: tie-aware routing is the right decision-layer change when most apparent winner gaps are ties. Repeat-stability labels remain necessary before treating pairwise stable edges as paper-grade training targets.
