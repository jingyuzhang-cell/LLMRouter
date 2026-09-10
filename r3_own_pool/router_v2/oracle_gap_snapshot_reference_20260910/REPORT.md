# Oracle Gap And Winner Distribution

Scope: original train split only. Missing and infrastructure-failure labels are excluded, not converted to zero.

## Overall

- complete queries: 2867
- best single: reasoning (87.91%)
- oracle quality: 93.33%
- mean gap: 5.42 pp
- median gap: 0.00 pp
- p90 gap: 0.00 pp
- nonzero opportunity queries: 6.17%

## Dataset Gap

| dataset | n | missing | local best | oracle | mean gap | median | p90 | nonzero |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| arenahard | 67 | 458 | large | 95.22% | 4.40 pp | 0.00 pp | 10.00 pp | 38.81% |
| gsm8k | 1479 | 0 | large | 98.04% | 2.50 pp | 0.00 pp | 0.00 pp | 2.50% |
| humaneval | 115 | 0 | reasoning | 97.39% | 2.61 pp | 0.00 pp | 0.00 pp | 2.61% |
| mbpp | 631 | 51 | reasoning | 92.87% | 4.28 pp | 0.00 pp | 0.00 pp | 4.28% |
| mmlupro | 575 | 124 | reasoning | 80.70% | 14.26 pp | 0.00 pp | 100.00 pp | 14.26% |

## Winner Distribution

Strict counts exclude ties. Fractional rates split tied winners equally.

| scope | unique winner | small | medium | large | reasoning | large+reasoning |
|---|---:|---:|---:|---:|---:|---:|
| overall | 7.32% | 20.74% | 23.67% | 25.87% | 29.73% | 55.60% |
| arenahard | 35.82% | 15.55% | 26.24% | 26.74% | 31.47% | 58.21% |
| gsm8k | 1.15% | 23.22% | 24.85% | 25.90% | 26.03% | 51.93% |
| humaneval | 6.96% | 18.70% | 23.77% | 24.20% | 33.33% | 57.54% |
| mbpp | 12.36% | 17.84% | 21.20% | 24.26% | 36.70% | 60.96% |
| mmlupro | 14.43% | 18.54% | 23.00% | 27.78% | 30.68% | 58.46% |

## Large Vs Reasoning

| scope | strict n | ties | large wins among strict | reasoning wins among strict | tie rate |
|---|---:|---:|---:|---:|---:|
| overall | 374 | 2493 | 33.69% | 66.31% | 86.96% |
| arenahard | 34 | 33 | 47.06% | 52.94% | 49.25% |
| gsm8k | 59 | 1420 | 52.54% | 47.46% | 96.01% |
| humaneval | 17 | 98 | 0.00% | 100.00% | 85.22% |
| mbpp | 135 | 496 | 16.30% | 83.70% | 78.61% |
| mmlupro | 129 | 446 | 44.19% | 55.81% | 77.57% |

Interpretation: routing is worth studying when the mean gap is material after cleaning. The hard part is not whether an oracle opportunity exists, but whether stable query-level compatibility labels can recover it without creating extra wrong switches.
