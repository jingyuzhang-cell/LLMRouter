# M5_ERRATA — final-acceptance targeted fixes (operator review of ff7ba93)

Baseline: commit ff7ba93. Authorization: M5 targeted fixes + zero-call
regression only; M6, phase-3 formal acceptance, production, net-benefit,
and real-model experiments remain HOLD. All four mandated tasks closed;
M5 suite now 20/20; full repo regression green (193 checks); zero real
model calls; frozen Formal/net-benefit evidence untouched.

## Task 3 (done first, root-cause first) — report/evidence mismatch

Reproduced: `M5_EVIDENCE.json` records loose/tight e1 = **medium**; the
acceptance text said coder. Root cause: the e1 menu profiles tie on
q (all 0.99) and coder/medium tie on latency (0.8); the declared
test-rule tie-break (score tuple, then π-tuple ordering) yields
**medium** in both regimes — the EVIDENCE was correct, the report
paragraph was a hand-copy slip. Fix: text aligned to the replayable
evidence + new guard `m5_v10_pi_matches_rule` pins the rule's actual
output so any future drift fails the suite. No evidence file was edited
to match prose.

## Task 1 — REAL time-state input, boundary made explicit

New tests (`m5_t1_*`): same task/fault/history/costs, only the DEADLINE
differs (30 vs 200) → `state.d_remain` differs by exactly 170 at the
decision point (asserted). The M5 machinery (enumerate + apply) is
deliberately **time-invariant**: identical candidate sets under both
deadlines (asserted signature equality). The test-local time rule is
asserted NOT to read d_remain (`m5_t1_rule_not_a_policy`) — it is not
wrapped as a policy. Filtering/selection by d_remain is M6 and remains
unclaimed. **V10-M5 claim scope corrected:** M5 proves execution
capability per externally supplied selection; time-DRIVEN selection is
M6 (per the reviewer's boundary).

## Task 2 — static vs dynamic FULL, explicitly separated

`reassign.enumerate_candidates` now emits two distinct arms:
- **`FULL`** (static E-arm, unchanged): trigger nodes take menu
  variants, every NON-trigger node pinned to its PLANNED model — the
  exact semantics M4's T3a/T3b reference equivalence is proven against;
  `recovery.py` executes it; untouched.
- **`FULL_DYNAMIC`** (new): the frozen dynamic joint-action target —
  every legal re-execution node (non-fault r/v included) may be
  reassigned within its frozen menu, all candidates still M3-adjudicated
  (menus, closure, RUNNING, cache identity).

Tests (`m5_t2_*`): with an e1 fault (and its cascaded D3 on r — both are
trigger nodes), static FULL pins all non-trigger nodes to planned models
while trigger nodes vary over menus (as `recovery_plans` prescribes);
dynamic FULL offers candidates with r/v different from plan, all legal;
executing one dynamic FULL candidate puts ALL FOUR nodes on the chosen π
in the ledger — changed/fresh nodes as REAL charged calls, while an
identity-unchanged node may legally ALIAS (the deliberate cost-saving
distinction from the static E-arm's forced re-execution). The M6 tie-break
arm tuple extended to include the new arm; the M6 scorer handles its
cache-hit cost naturally (zero-cost unchanged nodes) — no static-arm
semantics touched.

## Task 4 — unified plan application entry

`reassign.apply_whole_plan(engine, state, task, node_models, chosen)`:
applies the chosen (Z, R, π) so that recovery re-executions AND
subsequent PENDING nodes run under the SAME selected π — no silent
fallback to the originally planned model. Delegates non-PENDING retries
to `apply_decision` (M4 semantics: batching, corruption-after-metering,
no-cache rules), then runs each PENDING execute-set node in stage order
with the π-assigned model; returns the effective per-node models
(audit). Test `m5_t4_no_fallback_to_planned`: with a loose π
(v=large ≠ planned coder), the ledger's v call runs on large —
same model as the recovery retries' π, planned model never reappears.
Batching, cost metering, E2E, and the M4 static-reference semantics are
preserved (full regression incl. test_recovery 28/28).

## Regression

M1 21/21 · M2 24/24 · M3 37/37 · M4 28/28 · **M5 20/20** (12 prior + 8
new: t1×3, t2×3, t4×1, pi-matches-rule guard; two prior assertions
corrected — static-FULL pins NON-trigger nodes (e1's D3 cascade makes r
a trigger node), and dynamic-FULL's unchanged node is a LEGAL cache
alias rather than a forced physical call — both were test-expectation
errors against correct semantics, recorded here) · M5+M6 18/18 ·
phase-3 19/19 · boundary 14/14 = **193 checks, zero real calls.**

## Addendum — final enumeration-gap fix (operator review of 393b8fb)

Gap: FULL_DYNAMIC's model free variables covered only FAILED ∪ PENDING;
DONE non-FAILED re-execution nodes (e.g. r) were pinned to planned
models — contradicting the frozen dynamic target.

Fix: `_menu_variants` over the ENTIRE legal re-execution set R (the
full graph). Static `FULL` untouched (requirement 2: non-trigger nodes
still pinned to planned models — M4 T3a/T3b reference semantics
unchanged, test_recovery 28/28).

New decisive tests (`m5_g1_*`, reviewer's exact state: e1 FAILED,
e2 DONE, r DONE, v PENDING, built on a real engine run):
- FULL_DYNAMIC contains legal candidates with r=medium AND r=large;
  static FULL offers only r=planned(medium).
- every dynamic candidate menu-legal and judged legal.
- r RUNNING ⇒ ALL FULL/FULL_DYNAMIC candidates rejected outright
  (judge: running_in_R / running_node_immutable) — never silently
  rebound; NONE candidates never touch r.
- executing a r=large dynamic candidate: ledger r model == 'large',
  REAL charged call (100 tokens, latency metered), and every post-
  decision call model equals the chosen π node-for-node.

Downstream (recorded): the phase-3 "FULL wins" scenario now correctly
elects a FULL_DYNAMIC winner (it can upgrade the planned coder v to
large; static FULL is pinned to coder q=0.85 vs dynamic 0.95) — the
scenario's intent (full-graph plan beats every LOCAL due to the
q_obs=0.70 e2 reuse) is unchanged; its reconciliation now follows the
CHOSEN arm. M4 static equivalence unaffected.

M5 suite 24/24; full regression 8 suites = 185 checks ALL PASS; zero
real model calls.

**Status: enumeration gap closed; paused for final M5 acceptance and
the M6 admission review.**
