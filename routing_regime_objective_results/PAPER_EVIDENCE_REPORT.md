# Static, Dynamic, DAG, and Objective-Cardinality Evidence

## Scope and integrity

This frozen benchmark uses 419 development tasks, five models, and three empirical repeats per task. Request-routing results are grouped out-of-fold estimates. The 104 four-node diamond DAGs are deterministic empirical-node replays; they validate routing and recovery mechanics, not semantic decomposition quality. The independent v3 holdout was not accessed.

## Request-level routing

| Objective | Static best | Dynamic OOF | Dynamic − static (95% CI) | Oracle | Oracle headroom |
|---|---:|---:|---:|---:|---:|
| Single: quality | 0.8029 | 0.8071 | +0.0042 [-0.0037, 0.0130] | 0.8807 | +0.0778 |
| Dual: quality + cost | 0.8603 | 0.8591 | -0.0012 [-0.0056, 0.0027] | 0.9136 | +0.0533 |
| Multi: quality + cost + latency + reliability | 0.7976 | 0.8055 | +0.0079 [0.0031, 0.0134] | 0.8562 | +0.0586 |

The strongest deployable result is multi-objective dynamic routing. It improves over the fold-local static optimum with a confidence interval wholly above zero, but recovers only 13.5% of available oracle headroom. Single-objective routing is directionally positive but inconclusive. The tested dual-objective policy does not beat static routing.

## DAG replay

| Objective | Regime | Score Δ vs static (95% CI) | Completion Δ vs static (95% CI) | Mean retries | Mean cost | Critical-path latency (ms) |
|---|---|---:|---:|---:|---:|---:|
| Single | Dynamic | +0.0032 [-0.0056, 0.0128] | +0.0096 [0.0000, 0.0288] | 0.000 | 0.000749 | 270,921 |
| Single | Adaptive retry | +0.0353 [0.0170, 0.0555] | +0.1442 [0.0769, 0.2115] | 0.760 | 0.001561 | 306,633 |
| Dual | Dynamic | -0.0023 [-0.0063, -0.0001] | 0.0000 [0.0000, 0.0000] | 0.000 | 0.000478 | 270,022 |
| Dual | Adaptive retry | +0.0247 [0.0116, 0.0393] | +0.1442 [0.0769, 0.2115] | 0.788 | 0.000639 | 306,289 |
| Multi | Dynamic | +0.0052 [-0.0008, 0.0123] | +0.0385 [0.0096, 0.0769] | 0.000 | 0.000517 | 269,624 |
| Multi | Adaptive retry | +0.0157 [0.0075, 0.0250] | +0.1346 [0.0769, 0.2019] | 0.721 | 0.000641 | 304,004 |

Adaptive local rerouting is consistently beneficial in replay, with an explicit cost/latency tradeoff. This supports a mechanism claim: DAG execution benefits from failure-conditioned local recovery. It does not yet prove that learned semantic decomposition improves end-to-end answer quality.

## Evidence status for the paper

1. **Static vs dynamic:** supported on a large empirical repeated matrix; the positive result is specific to the four-objective formulation.
2. **Single/dual/multi-objective optima:** static, learned dynamic, and oracle operating points are all quantified. Negative dual-objective findings must be retained.
3. **DAG:** mechanism-level replay evidence is positive, especially for local adaptive recovery, but confirmatory semantic DAG evidence remains pending.
4. **Decomposition bridge:** E2.1-A remains incomplete (917 raw rows; 748 provider-success rows observed during audit, versus 3240 required cells). Collection stopped after qwen-plus returned an account-arrears error. Frozen model substitution is not allowed.

## Remaining confirmatory gate

The paper can presently support a multi-objective routing and adaptive-DAG mechanism contribution. A stronger causal claim that decomposition exposes exploitable specialization still requires completing frozen E2.1-A, passing its preregistered gate, and then running E2.1-B. Until qwen-plus access is restored, this is an external execution blocker rather than an analytic one.
