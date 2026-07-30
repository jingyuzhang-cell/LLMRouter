# E5 + KQAPro program safe router

- Validation Gemini baseline: 75.28%
- Selected policy: no nontrivial strategy met validation safety; fallback always Gemini
- Validation candidate accuracy: 75.28%
- Validation downgrades/rescues/harms: 0/0/0
- Test Gemini baseline: 75.47%
- Test candidate accuracy: 75.47%
- Test downgrades/rescues/harms: 0/0/0
- Candidate accepted: False
- Production policy: always_gemini
- Test oracle: 86.80%

## Calibrated correctness models

| Model | Val AUC | Test AUC | Test Brier |
|---|---:|---:|---:|
| qwen-3b-local | 0.738 | 0.722 | 0.210 |
| deepseek | 0.741 | 0.756 | 0.194 |
| qwen | 0.740 | 0.760 | 0.195 |
| gemini | 0.827 | 0.808 | 0.139 |
| zhipu | 0.768 | 0.744 | 0.205 |

## Fine-threshold safety audit

- Validation candidate: 75.57%, 18 downgrades, 6 rescues, 1 harm.
- Test candidate: 75.47%, 25 downgrades, 6 rescues, 6 harms.
- 3x-harm-weighted test utility: -12.
- Decision: rejected; production remains always_gemini.
