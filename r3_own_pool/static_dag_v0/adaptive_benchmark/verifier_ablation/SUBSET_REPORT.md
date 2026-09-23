# Hard-Subset Evaluation & Dynamic+Verifier Ablation

Split (pre-execution, frozen): Easy = 1 operator (74 tasks); Hard = >=2 operators (46 tasks).

## Clean scenario per subset

| Method | overall | easy | hard |
|---|---:|---:|---:|
| router | 0.5500 | 0.7027 | 0.3043 |
| static | 0.3500 | 0.4324 | 0.2174 |
| dynamic | 0.4000 | 0.4595 | 0.3043 |
| dynamic_verifier | 0.4000 | 0.4595 | 0.3043 |

## Fault scenarios per subset (accuracy)

| Scenario | Method | overall | easy | hard |
|---|---|---:|---:|---:|
| fault 20% | router | 0.4250 | 0.5811 | 0.1739 |
| fault 20% | static | 0.2917 | 0.4054 | 0.1087 |
| fault 20% | dynamic | 0.4083 | 0.5000 | 0.2609 |
| fault 30% | router | 0.3500 | 0.4730 | 0.1522 |
| fault 30% | static | 0.2667 | 0.3649 | 0.1087 |
| fault 30% | dynamic | 0.4083 | 0.4865 | 0.2826 |

## Dynamic + Verifier ablation (clean)

| Method | Accuracy | tokens/task | latency s |
|---|---:|---:|---:|
| static | 0.3500 | 1503 | 4.63 |
| dynamic | 0.4000 | 2324 | 6.69 |
| dynamic_verifier | 0.4000 | 2727 | 7.06 |

DV vs Dynamic paired: dQ=0.0, help/harm=1/1, McNemar p=1.0.
Verifier signal stats: {"fired": 34, "both_exec": 104, "correct_initial": 34, "wrong_initial": 71, "new_fired": 28}.
DV extra calls vs Dynamic: 146.
