# Existing Router Failure Analysis

Step-1 deliverable (paper Motivation / Related-Work evidence). Consolidates three runs on the
frozen R2A binary protocol (math500 / mbpp / mmlupro; Fin-R1 vs cogito-v1-preview-llama-8B;
seed42 0.8 prompt split; gte-Qwen2-7B-instruct 3584-d embeddings; 0 inference API calls):

- R2B symptom run: `run_r2b_neural_baselines.py` -> `r2b_neural_baselines/`
- R2C cause diagnosis: `run_r2c_failure_diagnosis.py` -> `r2c_failure_diagnosis/DIAGNOSIS.json`
- R2D train-construction ablation: `run_r2d_train_ablation.py` -> `r2d_train_ablation/`

## 1. Symptom (R2B, frozen protocol)

| dataset | Best Single | KNNRouter | MLPRouter | Oracle | MLP train acc |
|---|---|---|---|---|---|
| math500 | 0.6800 | 0.6800 | 0.6800 | 0.7400 | 1.000 |
| mbpp    | 0.6667 | 0.6667 | **0.6462** | 0.7026 | 1.000 |
| mmlupro | 0.5400 | 0.5400 | **0.5350** | 0.6400 | 1.000 |

Query-embedding routers never beat Best Single on accuracy; MLP fits train perfectly
(overfit) yet adds nothing on test. Oracle gap (6.0 / 3.6 / 10.0 pts) is real.

## 2. Cause A (largest, newly isolated): the training set drops all ties

The frozen train file is built by the official RouteLLM adaptor with
`include_ties=False` (`LLMRouterBench/baselines/adaptors/routellm_adaptor.py:151`)
because matrix-factorization training consumes preference pairs only. Consequences:

- train has ZERO ties; test is 68-73% ties (`train tie frac 0.00 vs test informative
  frac 0.27/0.28/0.32`);
- class balance inflated to 92% / 77% / 63% majority -> constant prediction is
  train-optimal, which is exactly what KNN/MLP/LogReg all collapse to;
- minority class starved: 10 / 53 / 83 informative minority examples.

**Ablation fix (R2D)**: rebuild the full split (same loader config, same 0.8/seed42;
+54/+89/+573 tie prompts recovered; test set gated identical; Best Single/Oracle gates
3/3 PASS) and rerun the SAME official algorithms:

| dataset | method | acc | cost ($) | vs Best Single |
|---|---|---|---|---|
| math500 | MLP (full train) | 0.6800 | 0.0000904 | **equal acc, 20% cheaper -> Pareto-dominates** |
| math500 | RewardMLP lam=1e6 | 0.6800 | 0.0000893 | equal acc, 21% cheaper |
| mmlupro | KNN (full train) | 0.5550 | 0.0000203 | **+1.5 pts acc** (3 queries, nominal) |
| mmlupro | RewardMLP lam=1e8 | 0.5450 | 0.0000005 | **+0.5 pt acc at ~zero cost -> dominates on both axes** |
| mbpp    | MLP (full train) | 0.6103 | 0.0000544 | still below Best Single |

Restoring ties alone flips the conclusion on 2 of 3 tasks: dynamic routing >= static on
the cost axis immediately (ties are free to route to the cheap model), and nominally on
accuracy for mmlupro. mbpp stays unrecovered -> a residual, representation-bound gap.

Side observation: thresholded probability routing is fragile — a logistic P(strong>weak)
on the full train compresses to the weak model on math500/mbpp (acc equals always-weak),
while per-model score regression degrades gracefully and wins via the reward sweep.

## 3. Cause B: the prize is small and localized

Binary scores => oracle headroom == minority-only-win fraction (6/100, 7/195, 20/200
queries). Recovering it means identifying exactly those queries; everything else is
accuracy-invariant tie traffic. With n_test <= 200 a 3-query swing is 1.5 pts — claims
need McNemar-style caution at this scale.

## 4. Cause C: the query embedding barely encodes the winner (or even the outcome)

- Informative-subset separability (train->CV): AUC 0.34-0.61 vs majority baseline
  (math minority n=10 is degenerate; mbpp 0.54-0.56; mmlupro 0.61).
- Pooled representation probe (train+test CV): winner AUC 0.537 / 0.608 / 0.625.
- kNN local winner consistency at k=5/10/25: at or barely above majority baseline.
- Idealized probabilistic router (oracle-thresholded CV probabilities): gap recovery
  0% / 0% / 15%.
- Control: 4-class outcome (difficulty) prediction shows ~no linear lift either
  (0.606 vs 0.606; 0.531 vs 0.531; 0.447 vs 0.440) — within-task, the gte embedding
  carries little supervised signal about outcome OR winner at this data scale.

This is the binding constraint that Cause-A repair does not remove: the accuracy-side
oracle gap is not reachable from the query embedding alone (consistent with the frozen
R2A linear-probe finding, probe AUC 0.63/0.73/0.64 on the informative task).

## 5. Cause D: the objective was not the binding constraint — but the reward form matters

Even an oracle-thresholded probabilistic router recovers ~0 of the accuracy gap (D5), so
switching classification->ranking alone cannot fix accuracy on this data. But per-model
score regression + `reward = pred_score - lam * cost` is precisely what unlocks the
cost-axis wins in R2D: it makes tie traffic routable to the free model without breaking
accuracy. For the own-pool dataset this argues for recording latency and using
`reward = quality - lambda*cost - mu*latency` with a Pareto sweep, not a fixed argmax.

## 6. Design implications for the Multi-objective Adaptive Router

1. Never drop ties at train time; train per-model score regression (reward form).
2. Expect the first wins on the cost/latency axis (tie-aware routing), not accuracy.
3. The accuracy-side oracle gap needs signal beyond the raw query embedding:
   model-conditioned features (query x model interaction) and/or task decomposition.
4. Prefer regression + lambda-swept Pareto selection over thresholded classification
   (probability compression is real and silently collapses to one model).
5. Next data collection must record latency (absent in all official artifacts here)
   and use graded quality scores (binary scores cap the headroom at minority-only wins).

## Artifacts

- r2b_neural_baselines/{RESULTS.csv,TABLE.md,RUN.json}  (symptom, gated)
- r2c_failure_diagnosis/{DIAGNOSIS.json,tsne_*.png}      (causes B/C/D)
- r2d_train_ablation/{RESULTS.csv,RUN.json}              (cause A fix, gated)
- All runs offline; test sets and Best Single/Oracle gates reproduce the frozen
  R2A closure (r2a_local/STATIC_VS_DYNAMIC.json) exactly.
