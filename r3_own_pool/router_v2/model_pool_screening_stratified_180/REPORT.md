# Stratified Model Pool Capability Screening 180

BestSingle=reasoning (85.00%); Oracle=93.33%; Oracle Gap=8.33pp.

## Domain Quality

| Domain | n | Best | Oracle | small | medium | large | coder | math | reasoning |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| code | 60 | reasoning | 93.33% | 31.67% | 73.33% | 73.33% | 75.00% | 20.00% | 90.00% |
| knowledge | 60 | reasoning | 86.67% | 30.00% | 60.00% | 63.33% | 48.33% | 48.33% | 70.00% |
| math | 60 | large | 100.00% | 80.00% | 95.00% | 96.67% | 90.00% | 95.00% | 95.00% |

## Winners

| Model | Accuracy | Strict winners | Fractional winners | Unique winners | > R1 | = R1 | < R1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| small | 47.22% | 0 | 17.4 | 0 | 4 | 104 | 72 |
| medium | 76.11% | 3 | 34.0 | 3 | 11 | 142 | 27 |
| large | 77.78% | 1 | 34.0 | 1 | 9 | 149 | 22 |
| coder | 71.11% | 0 | 29.7 | 0 | 5 | 145 | 30 |
| math | 54.44% | 0 | 21.4 | 0 | 7 | 111 | 62 |
| reasoning | 85.00% | 7 | 43.6 | 7 | 0 | 180 | 0 |

## Subpool Oracle

| Subpool | Oracle | Gain vs R1 | Gain vs BestSingle |
|---|---:|---:|---:|
| R1+Large | 90.00% | 5.00pp | 5.00pp |
| R1+Math | 88.89% | 3.89pp | 3.89pp |
| R1+Coder | 87.78% | 2.78pp | 2.78pp |
| R1+Math+Coder | 89.44% | 4.44pp | 4.44pp |
| R1+Large+Math+Coder | 91.67% | 6.67pp | 6.67pp |
| Full | 93.33% | 8.33pp | 8.33pp |

## 1.5B Near Best

| Quality epsilon | Count | Ratio | Mean cost saving | Mean latency saving |
|---:|---:|---:|---:|---:|
| 0.0 | 97 | 53.89% | $0.000000 | 0.0 ms |
| 0.05 | 97 | 53.89% | $0.000000 | 0.0 ms |
| 0.1 | 97 | 53.89% | $0.000000 | 0.0 ms |
| 0.2 | 97 | 53.89% | $0.000000 | 0.0 ms |

## Pairwise Complementarity

| Pair | Pair oracle | Left-only | Right-only | Correct corr | Error corr |
|---|---:|---:|---:|---:|---:|
| medium:reasoning | 91.11% | 11 | 27 | 0.348 | 0.348 |
| large:reasoning | 90.00% | 9 | 22 | 0.449 | 0.449 |
| math:reasoning | 88.89% | 7 | 62 | 0.241 | 0.241 |
| coder:reasoning | 87.78% | 5 | 30 | 0.487 | 0.487 |
| small:reasoning | 87.22% | 4 | 72 | 0.273 | 0.273 |
| large:coder | 84.44% | 24 | 12 | 0.485 | 0.485 |
| medium:large | 83.89% | 11 | 14 | 0.609 | 0.609 |
| medium:coder | 83.33% | 22 | 13 | 0.505 | 0.505 |
| large:math | 81.67% | 49 | 7 | 0.397 | 0.397 |
| medium:math | 80.56% | 47 | 8 | 0.403 | 0.403 |
| small:large | 78.33% | 1 | 56 | 0.479 | 0.479 |
| small:medium | 77.22% | 2 | 54 | 0.478 | 0.478 |
| coder:math | 76.67% | 40 | 10 | 0.451 | 0.451 |
| small:coder | 75.56% | 8 | 51 | 0.406 | 0.406 |
| small:math | 61.67% | 13 | 26 | 0.575 | 0.575 |
