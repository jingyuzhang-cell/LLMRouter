# Paper Evidence Pack — Frozen Experimental Results (as of 2026-09-23)

Consolidated from the frozen 4-node-DAG 120-task panel (multidag_dynamic_120) after the
json_value parser correction. All model calls real. Supplementary status (designed after
known results; not independent confirmation). Gold used only for scoring. All 120 tasks
in every denominator. Full provenance: corrected_replay/BUG_REPORT.md (parser fix),
BENCHMARK_PROTOCOL.md, VERIFIER_SUBSET_PROTOCOL.md, FULLGRAPH_PROTOCOL.md.

Experiment tiers (stated explicitly, do not present all as equal weight):
- MAIN EVALUATION: Table 1 / Figure 1 — 120 tasks, all methods, clean + fault
  injection at 10/20/30% with THREE seeds (20260923/24/25; fault numbers are
  mean±std across seeds; MULTI_SEED_REPORT.md).
- RECOVERY-EFFICIENCY EVALUATION (main): Table 2 — RD vs FG on the same 120 tasks.
- DIAGNOSTIC ANALYSES (mechanism explanations, smaller subsets — never headline
  claims): hard/easy subsets (74/46 tasks), recovery attribution (78 failures),
  verifier ablation (34 triggers), detection evaluation (per-node instances).

## Table 1 — Task Completion under Different Execution Conditions

Baseline taxonomy (two categories, stated explicitly):
- CAPABILITY baseline (answers "how strong is the model itself?"):
  Single LLM — 14B direct QA; under faults its only policy is same-model retry.
- WORKFLOW-EXECUTION baselines (answer "how is execution organized?"):
  Static DAG (fixed structure/models, no feedback), Full replay (FG control), Dynamic DAG.

| Method | Clean | Fault 10% | Fault 20% | Fault 30% | tokens/task (clean→f30) | latency s (clean) |
|---|---:|---:|---:|---:|---:|---:|
| Single LLM (retry on failure) | 0.5500 | 0.4972±0.0142 | 0.4389±0.0142 | 0.3639±0.0258 | 603→783 | 0.53 |
| Static DAG (no feedback) | 0.3500 | 0.3361±0.0142 | 0.3250±0.0236 | 0.3111±0.0322 | 1503→1487 | 4.63 |
| Dynamic DAG (feedback + local recovery) | 0.4000 | 0.4111±0.0039 | 0.4139±0.0079 | 0.4083±0.0136 | 2324→2224 | 6.69 |

Fault columns: mean±std over 3 injection seeds (population std; 120 tasks each).

Reference rows (corrected arms, clean): dynamic-ideal 0.4250 (gold-driven triggers, not
deployable); static-with-fallback 0.3917.

Reading: on clean, easy-heavy tasks the single model dominates quality AND cost — the
DAG pays decomposition/interface losses (consistent with the loss-attribution study).

Paired statistics (STAT_CHECK.md, task bootstrap CI + McNemar exact):
- Router vs Static +20.0pp, CI [+12.5, +28.3], p=3e-06 (Router significantly best).
- Router vs Dynamic +15.0pp, CI [+7.5, +23.3], p=0.0005.
- Dynamic vs Static +5.0pp, CI [0.0000, +10.0], p=0.109 — directionally positive,
  NOT significant on the full clean panel (do not claim clean superiority).

### Table 1b — Clean per-subset (difficulty = pre-execution operator count)

| Method | Easy (1 op, n=74) | Hard (>=2 ops, n=46) |
|---|---:|---:|
| Single LLM | 0.7027 | 0.3043 |
| Static DAG | 0.4324 | 0.2174 |
| Dynamic DAG | 0.4595 | 0.3043 |

### Table 1c — Quality-cost trade-off (Q per 1000 tokens; Pareto dominance)

| Scenario | Single LLM | Static | Dynamic | Non-dominated set |
|---|---:|---:|---:|---|
| Clean | 0.913 | 0.233 | 0.172 | Single LLM only |
| Fault 10% | 0.742 | 0.211 | 0.188 | Single LLM only |
| Fault 20% | 0.587 | 0.196 | 0.186 | Single LLM only (overall); Hard: {Single, Dynamic} |
| Fault 30% | 0.447 | 0.179 | 0.184 | {Single, Dynamic}; Hard: {Single, Dynamic} |

Honest Pareto reading: in clean conditions the single model dominates BOTH DAG methods
on quality and cost simultaneously — the DAG's tokens buy structure the task does not
need. Static DAG is Pareto-DOMINATED at every operating point (by the single model
everywhere; additionally by Dynamic at 30%). Dynamic becomes non-dominated only where
its robustness pays: >=20% faults on hard tasks and >=30% overall, where it is the sole
owner of the high-quality end of the frontier (0.408 vs 0.350; hard 0.283 vs 0.152).
Efficiency claims vs Static must be scoped accordingly: Dynamic spends ~1.5x Static's
tokens for +9 to +14pp under faults with zero harm; its cost advantage claim is versus
FULL REPLAY (Table 2), not versus the single model.

## Figure 1 — Failure robustness curve (core figure)

`adaptive_benchmark/robustness_curve_2panel_multiseed.png` (overall + Hard subset, mean±std over 3 seeds; single-seed version kept as robustness_curve_2panel.png).
Data: injected capability faults at 10/20/30%, seed 20260923:

| Fault rate | Router | Static | Dynamic | Router degr. | Static degr. | Dynamic degr. | Dynamic recovery |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0% | 0.5500 | 0.3500 | 0.4000 | — | — | — | — |
| 10% | 0.4833 | 0.3167 | 0.4083 | +12.1% | +9.5% | −2.1% | 50% |
| 20% | 0.4250 | 0.2917 | 0.4083 | +22.7% | +16.7% | −2.1% | 42% |
| 30% | 0.3500 | 0.2667 | 0.4083 | +36.4% | +23.8% | −2.1% | 44% |

Hard subset under faults: Dynamic 0.2609/0.2826 vs Router 0.1739/0.1522 at 20/30%.

Robustness significance (STAT_CHECK.md per-seed paired tests; MULTI_SEED_REPORT.md for
cross-seed consistency):
- Dynamic vs Static under faults: cross-seed dQ = +7.5±1.4 / +8.9±2.1 / +9.7±3.8 pp at
  10/20/30% — positive under every seed; per-seed paired tests reach p<=0.001
  (seed 20260923: Help/Harm 11/0, 14/0, 17/0 — Dynamic NEVER harms a task Static
  got right, at any rate).
- Dynamic vs Single LLM at 30%: cross-seed dQ = +4.4±1.4pp — the crossover occurs
  under ALL THREE seeds (any single-seed paired test remains directional, e.g.
  p=0.31 for seed 20260923; report the cross-seed consistency, not a single p).
- Hard subset: Dynamic 0.2754±0.010 / 0.2754±0.010 / 0.2681±0.021 vs Single LLM
  0.2681±0.010 / 0.2174±0.036 / 0.1812±0.041 — Dynamic ahead at every rate >=10%
  in the multi-seed mean (equal at 10%: 0.275 vs 0.268), and far ahead of Static.
- Clean Hard: Dynamic vs Static +8.7pp, CI [+2.2, +17.4] (bootstrap CI excludes 0;
  McNemar 4/0, p=0.125 — report both).

## Table 2 — Recovery efficiency: local vs full-graph re-execution (corrected arms)

| Method | Accuracy | tokens/task | adaptation calls | latency s | budget violations @1.2x |
|---|---:|---:|---:|---:|---:|
| RD (local recovery) | 0.4000 | 2323.7 | 309 | 6.69 | 0/120 |
| FG (full-graph re-execution, same rules) | 0.3750 | 3346.6 | 592 | 10.36 | 54/120 (45%) |

FG vs RD paired: dQ −0.025, CI [−0.0583, 0.0000], McNemar p=0.25, Help/Harm 0/3
(all within the measured 14B session nondeterminism). Local scope saves 1023 tokens/task
(−31%), 283 calls (−48%), 3.67 s/task; FG re-executes unaffected branches 217 times.
FG needs ~2.1x the reference budget to be violation-free (sweep: 68%/45%/12%/1.7%/0%
violations at 1.0/1.2/1.5/2.0/2.5x; RD 5%/0/0/0/0).

## Table 3 — Recovery attribution (Success = Detection x Repairability)

Clean scenario, N=78 initially-wrong tasks under Dynamic (corrected):

| Primary failure type | n | node detection | any detection | recovered |
|---|---:|---:|---:|---:|
| evidence (parse/empty) | 44 | 100% | 100% | 16% (7) |
| evidence (wrong values) | 8 | 0% | 100% | 12% (1) |
| execution (r unexecutable) | 4 | 100% | 100% | 0% (0) |
| reasoning (r executable-wrong) | 20 | 0% | 100% | 0% (0) |
| verification (v) | 2 | 100% | 100% | 0% (0) |

Injected faults (fault origin = incidental): Dynamic recovery 29–100% by node type;
Static survival (no repair, cascade only) 0–50% (v-faults: Static 0% at every rate).
Verifier set: cross-model disagreement detects reasoning errors with 82% precision
(28/34) but repairs only 7/34 (21%) — detection solved, repairability is the bottleneck.

Mechanism reading: clean-run failures are largely task-fundamental (all pool models
fail) and mostly irrecoverable; incidental faults (injected) are largely recoverable
by model switching. Recovery value concentrates in failure-prone execution, not in
lifting the base capability ceiling.

## Table 4 — Detection evaluation (initial-pass outputs, fixed parser)

| Failure type | n | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| Evidence (e) | 84 | 1.000 | 0.869 | 0.930 |
| Reasoning (r executable-wrong) | 68 | — | 0.000 | — (recall 0 by design; verifier adds 82%-precision detection) |
| Execution (r unexecutable) | 18 | 1.000 | 1.000 | 1.000 |
| Verification (v) | 90 | 0.826 | 0.731 | 0.776 |
| Structure/topology | N/A | fixed-DAG panel; needs an injection run |

Deterministic evidence-injection check: x0.8 perturbation of one fact value leaves the
real r expression executable in 32/36 tasks (evidence errors invisible at e and r).

## Claim-strength rules for the manuscript

- Confirmed by these data (with statistics in STAT_CHECK.md): robustness under
  capability faults — Dynamic vs Static +9.2/+11.7/+14.2pp, p<=0.001, Help/Harm with
  ZERO harm at every rate; local-recovery efficiency (FG ablation); detection
  precision on execution-level failures; hard-task concentration of the robustness
  advantage (fault30 hard +13.0pp vs Router, CI [+2.2, +23.9]); repairability
  bottleneck (verifier ablation).
- Must NOT be claimed: clean-scenario accuracy superiority over a single strong model
  (Single LLM vs Dynamic +15.0pp, p=0.0005 in the model's favor; it also Pareto-dominates
  both DAG methods in clean conditions — state this openly); "Dynamic > Static on clean"
  as significant (+5.0pp, p=0.109 — say "directionally positive, not significant");
  cost superiority over the single model (Q/1000 tokens favors it in every scenario —
  Dynamic's efficiency claim is versus full-graph replay and, under faults, versus Static
  per unit of recovered quality); a significant OVERALL crossover vs Single LLM at 30%
  (directional only, p=0.31; the significant crossover is on the hard subset);
  semantic evidence-error detection (recall gap quantified).
- Abstract wording: use "improve workflow reliability / reduce degradation under
  failures / enable efficient local recovery"; never "improve reasoning accuracy /
  outperform LLMs / superior task solving". Problem A (task solving: single model wins)
  is distinguished from Problem B (reliable workflow execution: this paper's problem).
- Caveats to carry: capability-fault model (same-model retry reproduces the fault at
  temp 0; transient-fault cost table reported separately); fault injection now 3 seeds
  (mean±std reported; original single-seed caveat resolved); 14B-GPTQ session
  nondeterminism ~10–15% (bounds the FG−RD and fault-scenario noise); supplementary
  status — an independent confirmation would require a fresh frozen panel.

## Supplementary simulation — Adaptive Decomposition (entry-decision routing; zero calls, post-hoc)

Question: does routing Easy tasks to Single LLM and Hard tasks to Dynamic DAG beat
Single-all? Simulated from executed per-task results (ADAPTIVE_SIMULATION.md):
- CLEAN: Adaptive(oracle difficulty, upper bound) = 0.5500 = Single-all EXACTLY —
  Dynamic's hard-subset accuracy (0.3043; ideal-detector variant 0.3261) does not
  EXCEED the single model on hard tasks, so the entry decision cannot lift clean
  accuracy on this panel; it only shapes cost (0.55 at 1308 tokens vs 603 for
  Single-all, 2324 for Dynamic-all). Deployable rules (question numerals/length,
  table size) agree with the oracle split at only 19-32% and score 0.41-0.49.
- FAULTS (3 seeds): Adaptive(oracle) 0.5000±0.017 / 0.4611±0.005 / 0.3972±0.021 —
  tied-best at 10%, best at 20% (vs Single 0.4389, Dynamic-all 0.4139), and at 30%
  below Dynamic-all (0.4083). Value = cost shaping + moderate-fault composition,
  not accuracy.
Positioning: this stays a supplementary simulation; the failure-aware mainline is
unchanged. Consistent with the earlier Selective-DAG gate finding (deployable
difficulty signal exists, AUC 0.734 on TAT-QA-200) — the conditional DAG advantage
on this panel is robustness, not clean accuracy. Do NOT claim adaptive > single on
clean (oracle-level equality only).

## Multi-objective execution trade-off analysis (ch4.5; zero calls; MULTIOBJECTIVE_TRADEOFF.md)

Section renamed from "optimization boundary" to EXECUTION TRADE-OFF ANALYSIS — no
optimizer is proposed; we quantify when each execution policy is worth its cost.
- T1 Pareto + exclusive hypervolume (Q / -tokens / -latency; per-scenario reference
  point 1.1x worst; 3D and 2D Q-C): Single LLM is the dominant HV contributor in
  EVERY scenario (clean 0.31/0.23); Static and Full-Replay contribute ZERO everywhere
  (dominated at all operating points); Dynamic is off-frontier through 20% faults and
  JOINS the frontier at 30% (exclusive HV small: 0.0004 3D / 0.0040 2D — it owns the
  high-quality corner but sits at the worst cost/latency end of the set).
- T2 Budget-constrained completion Q(B) = #(correct AND used<=B)/N (all tasks kept):
  Single dominates the budget curve at every B in clean and at 10/20% faults; at 30%
  faults the curves CROSS — Dynamic overtakes for B >= ~2800 tokens (0.378±0.017 vs
  0.364±0.032 at 3000). Budget dimension reproduces the robustness crossover.
- T3 Policy transition (multi-seed means): Single best overall through 20%; Dynamic
  best at 30% overall and from 10-20% on the Hard subset. Transition band (20%,30%].
Literature candidates for related work (PENDING VERIFICATION before citation, per the
no-unverified-references rule): multi-objective BO for LLM agent-team configuration
(MALBO), capability-cost coordinated multi-LLM serving (ECCOS), classic MOBO/NSGA-II
as background. Positioning: related work discusses; this paper does not propose an
optimization algorithm.
