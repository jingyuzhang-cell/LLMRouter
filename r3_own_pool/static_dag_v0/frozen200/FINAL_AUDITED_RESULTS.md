# FINAL AUDITED RESULTS — Status After All Corrections
# 2026-09-26 | Experiment permanently closed after this audit

## Status Summary

| Experiment | Status | Notes |
|---|---|---|
| 主面板 120 题(修正后) | VALIDATED | Parser + fault-semantics corrected |
| 多种子 20260924/25(修正后) | VALIDATED | Fault-semantics corrected |
| Exact Pareto 18 配置 | VALIDATED | Config effectiveness verified |
| DV/FR 池扩展 | VALIDATED | |
| Frozen 200 Static/Dynamic Q | VALIDATED | |
| Frozen 200 Single Q | VALIDATED | |
| Frozen 200 Single cost | **CORRECTED** | FZ-1: used=0→1225.5 |
| Frozen 200 Pareto/HV/Budget | **CORRECTED** | Recalculated from corrected cost |
| Frozen 200 correctness diagnostics | VALIDATED | Recovery 48.4%, Oracle 101/200, Help/Harm |
| 修正前旧数据(+20pp, 91.7% retention) | INVALIDATED | Do not use |
| Workflow Scheduler 56.0% | EXCLUDED | Source unverified |

## FZ-1 Correction Detail

**What changed (cost-dependent only):**
- Single f30 avg cost: 434 → **802.0** (+85%)
- Pareto front: {Single(C=802), Dynamic(C=2530)} — structure unchanged
- Single exclusive HV: decreased (0.1362 in corrected calc)
- Budget curves: Single still leads at all evaluated B levels on frozen panel, but margin narrows
- No budget crossover between Single and Dynamic on frozen panel at f30 (Single leads throughout)

**What did NOT change (correctness-only):**
- All Q values: Single=0.3967, Static=0.2933, Dynamic=0.4033
- Dynamic vs Single: +0.7pp, not significant (unchanged)
- Help/Harm (Dynamic vs Static): 18/1, 23/1, 28/1 (unchanged)
- Recovery rate: 15/31 = 48.4% (unchanged)
- Oracle Selective: 101/200 = 50.5% (unchanged)
- Degradation: Single +27.9%, Dynamic +2.8% (unchanged)

## 论文表述需同步修改的定性描述

旧(不再成立到原强度):
> "Single exhibits a substantial cost advantage under faults"

修正后(正确):
> "Single LLM maintains a cost advantage under the evaluated fault conditions, though the margin narrows when accounting for the retry overhead of faulted tasks (avg 802 vs 2530 tokens). The Pareto structure remains {Single, Dynamic} with Dynamic occupying the high-quality end."

## Conclusion Impact

- Pareto front structure: UNCHANGED ({Single, Dynamic})
- Budget crossover on frozen panel: Single leads at ALL B levels (no crossover at f30, unlike main panel where crossover occurs at B≥2800)
- Single's cost dominance narrative: needs softening (advantage exists but less dramatic)
- All quality/robustness/recovery conclusions: FULLY PRESERVED
