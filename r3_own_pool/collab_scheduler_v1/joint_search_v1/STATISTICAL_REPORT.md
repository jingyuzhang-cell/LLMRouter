# NET-BENEFIT Statistical Report (template — finalized after real execution)

Status: IN PROGRESS — this file is finalized only from `NB_ROWS.jsonl`
(execute=true) via `analyze_netbenefit.py` after the run completes.
Any number below marked PENDING is not yet a result.

## 1. Design

- Paired task-level design: 50 frozen held-out tasks (content hashes in
  `NET_BENEFIT_FREEZE.json`), identical fault draws across all strategies.
- 8 arms (six attribution A/A'/B/C/D/E + two V2 candidates), 4 states
  (clean/fault10/fault20/fault30), 2 fault protocols (mechanism, competitive).
- Scoring: contract v2.1 (`score_v21`) with GOLD_CONTRACT_V1 gold.
- Cost: dual track — logical tokens (strategy comparison) vs physical
  requests (budget enforcement); never mixed.

## 2. Primary confirmatory endpoint (pre-registered)

- State fault30, budget B*=3000 logical tokens, metric
  Q_B = #(correct AND C<=B)/50.
- Gate 1: Q_B(D) − Q_B(A) > 0, one-sided exact McNemar α=0.05.
- Gate 2 (only if gate 1 passes): Q_B(D) − Q_B(A') > 0, same test.
- Mechanism family = primary for the recovery-mechanism claim;
  competitive family = required for any deployment-condition claim.
- Power framing (POWER_SIMULATION.json): pilot-confirmatory. At the
  historical anchor (q=0.514, p_d=0.23) n=50 has power 0.032; the design is
  confirmatory only for strong effects (q≳0.8).

### Results — PENDING

## 3. Exploratory family

- All (state, budget) D-vs-A comparisons within each fault family,
  Holm-corrected (40 comparisons per family).
- Help/Harm counts, task-cluster bootstrap 95% CIs everywhere.
- Non-significant results are reported as "failed to demonstrate
  superiority", never as "proven equivalent".

### Results — PENDING

## 4. Secondary analyses (derived, same trajectories)

- Experiment 1: ΔQ_structure (B−A), ΔQ_hetero (C−B) on clean.
- Experiment 2: ΔQ_recovery (D−C) per state; detection vs repair funnel.
- Experiment 3: D vs E (recovery scope) — Q/C/L and re-execution volume.
- Experiment 6: per-state Q/C and Q/C/L non-dominated sets; a strategy
  dominated by Single on all three axes is reported as dominated.
- Experiment 8: fault-type × diagnosability funnel.

### Results — PENDING

## 5. V2 search efficiency (Experiment 5, zero new calls)

From `V2_FORMAL_SEARCH_ANALYSIS.json` (complete, frozen):

- All six methods reach the panel ceiling best-Q=0.5 by step 24 — no final
  quality separation on the 8-task panel (ceiling effect).
- First-hit steps overlap (SA-PGFS 9/11, Random 11/9, BO 9/19, qNEHVI
  11/13) — no speed claim is supportable at n=2 seeds.
- Physical cost for the full 24-eval budget: SA-PGFS ~223 requests vs
  Random ~343 (≈35% fewer physical requests). Attribution to the
  incremental-cost mechanism is NOT established: the single-seed
  w/o-incremental-cost ablation shows the same saving (223).
- Ablation deltas on final best-Q: 0.0 for both ablations (dual-seed for
  w/o-state, single-seed preliminary for w/o-incremental-cost).
- Non-claims: search cost ≠ deployment cost; campaign Q ≠ validation Q.

## 6. Integrity

- All confirmatory rules frozen in NET_BENEFIT_FREEZE.json before the first
  model call (freeze hash bound in every run directory).
- Audit v3: 49/49 real assertions incl. negative samples; checkpoint
  isolation between stub and real executions (a defect where the real run
  skipped cells via stub records was caught and fixed before any real call).
- Physical ledger reconciliation: DISPATCH totals == per-cell sums;
  budget utilization tracked in RUN_SUMMARY per invocation.
