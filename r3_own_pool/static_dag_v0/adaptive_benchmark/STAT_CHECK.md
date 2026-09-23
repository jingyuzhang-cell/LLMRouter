# Pre-submission statistical check

Method: paired task bootstrap CI (seed 20260918, B=10000) + McNemar exact, recomputed from frozen artifacts.

## Headline comparisons

| Comparison | n | dQ | CI | help/harm | McNemar p |
|---|---:|---:|---|---:|---:|
| clean: router vs static | 120 | +0.2000 | [+0.1250, +0.2833] | 26/2 | 3e-06 |
| clean: router vs dynamic | 120 | +0.1500 | [+0.0750, +0.2333] | 22/4 | 0.000534 |
| clean: dynamic vs static | 120 | +0.0500 | [+0.0000, +0.1000] | 8/2 | 0.109375 |
| clean easy: dynamic vs static | 74 | +0.0270 | [-0.0405, +0.0946] | 4/2 | 0.6875 |
| clean hard: dynamic vs static | 46 | +0.0870 | [+0.0217, +0.1739] | 4/0 | 0.125 |
| clean hard: dynamic vs router | 46 | +0.0000 | [-0.0652, +0.0652] | 1/1 | 1.0 |
| fault10: dynamic vs router | 120 | -0.0750 | [-0.1667, +0.0167] | 11/20 | 0.149613 |
| fault10: dynamic vs static | 120 | +0.0917 | [+0.0417, +0.1417] | 11/0 | 0.000977 |
| fault10 hard: dynamic vs router | 46 | +0.0000 | [-0.0870, +0.0870] | 2/2 | 1.0 |
| fault20: dynamic vs router | 120 | -0.0167 | [-0.1083, +0.0750] | 15/17 | 0.86005 |
| fault20: dynamic vs static | 120 | +0.1167 | [+0.0583, +0.1750] | 14/0 | 0.000122 |
| fault20 hard: dynamic vs router | 46 | +0.0870 | [+0.0000, +0.1957] | 5/1 | 0.21875 |
| fault30: dynamic vs router | 120 | +0.0583 | [-0.0417, +0.1500] | 21/14 | 0.310505 |
| fault30: dynamic vs static | 120 | +0.1417 | [+0.0833, +0.2083] | 17/0 | 1.5e-05 |
| fault30 hard: dynamic vs router | 46 | +0.1304 | [+0.0217, +0.2391] | 7/1 | 0.070312 |
| RD vs FG (local vs full-graph) | 120 | -0.0250 | [-0.0583, +0.0000] | 0/3 | 0.25 |
| DV vs Dynamic | 120 | +0.0000 | [-0.0250, +0.0250] | 1/1 | 1.0 |

## Accuracy audit (reported vs recomputed)

| Scenario | Arm | reported | recomputed | match |
|---|---|---:|---:|---|
| clean | router | 0.55 | 0.55 | OK |
| clean | static | 0.35 | 0.35 | OK |
| clean | dynamic | 0.4 | 0.4 | OK |
| fault10 | router | 0.4833 | 0.4833 | OK |
| fault10 | static | 0.3167 | 0.3167 | OK |
| fault10 | dynamic | 0.4083 | 0.4083 | OK |
| fault20 | router | 0.425 | 0.425 | OK |
| fault20 | static | 0.2917 | 0.2917 | OK |
| fault20 | dynamic | 0.4083 | 0.4083 | OK |
| fault30 | router | 0.35 | 0.35 | OK |
| fault30 | static | 0.2667 | 0.2667 | OK |
| fault30 | dynamic | 0.4083 | 0.4083 | OK |
| corrected | static | 0.3917 | 0.3917 | OK |
| corrected | dynamic | 0.425 | 0.425 | OK |
| corrected | sm | 0.4167 | 0.4167 | OK |
| corrected | rd | 0.4 | 0.4 | OK |
| corrected | fg | 0.375 | 0.375 | OK |
| dv | dv | 0.4 | 0.4 | OK |

Problems: 0
[]
