# Multi-seed fault injection (3 seeds: 20260923/24/25)

Mean +/- std over seeds (population std). Same procedure, pools and policies; calls reused at temperature 0; only new prompts executed for real.

| Fault rate | Single LLM (retry) | Static | Dynamic | dQ(Dyn-Static) | dQ(Dyn-Single) | Dynamic recovery | Static survival |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10% | 0.4972±0.0142 | 0.3250±0.0068 | 0.4056±0.0039 | +0.0806±0.0104 | -0.0917±0.0136 | 0.39±0.10 | 0.11±0.08 |
| 20% | 0.4389±0.0142 | 0.3056±0.0104 | 0.4111±0.0039 | +0.1056±0.0104 | -0.0278±0.0104 | 0.42±0.03 | 0.15±0.04 |
| 30% | 0.3639±0.0258 | 0.2861±0.0142 | 0.4056±0.0104 | +0.1194±0.0171 | +0.0417±0.0180 | 0.44±0.01 | 0.20±0.03 |

## Hard subset (46 tasks)

| Fault rate | Single LLM | Static | Dynamic |
|---:|---:|---:|---:|
| 10% | 0.2681±0.0102 | 0.1957±0.0177 | 0.2609±0.0000 |
| 20% | 0.2174±0.0355 | 0.1667±0.0410 | 0.2681±0.0102 |
| 30% | 0.1812±0.0410 | 0.1522±0.0355 | 0.2609±0.0177 |