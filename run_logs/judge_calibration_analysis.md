# Judge Calibration Analysis

Snapshot: 1200 successful runs (interim only)

## Threshold sensitivity
- 0.10: 592 (49.33%)
- 0.15: 504 (42.00%)
- 0.20: 433 (36.08%)
- 0.25: 384 (32.00%)
- 0.30: 364 (30.33%)
- 0.35: 342 (28.50%)
- 0.40: 318 (26.50%)
- 0.45: 263 (21.92%)
- 0.50: 253 (21.08%)

## Judge parsing
- qwen-plus: 894/900 (99.33%)
- glm-5.2: 3/601 (0.50%)
- qwen-turbo: 601/601 (100.00%)
- deepseek-chat: 900/900 (100.00%)

## Objective calibration
- Pearson: 0.5833
- MAE: 0.1933
- Judge minus objective bias: 0.0687

## Recommendation
- store raw failed judge text after the frozen run
- repair GLM reasoning/content JSON extraction
- report result-level coverage separately from attempt parse rate
- report sensitivity at thresholds 0.20/0.25/0.30/0.35
- do not describe GLM as a successful judge in the current run
