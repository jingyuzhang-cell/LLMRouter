# DAG_MAINLINE_EVIDENCE_AUDIT — paper-core evidence inventory, pairing validity, and net-benefit determinations

Zero real model calls, zero GPU, no new frameworks, no protocol changes,
no frozen-data modifications. Every entry cites the original experiment
path, panel/identities, conditions, scoring convention, and code state.
Repository HEAD at audit time: `9df41f4` (line of custody: all cited
artifacts committed before this audit).

Research questions under audit:
- How much quality does DAG decomposition lose, and how much does
  heterogeneous node-level model assignment recover?
- After node-execution-instance failures, does dynamic recovery produce
  net benefit beyond its extra cost and latency?
- Which claims are PROVEN, which exploratory, which stub-only, which
  unsupported?

---

## 1. Existing experiments and source-file index

| # | experiment (path) | panel / identities | conditions | scoring | code state | real calls |
|---|---|---|---|---|---|---|
| E1 | `static_dag_v0/decomposition_benchmark/paired_run/RESULTS.json` (+ `DECOMPOSITION_BENCHMARK_PROTOCOL.json`, `DECOMPOSITION_PAIRING_AUDIT.json`) | 300 tasks frozen before execution (MultiHiertt 100 + TAT-QA 200), one-shot, temp 0 | mono-L vs DAG-L/L vs DAG-L/M; strata by derivation op count | per-arm contract (mono `extract_value` close; DAG `exec_calc(expr, parse_facts(ext))` close) | commits e522383/5748b63/872d7fb (protocol frozen before execution) | YES |
| E2 | `static_dag_v0/decomposition_benchmark/loss_attribution/RESULTS.json` | TAT-QA 200 subset of E1 | A/B/C/D arms (post-hoc attribution arms) | same convention family | same | YES (derived from E1 executions) |
| E3 | `static_dag_v0/PAPER_EVIDENCE.md` (120-task multidag panel; `BENCHMARK_PROTOCOL.md`, `MULTI_SEED_REPORT.md`, `STAT_CHECK.md`) | 120 frozen tasks; 3 fault seeds 20260923/24/25 at 10/20/30% | Single(retry) / Static DAG / Dynamic DAG (local recovery); RD vs FG recovery efficiency; attribution + detection diagnostics | json_value-close after parser correction; gold only for scoring | frozen 2026-09-23; parser-corrected replay | YES |
| E4 | `paper_method_feedback_aware_dag/FINAL_AUDITED_RESULTS.md` (+ `chapter4_audit_20260926/`) | re-audit of E3 (+frozen200/oracle lines) on repo `61f3655` | corrected arms RD/FG; per-state regret; oracle unions; superseded-claims ledger | corrected keys/fee/fault-namespace fixes | audit dated 2026-09-26, status BLOCKED_FOR_MANUSCRIPT_REWRITE | re-analysis (no new calls) |
| E5 | Formal joint-search campaigns: `collab_scheduler_v1/joint_search_v1/formal_campaign_v2*/` (+ `FINAL_INTEGRATION_REPORT.md`, `STATISTICAL_REPORT.md`) | search panel (TASK_PANEL_V1: 8 search + 16 test + 2 reserve) × 48 X/Z configs × 6 methods; fault30/clean states | (Q, C, L) objective evaluation of jointly chosen (X, Z); MeteredExecutor semantics | v2.1 canonical Q (`score_v21` + `contract_v2_gold`) | code 9d770ef (six methods aligned); settlement audit 23/23, net-benefit audit 46/46 (structural) | YES (search spend real; see §3 grading) |
| E6 | `deadline_reward_v1` supplementary measurement: `supplementary_runs/run_20261012_092146/`, `PRIORS_REAL_V1_quality.json` | frozen 20-task panel × 2 conditions (clean / fault30_D3) × 5 arms | SS/DS/SD/DD/NONE via frozen arm_entry; full cascade | v2.1 terminal only | executed under freeze manifest (this line, commit 9b29672 ancestry) | YES — **confounded: M5 enumeration defect live at run time** (SS/SD no-candidate blocks; fixed later in 351ed91, never re-run) |
| E7 | `deadline_reward_v1` M1–M6 + stub suites (`evidence/M*_EVIDENCE.json`, `ADMISSION_CHECK.json`, `M5_CLOSURE_FIX.json`, `v23_pilot`) | stub scenarios, golden fixtures | five-arm behavioral proof, decision goldens, 750-episode stub pilot | stub contracts | green at HEAD | NO (stub) |
| E8 | reliability round (`reliability_runs/run_20261012_*`, `RELIABILITY_ROUND_CLOSEOUT.md`) | fit 24 / screen 12 / validate 90 (partial) tasks | full-menu cascade latency; coverage exploration | reliability_stats (exact CP / PB regions) | closed 2026-10-12; formal certification NOT ESTABLISHED | YES (exploratory only) |

Naming crosswalk (task 2 requirement — **no equivalence asserted without
proof**):

| NET-BENEFIT protocol family (`NET_BENEFIT_PROTOCOL_DRAFT.json`; results STUB-only) | closest real instance | equivalence status |
|---|---|---|
| A_single | E1 mono-L; E3 Single(retry) | same concept, DIFFERENT panels/protocols/retry semantics — not provably equivalent |
| A′_single_cross_fallback | none real | no evidence |
| B_same_model_dag | E1 DAG-L/L; E3 Static DAG | same concept, different panels; Static has no fallback — not equivalent |
| C_static_hetero | E1 DAG-L/M; Formal X-configs (static Z) | different panels/scoring — not equivalent |
| D_dynamic_local | E3 Dynamic (RD); Formal LOCAL_REROUTE configs | different panels/semantics — not equivalent |
| E_dynamic_full | E3 FG arm (as control); Formal FULL configs | FG is a control arm, not the protocol's E — not equivalent |
| M6 SS/DS/SD/DD/NONE (E6/E7) | own protocol (V2.3) | separate lineage; only stub-level behavioral separation proven; real run confounded |

---

## 2. Main results per conclusion (with data)

### RQ1 — decomposition loss (mono vs same-model DAG)

**E1, TAT-QA stratum (n=200, strictly paired, frozen-before-execution):**
52.5% → 31.5%, **Δ = −21.0pp**, McNemar p = 4.3e-07, CI [−28.5, −13.5];
tokens 832→1092 (+31%), latency 2.02→2.28s (+13%). MultiHiertt stratum
(n=100): 11% → 17% (+6pp, p = 0.21, ns). Overall 300: −12pp (p=1.3e-4).
**The loss is real, large, and domain-dependent: severe on TAT-QA
finance QA, absent-to-reversed on MultiHiertt.**

### RQ2 — heterogeneous allocation recovery (DAG-L/L → DAG-L/M)

**E1, TAT-QA:** 31.5% → 40.0%, **Δ = +8.5pp**, p = 0.0015, CI
[+3.5, +13.5]; tokens 1092.3 → 1092.5 (cost-neutral), latency −2%.
MultiHiertt: −2pp (ns). Overall: +5pp (p = 0.0135). **On the stratum
where decomposition hurts, re-assigning the reasoning node to a
different model recovers ~40% of the loss at zero marginal cost.**
Remaining gap vs mono-L: −12.5pp.

### RQ3 — recovery benefit after instance failures (local vs full vs none)

**E3/E4 (120 tasks, 3 seeds, corrected RD/FG re-analysis):**
- Dynamic(local) vs Static(no repair) under faults: +7.5±1.4 /
  +8.9±2.1 / +9.7±3.8 pp at 10/20/30%, per-seed paired p ≤ 0.001,
  Help/Harm 11/0, 14/0, 17/0 (zero harm every seed). Clean: +5pp,
  p=0.109 (directional only). ⚠ audit layer (E4): the 2026-09-26 audit
  blocks manuscript-level sign-off of the family pending repaired-path
  real outputs (cache-replay coverage only 1/54 Exact combos; Frozen
  arms incomplete) — the arithmetic passes, the family is not
  re-certified.
- Local scope vs full replay (corrected arms): Q .3667 vs .3333
  (+3.33pp, McNemar 4/0, **p = 0.125 — not significant**); efficiency
  −33.0% tokens, −50.3% adaptation calls, −38.3% service latency;
  older pre-audit numbers (.40 vs .375, p=0.25) superseded. **The
  LOCAL-vs-FULL claim that survives is efficiency, not quality.**
- Recovery attribution (E3 Table 3): injected faults recoverable
  29–100% by node type; clean-run wrong answers largely irrecoverable
  (evidence-wrong 12–16%, reasoning-wrong 0%); cross-model verifier
  detects reasoning errors at 82% precision but repairs 21% —
  **detection ≠ repairability ≠ fault localization** (the D5 lesson
  re-confirmed in E6: 3 tasks where v was right, r wrong, contract
  flagged v).

### RQ4 — static vs dynamic recovery; fixed vs dynamic assignment

- Recovery-scope dimension (local vs full): real evidence above.
- Scope × assignment JOINT dimension (the paper's DD-style joint
  action): **no real paired evidence**. E5 evaluates the joint (X, Z)
  space and searches it with six methods, but as configuration search
  over a test panel — its published comparisons are search-efficiency
  and engineering-integration statements, not a deployed-arm
  SS/DS/SD/DD contrast; E6's real five-arm run is M5-confounded.
- Dynamic assignment alone (B→C above) is proven at the STATIC
  allocation level (one frozen hetero assignment), not as an online
  re-assignment policy.

### RQ5 — recovery cost, latency, and deadline behavior

- E1: decomposition costs +31% tokens / +13% latency; hetero
  reassignment ~free.
- E3: Dynamic costs 2324 vs Static 1503 vs Single 603 tokens/task
  (clean); RD vs FG efficiency above; FG needs ~2.1× budget to be
  violation-free at 1.2× (45% violations vs RD 0/120) — the only
  deadline-adjacent evidence (budget-violation sweep, not deadline
  tiers).
- **True deadline-conditioned experiments (D-tiers, on-time
  probability, deadline-driven model choice): NEVER RUN.** E8's
  reliability line closed with formal certification NOT ESTABLISHED
  (exploratory: fit-declared P90s under-cover on 6/10 cells; predictor
  mismatch is a measured boundary, not a certified prior).

---

## 3. Strict pairing and statistical-validity check

| comparison | same tasks? | same conditions/budget? | paired test | verdict |
|---|---|---|---|---|
| mono vs DAG-L/L (E1) | YES (300, frozen) | YES (one-shot, temp 0, same context) | exact McNemar + CI | **VALID** |
| DAG-L/L vs DAG-L/M (E1) | YES | YES | exact McNemar + CI | **VALID** |
| Single vs Static vs Dynamic (E3) | YES (120) | YES per seed; 3 seeds | McNemar + bootstrap CI; cross-seed consistency | valid, with E4 audit overlay (blocks manuscript sign-off pending repaired-path outputs) |
| RD vs FG (E4 corrected) | YES (120) | YES (same rules) | exact McNemar p=0.125 | valid but **null result for quality** |
| Formal six-method search (E5) | search panel (n=26) | per-method budgets | STATISTICAL_REPORT | search-efficiency evidence only; ❌ observation-influences-selection special test pending; ❌ real-LLM Q-differentiation pending (FINAL_INTEGRATION §4) |
| A–E net-benefit family | — | — | — | **STUB ONLY** (`NET_BENEFIT_RESULTS.json` self-labeled structural proof); no real run |
| SS/DS/SD/DD/NONE (E6) | YES (20) | YES (frozen) | Wilson CI only (n=20) | **CONFOUNDED** (M5 defect at run time); calibration-scope only |
| SS…DD behavioral separation (E7) | stub | stub | deterministic ledgers | mechanism proof only |
| 56% workflow scheduler | TAT subset | — | — | **BLOCKED by E4 §8** (generation chain missing; not quotable) |

Statistical-validity notes: E1's CIs are paired bootstrap + exact
McNemar (appropriate); E3's fault columns are 3-seed mean±SD with
per-seed paired tests (cross-seed consistency reported, no pooled
p-values); E4 explicitly withdraws mixed-seed oracle claims and
documents a McNemar mis-recording (OOF 20/10 p=.0987 vs recorded .1975)
in a historical artifact.

---

## 4. Claim grades

### 已证实 (protocol-compliant real paired data + tests)

1. **DAG decomposition quality loss on TAT-QA-style finance QA**:
   −21.0pp (52.5→31.5), p=4.3e-07, 200 strictly paired frozen tasks
   (E1), with +31% token and +13% latency cost. Domain-scoped: NOT
   established on MultiHiertt (+6pp ns, n=100).
2. **Heterogeneous node-level assignment recovers part of the loss at
   ~zero marginal cost**: +8.5pp (31.5→40.0), p=0.0015, same panel
   (E1); cost-neutral, latency-neutral.
3. **Local recovery scope dominates full replay on efficiency**:
   −33% tokens / −50% calls / −38% latency with no significant quality
   difference (E4 corrected arms; the efficiency direction is also
   supported by the budget-violation sweep).

### 探索性支持 (real observations; power/coverage/condition limits)

4. **Dynamic(local-recovery) vs Static(no-repair) robustness under
   faults**: +9–14pp, p≤0.001 per seed, zero harm — real 120-task
   panel, but under the E4 audit overlay (repaired-path outputs
   incomplete; family blocked for manuscript sign-off until re-run or
   explicitly accepted as-is by the operator).
5. **Dynamic vs Single crossover at ≥30% faults / hard subsets**:
   cross-seed consistent (+4.4pp overall; hard-subset ahead at every
   rate) but single-seed ns — directional.
6. **Recovery attribution structure**: injected faults recoverable,
   clean failures mostly irrecoverable; 82% detection precision vs 21%
   repair rate (diagnostic subsets n=78/34).
7. **Predictor-mismatch boundary** (E8, closed line): declared-P90
   under-coverage 6/10 cells (exploratory); parse-proxy vs terminal
   correctness gap (E6: beliefs 0.78–1.0 vs realized 0.05–0.45).
8. **Full-menu cascade latency characterization** (E8 fit object,
   n=24/36 per cell, replication-stable).

### Stub/模拟支持 (mechanism only)

9. Five-arm SS/DS/SD/DD/NONE behavioral separation (deterministic stub
   ledgers; policy entry-point proof).
10. Net-benefit decomposition arithmetic (B-REC/B-REA/B-JOINT) and the
    A–E family comparison (STUB structural proof only).
11. Formal-line six-method selector machinery, cost predictor (MAPE
    4.5% on stub-shaped costs), qNEHVI objective alignment.
12. M6 deadline-reward decision loop, goldens V1/V8/V9/V10, M5 closure
    fix scenarios.

### 尚无证据 (no legitimate observation)

13. **Joint scope×assignment interaction benefit (the DD-vs-SS "joint
    advantage") on real tasks** — no unconfounded real run exists.
14. **Any deadline-conditioned claim** (on-time under tight D, dynamic
    fast-model selection under time pressure, deadline-weighted reward
    benefit).
15. **A′ (cross-fallback) arm; 56% workflow scheduler as formal
    performance; adaptive-entry routing beyond post-hoc simulation**
    (oracle-equality only).
16. **Formal 90% latency-quantile certification** (NOT ESTABLISHED,
    closed).

---

## 5. Net-benefit determinations (Q, C, L, deadlines) and the minimal-gap list

**Relative to single-model execution:** clean → single model wins on
quality AND cost (Pareto-dominates; +15pp, p=0.0005) — decomposition
should NOT be entered on easy/clean work (proven). Under ≥30% faults on
hard tasks → dynamic DAG is the only non-dominated high-quality point
(cross-seed; overall crossover directional +4.4pp).

**Relative to static DAG (no recovery):** recovery pays under faults
(+9–14pp, zero recorded harm; exploratory pending E4 sign-off);
on clean it does not (+5pp ns at +55% token cost vs Static).

**Recovery scope:** choose LOCAL over FULL — same quality (ns),
−33/−50/−38% cost/calls/latency (proven direction).

**Dynamic×heterogeneous interaction:** unproven (no real unconfounded
data). The two PROVEN levers (static hetero allocation; local recovery)
are separable; their interaction is a hypothesis.

**When not to recover / fall back to single:** clean conditions
(proven); low-fault easy-task regimes (single ahead at 10% overall);
irrecoverable failure classes (reasoning-wrong 0% repair) argue for
detect-and-abort rather than blind retry — supported by attribution
diagnostics.

### Minimal gap list

**Zero-call re-analyses sufficient (recommended first):**
- g1. Reconcile E4's audit overlay into a final per-claim eligibility
  table for the 120-task family (which of Table 1/2/3's numbers may be
  quoted, with which qualification) — pure documentation from existing
  audit files.
- g2. Cross-check E2 loss-attribution arms (A/B/C/D = .525/.315/.35/.27)
  against E1's numbers and document arm semantics (they differ from
  E1's C2 arm) — read-only.
- g3. Consolidate E5's campaign search results into one statistical
  summary from existing CAMPAIGN artifacts (read-only).
- g4. Write the E1↔E3↔E5↔E6 scoring-convention map (close() vs v2.1)
  so cross-experiment quoting is explicit.

**Genuinely requires future real experiments (only if the paper claims
them):**
- g5. One unified A–E (or SS/DS/SD/DD post-M5-fix) paired run on a
  fresh frozen panel under one protocol — the single experiment that
  would upgrade claims 13 (joint interaction) from unsupported to
  testable.
- g6. Deadline-tier experiments (the V2.3 confirmation design) for any
  time-pressure claim.
- g7. Repaired-path re-execution of the 120-task family if the operator
  wants E4's blocks lifted rather than qualified.

**Not recommended**: further reliability-certification loops (closed
by ruling); re-running E6 as-is (M5-fixed runner exists; only meaningful
as part of g5's design).

---

### Bottom line

The paper's defensible core TODAY: **decomposition loses 21pp on
finance QA (proven); a zero-cost heterogeneous reassignment recovers
8.5pp (proven); when failures occur, local-scope recovery buys 9–14pp
robustness at zero recorded harm, and dominates full replay on
efficiency (proven direction, audit-qualified); detection is largely
solved while repairability is the bottleneck (diagnostic).** The joint
dynamic-scope×dynamic-assignment thesis — the reward-punishment
mechanism's headline — currently has stub-level mechanism proof and
confounded/incomplete real evidence (g5). All deadline-linked claims
remain untested (g6).
