# P0 Gap Learnability Diagnostics

Scope: frozen original-train objective subset only. Validation and test labels were not loaded.

## P0-1 Winner Stability

- Objective subset n=2975: unique winner 7.19%, multi-winner 92.81%, mean winner-set size 3.445.
- Objective pair labels are strict for 17.55% of model pairs; the rest are ties.
- Available repeated judge grades: 9 repeated response keys, 3 changed labels, 0 complete query-level attempt pairs.
- Judge component proxy: label change 36.87%, best-slot set changed 56.72% on 67 complete open-ended queries.

## P0-2 Task-Level vs Query-Level

| policy | quality | gap recovery | gain vs dataset-best |
|---|---:|---:|---:|
| task_type_best | 84.739% | 25.58% | +0.000 pp |
| dataset_best | 84.739% | 25.58% | +0.000 pp |
| query_ridge | 84.739% | 25.58% | +0.000 pp |

Query Ridge agrees with dataset-best on 80.47% of queries; on 581 changed decisions, wins and losses each account for 2.58% when labels differ, so net gain is +0.000 pp.

## P0-3 Pairwise Ranking

| policy | quality | gap recovery | gain vs dataset-best | changed from dataset-best |
|---|---:|---:|---:|---:|
| pairwise_query_seed42 | 84.706% | 25.25% | -0.034 pp | 0.54% |
| pairwise_query_seed43 | 84.605% | 24.25% | -0.134 pp | 14.55% |
| pairwise_query_seed44 | 84.739% | 25.58% | +0.000 pp | 8.24% |

Large-vs-reasoning pair, query model:

| seed | strict n | ties | positive rate | accuracy | AUC |
|---:|---:|---:|---:|---:|---:|
| 42 | 458 | 2517 | 49.78% | 64.41% | 0.653 |
| 43 | 458 | 2517 | 49.78% | 63.97% | 0.652 |
| 44 | 458 | 2517 | 49.78% | 64.41% | 0.665 |

Interpretation: if pairwise query routing does not beat dataset-best, the current train evidence still says most recoverable signal is coarse task/domain signal. If large-vs-reasoning pair AUC is meaningfully above 0.5, MA should focus on that edge with additional independent repeats or stronger compatibility features.
