# Adaptive Failure Benchmark — Results

Panel: frozen 4-node DAG, 120 TAT-QA arithmetic table-text tasks. All calls real (identical (model,prompt) pairs reused at temperature 0; faulted calls overridden by definition).
Failure model: capability fault on (task, node, planned model) — same-model retry/re-execution reproduces the fault; only model switching can repair. Fixed seed 20260923.

## Clean scenario

| Method | Accuracy | tokens/task | calls | latency s |
|---|---:|---:|---:|---:|
| Router (single large) | 0.5500 | 603 | 120 | 0.53 |
| Static DAG | 0.3500 | 1503 | 480 | 4.63 |
| Dynamic DAG | 0.4000 | 2324 | 789 | 6.69 |

Reference rows (corrected arms): dynamic-ideal 0.4250 (gold-driven triggers, not deployable); static-with-fallback 0.3917.

## Failure scenario (core table)

| Failure | Method | Acc | Degradation | Recovery | tokens/task | cost + | latency s |
|---|---|---:|---:|---:|---:|---:|---:|
| 10% | Router | 0.4833 | +12.1% | 0% (0/12) | 652 | +8.2% | 0.56 |
| 10% | Static | 0.3167 | +9.5% | 17% (2/12) | 1500 | -0.2% | 4.66 |
| 10% | Dynamic | 0.4083 | -2.1% | 50% (6/12) | 2171 | -6.6% | 6.57 |
| 20% | Router | 0.4250 | +22.7% | 0% (0/24) | 723 | +20.1% | 0.60 |
| 20% | Static | 0.2917 | +16.7% | 12% (3/24) | 1491 | -0.8% | 4.65 |
| 20% | Dynamic | 0.4083 | -2.1% | 42% (10/24) | 2191 | -5.7% | 6.62 |
| 30% | Router | 0.3500 | +36.4% | 0% (0/36) | 783 | +30.0% | 0.66 |
| 30% | Static | 0.2667 | +23.8% | 17% (6/36) | 1487 | -1.1% | 4.68 |
| 30% | Dynamic | 0.4083 | -2.1% | 44% (16/36) | 2224 | -4.3% | 6.68 |

## Budget scenario (post-hoc violations vs static-realized reference)

| Method | clean 1.0x / 1.2x / 1.5x | fault20 1.0x / 1.2x / 1.5x | max ratio (clean/fault20) |
|---|---|---|---|
| router | 0% / 0% / 0% | 0% / 0% / 0% | 0.41 / 0.74 |
| static | 0% / 0% / 0% | 0% / 0% / 0% | 0.86 / 0.86 |
| dynamic | 5% / 0% / 0% | 4% / 1% / 0% | 1.16 / 1.23 |

Figures: robustness_curve.png (paper core), pareto.png.

Reading (honest): the single-model Router dominates the clean scenario in both quality and cost (the DAG pipeline pays decomposition/interface losses on this panel). The Dynamic DAG's value is robustness: accuracy is flat under injected capability faults while the Router degrades linearly (its retry cannot repair a capability fault) and Static degrades with no repair mechanism. Degradation and recovery-rate columns quantify this; the crossover point is visible in the curve.
