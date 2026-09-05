# Experiment Ledger

Generated: `2026-09-04T16:00:50.893915+00:00`

## Paper-critical path

1. **E2.1-A — READY_FOR_FROZEN_ANALYSIS**: 3240/3240 frozen cells are provider-successful; 0 remain unresolved.
2. **E2.1-B — BLOCKED** until E2.1-A passes its frozen gate.
3. **E2.2 Router — BLOCKED** until both E2.1-A and E2.1-B pass.

## E2.1-A matrix

| Model | Expected | Recorded | Provider success | Format valid | Unresolved |
|---|---:|---:|---:|---:|---:|
| qwen-plus | 1080 | 1080 | 1080 | 1078 | 0 |
| glm-5.2 | 1080 | 1080 | 1080 | 1080 | 0 |
| deepseek | 1080 | 1080 | 1080 | 1080 | 0 |

Raw rows: 4291; duplicate/retry rows: 1051; missing keys: 0.

## Other branches

- **C9 — CALIBRATION_ONLY_NO_FORMAL_LABELS**: formal labels created = 0; not eligible for a paper outcome claim.
- **E4.0-B-v2 — COMPLETE**: final 640 engineering audit PASS; 640 canonical outcomes, 0 missing keys, 0 active duplicate terminals, 0 terminal ceiling bindings. Collection engineering CLOSED. Judge calibration and scorer freeze remain separate; semantic scoring has not started.

## Frozen next action

run analyze_e2_1_a.py.
