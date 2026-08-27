# FRAR-v2 Five-Model Experiment

## Integrity

- Training tasks: 400; frozen v2 test tasks: 140; overlap: 0.
- Models: DeepSeek, GLM, Qwen Plus, Qwen Turbo, Gemini 2.5 Flash.
- Pairwise classifiers: 10; grouping unit for CV: task.

## Main results

| Method | Quality | Failure | High-risk failure | Utility | Oracle regret | Selection change |
|---|---:|---:|---:|---:|---:|---:|
| best_single | 0.6275 | 23.10% | 54.17% | 0.6487 | 0.1086 | 0.00% |
| cost_only | 0.6070 | 26.90% | 60.00% | 0.6717 | 0.0856 | 100.00% |
| utility_only | 0.6070 | 26.90% | 60.00% | 0.6717 | 0.0856 | 100.00% |
| rank_safety | 0.6125 | 24.52% | 51.67% | 0.6716 | 0.0857 | 74.29% |
| route_pairwise | 0.7725 | 5.24% | 7.50% | 0.6945 | 0.0628 | 98.57% |
| frar_v2 | 0.7683 | 5.71% | 9.17% | 0.6926 | 0.0647 | 97.14% |
| oracle | 0.8742 | 3.81% | 5.00% | 0.7573 | 0.0000 | 93.57% |

## Conclusion

- Post-hoc test Best Single is gemini-2.5-flash (0.7795); this is diagnostic only, not used for leakage-safe selection.
- Quality Oracle is 0.8940; FRAR-v2 closes the quality gap to 0.1257.
- Pairwise CV mean AUC is 0.7870.
- Pure pairwise compatibility slightly outperforms the illustrative FRAR-v2 mixture; any weight tuning must be performed only with training CV.
