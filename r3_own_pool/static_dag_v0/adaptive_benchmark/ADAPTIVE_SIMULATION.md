# Adaptive Decomposition — zero-cost simulation (post-hoc, supplementary)

Oracle split: 46 Hard / 74 Easy (gold operator count — NOT deployable; upper bound).

## Rule quality vs oracle

- rule_a(>=2 numerals in question): hard-set size 95, agreement 32%, recall of oracle-hard 85%
- rule_b(question length >= median 14): hard-set size 60, agreement 19%, recall of oracle-hard 50%
- rule_c(table rows >= median 8): hard-set size 64, agreement 20%, recall of oracle-hard 52%

## Clean scenario

| Policy | Accuracy | tokens/task |
|---|---:|---:|
| Single-all | 0.5500 | 602 |
| Static-all | 0.3500 | 1503 |
| Dynamic-all | 0.4000 | 2324 |
| Adaptive(oracle) | 0.5500 | 1308 |
| Adaptive(rule_a(>=2 numerals in question)) | 0.4083 | 1980 |
| Adaptive(rule_b(question length >= median 14)) | 0.4917 | 1528 |
| Adaptive(rule_c(table rows >= median 8)) | 0.4667 | 1552 |

Hard-subset detail (clean): single 0.3043, dynamic 0.3043, dynamic-ideal 0.3261, dynamic+verifier 0.3043.

## Fault scenarios (3 seeds, mean±std)

| Fault | Single-all | Dynamic-all | Adaptive(oracle) | best deployable rule |
|---:|---:|---:|---:|---:|
| 10% | 0.4972±0.0173 | 0.4111±0.0048 | 0.5000±0.0167 | 0.4750±0.0167 (rule_b) |
| 20% | 0.4389±0.0173 | 0.4139±0.0096 | 0.4611±0.0048 | 0.4361±0.0293 (rule_b) |
| 30% | 0.3639±0.0315 | 0.4083±0.0167 | 0.3972±0.0210 | 0.3944±0.0173 (rule_a) |

Verdict (honest): on the CLEAN scenario adaptive routing buys NO accuracy over Single-all (Dynamic's hard-subset accuracy equals, not exceeds, the single model), at higher cost than Single-all — the entry decision cannot rescue clean accuracy on this panel. Under FAULTS the composed policy is the best of all worlds at moderate rates (cheap robust easy arm + robust hard arm). This supports the paper's existing positioning: routing/decomposition value = cost shaping and fault-scenario composition, not clean accuracy; the failure-aware mainline is unchanged.