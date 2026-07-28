# Stage Offline Analysis

Snapshot successes: 346 / 1200
> Interim development-only results; recompute after 1200 successful calls.

## Judge consistency
- Dual coverage: 99.42%
- Judge attempt parse rate: 79.56%
- Mean/median disagreement: 0.2346 / 0.2
- Disagreement >=0.20: 226 (65.32%)
- Objective/judge Pearson: 0.6842 (n=274)
- Risks: ['judge attempt parse rate below 90%', 'at least 20% of runs have judge disagreement >=0.20']

## Weight robustness and Pareto
- Complete tasks: 28
- Weight vectors: 428
- Base best: balanced_utility
- Base-best winner rate: 0.8902
- Stable top-3: ['balanced_utility', 'risk_adaptive', 'pareto_utility']
- Weight-sensitive: ['fixed_qwen-plus', 'quality_first', 'latency_first']
- Pareto validation: True

## Memory replay
- Status: PASS
- Modes: {'none': {'cumulative_regret': 25.0, 'routing_accuracy': 0.5}, 'positive_only': {'cumulative_regret': 25.0, 'routing_accuracy': 0.5}, 'full': {'cumulative_regret': 0.5, 'routing_accuracy': 0.99}}
- Guards: {'pending_and_expired_excluded': True, 'negative_lowers_wrong_model': True, 'high_risk_wrong_objective_blocked': True, 'version_change_isolated': True}
- Full vs no-memory regret reduction: 24.5
