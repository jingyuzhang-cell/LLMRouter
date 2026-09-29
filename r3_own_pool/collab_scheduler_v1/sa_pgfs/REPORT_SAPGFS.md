# SA-PGFS Reveal/Replay Results (2026-09-28, zero LLM calls)

Protocol frozen pre-run (`PROTOCOL_SAPGFS_FREEZE.json`); 200 paired replay
seeds × 5 algorithms × 2 states (s_clean, s_fault30), shared n_0=3 initial
design per seed; full curve t=3..14 on |G_collab|=14; Single as external
global baseline. All algorithms eventually reach the full front (R_final=0,
Recall=1.0), so the differentiating metric is EARLY-BUDGET sample efficiency.

## Main table

| Method | N95 (clean) | AUC-HV (clean) | N95 (fault) | AUC-HV (fault) |
|---|---|---|---|---|
| Random | 8.0±1.6 | 0.768 | 8.0±1.6 | 0.804 |
| Scalarized (frozen bank) | **4.2±0.9** | **0.939** | **4.5±1.2** | **0.933** |
| Greedy-Q | 6.3±1.4 | 0.813 | 7.0±1.5 | 0.817 |
| EHVI | 7.6±1.8 | 0.831 | 6.3±1.5 | 0.887 |
| SA-PGFS (cost-aware) | 7.6±1.8 | 0.833 | 6.2±1.5 | 0.890 |

## Findings

1. **Scalarized search is the best method on this 14-config cube** (N95=4.2
   clean / 4.5 fault, AUC=0.94). SA-PGFS and EHVI tie for second (N95≈6.2-7.6);
   all methods beat Random (N95=8.0). This is reported honestly: on a small,
   well-structured search space, a frozen multi-weight scalarized surrogate
   query is a strong baseline and outperforms information-theoretic acquisition.

2. **SA-PGFS does not beat plain EHVI on this cube** (AUC 0.890 vs 0.887 fault;
   0.833 vs 0.831 clean). The cost-aware denominator provides no measurable
   advantage when evaluation costs are roughly uniform (all configs are 2-4
   node workflows with similar token ranges). The cost-aware acquisition is
   expected to differentiate on larger, more heterogeneous spaces — this is a
   scope claim, not a general claim.

3. **All methods converge to the full front by t=14** (R_final=0, Recall=1.0),
   confirming that the cube is a search benchmark, not a difficulty benchmark.
   The algorithmic claim is about EARLY budget: scalarized reaches 95% HV in
   4-5 reveals vs 8 for random.

4. **State does not change the algorithm ranking** (scalarized > EHVI ≈ SA-PGFS
   > greedy > random in both states), though fault30 slightly compresses gaps.

## Honest positioning

- On THIS search space (14 configs, ~6 structural features, Q is the only
  stochastic objective), simple methods are strong. SA-PGFS's value is NOT
  demonstrated here as superior sample efficiency — the cube validates the
  machinery, not the algorithm's advantage.
- The paper should report this as: "on a complete 14-config reference cube,
  scalarized search with a frozen weight bank achieves the best early-budget
  efficiency; SA-PGFS matches EHVI but does not exceed it at this scale." The
  need for surrogate-assisted acquisition over scalarization is expected to
  emerge in larger, more heterogeneous combinatorial spaces (e.g., 559+,
  non-uniform evaluation costs), which the sa_pgfs_v1 prototype simulates.

Figures: F1 (state-conditioned fronts, Single external), F2 (recovery arrows),
F3 (HV curves, 200 seeds with CI).
