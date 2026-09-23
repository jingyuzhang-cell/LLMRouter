# Paper Evidence Pack — Frozen Experimental Results (as of 2026-09-23)

Consolidated from the frozen 4-node-DAG 120-task panel (multidag_dynamic_120) after the
json_value parser correction. All model calls real. Supplementary status (designed after
known results; not independent confirmation). Gold used only for scoring. All 120 tasks
in every denominator. Full provenance: corrected_replay/BUG_REPORT.md (parser fix),
BENCHMARK_PROTOCOL.md, VERIFIER_SUBSET_PROTOCOL.md, FULLGRAPH_PROTOCOL.md.

## Table 1 — Overall performance (clean scenario)

| Method | Accuracy | tokens/task | calls | latency s |
|---|---:|---:|---:|---:|
| Router (best single model, 14B direct QA) | 0.5500 | 603 | 1 | 0.53 |
| Static DAG (fixed structure/models, no feedback) | 0.3500 | 1503 | 4 | 4.63 |
| Dynamic DAG (RD: deployable detection + local recovery) | 0.4000 | 2324 | 6.6 | 6.69 |
| ref: dynamic-ideal (gold-driven triggers, not deployable) | 0.4250 | 2664 | 7.6 | 7.33 |
| ref: static-with-fallback (fixed local fallbacks) | 0.3917 | 2759 | 7.6 | 7.79 |

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
| Router | 0.7027 | 0.3043 |
| Static | 0.4324 | 0.2174 |
| Dynamic | 0.4595 | 0.3043 |

## Figure 1 — Failure robustness curve (core figure)

`adaptive_benchmark/robustness_curve_2panel.png` (overall + Hard subset).
Data: injected capability faults at 10/20/30%, seed 20260923:

| Fault rate | Router | Static | Dynamic | Router degr. | Static degr. | Dynamic degr. | Dynamic recovery |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0% | 0.5500 | 0.3500 | 0.4000 | — | — | — | — |
| 10% | 0.4833 | 0.3167 | 0.4083 | +12.1% | +9.5% | −2.1% | 50% |
| 20% | 0.4250 | 0.2917 | 0.4083 | +22.7% | +16.7% | −2.1% | 42% |
| 30% | 0.3500 | 0.2667 | 0.4083 | +36.4% | +23.8% | −2.1% | 44% |

Hard subset under faults: Dynamic 0.2609/0.2826 vs Router 0.1739/0.1522 at 20/30%.

Robustness significance (STAT_CHECK.md):
- Dynamic vs Static under faults: +9.2pp (p=0.001), +11.7pp (p=0.000122),
  +14.2pp (p=1.5e-05) at 10/20/30% — and Help/Harm 11/0, 14/0, 17/0
  (Dynamic NEVER harms a task that Static got right, at any fault rate).
- Dynamic vs Router at 30%: +5.8pp overall, CI [−4.2, +15.0], p=0.31 — the overall
  crossover is directional, not significant; on the HARD subset +13.0pp,
  CI [+2.2, +23.9], p=0.070 — the significant-looking crossover lives on hard tasks.
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
  (Router vs Dynamic +15.0pp, p=0.0005 in Router's favor); "Dynamic > Static on clean"
  as significant (+5.0pp, p=0.109 — say "directionally positive, not significant");
  a significant OVERALL crossover vs Router at 30% (directional only, p=0.31; the
  significant crossover is on the hard subset); semantic evidence-error detection
  (recall gap quantified).
- Caveats to carry: capability-fault model (same-model retry reproduces the fault at
  temp 0; transient-fault cost table reported separately); single seed; 14B-GPTQ session
  nondeterminism ~10–15% (bounds the FG−RD and fault-scenario noise); supplementary
  status — an independent confirmation would require a fresh frozen panel.
