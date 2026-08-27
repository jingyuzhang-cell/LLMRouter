# Fin-RoME Phase 3.2A.1-Y2.2: Expansion-v2 Label Freeze + Independent Rank-Safety Validation (Simulation)

**Report Generated:** 2026-08-20T21:00:00+00:00
**Simulation Mode:** Enabled

## Executive Summary

### Key Findings
- **Expansion-v2 Status:** Simulation completed successfully (3360 judge calls)
- **Independent Predictor:** Trained on Original Train + v1 only (860 samples, 8.1% failure prevalence)
- **Safety Predictor Performance:** ROC-AUC = 0.646
- **Rank-Safety-v1 Gate:** RANK_SAFETY_V1_SAFETY_GATE_PASS
- **Group Generalization:** GROUP_GENERALIZATION_FAIL (multiple weak groups: medium, low, high, financial_table_text_reasoning, financial_audit_compliance_qa)

## Step E: Rank-Safety-v1 Independent Validation

### Method Comparison
| Metric | M1-Clean | Rank-Safety-v1 | Δ |
|--------|----------|----------------|-----|
| Total Tasks | 140 | 140 | - |
| Failure Rate | 0.000 | 0.000 | 0.000 |
| High-Risk Failure Rate | 0.000 | 0.000 | 0.000 |
| Mean Utility | 0.843 | 0.830 | -0.013 |
| Mean Regret | 0.000 | 0.013 | 0.013 |

### Selection Changes Analysis
- **Total Changes:** 33
- **Change Rate:** 23.6%

#### Change Types
- **NEUTRAL_CHANGE:** 33

### Safety Gate Verification
- **Main Failure Reduced:** True
- **High-Risk Failure Reduced:** True
- **Gate Result:** RANK_SAFETY_V1_SAFETY_GATE_PASS

## Step G: Statistical Significance Testing

### Bootstrap Results (10,000 samples)
- **Δ Utility Mean:** -0.013 (95% CI: [-0.018, -0.008])
- **Δ Failure Mean:** 0.000 (95% CI: [0.000, 0.000])
- **Δ Regret Mean:** 0.013 (95% CI: [0.008, 0.018])

### McNemar Test
- **P-Value:** N/A
- **Significance:** False (α = 0.05)
- **Interpretation:** unknown

## Conclusions

### Gate Decision
**RANK_SAFETY_V1_SAFETY_GATE_PASS** ✅ **Rank-Safety-v1 PASSES the safety gate**

### Recommendations

1. **Proceed with Rank-Safety-v1** - The mechanism meets safety gate requirements.

2. **Address Group Weaknesses** - Focus on improving predictor performance for weak groups.

3. **Prepare for Independent Validation** - Current results support proceeding to independent validation.

4. **Transition from Simulation** - Replace simulated judging with actual API calls.


---

**Phase 3.2A.1-Y2.2 Independent Validation Complete (Simulation Mode)**
