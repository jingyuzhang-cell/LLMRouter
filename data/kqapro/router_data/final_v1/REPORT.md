# KQAPro five-model final_v1 report

- Aligned tasks: 11761
- Long rows: 58805
- Split: train 8232, validation 1764, test 1765
- Full-set oracle accuracy: 86.81%
- All models wrong: 1551

## Per-model metrics

| Model | Accuracy | Unique correct | Mean latency (s) | P95 latency (s) | Mean tokens |
|---|---:|---:|---:|---:|---:|
| qwen-3b-local | 43.54% | 163 | 0.181 | 0.193 | 166.3 |
| deepseek | 60.56% | 213 | 0.925 | 1.179 | 152.7 |
| qwen | 58.42% | 180 | 0.763 | 1.045 | 182.3 |
| gemini | 75.38% | 1087 | 1.698 | 2.304 | 163.3 |
| zhipu | 50.08% | 154 | 1.080 | 2.179 | 156.0 |

## Router test evaluation

- Selected latency penalty: 0.01
- Validation accuracy: 71.37%
- Test accuracy: 70.03%
- Test mean latency: 1.201s
- Best always-one test accuracy: 75.47%
- Test oracle accuracy: 86.80%
- Selection counts: {'gemini': 934, 'deepseek': 226, 'qwen-3b-local': 261, 'qwen': 166, 'zhipu': 178}

cost_proxy is 0.5 for all aligned rows/models and is non-informative; latency and token counts are used.
