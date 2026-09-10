# Oracle Gap And Winner Distribution

Scope: original train split only. Missing and infrastructure-failure labels are excluded, not converted to zero.

## Overall

- complete queries: 2975
- best single: reasoning (87.03%)
- oracle quality: 92.84%
- mean gap: 5.82 pp
- median gap: 0.00 pp
- p90 gap: 0.00 pp
- nonzero opportunity queries: 5.82%

## Dataset Gap

| dataset | n | missing | local best | oracle | mean gap | median | p90 | nonzero |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| arenahard | 0 | 525 | NA | NA | NA | NA | NA | NA |
| gsm8k | 1479 | 0 | large | 98.04% | 2.50 pp | 0.00 pp | 0.00 pp | 2.50% |
| humaneval | 115 | 0 | reasoning | 97.39% | 2.61 pp | 0.00 pp | 0.00 pp | 2.61% |
| mbpp | 682 | 0 | reasoning | 92.67% | 4.11 pp | 0.00 pp | 0.00 pp | 4.11% |
| mmlupro | 699 | 0 | reasoning | 81.26% | 14.59 pp | 0.00 pp | 100.00 pp | 14.59% |

## Winner Distribution

Strict counts exclude ties. Fractional rates split tied winners equally.

| scope | unique winner | small | medium | large | reasoning | large+reasoning |
|---|---:|---:|---:|---:|---:|---:|
| overall | 7.19% | 20.79% | 23.43% | 25.89% | 29.89% | 55.78% |
| gsm8k | 1.15% | 23.22% | 24.85% | 25.90% | 26.03% | 51.93% |
| humaneval | 6.96% | 18.70% | 23.77% | 24.20% | 33.33% | 57.54% |
| mbpp | 12.17% | 17.93% | 21.22% | 24.30% | 36.55% | 60.85% |
| mmlupro | 15.16% | 18.79% | 22.51% | 27.68% | 31.02% | 58.70% |

## Large Vs Reasoning

| scope | strict n | ties | large wins among strict | reasoning wins among strict | tie rate |
|---|---:|---:|---:|---:|---:|
| overall | 377 | 2598 | 32.63% | 67.37% | 87.33% |
| gsm8k | 59 | 1420 | 52.54% | 47.46% | 96.01% |
| humaneval | 17 | 98 | 0.00% | 100.00% | 85.22% |
| mbpp | 142 | 540 | 16.20% | 83.80% | 79.18% |
| mmlupro | 159 | 540 | 43.40% | 56.60% | 77.25% |

Interpretation: routing is worth studying when the mean gap is material after cleaning. The hard part is not whether an oracle opportunity exists, but whether stable query-level compatibility labels can recover it without creating extra wrong switches.
