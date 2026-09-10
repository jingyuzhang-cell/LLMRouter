# Effective Gap and Tie-Aware Decision

Scope: frozen original-train objective subset only. Validation and test labels were not loaded.

## Effective Gap

Baseline is dataset-best on the same frozen OOF folds.

| delta | opportunity n | opportunity rate | conditional oracle gap |
|---:|---:|---:|---:|
| 0.0 | 170 | 5.71% | 100.00 pp |
| 0.05 | 170 | 5.71% | 100.00 pp |
| 0.1 | 170 | 5.71% | 100.00 pp |

## Tie-Aware Grid

| policy | quality | quality delta | cost saving | latency delta | routing small/medium/large/reasoning |
|---|---:|---:|---:|---:|---|
| query_ridge_argmax | 87.193% | +0.067 pp | -1.53% | -7886.7 ms | 0.0/0.1/25.6/74.3 |
| tieaware_eps0.0 | 87.193% | +0.067 pp | -1.53% | -7886.7 ms | 0.0/0.1/25.6/74.3 |
| tieaware_eps0.005 | 87.126% | +0.000 pp | 1.92% | -11969.0 ms | 0.0/0.9/33.8/65.3 |
| tieaware_eps0.01 | 87.092% | -0.034 pp | 4.87% | -14917.2 ms | 0.0/2.2/39.9/57.8 |
| tieaware_eps0.02 | 86.924% | -0.202 pp | 12.43% | -25064.1 ms | 0.0/10.0/43.4/46.6 |
| tieaware_eps0.05 | 85.748% | -1.378 pp | 32.00% | -55700.6 ms | 2.9/40.6/22.7/33.8 |
| tieaware_eps0.1 | 82.689% | -4.437 pp | 46.02% | -77884.1 ms | 40.1/16.2/18.6/25.2 |
| tieaware_eps0.2 | 75.160% | -11.966 pp | 88.50% | -128347.6 ms | 55.6/34.1/10.4/0.0 |

No epsilon selected on these evaluation outcomes; this grid is descriptive development evidence.

## Large vs Reasoning Effective Pair Gap

| delta | stable n | stable rate | reasoning win rate when stable | pair oracle gain vs cheaper | near tie rate |
|---:|---:|---:|---:|---:|---:|
| 0.0 | 377 | 12.67% | 67.37% | 67.37 pp | 87.33% |
| 0.05 | 377 | 12.67% | 67.37% | 67.37 pp | 87.33% |
| 0.1 | 377 | 12.67% | 67.37% | 67.37 pp | 87.33% |

Interpretation: tie-aware routing is the right decision-layer change when most apparent winner gaps are ties. Repeat-stability labels remain necessary before treating pairwise stable edges as paper-grade training targets.
