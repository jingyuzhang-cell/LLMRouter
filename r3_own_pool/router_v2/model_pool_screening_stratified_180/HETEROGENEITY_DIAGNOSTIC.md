# Six-Model Heterogeneity Diagnostic 180

This is a diagnostic screening panel only: 60 MMLU-Pro, 60 GSM8K, 30 HumanEval, 30 MBPP from the train split. It is not Router training data and not final test data.

## Routing Feasibility Table

| Dataset | n | BestSingle | Best Acc | Oracle Acc | Oracle Gap | Winner Entropy | Unique Winner Ratio | Mean Model Corr |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| overall | 180 | reasoning | 85.00% | 93.33% | 8.33pp | 0.976 | 6.11% | 0.439 |
| knowledge | 60 | reasoning | 70.00% | 86.67% | 16.67pp | 0.964 | 13.33% | 0.443 |
| math | 60 | large | 96.67% | 100.00% | 3.33pp | 0.998 | 0.00% | 0.232 |
| code | 60 | reasoning | 90.00% | 93.33% | 3.33pp | 0.924 | 5.00% | 0.351 |

## Model Accuracy By Dataset

| Dataset | small | medium | large | coder | math | reasoning |
|---|---:|---:|---:|---:|---:|---:|
| overall | 47.22% | 76.11% | 77.78% | 71.11% | 54.44% | 85.00% |
| knowledge | 30.00% | 60.00% | 63.33% | 48.33% | 48.33% | 70.00% |
| math | 80.00% | 95.00% | 96.67% | 90.00% | 95.00% | 95.00% |
| code | 31.67% | 73.33% | 73.33% | 75.00% | 20.00% | 90.00% |

## Unique Winners

| Dataset | small | medium | large | coder | math | reasoning |
|---|---:|---:|---:|---:|---:|---:|
| overall | 0 | 3 | 1 | 0 | 0 | 7 |
| knowledge | 0 | 2 | 1 | 0 | 0 | 5 |
| math | 0 | 0 | 0 | 0 | 0 | 0 |
| code | 0 | 1 | 0 | 0 | 0 | 2 |

## Immediate Decision

Proceed to final-pool freezing and then train QueryOnly vs Model-Aware Router on this heterogeneous pool.

## Caveats

- Local small/coder/math were rerun with knowledge max_new_tokens=1024 after the original 256-token run caused systematic truncation on knowledge questions.
- Math still has several knowledge parse failures from very long answers; this affects knowledge-domain Math accuracy more than the math-domain conclusion.
- Medium/large/reasoning are reused legacy full-cohort rows per the frozen screening protocol.
