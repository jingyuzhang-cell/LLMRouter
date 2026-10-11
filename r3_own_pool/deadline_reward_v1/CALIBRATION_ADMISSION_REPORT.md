# CALIBRATION_ADMISSION_REPORT — 5 pre-authorization gates for the supplementary DAG-quality measurement

Zero real model calls. Socket blocked at process level. Evidence:
`evidence/ADMISSION_CHECK.json` (+ `evidence/adm2_arms/` stub ledgers,
`evidence/adm4_drill/` synthetic dispatch ledgers,
`evidence/SUPPLEMENTARY_PANEL_FREEZE.json`, `PRIORS_REAL_V1_families.json`).
**Result: ALL 5 GATES PASS.** Real calls remain HOLD pending operator GO.

## Gate 1 — statistical reproducibility: COMPLETE frozen protocol

The earlier DISTRIBUTION_TESTS_V2 was INCOMPLETE (Shapiro-Wilk only,
no multiple-testing correction). This gate runs the exact procedure frozen
in `CALIBRATION_FREEZE_PREREQUISITES.json .distribution_family_validation`
(frozen before any calibration data was viewed): per cell Shapiro-Wilk AND
D'Agostino K², Bonferroni WITHIN each (node, model, condition) cell across
the 2 tests (per-test threshold 0.005), applied to both families (normal on
raw latencies, lognormal on log latencies); a family is selected only if
BOTH tests pass after correction; normal preferred, else lognormal, else
empirical.

**Result: 0 normal / 12 lognormal / 28 empirical (40 cells, n=30 each,
1200 calls).** All statistics (W, K², raw and adjusted p, sorted
latencies, lognormal μ/σ) saved per cell with code versions (python/
numpy/scipy/git commit), script SHA-256, and raw-data hashes (ledger +
prerequisites).

Three cells CHANGE family vs the Shapiro-only V2 — all empirical →
lognormal (`e1|medium|clean`, `e2|medium|D1_e_empty`,
`e2|medium|D3_r_unparseable`): their log-Shapiro p ∈ [0.005, 0.01) was
rejected by V2's UNCORRECTED 0.01 but survives the protocol's corrected
2-test battery. No cell moved lognormal → empirical (K² rejected none of
V2's nine). The complete protocol is the binding one; V2 remains as the
incomplete-Shapiro-only audit. The frozen `DAG_QUALITY_CALIBRATION_
PROTOCOL.json` distribution_finding note ("9/40 lognormal") was the
V2 snapshot — superseded by this gate per the frozen prerequisites; the
protocol file itself is untouched. E1's normal estimator remains
unsupported (0/40); the per-cell binding is written to
`PRIORS_REAL_V1_families.json` (companion file; PRIORS_REAL_V1.json NOT
modified), estimator rule: lognormal → log-lognormal params, empirical →
empirical CDF (sorted latencies saved for exact reconstruction).

## Gate 2 — execution capability: five REAL policy entry points, behaviorally distinct

New frozen module `deadline_reward_v1/arm_entry.py`: DS/SD/DD all route
through the SAME `policy._score_and_pick` (two-stage filter + argmax
E[R]) over DIFFERENT candidate sets — DS: π pinned to planned (scope is
the choice); SD: scope pinned to the LOCAL recipe (π free over menus);
DD: all candidates. SS is the fixed LOCAL/planned recipe with NO policy
scoring and NO constraint filter (static = executes regardless — the
ablation, not a bug). NONE accepts the failure and only completes pending
planned nodes. This fixes the stub pilot's defect where DS/SD were
index-based picks that could coincide with SS by construction.

Stub scenario (r|medium D3 unparseable fault, declared synthetic priors
r|medium q=0.60 / r|large q=0.95 / v|coder q=0.85 / v|large q=0.95,
q_min=0.80, D=80s), observable post-decision call sequences from the
engine ledger:

| Arm | Decision (real entry) | Post-decision calls | q |
|---|---|---|---|
| SS | fixed recipe LOCAL π(r=medium,v=coder) — executes despite q̂=0.60 | r:medium(FAULT AGAIN), v:coder | 0 |
| DS | policy over planned-π pool: ALL scopes infeasible (q_min) → DEGRADE | (none — D10 early stop) | 0 |
| SD | policy over LOCAL pool → argmax LOCAL π(r=large,v=large) score 0.80 | r:large, v:large | 1 |
| DD | policy over ALL 44 candidates → same argmax as SD | r:large, v:large | 1 |
| NONE | accept failure | v:coder | 0 |

DS≠SS (2 blind calls vs 0, degraded flag), SD≠SS (model sequence AND
outcome), DD≠SS (same), NONE floor distinct; SD≠DS. Deterministic
re-run reproduced identical ledgers. Full scored tables + violation
vectors are in the evidence (DS: 4 candidates all q_min-infeasible across
all three scopes; DD evaluated 44 incl. FULL/FULL_DYNAMIC). Honest caveat,
recorded in the evidence: DD≡SD ON THIS SCENARIO — SD's candidate set is
a subset of DD's and with stub priors DONE nodes carry observed quality
1.0 so full replays never win the argmax; the candidate sets and scored
tables still differ, and with real quality priors the argmax can diverge
(measuring that divergence is the point of the supplementary run).

## Gate 3 — data isolation: frozen supplementary panel

`evidence/SUPPLEMENTARY_PANEL_FREEZE.json`: 20 tasks =
`Random(42).sample(frozen200 − evaluation panel − calibration panel, 20)`
(26 evaluation UIDs across search/test/reserve; 30 calibration UIDs from
the 1200-call ledger; 170 available), same 20 tasks across all 5 configs
× 2 conditions for within-task pairing. Fault assignment frozen:
`Random(20261011).sample(supplementary, 6)` (rate 0.30, node r, D3
unparseable, answer string identical to the calibration ledger's D3
fault). Both seeds independently re-derived and asserted equal before
writing. SHA-256 frozen for the UID list, task snapshot (uid/answer/
derivation), frozen200 source, evaluation panel, and calibration ledger.
Intersections: supplementary ∩ evaluation = ∅, supplementary ∩
calibration = ∅, faults ⊆ supplementary, supplementary ⊆ frozen200 —
**PASS**. (Noted: 3 of the 26 evaluation UIDs are not frozen200 members;
irrelevant to isolation since exclusion is by set difference.)

## Gate 4 — budget/stop: zero-call drill on the PRODUCTION metering class

Drives the real `Budget` class (joint_search_smoke/proposal_v2/
smoke_runner.py — reserve-then-settle, per-request reservation 1700 ≥ max
single-call p95 1602, append-only DISPATCH ledger) with SYNTHETIC
responses only, caps mapped 1200 requests / 800K tokens / 7200s:

- request cap: trips at attempt 1201 (`request budget`) — PASS
- token cap: trips at attempt 471 (`token budget`, 470×1700 = 799K) — PASS
- wall cap: fake clock past start+7200 (`wall budget`) — PASS
- invalid-usage guard: missing usage → StopRun, FULL reservation retained
  (charge unchanged) — PASS
- full-plan rehearsal at DECLARED WORST CASE: 800 base calls at per-node
  p95 token costs (e1 826 / e2 1602 / r 198 / v 177) + 300 worst-case
  recovery = 1100 requests / 620,000 tokens → COMPLETED WITHIN CAPS
  (headroom 100 requests / 180K tokens) — PASS
- resume refusal: existing DISPATCH ledger → ValueError, no silent
  resume — PASS

## Gate 5 — scope (binding statement)

The supplementary measurement is INITIAL QUALITY CALIBRATION ONLY:
P(task correct | config, condition) under v2.1 scoring to validate that
Q_min=0.80 is a reasonable threshold and to bind per-cell quality priors.
Forbidden uses: selecting the SS recipe on this panel; claiming DD>SS or
any policy superiority; adjusting Q_min/eps/λ/reward formulas; treating
node format rates as correctness. With 20 tasks/cell the binomial CI is
wide (17/20 → 64–95%); overlapping CIs are expected and carry no
superiority information. Full statement in the evidence file.

## Status

All five operator pre-authorization conditions are satisfied with zero
real model calls. The ~1000-call supplementary measurement itself remains
HOLD until the operator issues the measurement GO (and its runner still
needs to be written against the real-model execution path — it will reuse
`arm_entry.py` unchanged as the frozen selection layer).
