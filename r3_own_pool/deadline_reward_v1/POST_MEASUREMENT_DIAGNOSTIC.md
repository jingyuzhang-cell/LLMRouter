# POST_MEASUREMENT_DIAGNOSTIC — node-failure, degradation & quality-mismatch audit

Zero real model calls. Data basis: `supplementary_runs/run_20261012_092146`
(CELL_RECORDS 10 cells × 20 tasks; TASK_LEDGER 702 logical calls /
124 physical, 37 switches, 185 arm_decision events, 200 task summaries;
DISPATCH 124=124). Evidence: `evidence/POST_MEASUREMENT_DIAGNOSTIC.json`.
No M1–M6 algorithm, threshold, weight, panel, or run artifact was
modified. **No strategy-ranking inference is drawn anywhere below.**

## 1. Degradation-reason audit (per task, per arm)

Operator-quoted counts CONFIRMED from the row records:

| cell | degraded/20 | decisions | chose | reason classes |
|---|---|---|---|---|
| clean\|SS | 15 | 18 | 3 | 15× static-recipe-no-match |
| clean\|DS | 18 | 18 | 0 | 18× quality (q_min) |
| clean\|SD | 18 | 18 | 0 | 15× no-legal-recovery-action, 3× q_min |
| clean\|DD | 17 | 18 | 1 | 17× q_min |
| fault\|SS | 11 | 19 | 8 | 11× static-recipe-no-match |
| fault\|DS | 19 | 19 | 0 | 19× q_min |
| fault\|SD | 18 | 19 | 1 | 11× no-legal-recovery-action, 7× q_min |
| fault\|DD | 17 | 19 | 2 | 17× q_min |
| NONE (both) | 0 | — | — | no recovery machinery |

Zero time-constraint and zero budget-constraint rejections occurred
(D=3600 inert by design; 40.3K/800K tokens).

### Root cause of the SS/SD "no candidate" blocks — an M5 enumeration defect (newly identified)

For every e-node-only failure observed (final e1 or e2 FAILED with r
DONE — 15 clean / 11 fault tasks), the LOCAL candidate family came out
EMPTY. Mechanism, from the frozen code:

- `reassign.enumerate_candidates` builds LOCAL over `base_R = failed`
  with π variants over `free = {n for n,_ in j0.execute} | pending`
  (`reassign.py:68-71`); the M3 closure (on_incomplete='complete') pulls
  the invalidated DONE descendant r (and v) into `j0.execute`, so
  `free ⊋ R`.
- Every π over `free` therefore assigns a model to r, which is DONE and
  NOT in R — the structural rule "changing a finished node's model
  requires re-execution" rejects the plan
  (`dag_closure.py:119-121`, `done_node_model_change_without_reexec`).
- Hence ALL LOCAL variants are illegal whenever the failed set
  invalidates a DONE node outside R. LOCAL is reachable only when the
  failed set already covers the closure — observed exactly: SS's chosen
  clean tasks had failure set {e1,e2,r} (nothing DONE left to invalidate)
  and fault-side chosen sets were {e2,r}, {r}, {e1,e2,r}.

Consequences in this run: (a) SS (static recipe = LOCAL/planned) has no
match on e-failures → `degraded=True`; (b) SD (policy over LOCAL-only)
sees an empty pool; (c) because the runner's D10 semantics skip the V
stage for degraded tasks, **those tasks never ran v at all**
(logical_calls==3, empty final answer, Q=0) — the dominant driver of
clean|SS 0.10 vs clean|NONE 0.45. The stub evidence chain never exposed
this because its failure scenarios were r-only (gate 2 / smoke).

**Classification: this is an M5 candidate-enumeration defect (π-domain
vs closure mismatch for non-leaf failures), NOT a policy decision and
NOT a quality rejection.** Fixing it changes M5 → frozen-mainline
change requiring explicit operator authorization; NOT done here.

### The 8 correct-despite-failure tasks (clean|NONE) — divergence mechanisms

Node-contract failure and terminal correctness diverge through two
distinct, evidenced mechanisms:

1. **D5 compares v against r's value, not gold** (3 tasks:
   06ef962a, 2491bcc9, 5aab40b4 — v flagged FAILED while final ==
   gold exactly): when r is wrong (bad/partial facts) and v is right,
   the contract flags v. Node status is an INTERNAL-consistency signal;
   terminal v2.1 is gold-consistency; they disagree exactly when r errs
   and v does not.
2. **Partial-facts sufficiency** (5 tasks, e2-FAILED only): e1's facts
   alone sufficed for r's expression and v to reach the correct value —
   the e2 contract failure removed context the answer did not need.

### Cache identity & execution-order effects (no strategy inference)

- Retried (task, node) pairs across the run: 67 identical answers, 13
  changed (2× e2, 1× e1, 6× r retry-vs-R1, 3× v same-stage across cells,
  1× r multi-arm). Changed upstream answers shift downstream
  input-identities; later cells' 0–3 new-call metering is consistent
  with this (tasks whose upstream changed AND were executed in the later
  cell re-called; degraded tasks consumed nothing).
- Later cells observed post-retry upstream state from earlier cells
  (one shared engine): identical-answer retries preserved identities
  (cache hits); changed-answer retries would have forced new downstream
  calls wherever the later arm actually executed them. The NONE cells'
  near-total cache reuse (fault|NONE: 2 new) shows the fault condition's
  terminal outcomes were derived from the same underlying responses as
  clean's — the D3 corruption is applied per-call after metering and
  never entered the cache.

## 2. Quality-prediction mismatch diagnosis

### The three rates, never mixed

| quantity | e1\|large | e2\|large | r\|medium | v\|coder |
|---|---|---|---|---|
| node parse success (belief, trajectories) | 1.00 | 0.25 | 0.78* | 1.00 |
| node parse success (THIS run, physical) | 16/28=.571 | 3/30=.10 | — | 30/32=.9375 |
| node contract DONE (final status, clean\|NONE) | 16/20 | 3/20 | 17/20 | 12/20 |
| terminal task correctness (clean\|NONE) | — | — | — | 9/20=.45 |

\* r belief is evaluability (0.7826), itself a proxy layer. Every layer
differs from the next: parse ≠ contract ≠ terminal. The e2 gap is
panel-dependent (trajectory 0.25 → this run 0.10).

### How min-composition produced the EARLY_STOP lists

For any candidate whose execute set includes a NEW e2 call,
q̂ = min(...) ≤ q̂(e2) ≤ 0.375 < 0.80 → infeasible. Hence:
- DS (π-planned pool: NONE/FULL/FULL_DYNAMIC-planned): every candidate
  either leaves the failure unrecovered (q̂→0) or re-executes e2
  (q̂ ≤ 0.375) → **all 18/19 decisions q_min-rejected, zero recovery
  calls** — EARLY_STOP by quality proxy.
- DD: same barrier across the full pool (17 both conditions); its rare
  executions (1 clean / 2 fault) were r-failure tasks where q̂(r|large)
  = 0.838 ≥ 0.80 made LOCAL feasible.
- SD's 3 q_min (clean) are the {e1,e2,r}-failed tasks whose LOCAL
  candidates existed but q̂ ≤ 0.25.
The binding belief is q̂(e2|large)=0.25 (realized 0.10) — the filter's
behavior is dominated by one node's proxy.

### What the current quality estimator can and cannot support

CAN: ranking candidates by a DECLARED proxy under frozen composition;
refusing recovery when even the proxy is below threshold; per-node
parse-layer diagnosis. CANNOT: statements about real task correctness
(proxy gap 0.78–1.0 belief vs 0.05–0.45 realized); any claim that a
feasible plan achieves ≥ 0.80 real accuracy; arm comparisons (CIs
overlap); Q_min suitability judgments beyond "0.80 is far above every
observed cell". Q_min, composition, and weights remain untouched.

## 3. Verdict table

| item | verdict | evidence |
|---|---|---|
| Recording completeness (calls/switches/summaries/panels) | **PASS** | 702/702 calls with t_start/t_end/latency/usage; 37/37 switches with wall_s; 200/200 task summaries; 10/10 panel starts |
| Degradation-reason taxonomy extractable per task | **PASS** | violations + node_status per row; uid-level lists in evidence JSON |
| SS/SD "no candidate" blocks explained | **FAIL (defect found)** | M5 π-domain/closure mismatch — LOCAL empty for e-node failures; mechanism + code refs above |
| Contract-vs-terminal divergence mechanisms | **PASS** | 3× D5-compares-to-r-not-gold + 5× partial-facts sufficiency, with task ids |
| Cache/order effect auditability | **PASS** | 67/13 identical/changed retries; metering consistent; no ranking inference |
| Three-rate separation | **PASS** | table above; never mixed |
| EARLY_STOP attribution | **PASS** | per-arm uid lists + binding-constraint analysis (q̂(e2)) |
| Quality estimator scope honesty | **CONDITIONAL** | proxy gap empirically confirmed; estimator unchanged |

## 4. Recommendations (require authorization; nothing auto-applied)

1. **M5 LOCAL enumeration fix** (pre-registered proposal): either
   restrict π variants to R ∪ PENDING (closure nodes keep bound models)
   or extend R to include closure-completed nodes. Requires new stub
   e-failure scenarios in the gate-2 smoke before any code change is
   accepted; frozen-mainline change process.
2. **Persist full decision rows** (mu_e2e, p90, p_on_time, estimator,
   estimator_claim) in arm_decision events — currently trimmed; blocks
   the predicted-vs-actual E2E audit (see DEADLINE_RELIABILITY_
   READINESS).
3. **Decide SS's no-match semantics** (degrade-and-skip-V vs
   complete-DAG-fallback like NONE) — an arm-definition ruling, not a
   code choice.
4. Latency re-derivation on cascade prompts for r/v cells (see
   readiness report) before any deadline experiment.
