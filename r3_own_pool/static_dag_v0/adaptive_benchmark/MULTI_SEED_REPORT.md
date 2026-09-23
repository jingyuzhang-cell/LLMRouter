# Multi-seed fault injection (3 seeds: 20260923/24/25)

Mean +/- std over seeds (population std). Same procedure, pools and policies; calls reused at temperature 0; only new prompts executed for real.

| Fault rate | Single LLM (retry) | Static | Dynamic | dQ(Dyn-Static) | dQ(Dyn-Single) | Dynamic recovery | Static survival |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10% | 0.4972±0.0142 | 0.3361±0.0142 | 0.4111±0.0039 | +0.0750±0.0136 | -0.0861±0.0104 | 0.39±0.10 | 0.22±0.08 |
| 20% | 0.4389±0.0142 | 0.3250±0.0236 | 0.4139±0.0079 | +0.0889±0.0208 | -0.0250±0.0068 | 0.42±0.03 | 0.25±0.09 |
| 30% | 0.3639±0.0258 | 0.3111±0.0322 | 0.4083±0.0136 | +0.0972±0.0375 | +0.0444±0.0142 | 0.44±0.01 | 0.29±0.10 |

## Hard subset (46 tasks)

| Fault rate | Single LLM | Static | Dynamic |
|---:|---:|---:|---:|
| 10% | 0.2681±0.0102 | 0.1957±0.0177 | 0.2754±0.0102 |
| 20% | 0.2174±0.0355 | 0.1667±0.0410 | 0.2754±0.0102 |
| 30% | 0.1812±0.0410 | 0.1667±0.0410 | 0.2681±0.0205 |