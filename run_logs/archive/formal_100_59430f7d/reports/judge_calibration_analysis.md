# Judge Calibration Analysis

Snapshot: 388 successful runs (interim only)

## Threshold sensitivity
- 0.10: 277 (71.39%)
- 0.15: 268 (69.07%)
- 0.20: 250 (64.43%)
- 0.25: 142 (36.60%)
- 0.30: 125 (32.22%)
- 0.35: 107 (27.58%)
- 0.40: 85 (21.91%)
- 0.45: 49 (12.63%)
- 0.50: 45 (11.60%)

## Judge parsing
- qwen-plus: 289/291 (99.31%)
- glm-5.2: 1/196 (0.51%)
- qwen-turbo: 194/195 (99.49%)
- deepseek-chat: 289/289 (100.00%)

## Objective calibration
- Pearson: 0.6598
- MAE: 0.1526
- Judge minus objective bias: 0.0788

## Recommendation
- store raw failed judge text after the frozen run
- repair GLM reasoning/content JSON extraction
- report result-level coverage separately from attempt parse rate
- report sensitivity at thresholds 0.20/0.25/0.30/0.35
- do not describe GLM as a successful judge in the current run
