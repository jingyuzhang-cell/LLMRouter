# M5_ACCEPTANCE — dynamic node-level model reassignment

Authorization: operator M5 review GO (2026-10-11, baseline 758ec8a).
Scope: review the EXISTING M5 implementation, fix in-scope issues, add
necessary tests. M6, phase-3 formal acceptance, production integration,
net-benefit, and real-model calls remain HOLD. Zero real model calls.

## 1. What existed vs what this round changed

Existed (delivered in the superseded "keep going" round, commit 7459698,
inside `policy.py`): candidate enumeration (NONE/LOCAL/FULL × menu
variants, M3-adjudicated) and plan application — but physically mixed
with M6 scoring code in one module, so M5 could not be reviewed in
isolation.

**This round's structural fix (no behavior change):** the M5 machinery
moved to its own module **`reassign.py`** — `enumerate_candidates`,
`apply_decision`, `Candidate`, `_menu_variants`. `policy.py` (M6) now
IMPORTS it. Full regression after the move: all suites green
(161/161 + the new M5 suite). `reassign.py` imports stdlib +
`dag_closure` ONLY — predictor/compensator/reward/policy-free, proven
by AST import check (`m5_c9_module_isolation`).

## 2. The ten mandated checks → evidence

| # | Requirement | Evidence (all in `test_m5.py`, 12/12) |
|---|---|---|
| 1 | π reaches PHYSICAL calls, not just fields | `m5_c1`: post-decision ledger call models == chosen π exactly, both regimes |
| 2 | per-task models differ on the same node | `m5_c2`: one faulted task applies loose π (v=large) while the clean task's v runs coder — same node, two models, one batched V1 stage |
| 3 | DONE rebind requires re-execution | `m5_c3` (enumeration-level: every candidate rebinding a DONE node has it in its execute set) + M3 f5/s5 (judge rejects otherwise) |
| 4 | RUNNING + downstream protected | `m5_c4` (no enumerated candidate executes/touches a RUNNING node) + M3 s6/f3/f4 (judge rejects R/π and downstream invalidation) |
| 5 | FAILED real retry, no stale-success cache | `m5_c5` (e1 retried as a REAL charged call on the chosen alternative model; M4 b3 + M3 f1/f2 pin the semantics) |
| 6 | menus strictly enforced | `m5_c6` across every enumerated candidate; M3 f5/f6 at the judge |
| 7 | closure + cache identity after upstream re-exec | `m5_c7`: e1 retry invalidates r,v (executed as new calls); e2's frozen identity unchanged → ZERO new e2 call; M3 S-tests + M4 b4 |
| 8 | M1 ledgers retained | `m5_c8`: switch events + task summaries present, tokens metered exactly (3 new × 100 post-decision), untorn; E2E via task_summary |
| 9 | legal-view-only interface | `m5_c9_no_illegal_payloads` (no gold/fault/answer payloads in candidates) + module isolation AST + M2/M3 firewall suites |
| 10 | M4 equivalence still passes | `test_recovery` 28/28 re-run in this round's regression |

## 3. Decisive scenario V10-M5 (mandated §四)

ONE task, ONE fault observation (e1 corrupted @large), identical node
states / frozen cache identities / history costs; ONLY the
remaining-time regime varies. A **TEST-LOCAL time rule** (NOT the M6
policy — explicitly out of M5 scope) selects a legal candidate per
regime from the enumerated set: loose → highest-q models, tight →
fastest models, per the synthetic priors.

Results: loose π = {e1: coder, r: large, v: **large**}; tight π =
{e1: coder, r: medium, v: **coder**} — different LEGAL allocations per
remaining time, both REALLY executed: ledger call models match π
exactly on every executed node; re-execution set {e1, r, v} matches the
M3 closure; e2 reused with no new call; post-decision cost exactly
300 tokens in both regimes (3 new calls × 100).

**Claim discipline:** this proves M5's time-conditioned
model-assignment EXECUTION capability. The A/B/C quality/deadline
filtering and the "choose B" decision are M6 and are NOT claimed here
(the M5 suite contains no predictor/filter/scoring import at all).

## 4. Gaps / blind spots (honest)

- π application for PENDING nodes happens in the stage driver (the
  mainline's planned-stage execution under chosen π); `apply_decision`
  itself covers non-PENDING retries. The M5 test drives both paths
  exactly as the mainline prescribes, but there is no single
  "apply_whole_plan" API — M6's episode driver composes them. If the
  operator prefers an M5-owned single entry point, that is a small
  refactor for the next round.
- No multi-EPISODE π persistence (out of scope everywhere so far).
- Candidate enumeration is exhaustive over menus (≤36 variants) — fine
  at 4 nodes; scaling behavior is an M6/calibration concern, not M5.
- The M4-era caveats still apply to the underlying engine conventions
  (cached-usage VALUE differences vs production aliases; documented in
  M4_REPORT).

## 5. Regression & evidence

This round: M5 suite 12/12; full repo: M1 21/21 · M2 24/24 · M3 37/37 ·
M4 28/28 · **M5 12/12** · M5+M6 18/18 · phase-3 19/19 · boundary 14/14
= 173 checks green, zero real calls, socket-blocked. Evidence:
`evidence/M5_EVIDENCE.json`, ledgers under `evidence/m5_runs/`.

**Status: M5 acceptance submitted. M6, phase-3 formal acceptance,
production integration, net-benefit, and real-model experiments remain
HOLD pending separate authorization.**
