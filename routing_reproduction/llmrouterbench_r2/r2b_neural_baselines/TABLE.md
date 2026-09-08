# Phase 1: neural router baselines - can a simple neural router beat Best Single?

Frozen R2A binary protocol: math500 / mbpp / mmlupro, pool Fin-R1 vs cogito-v1-preview-llama-8B,
seed42 0.8 split, gte-Qwen2-7B-instruct 3584-dim L2-normalized embeddings. 0 API calls.
Validation gate: Best Single and Oracle reproduce r2a_local/STATIC_VS_DYNAMIC.json exactly (3/3 PASS).
Latency: NOT RECORDED in the frozen official data -> N/A (own-pool collection must record it).

## math500 (n_test=100)

| Method | Accuracy | Cost ($) | Latency |
|---|---|---|---|
| Random | 0.6200 | 0.0000729 | N/A |
| Best Single | 0.6800 | 0.0001134 | N/A |
| KNNRouter | 0.6800 | 0.0001134 | N/A |
| MLPRouter | 0.6800 | 0.0001115 | N/A |
| Oracle | 0.7400 | - | N/A |

## mbpp (n_test=195)

| Method | Accuracy | Cost ($) | Latency |
|---|---|---|---|
| Random | 0.5385 | 0.0000413 | N/A |
| Best Single | 0.6667 | 0.0000924 | N/A |
| KNNRouter | 0.6667 | 0.0000924 | N/A |
| MLPRouter | 0.6462 | 0.0000770 | N/A |
| Oracle | 0.7026 | - | N/A |

## mmlupro (n_test=200)

| Method | Accuracy | Cost ($) | Latency |
|---|---|---|---|
| Random | 0.4750 | 0.0001044 | N/A |
| Best Single | 0.5400 | 0.0000000 | N/A |
| KNNRouter | 0.5400 | 0.0000003 | N/A |
| MLPRouter | 0.5350 | 0.0000441 | N/A |
| Oracle | 0.6400 | - | N/A |

## Step-1 oracle-gap context (test winner stats)

| dataset | a-only wins | b-only wins | both right | both wrong | headroom source |
|---|---|---|---|---|---|
| math500 | 21 | 6 | 47 | 26 | mostly strong-model-only |
| mbpp | 48 | 7 | 82 | 58 | mostly strong-model-only |
| mmlupro | 20 | 44 | 64 | 72 | mostly weak-model-only |

## Headline answer

**No.** KNNRouter ties Best Single on all 3 tasks (collapses to the majority model);
MLPRouter ties on math500 but is BELOW Best Single on mbpp (0.646 vs 0.667) and mmlupro
(0.535 vs 0.540). MLP train accuracy = 1.000 on all tasks (126-231 train samples, 3584-dim
inputs) - pure overfit; per-prompt decisions are rare and net-negative. Oracle headroom
(0.06-0.10) is real but not recoverable by query-embedding -> model-id classification,
consistent with the R2A linear-probe finding (probe AUC 0.63-0.73, MF recovery 0%).
Next step per plan: reward-prediction router (predict per-model score under
quality - lambda*cost - mu*latency) + Pareto selection, on an own-pool dataset with latency recorded.
