# Post-hoc Judge and Quality Audit

- GLM removed from Judge order; candidate pool unchanged.
- Frozen 60-run validation: 60/60 retained two valid non-GLM judges; no API calls.
- Objective scorer drift: 32/1200 records (23 up, 9 down).
- Preference-sensitive task winners: 19/100 tasks.

## Manual case review

- Confirmed false negatives caused by late template placeholders after correct answers.
- Confirmed unit-equivalent answers such as 0.34 vs 34% and 234 thousand vs 234000 dollars.
- Confirmed some previous positives were incomplete model outputs and should be downgraded.
- Judge-objective disagreement is therefore partly scorer-driven, not solely judge bias.

## Paper conclusion gate

Current main-table significance claims are provisional. Until strategy metrics and paired tests are recomputed from the frozen response pool with scorer v2.2, use only “numerically higher” or “no significant difference established.”

Raw responses are intentionally excluded from this report and PR.
