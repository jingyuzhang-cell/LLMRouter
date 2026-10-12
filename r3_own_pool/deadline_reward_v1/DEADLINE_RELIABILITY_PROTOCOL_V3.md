# DEADLINE_RELIABILITY_PROTOCOL_V3 — executable admission package

Supersedes V2 (its §4–7 ambiguities resolved). Zero real model calls
were used to produce this document. Panels frozen in
`RELIABILITY_PANEL_FREEZE.json` (seeds 20261012/13/14/15/16; SHA-256
per panel; disjointness + isolation from all prior panels asserted and
re-derivable). Statistics frozen in `reliability_stats.py` (the run MUST
use these audited implementations). Budget in
`DEADLINE_RELIABILITY_BUDGET_AUDIT.md`. Gates in
`DEADLINE_RELIABILITY_ADMISSION.md`.

## 1. Panels, sample units, cache rules (task 1.1–1.3)

- Pool: frozen200 − evaluation(26) − 1200-call calibration(30) −
  supplementary(20) = **150**. Drawn without replacement:
  **fit(24, seed 20261012)** → **screen(12, seed 20261013)** →
  **validate(90, seed 20261014)**; 24 spare remain unallocated.
- **Isolation (task 1.2)**: the VALIDATION panel is used ONCE for final
  coverage evaluation only. Estimator/family selection, quantile
  derivation, sample-size revision, thresholds and tolerances are
  decided on fit+screen data exclusively. Screen results may resize the
  plan (e.g., trigger a CONDITIONAL extension using the SPARE pool
  under a new freeze with the estimator unchanged) but never re-select
  estimators on validation data.
- **Sample unit**: one PHYSICAL call (charged request) at a unique
  (model, input_sha) execution identity. Cache hits are replays, not
  samples — quantile fitting and coverage evaluation count physical
  calls only.
- **Cache/retry rules**: (a) FIT repeats use declared no_cache
  re-execution (K≤3 per task): answer repetition at temperature 0 does
  not impair latency sampling — service time is not answer-deterministic
  (67-identical/13-changed answers in run_20261012_092146 while
  latencies varied); (b) FAILED-node retries with UNCHANGED identity are
  excluded from quantile fitting (deterministic-repeat bias); retries
  with changed identity count; (c) D3 faults are cache+corruption
  events — zero new base requests; only policy-chosen retries charge.

## 2. Frozen statistical rules (task 1.4–1.5)

All implemented in `reliability_stats.py` (tested 14/14 vs exact
enumeration and closed forms; evidence `RELIABILITY_TOOLKIT.json`):

- **Coverage acceptance**: one-sided exact **Clopper–Pearson lower
  bound at α=0.05 must be ≥ 0.90** per menu cell (H0: coverage < 0.90
  rejected only then). The 0.80–1.00 Wilson band is EXPLORATORY
  diagnostic output only — it never admits anything.
- **Joint acceptance across the 10 menu cells**: PASS ⟺ every cell
  passes individually; a cell with point coverage ≥ 0.90 but CP-LB <
  0.90 is **CONDITIONAL** (staged n-extension path, spare pool, new
  freeze, estimator unchanged); any cell with point coverage < 0.90, or
  a missing cell, is FAIL.
- **On-time calibration**: per D-tier, the realized on-time count must
  lie inside the exact **Poisson-binomial acceptance region** (mass
  ≥ 1−α) computed from the ex-ante predicted p_on values (P0-B rows).
  The tolerance IS the region — no fixed band is ever substituted.
- **Exact sample-size arithmetic** (frozen table, `sample_size_table`):
  CP-LB ≥ 0.90 requires n = **29** at perfect coverage, **61** at 0.97,
  **116** at 0.95, **298** at 0.93. Consequences, stated honestly:
  validation n=30/e-cell certifies only at 30/30; n=45/r,v-cell
  certifies at 45/45 (44/45 → LB ≈ 0.889 → CONDITIONAL). No
  exploratory interval is ever reported in place of these tests.

## 3. Stage design and the E2E closed loop (task 3)

Common: stage-major batched execution (production `run_stage`
semantics: jobs of one stage grouped by model — the wall-clock driver),
full P0-B decision rows before execution, decision_id correlation.

- **S-FIT (24 tasks × 4 nodes × K=3)**: round-robin menu assignment
  (task i: e1,e2 ∈ {medium,large,coder}[i%3]; r ∈ {medium,large}[i%2];
  v ∈ {coder,large}[i%2]). Output: per-cell latency samples on REAL
  cascade prompts (upstream answers fed forward), per-cell family
  binding (frozen distribution-protocol statistics: SW+K²+Bonferroni),
  measured switch costs per ordered model pair. Fixed-path calibration
  object #1.
- **S-SCREEN (12 tasks × 1)**: exploratory coverage of the fit-derived
  P90s on fresh identities; no admission force.
- **S-VALIDATE (90 tasks × 1 + fault sub-experiment)**: final
  independent coverage (n=30/e-cell, n=45/r,v-cell). D3 faults on 27
  frozen tasks (cache+corruption) drive DYNAMIC decisions under ONE
  assigned D-tier each (9/9/9 across tight/medium/wide) — the dynamic
  prediction-vs-actual comparison is **exploratory** (n=9/tier cannot
  power the acceptance region); formal dynamic on-time validation
  remains V2.3's confirmation role (see §6).
- **S-CONTENTION (8 co-resident pairs from the fit panel)**: measured
  queue wait under the shared serial executor.
- **Fixed-path D-tier replay (ZERO-CALL)**: tiers at the measured P40/
  P60/P80 of realized task-level E2E (service + own switches + queue —
  the supplementary run showed queue is the dominant term: median 125 s
  of 143 s); replay computes on-time per task per tier with NO new
  calls, because planned-path actuals do not depend on D. Verified
  end-to-end on a synthetic ledger (`test_reliability_stats.py` part D:
  hand-computed E2E decomposition, tier discrimination 3/5/6,
  acceptance-region verdicts, decision_id join).
- **Decomposition (task 3.3)**: per task — node service (per-call
  latency), own switches (attributed wall), queue wait (E2E − service −
  switches; cross-task interleaving), full E2E (t_last − release);
  reconciled against task summaries (0 mismatches on the supplementary
  run's 200 summaries).
- **Counterfactual prohibition (task 3.6)**: unexecuted candidates keep
  their P0-B predictions and never acquire outcomes; realized latencies
  are joined only via decision_id to the executed plan's calls.

## 4. INCOMPLETE semantics (task 2.5)

Every stage writes its own append-only ledger and a stage status. A
stage that stops on any cap (requests/tokens/wall/SIGALRM) or error is
**INCOMPLETE**: its partial data goes to a distinctly-named
`..._INCOMPLETE.json`, the stage gate closes, downstream stages refuse
to start, and NO partial output may be packaged as a validation verdict
(the official `RELIABILITY_RESULTS.json` is written only for a fully
COMPLETE pipeline — the write_quality_output discipline, never
overwritten). CONDITIONAL cells are reported as CONDITIONAL with their
extension path, never upgraded.

## 5. Research boundaries (task 4)

- The four-level distinction is binding everywhere: node-anomaly
  OBSERVATION → execution-CONTRACT failure → downstream-dependency
  invalidation → TERMINAL task failure (D5 compares v against r, not
  gold: "inconsistency detected" ≠ "fault localized" — 3 concrete cases
  in run_20261012_092146). No detector is modified in this protocol.
- Old measurement data and quality conclusions untouched; Q_min=0.80,
  ε, λ weights, and the reward function unchanged, and NOT recalibrated
  from any reliability result.
- **Quality-proxy impact (task 4.4)**: with the current strict
  parse-rate beliefs (e2|large q̂=0.25), dynamic candidates involving
  e-recovery remain q-infeasible, so tight-deadline DYNAMIC decisions
  will frequently degrade rather than reassign. The reliability
  experiment therefore primarily validates FIXED-PATH quantile
  coverage + planned-path on-time replay; its dynamic arm is
  exploratory and REPORTED AS SUCH. This is a known limitation of the
  proxy, recorded — not a reason to touch Q_min.
- **D-tier separation (task 4.5)**: this protocol's replay tiers are
  derived from ITS OWN measured E2E quantiles for reliability
  calibration only. They neither override nor transfer to the frozen
  V2.3 confirmation P40/P60/P80 generation rules; the two rule sets
  live in separate frozen documents with separate hashes.

## 6. What this experiment can and cannot conclude

CAN: per-cell declared-P90 coverage verdicts (exact CP bounds);
planned-path on-time calibration at replayed tiers (exact
Poisson-binomial regions); switch-cost and queue-wait measurement;
exploratory dynamic-decision prediction error. CANNOT: strategy
superiority; any statement that 80%-band coverage satisfies the 90%
requirement; formal dynamic on-time guarantees (V2.3's role); any
recalibration of frozen quality/weight parameters.
