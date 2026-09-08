# Phase 1: official router baselines (Random / KNN / MLP)

Protocol: frozen R1 reproduction setting - official `routerbench_0shot.pkl`, 5/95 split (seed 42),
9 settings = {gsm8k, mbpp, mmlu} x {3, 5, 11}-model pools. Routers: official `KNNRouter` / `MLPRouter`
(unmodified, official defaults, `all-MiniLM-L6-v2` embeddings), Random = uniform over pool (seed 0).
AUC = upstream `auc_all` over the official 32-point willingness-to-pay grid (same definition as R1).
quality/mean_cost for KNN & MLP are taken at the max-quality point of their curve;
Random / Best Single / Oracle are single operating points (no AUC). `Routing LogReg (R1)` is the frozen
R1 LogisticRegression router, shown for reference. Full curves in ROUTER_BASELINE_CURVES.csv.

## gsm8k / 3-model pool

| Method | AUC | Quality | Mean cost |
|---|---|---|---|
| Random | - | 0.5917 | 0.003024 |
| KNN (official) | 0.6298 | 0.6591 | 0.008542 |
| MLP (official) | 0.6298 | 0.6591 | 0.008542 |
| Best Single (train selected) | - | 0.6591 | 0.008542 |
| Routing LogReg (R1 frozen) | 0.6472 | - | - |
| Oracle (per-query hindsight) | - | 0.7158 | - |

## gsm8k / 5-model pool

| Method | AUC | Quality | Mean cost |
|---|---|---|---|
| Random | - | 0.5874 | 0.003119 |
| KNN (official) | 0.6387 | 0.6622 | 0.006043 |
| MLP (official) | 0.6387 | 0.6622 | 0.006043 |
| Best Single (train selected) | - | 0.6622 | 0.006043 |
| Routing LogReg (R1 frozen) | 0.6596 | - | - |
| Oracle (per-query hindsight) | - | 0.7352 | - |

## gsm8k / 11-model pool

| Method | AUC | Quality | Mean cost |
|---|---|---|---|
| Random | - | 0.5590 | 0.002001 |
| KNN (official) | 0.6446 | 0.6622 | 0.006043 |
| MLP (official) | 0.6446 | 0.6622 | 0.006043 |
| Best Single (train selected) | - | 0.6622 | 0.006043 |
| Routing LogReg (R1 frozen) | 0.6703 | - | - |
| Oracle (per-query hindsight) | - | 0.7494 | - |

## mbpp / 3-model pool

| Method | AUC | Quality | Mean cost |
|---|---|---|---|
| Random | - | 0.6502 | 0.003135 |
| KNN (official) | 0.6699 | 0.6872 | 0.009433 |
| MLP (official) | 0.6448 | 0.6552 | 0.005829 |
| Best Single (train selected) | - | 0.6872 | 0.009433 |
| Routing LogReg (R1 frozen) | 0.7551 | - | - |
| Oracle (per-query hindsight) | - | 0.8054 | - |

## mbpp / 5-model pool

| Method | AUC | Quality | Mean cost |
|---|---|---|---|
| Random | - | 0.5714 | 0.003237 |
| KNN (official) | 0.6678 | 0.6872 | 0.009433 |
| MLP (official) | 0.6233 | 0.6429 | 0.005759 |
| Best Single (train selected) | - | 0.6872 | 0.009433 |
| Routing LogReg (R1 frozen) | 0.7794 | - | - |
| Oracle (per-query hindsight) | - | 0.8424 | - |

## mbpp / 11-model pool

| Method | AUC | Quality | Mean cost |
|---|---|---|---|
| Random | - | 0.5517 | 0.002073 |
| KNN (official) | 0.6668 | 0.6872 | 0.009433 |
| MLP (official) | 0.6108 | 0.6355 | 0.004771 |
| Best Single (train selected) | - | 0.6872 | 0.009433 |
| Routing LogReg (R1 frozen) | 0.8161 | - | - |
| Oracle (per-query hindsight) | - | 0.8695 | - |

## mmlu / 3-model pool

| Method | AUC | Quality | Mean cost |
|---|---|---|---|
| Random | - | 0.7012 | 0.000546 |
| KNN (official) | 0.7242 | 0.8095 | 0.001402 |
| MLP (official) | 0.7204 | 0.7496 | 0.000837 |
| Best Single (train selected) | - | 0.8120 | 0.001430 |
| Routing LogReg (R1 frozen) | 0.8288 | - | - |
| Oracle (per-query hindsight) | - | 0.8837 | - |

## mmlu / 5-model pool

| Method | AUC | Quality | Mean cost |
|---|---|---|---|
| Random | - | 0.6341 | 0.000571 |
| KNN (official) | 0.7183 | 0.8095 | 0.001402 |
| MLP (official) | 0.6835 | 0.7197 | 0.000849 |
| Best Single (train selected) | - | 0.8120 | 0.001430 |
| Routing LogReg (R1 frozen) | 0.8458 | - | - |
| Oracle (per-query hindsight) | - | 0.9226 | - |

## mmlu / 11-model pool

| Method | AUC | Quality | Mean cost |
|---|---|---|---|
| Random | - | 0.4897 | 0.000411 |
| KNN (official) | 0.7219 | 0.8080 | 0.001387 |
| MLP (official) | 0.6655 | 0.6942 | 0.000727 |
| Best Single (train selected) | - | 0.8120 | 0.001430 |
| Routing LogReg (R1 frozen) | 0.8714 | - | - |
| Oracle (per-query hindsight) | - | 0.9546 | - |

## Notes

- KNN `n_neighbors=50` capped to n_train where the frozen 5/95 split has <50 train samples (mbpp: 21); modern sklearn raises where older sklearn auto-capped.
- Train sizes under the frozen split: mbpp 21, gsm8k 372, mmlu 702 - a deliberately low-signal regime; KNN largely collapses toward Best Single, MLP retains per-prompt routing.
- On gsm8k both KNN and MLP hit every single-model anchor across the WTP grid, so their deduplicated cost-quality curves (and AUCs) coincide; the underlying per-WTP decisions still differ (see curves CSV).
- New code: RandomRouter + this harness. Upstream router classes, data, splits, AUC implementation unmodified.
