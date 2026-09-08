# Pilot 500x4 Routing Opportunity Analysis

Queries analyzed: 490 (complete labels; arenahard judge = qwen-max v1 rubric)

## 1. Oracle gap (routing headroom)

| scope | Best Single (model) | Oracle | gap |
|---|---|---|---|
| overall | 0.8960 (DS-R1-Distill-14B) | 0.9468 | **+0.0508** |
| math | 0.9800 (DS-R1-Distill-14B) | 0.9800 | **+0.0000** |
| code | 0.9293 (DS-R1-Distill-14B) | 0.9646 | **+0.0354** |
| knowledge | 0.7500 (DS-R1-Distill-14B) | 0.8804 | **+0.1304** |
| general | 0.8945 (Qwen2.5-14B) | 0.9395 | **+0.0450** |

Best Single = max_m E[Q_m]; Oracle = E[max_m Q_m]. Positive gap = routing headroom exists.

## 2. Model complementarity

| model | unique-best share | tied-best share | mean quality |
|---|---|---|---|
| Qwen2.5-3B | 1.2% | 64.9% | 0.7151 |
| Qwen2.5-7B | 2.2% | 75.1% | 0.8076 |
| Qwen2.5-14B | 4.9% | 81.0% | 0.8662 |
| DS-R1-Distill-14B | 5.3% | 82.2% | 0.8960 |

Unique-best queries: 13.7% (ties at the top: 86.3% — on ties any choice is accuracy-equivalent; the win there is cost/latency).

Per dataset unique-best winner distribution:

| dataset | Qwen2.5-3B | Qwen2.5-7B | Qwen2.5-14B | DS-R1-Distill-14B |
|---|---|---|---|---|
| arenahard | 2% | 8% | 21% | 16% |
| gsm8k | 0% | 0% | 0% | 3% |
| humaneval | 1% | 0% | 0% | 2% |
| mbpp | 0% | 0% | 2% | 2% |
| mmlupro | 3% | 3% | 1% | 3% |

## 3. Cost-quality tradeoff

| model | mean quality | mean cost ($) | mean latency (ms) |
|---|---|---|---|
| Qwen2.5-3B | 0.7151 | 0.0001354 | 5442 |
| Qwen2.5-7B | 0.8076 | 0.0001538 | 8626 |
| Qwen2.5-14B | 0.8662 | 0.0004574 | 9634 |
| DS-R1-Distill-14B | 0.8960 | 0.0014353 | 64741 |

Quality-parity pairs (|Δquality| ≤ 2pp) — cost advantage:


Per task: cheapest model within 2pp of the best-quality model:

- math: best DS-R1-Distill-14B (0.980); cheapest within 2pp = DS-R1-Distill-14B (q=0.980, $0.0005576/query)
- code: best DS-R1-Distill-14B (0.929); cheapest within 2pp = DS-R1-Distill-14B (q=0.929, $0.0019554/query)
- knowledge: best DS-R1-Distill-14B (0.750); cheapest within 2pp = DS-R1-Distill-14B (q=0.750, $0.0013943/query)
- general: best Qwen2.5-14B (0.894); cheapest within 2pp = Qwen2.5-14B (q=0.894, $0.0008305/query)

NOTE: cost/latency are Phase-1 mixed-deployment values (indicative only; paper metric comes from Phase-2 all-local vLLM per protocol v1.1).

## Collection status

| slot | ok | truncated | failed | parse_failed |
|---|---|---|---|---|
| Qwen2.5-3B | 496 | 4 | 0 | 0 |
| Qwen2.5-7B | 496 | 4 | 0 | 0 |
| Qwen2.5-14B | 497 | 2 | 0 | 1 |
| DS-R1-Distill-14B | 493 | 0 | 0 | 7 |
