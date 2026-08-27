# Phase C3 Development Report

Status: **C3_DEVELOPMENT_PASS**

The 90-task C2 diagnostic set was excluded. Nested OOF used 419 development tasks, with no external API calls.

| Method | Utility | Gap recovery | P(ΔU>0) | Failure | High-risk failure |
|---|---:|---:|---:|---:|---:|
| best_single | 0.794792 | 0.00% | 0.00% | 19.57% | 28.00% |
| global_pairwise_c2 | 0.796652 | 3.09% | 62.03% | 26.01% | 46.29% |
| advantage_ridge | 0.814322 | 32.41% | 100.00% | 18.85% | 33.71% |
| noise_aware_advantage | 0.810981 | 26.86% | 99.91% | 19.33% | 34.86% |
| selective_advantage | 0.805994 | 18.59% | 99.77% | 18.62% | 30.29% |
| oracle | 0.855052 | 100.00% | 100.00% | 12.17% | 25.14% |

Development gate: {"oof_gap_recovery_above_0": true, "bootstrap_probability_ge_0.90": true, "failure_within_best_plus_0.02": true}
