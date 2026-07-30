# KQAPro five-model final_v2 report

- Frozen common tasks: 11786
- Long rows: 58930
- Split: train 8250, validation 1768, test 1768
- Oracle accuracy: 86.76%
- All models wrong: 1560

## Per-model metrics

| Model | Accuracy | Unique correct | Mean latency (s) | P95 latency (s) | Mean tokens | Est. API cost* |
|---|---:|---:|---:|---:|---:|---:|
| qwen-3b-local | 43.67% | 160 | 0.180 | 0.193 | 166.4 | 0.000000 |
| deepseek | 60.54% | 214 | 0.925 | 1.179 | 152.7 | 0.259904 |
| qwen | 58.39% | 180 | 0.763 | 1.045 | 182.3 | 0.923128 |
| gemini | 75.34% | 1087 | 1.699 | 2.305 | 163.4 | 0.147070 |
| zhipu | 50.08% | 154 | 1.080 | 2.181 | 156.0 | 0.319146 |

* Estimated from configured per-million-token rates. Provider currencies/rate cards may differ; do not sum across providers as one currency. Recorded `cost_proxy` is also retained in the data.

## Excluded task IDs

kqapro-val-01505, kqapro-val-02049, kqapro-val-04027, kqapro-val-04692, kqapro-val-04989, kqapro-val-06852, kqapro-val-08438, kqapro-val-09685, kqapro-val-09929, kqapro-val-10805, kqapro-val-11070
