# RouterBench subset reproduction: PASS

Completed settings: 9/9. Cascade Routing exceeds both baselines in 9 settings. Overall gate requires at least 5/9 joint wins.

| Dataset | Models | Train/Test | Routing AUC | Cascade AUC | Cascade Routing AUC | Joint gate |
|---|---:|---:|---:|---:|---:|---|
| gsm8k | 3 | 372/7078 | 0.647197 | 0.661975 | 0.664741 | PASS |
| gsm8k | 5 | 372/7078 | 0.659612 | 0.671477 | 0.677404 | PASS |
| gsm8k | 11 | 372/7078 | 0.670273 | 0.679662 | 0.694902 | PASS |
| mmlu | 3 | 702/13340 | 0.828799 | 0.842333 | 0.856819 | PASS |
| mmlu | 5 | 702/13340 | 0.845812 | 0.858692 | 0.887034 | PASS |
| mmlu | 11 | 702/13340 | 0.871392 | 0.877991 | 0.924347 | PASS |
| mbpp | 3 | 21/406 | 0.755077 | 0.730161 | 0.792712 | PASS |
| mbpp | 5 | 21/406 | 0.779386 | 0.758814 | 0.825546 | PASS |
| mbpp | 11 | 21/406 | 0.816140 | 0.797871 | 0.847895 | PASS |

## Interpretation and limits
The GSM8K three-model smoke passed before the extension was launched. Algorithms, optimization strategies, noise, and split settings were not retuned. Each dataset is filtered before the original 5%/95% split (seed 42). NumPy and upstream Hyperopt seeds are 0. Models and options follow the official scripts/main.sh and scripts/routerbench.py.
Quality/cost estimators use noisy ground truth as in upstream RouterBench simulations, including held-out labels for constructing the simulated estimators. The budget grid also uses held-out single-model aggregates. These results do not establish deployable predictor performance.
The official Hugging Face zero-shot file was SHA-256 verified and converted to CSV without reordering or imputation. Byte identity with the CSV in the authors separate archive has not been established. These subset results must not be equated with the full-benchmark scores quoted in the brief.
AUC uses the unmodified upstream integration. Total cost is replayed benchmark cost summed across all executed model calls, not money spent in this run. Normalized cost divides mean realized cost by the highest held-out single-model mean cost in the pool. Static is selected by training quality and reported as a point; Oracle is a quality upper bound. Their undefined AUC/cost fields remain blank.
One seed only: numerical superiority is not a claim of statistical significance. Small MBPP training set (21 examples) is retained without adjustment. No model API calls were made; the runtime blocks socket connections.
Environment deviations: Python 3.12 venv rather than suggested Python 3.11 Conda; same-release PyTorch CPU build; unused CUDA/triton, xgboost, and tokencost omitted. See REPRO_ENVIRONMENT.json and requirements-resolved.txt.

## Artifacts
Per-setting results, exact row indices, raw upstream per-sample outputs, and logs are under runs/. Smoke artifacts are preserved under runs/gsm8k_3/. REPRO_RESULTS.csv provides per-curve-point quality, total/normalized cost, AUC, test sample count and seeds.

## Sources
- https://github.com/eth-sri/cascade-routing
- https://github.com/withmartian/routerbench
- https://huggingface.co/datasets/withmartian/routerbench/tree/784021482c3f320c6619ed4b3bb3b41a21424fcb
