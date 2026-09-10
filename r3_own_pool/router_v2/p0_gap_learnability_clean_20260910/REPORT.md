# P0 Gap Learnability Diagnostics

Scope: frozen original-train objective subset only. Validation and test labels were not loaded.

## P0-1 Winner Stability

- Objective subset n=2975: unique winner 7.19%, multi-winner 92.81%, mean winner-set size 3.465.
- Objective pair labels are strict for 16.68% of model pairs; the rest are ties.
- Available repeated judge grades: 9 repeated response keys, 3 changed labels, 0 complete query-level attempt pairs.
- Judge component proxy: label change 36.87%, best-slot set changed 56.72% on 67 complete open-ended queries.

## P0-2 Task-Level vs Query-Level

| policy | quality | gap recovery | gain vs dataset-best |
|---|---:|---:|---:|
| task_type_best | 87.126% | 1.73% | +0.000 pp |
| dataset_best | 87.126% | 1.73% | +0.000 pp |
| query_ridge | 87.193% | 2.89% | +0.067 pp |

Query Ridge agrees with dataset-best on 71.23% of queries; on 856 changed decisions, wins and losses each account for 3.15% when labels differ, so net gain is +0.067 pp.

## P0-3 Pairwise Ranking

| policy | quality | gap recovery | gain vs dataset-best | changed from dataset-best |
|---|---:|---:|---:|---:|
| pairwise_query_seed42 | 87.160% | 2.31% | +0.034 pp | 18.62% |
| pairwise_query_seed43 | 86.958% | -1.16% | -0.168 pp | 43.26% |
| pairwise_query_seed44 | 87.160% | 2.31% | +0.034 pp | 24.34% |

Large-vs-reasoning pair, query model:

| seed | strict n | ties | positive rate | accuracy | AUC |
|---:|---:|---:|---:|---:|---:|
| 42 | 377 | 2598 | 32.63% | 70.29% | 0.695 |
| 43 | 377 | 2598 | 32.63% | 66.31% | 0.662 |
| 44 | 377 | 2598 | 32.63% | 68.70% | 0.696 |

Interpretation: if pairwise query routing does not beat dataset-best, the current train evidence still says most recoverable signal is coarse task/domain signal. If large-vs-reasoning pair AUC is meaningfully above 0.5, MA should focus on that edge with additional independent repeats or stronger compatibility features.
