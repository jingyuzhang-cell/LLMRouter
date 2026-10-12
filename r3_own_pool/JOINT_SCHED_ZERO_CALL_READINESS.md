# JOINT_SCHED_ZERO_CALL_READINESS — zero-call build complete; real execution remains UNAUTHORIZED

Operator mandate 2026-10-12 (baseline `83ea096`): G1–G3 zero-call
development approved; the 3-task micro-pilot and the confirmatory
experiment are NOT authorized. Everything below is zero-real-call, no
GPU initialization, historical frozen results untouched.

## Completed this round

**G1 — unified real-reward settlement (DONE).**
`deadline_reward_v1/joint_verification_runner.py`:
- terminal Q via `score_v21` + `contract_v2_gold` (production v2.1
  contract; the historical `reward.settle` v1-close path is left
  untouched — no frozen artifact modified);
- per-task realized rows: Q / physical C / real T / frozen D /
  on-time-correct / **realized R_task** (frozen λ, c0);
- predicted vs realized strictly separated: predictions live ONLY in
  the pre-execution `arm_decision` ledger (P0-B); settlement rows are
  computed from terminal outputs and never feed back into decisions;
- gold enters ONLY at settlement (T3 counterfactual test: perturbing
  the gold map changes settlement Q and nothing in the decision
  events).

**G2 — MONO baseline (DONE, six arms).**
`ARMS = (SS, DS, SD, DD, NONE, MONO)` — SIX (operator correction).
MONO = single-model full-context execution with a PRE-DEFINED fallback
(exactly one same-model retry when no value parses; extraction =
strict JSON then single-numeric-token, deterministic). Engine note:
MONO occupies the terminal v-slot with stage/kind labeled MONO — the
frozen four-node topology is untouched.
**Fault-semantics ruling implemented**: MONO has no r node; the DAG
arms' D3_r injection is NOT claimed equivalent for MONO. MONO is a
**descriptive baseline outside the same-fault causal contrasts**
(ΔR and I are computed over the five DAG arms under identical D3_r
draws). An OPTIONAL mono-side answer-corruption condition exists for
sensitivity ONLY (`mono_corrupt_uids`), explicitly labeled
non-equivalent, exercised in T4.

**G3 — deadline feasibility analysis (ANALYSIS ONLY, nothing frozen).**
`evidence/G3_FEASIBILITY.json` from E6 read-only:
- task-E2E quantiles P40/P60/P80 = 142/204/217 s — BUT the E2E range
  is compressed by batch saturation (position sensitivity ~0: first vs
  last in cell both ≈148 s median): under E6's cell structure nearly
  ALL tasks finish near the batch wall, so absolute E6-derived tiers
  would mostly measure BATCH POSITION, not scheduler ability —
  confirming the operator's objection;
- queue-free service+switch: median 46.8 s, P90 377 s, P99 1820 s —
  heavy-tailed; a workable tier design must anchor on per-task
  queue-free work (e.g., D_i = multiplier × measured service+own-switch
  of the PLANNED path, multipliers pre-registered) with the multiplier
  sweep validated for decision discrimination at micro-pilot scale —
  **NOT frozen now, per ruling**.

**Confirmatory-design revisions (DONE in the admission file v2 below).**
- primary ΔR = R_DD − R_SS; secondary DD−DS, DD−SD, interaction I;
- P2 exposure audit → P3 fresh-frozen panel is the confirmatory choice,
  P2 demoted to exploratory/sensitivity;
- power redesigned on DIVERGENT-task fraction: E6 fault30 shows
  dR≠0 on only 45% of tasks (9/20) and I≠0 on 45% — effective paired
  sample = n × 0.45, so nominal n must be ~2.2× the divergent-n
  requirement (table in the admission file);
- budget re-estimated for six arms incl. retries/switches and
  cumulative accounting.

**Zero-call tests — `test_joint_verification.py` 6/6 PASS**
(`evidence/JOINT_VERIFY_ZERO_CALL.json`): T1 six-arm end-to-end
recording (every row Q/C/T/D/on-time/R); T2 reward manual verification
incl. exact T==D boundary (on-time, no penalty) and T=D+ε (all three
penalty terms); T3 gold isolation (stable-field decision comparison —
volatile timestamps excluded); T4 fault isolation both directions
(DAG D3 never touches MONO; mono corruption fires twice — initial +
pre-defined fallback — clears, and a subsequent DAG cell is clean);
T5 interruption & ledger (INCOMPLETE artifact and official file each
never overwritten). No real-model entry point is enabled anywhere.

## Remaining blockers before an approvable micro-pilot

| # | blocker | what unblocks it |
|---|---|---|
| B1 | D-tier rule not frozen (G3 deliberate) | a pre-registered multiplier-on-queue-free-work rule + discrimination check at micro-pilot scale (analysis now, freeze at pilot authorization) |
| B2 | P3 confirmatory panel not drawn | fresh frozen-panel construction (same lineage filters, all used UIDs excluded, new seed) — zero-call, needs its own freeze+hash |
| B3 | execution wiring for the six-arm runner on the real path (budget/manifest/preflight) | extend the supplementary-runner GO machinery to joint_verification (zero-call) after B1/B2 |
| B4 | operator GO | explicit, separately worded |

**Approvable micro-pilot conditions (proposal)**: 3 tasks × 6 arms,
sole purpose = complete execution + correct records; D-tier rule
frozen per B1; budget ≤ 60 requests; fail-stop (any failure → report,
no in-round relaunch); results never quoted as effectiveness.

## Status

Stopped after the zero-call build, per mandate. No real model call, no
GPU, no protocol change; only named files staged.
