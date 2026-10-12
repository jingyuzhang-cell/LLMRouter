# DAG_MAINLINE_EVIDENCE_FINAL — one-time research verdict (g1–g4 closed)

Baseline `8d1f817`. Zero calls, zero GPU, no protocol changes. This file
closes g1–g4 and issues the final research verdict; no further audit
rounds are spawned from its findings. Supremacy note: where this
verdict and any earlier summary disagree, this file + the cited
originals govern.

---

## g1 — Recovery-experiment citation eligibility (FINAL_AUDITED_RESULTS.md as the controlling audit)

| result family | eligibility class | basis |
|---|---|---|
| E1 decomposition pairs (300 tasks, incl. 52.5/31.5/40.0) | **REAL EXECUTION, not affected by the E4 audit** | E1 is the decomposition_benchmark line, frozen before execution with its own pairing audit; E4's blocks concern the 120-task chapter-4 family, Exact/Frozen replay, scheduler lines |
| E3 Single & Static rows (clean + fault, 3 seeds) | **REAL EXECUTION, unaffected** | no feedback/V-trigger machinery in these arms (Single same-model retry; Static no repair); FINAL_AUDITED's trigger fix does not touch them |
| E3 Dynamic (fault columns) | **REAL EXECUTION with corrected-analysis dependency** | Dynamic = RD trajectories; the 2026-09-26 audit corrected the V-stage trigger logic; §4 re-analyzed RD/FG on existing trajectories; the fault-scenario Dynamic anchor inherits that correction — cite as corrected-trajectory analysis |
| E3 Table 2 RD vs FG | **CORRECTED RE-ANALYSIS of existing trajectories** (the citable form) | corrected arms: Q .3667 vs .3333, Δ=+3.33pp, exact McNemar p=0.125, Help/Harm 4/0. **p=0.125 is a null result: it demonstrates failure to detect a quality difference at n=120; it is NOT evidence of equivalence, non-inferiority, or 'same quality' — the paper must say 'no significant difference detected' and separately report the proven efficiency deltas (−33% tokens, −50% calls, −38% latency)**. Efficiency = causal (scope manipulation within one trajectory family); quality = unproven either way |
| E3 Dynamic-vs-Static fault robustness (+9–14pp, zero harm) | **REAL with audit overlay → exploratory-leaning citation** | per-seed McNemar p≤0.001 on real paired data, but the audit's repaired-path outputs are incomplete for the family; quote with the overlay stated |
| Exact-Pareto 54 combos / Frozen arms beyond 5/12 / Scheduler per-state claims | **BLOCKED** | cache-replay coverage 1/54; Frozen Dynamic/Static fault lines missing outputs; per-state regret is historical arithmetic — none may be written as re-certified |
| 56% workflow scheduler | **BLOCKED (not quotable)** | FINAL_AUDITED §8: generation chain absent; not claimed as leak-free either |
| Oracle unions (+11pp) | **diagnostic upper bounds only** | recorded unions, not deployable performance |
| E6 five-arm real run | **CONFOUNDED (M5 defect at run time); calibration-scope only** | SS/SD no-candidate blocks were an implementation defect since fixed (351ed91) but never re-run |

**LOCAL vs FULL ruling (g1 mandate)**: efficiency difference = causal
and citable; quality difference = null (p=0.125, no equivalence claim
permitted); strategy-level causal benefit of recovery must rest on the
Dynamic-vs-Static contrast (exploratory-leaning under the audit
overlay), NOT on RD-vs-FG.

## g2 — Decomposition-loss attribution (E2 vs E1)

E2 (`loss_attribution_run.py`, TAT-QA-200 subset, executed on E1's
frozen trajectories plus two new real arms):
- **A = mono-L** (E1 frozen per-task) = 52.5%.
- **B = DAG-L/L** (E1 frozen per-task) = 31.5%.
- **C = full-context passthrough reasoning** (facts + up to 2,000 chars
  of original context, large model) = 35.0%.
- **D = gold-facts reasoning** (gold facts from the derivation replace
  the actual extraction) = 27.0%.
Harm set (A right, B wrong) = 56 tasks; C recovers 17, D recovers 13.

Causal identifiability ruling:
- Total loss A−B = 21.0pp is the DECOMPOSITION PIPELINE as a whole
  (prompt split + extraction + interface + reasoning-on-facts); the
  design cannot isolate "decomposition per se".
- C−B = +3.5pp is attributable to context passthrough (partial lever).
- **D−B = −4.5pp: feeding GOLD facts does not help — it hurts.** D
  changes fact values AND their derivation-alignment/format
  simultaneously (the r-model's expression is written against its OWN
  extraction's indices and format), so D is CONFOUNDED and cannot
  cleanly separate "wrong extraction values" from "interface
  misalignment". Report as a diagnostic: interface/format friction is
  at least co-equal with fact-value error in the loss.
- Residual after the best single lever: 52.5 − 35.0 = 17.5pp
  unexplained by either passthrough or gold facts.
- **No merging across protocols**: E1's DAG-L/M (40.0%) is a MODEL
  reassignment arm; E2's C (35.0%) is a CONTEXT arm; same-strategy
  names across the two lines are never pooled.

## g3 — Joint-search existing results (E5)

- **Confirmatory net-benefit experiment: NEVER EXECUTED** —
  STATISTICAL_REPORT.md's primary/exploratory endpoints all PENDING;
  the 50-task × 8-arm × 4-state × 2-protocol design exists as a frozen
  protocol with honest power framing (n=50 confirmatory only for strong
  effects). `NET_BENEFIT_RESULTS.json` is a self-labeled STUB structural
  proof.
- **What IS complete (V2_FORMAL_SEARCH_ANALYSIS, frozen)**: all six
  search methods reach the panel ceiling best-Q = 0.5 by step 24
  (ceiling effect — no final-quality separation); first-hit steps
  overlap (no speed claim at n=2 seeds); physical search cost
  SA-PGFS ≈223 vs Random ≈343 requests (≈35% fewer) **without
  mechanism attribution** (the w/o-incremental-cost ablation shows the
  same saving; ablation deltas on best-Q = 0.0).
- **Therefore E5 supports**: engineering integration of the six
  selectors, objective-function alignment with official qNEHVI, and one
  weak physical-search-cost observation. **E5 does NOT support**: any
  deployment net-benefit of dynamic scheduling, search-method
  superiority, or the B-REC/B-REA/B-JOINT decomposition as real
  results. All such statements are UNPROVEN.

## g4 — Scoring-convention map (E1/E3/E5/E6)

| dimension | E1 decomposition | E3 120-task chapter-4 | E5 Formal search | E6 supplementary |
|---|---|---|---|---|
| terminal correctness | per-arm contract: mono `extract_value` close; DAG `exec_calc(expr, parse_facts(ext))` close (same tolerance) | `json_value` close (parser-corrected), gold only for scoring | **v2.1** (`score_v21` close ∨ 2dp-rounding, `contract_v2_gold`) | v2.1 terminal only |
| node contract vs terminal | — (node-level not scored) | D-observations drive recovery; Table 4 detection P/R separate | detected_failure = contract-level (never gold) | strict parse contracts; D5-compares-v-to-r (3 cases v right/r wrong/flagged v) |
| tokens | mean real tokens/task per arm | tokens/task incl. retries | **logical cold-workflow tokens (deployment C)** + physical search spend tracked separately, never mixed | physical per-task tokens + per-cell metering (cache split) |
| calls | per-arm call counts | adaptation calls vs total calls distinguished | logical calls vs new physical requests | logical vs physical split |
| latency | mean real latency/task | mean service latency; FG budget-violation sweep (the only deadline-adjacent evidence) | **L = reconstructed SERIAL service demand — never observed E2E wall** | service/switch/queue decomposition; D=3600 inert by design |
| panel / faults | 300 tasks frozen pre-execution (MH 100 + TATQA 200); no injection | 120 frozen; 3 seeds × 10/20/30% capability faults | search panel 8+16+2; states clean/fault30 via build_faults | 20 frozen; D3_r on planned model, 6/20 |
| same-comparison rule | E1 arms internally comparable (paired) | E3 arms internally comparable | E5 configs/states internally comparable | E6 cells internally comparable |

**Cross-line quoting rule**: numbers from different lines may appear
SIDE BY SIDE with convention labels, never inside one comparison,
never differenced across lines. In particular: E1's DAG arms (contract
scoring, no faults) vs E3's arms (json_value scoring, fault states) vs
E5's Q (v2.1, cold-workflow C) are three different yardsticks.

---

# FINAL VERDICT (the five mandated answers)

**1. RQ1 (decomposition loss) — what holds?**
HOLDS: on TAT-QA-style finance QA, same-model decomposition loses
21.0pp (52.5→31.5, p=4.3e-07, n=200 strictly paired) at +31% tokens /
+13% latency. Attribution is partial: context passthrough recovers
+3.5pp; gold-fact substitution does NOT help (confounded diagnostic
pointing at interface friction); 17.5pp residual unexplained. DOMAIN-
SCOPED: MultiHiertt shows +6pp (ns) — the loss is not universal.

**2. RQ2 (heterogeneous allocation) — what holds?**
HOLDS: static heterogeneous assignment (reasoning→different model)
recovers +8.5pp (31.5→40.0, p=0.0015, same paired panel) at zero
marginal cost/latency — ~40% of the loss recovered. Does NOT hold: any
claim about ONLINE dynamic re-assignment policy benefit (no unconfounded
real run).

**3. RQ3 (recovery net benefit in Q/C/L) — measured evidence?**
(a) LOCAL vs FULL: proven EFFICIENCY causal benefit (−33% tokens, −50%
calls, −38% service latency; FG needs ~2.1× budget at 1.2× to be
violation-free); quality difference NOT DETECTED (p=0.125 — no
equivalence claim). (b) Recovery vs no-repair (Dynamic vs Static under
faults): +9–14pp, zero recorded harm, per-seed p≤0.001 — real paired
data under the FINAL_AUDITED overlay (exploratory-leaning citation).
(c) vs Single: clean → single Pareto-dominates (recovery/decomposition
should not run); ≥30% faults + hard tasks → dynamic is the sole
non-dominated point (cross-seed consistent; overall directional).
(d) DEADLINE-conditioned net benefit: NO measured evidence anywhere.

**4. Is the joint dynamic-scheduling real benefit PROVEN?**
NO. The joint scope×reassignment interaction (the reward mechanism's
headline, DD-style) has: stub-level mechanism proof (deterministic
behavioral separation), a confounded real five-arm run (M5 defect,
calibration scope), and an unexecuted confirmatory protocol (E5
endpoints PENDING; results file is a stub). What IS proven are the two
SEPARABLE levers (static hetero allocation; local-recovery robustness
and efficiency). The interaction remains a hypothesis.

**5. Manuscript permissions.**
WRITE AS ESTABLISHED (with conventions and domains stated): RQ1 loss +
attribution diagnostics; RQ2 static hetero recovery; LOCAL-vs-FULL
efficiency; fault robustness of local recovery (audit overlay quoted);
Pareto boundaries incl. single-model dominance on clean; detection-
vs-repairability structure; predictor-mismatch as a measured boundary
(exploratory label).
WRITE AS LIMITS/OPEN: joint interaction hypothesis (mechanism described,
performance untested); deadline dimension untested; 56%/scheduler and
Exact/Frozen families blocked; E6 confounded; reliability certification
NOT ESTABLISHED.
DELETE/NEVER WRITE: any equivalence reading of p=0.125; cross-protocol
pooled numbers; 56% as performance; oracle unions as deployable;
"dynamic beats single in general"; any certified latency quantile.
MANDATORY BOUNDARY STATEMENT: real-task computation structures here are
mostly SHALLOW (e1→e2→r→v); constructed workflow nodes ≠ naturally
complex DAGs; shallow-task results must not be generalized into a
universal advantage of dynamic DAG scheduling.
