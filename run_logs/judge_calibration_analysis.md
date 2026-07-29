# Judge Calibration Analysis

Snapshot: 1200 successful runs (final completed snapshot)

## Threshold sensitivity
- 0.10: 588 (49.00%)
- 0.15: 501 (41.75%)
- 0.20: 425 (35.42%)
- 0.25: 375 (31.25%)
- 0.30: 355 (29.58%)
- 0.35: 333 (27.75%)
- 0.40: 307 (25.58%)
- 0.45: 249 (20.75%)
- 0.50: 239 (19.92%)

## Judge parsing
- qwen-plus: 894/900 (99.33%)
- glm-5.2: 3/601 (0.50%)
- qwen-turbo: 601/601 (100.00%)
- deepseek-chat: 900/900 (100.00%)

## Objective calibration
- Pearson: 0.5972
- MAE: 0.185
- Judge minus objective bias: 0.0569

## Recommendation
- store raw failed judge text after the frozen run
- repair GLM reasoning/content JSON extraction
- report result-level coverage separately from attempt parse rate
- report sensitivity at thresholds 0.20/0.25/0.30/0.35
- do not describe GLM as a successful judge in the current run
