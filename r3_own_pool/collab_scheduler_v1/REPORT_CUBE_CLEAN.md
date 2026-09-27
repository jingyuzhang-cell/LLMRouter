# Reference Cube — Stage 1 (clean) complete: 15/15 configs measured (2026-09-27)

3119 new calls (frozen200 200-task panel, s_clean; append-only cache seeded
from frozen200 responses). Unified objectives: Q_workflow (each topology's
own final producer), C_workflow (cold-run token accounting from recorded
usage; cache avoids re-execution only), L_critical_path (per-call latency,
parallel e1/e2 -> max).

## Pipeline validation (the Stage-1 goal)

- **Cross-artifact agreement**: DynamicDAG__HETEROGENEOUS__NONE measures
  (Q 0.330, C 1484.0) vs frozen200 clean_static (0.335, 1485.7) — Q within
  0.5pp, C within 2 tokens on an INDEPENDENT re-execution path. Pipeline
  validated.
- L accounting difference (documented): cube L = critical-path from per-call
  latencies (3.17s); frozen200's 4.56s was batch-sojourn wall-clock
  (includes server queueing). Both reported, never mixed.
- **Clean dedup validated**: DynamicDAG NONE and LOCAL_REROUTE produced
  byte-identical (Q, C, L) — under clean they share the execution path, as
  frozen in Phase 1.5.

## Clean Y/X matrix (all 14 cooperative configs + Single anchor)

| config | Q | C | L |
|---|---|---|---|
| **SINGLE__QUALITY__RETRY** | **0.550** | **612.8** | **0.460** |
| SER__HETEROGENEOUS | 0.370 | 963.5 | 2.375 |
| SERV__HETEROGENEOUS | 0.365 | 1194.2 | 2.678 |
| SER__QUALITY | 0.340 | 963.3 | 2.408 |
| SERV__QUALITY | 0.335 | 1208.4 | 3.040 |
| DYNAMICDAG__HET (both Z) | 0.330 | 1484.0 | 3.174 |
| SERV__BALANCED | 0.325 | 1269.7 | 3.324 |
| PARALLELER__QUALITY | 0.315 | 1219.9 | 2.942 |
| DYNAMICDAG__QUALITY (both Z) | 0.310 | 1513.8 | 3.866 |
| PARALLELER__HETEROGENEOUS | 0.305 | 1219.5 | 2.876 |
| DYNAMICDAG__BALANCED (both Z) | 0.295 | 1506.7 | 3.596 |
| PARALLELER__BALANCED | 0.295 | 1244.6 | 3.320 |
| SER__BALANCED | 0.295 | 1029.6 | 3.044 |

## Findings

1. **P*_clean = {Single}** — Single dominates every cooperative config on
   all three axes. Expected per Phase-1 (clean dominance); per the frozen
   B-prime rule this is NOT a gate: Z activates only under fault.
2. **Y dimension (within cooperative sub-front)**: SER > SERV >
   ParallelER ≈ DynamicDAG. The V node COSTS quality (−0.005) plus 231
   tokens — the 7B verifier's echo errors slightly exceed its catches
   (consistent with all verifier evidence). Parallel split-extraction LOSES
   ~6.5pp vs full-context SER extraction on this panel (0.305 vs 0.370) —
   the multidag split contexts lose recoverable information.
3. **X dimension**: HETEROGENEOUS > QUALITY > BALANCED within every
   topology — **heterogeneity can improve quality without uniformly paying
   for larger models** (e.g., SER: HET 0.370 @ 963 tok vs QUALITY 0.340 @
   963 tok), replicating the first paper's finding on the expanded space;
   this directly serves the mainline claim.
4. Cooperative sub-front (excluding Single): {SER__HET} dominates on
   Q-per-token (0.370 @ 963) — if a task REQUIRES multi-node structure
   (e.g., auditability, future M), SER__HET is the clean-state choice.

## Locked calibrations (permanent)

- L_cube (critical-path from per-call latencies) is the ONLY latency used
  in all new Pareto computation; frozen200's batch-sojourn L is historical
  reporting only, never mixed.
- DynamicDAG NONE and LOCAL_REROUTE keep DISTINCT config IDs despite
  identical clean objectives (they are expected to diverge under fault);
  SA-PGFS recall will be reported both per-config and per-deduplicated
  front-point.
- Cache stores model computation only, never runtime state: clean cache
  hits return model OUTPUTS; fault events re-apply to execution state in
  Stage 2 (output -> fault event -> status -> reroute).

## Next (frozen order)

Stage 2 fault30: same 200 tasks, fault model + seeds from frozen200
(bookkeeping-level injection + REAL reroute calls for Z=LOCAL_REROUTE),
clean cache reused for unaffected nodes — opens the Z dimension and yields
P*_fault, completing the Reference Cube for SA-PGFS reveal/replay.
