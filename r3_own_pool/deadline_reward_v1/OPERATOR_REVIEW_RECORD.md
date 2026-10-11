# OPERATOR_REVIEW_RECORD — standing audit trail of review verdicts

## 2026-10-11 (latest): round-3 math errata ACCEPTED; measurement HOLD stands

Operator code review over GitHub (`ba72888` evidence, `e26c856` fixes,
`1ae5363` preflight rebind, `10f82de` report) — verdict: the two
substantive math errors are resolved; the reward mechanism is now at the
"executable joint-scheduling prototype + math/engineering gate
verification" stage. Accepted in particular:

1. Per-node P90 sums are no longer claimed to give a path-wide 90%
   on-time guarantee (empirical branch = staircase-CDF lower bound +
   Markov; the counterexample returns 0.81, not 0.90);
2. service latency vs deterministic switch/contention shift are composed
   exactly once inside the estimator;
3. the empirical-family lateness quantity is a conditional UPPER bound,
   never a lower bound presented as a prediction;
4. probability ESTIMATES vs probability LOWER BOUNDS are explicitly
   separated per family in every decision row (estimator_claim).

Recorded regressions (present on GitHub, NOT a substitute for
independent re-testing or real-model validation): M1–M6 suites, 42/42
runner smoke, 8/8 admission-repair groups, preflight + admission check.

### Capability status as reviewed (operator table, confirmed)

| Capability | Status |
|---|---|
| Fault detection D1–D6, execution-state tracking | implemented, tested |
| DAG dependency closure, cache reuse/invalidation | implemented, tested |
| LOCAL/FULL recovery execution | implemented; static-equivalence evidence exists |
| Post-fault node model reassignment | implemented; stub-scenario verified |
| Q_min / on-time / remaining-budget filtering | implemented |
| On-time reward, cost & lateness penalties | implemented |
| A/B/C choose-B golden test | stub-passed |
| Latency-distribution math | this round: code-review passed |
| Real task-quality prior calibration | PENDING (the supplementary measurement) |
| Prediction reliability under real deadlines | NOT yet validated |
| Superiority over static scheduling | NOT proven |

The open question is no longer "is there an algorithm" but "is it
effective under real data and real time constraints".

### Three standing scientific boundaries (operator ruling, binding)

1. The empirical lower bound is NOT an unconditional real-world
   guarantee: the staircase CDF is valid under the declared per-node
   distributions + independence; ~30 samples per node make the empirical
   distribution an estimate of the unknown truth. A "model-conservative
   lower bound" must never be written up as a statistical guarantee of
   real on-time probability.
2. Cross-task contention remains an ESTIMATE inside the shift: real
   queuing/switch behavior can deviate; prediction error and on-time
   coverage need separate validation.
3. Current quality priors are parse-rate PROXIES (q_parse), not task
   correctness: q_parse ≥ 0.80 must never be read as "real accuracy
   ≥ 80%". Additionally the empirical-family e_late used in scoring is
   an upper bound, not an exact expectation — the policy optimizes a
   conservative reward PROXY, not (yet) the true expected reward.

### Scope of the NEXT authorization (when granted)

Real calls stay HOLD. The independent quality supplementary measurement
is the next SEPARATELY authorized item, with purpose strictly limited
to: calibrating task-level correctness (P(task correct | config,
condition), v2.1 scoring) and sanity-checking whether the 0.80 quality
threshold is reasonable. It may NOT be used to select a winning
strategy, adjust frozen reward weights, or claim dynamic > static.
PREFLIGHT_PASS evidences the preset admission checks only — it is not
an automatic GPU-inference permission. The preflight packet (10 cells,
20 frozen tasks, call/token/wall budgets) is the material for that
authorization review.

### The decisive evidence still ahead

Under real faults, real models, and real deadlines: can the system — by
dynamically adjusting recovery scope and model assignment — beat static
policies on on-time-correct completion and the cost-latency tradeoff.
