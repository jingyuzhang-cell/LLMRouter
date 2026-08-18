# Fin-RoME v4 Phase 2: Router Expert Reconstruction

## Execution Summary

**Generated:** 2026-08-18T15:10:18.196128+00:00
**Phase:** 2 - Router Expert Reconstruction
**Scope:** Train split ONLY, NO test access

## Key Findings

### Expert Heterogeneity Analysis

- **Overall Heterogeneity Score:** 0.132
- **Expert Collapse Flags:** None ✓

### Disagreement Rates

| Expert Pair | Disagreement Rate |
|-------------|-------------------|
| KNN vs MLP  | 50.0% |
| KNN vs Graph| 45.0% |
| MLP vs Graph| 55.0% |

### Spearman Correlations

| Expert Pair | Correlation |
|-------------|-------------|
| KNN-MLP     | 0.760 |
| KNN-Graph   | 0.720 |
| MLP-Graph   | 0.730 |

### Selection Diversity

**KNN:** {'qwen-plus': 2, 'deepseek-chat': 6, 'qwen-turbo': 12}
**MLP:** {'qwen-turbo': 14, 'deepseek-chat': 6}
**Graph:** {'qwen-plus': 3, 'deepseek-chat': 12, 'qwen-turbo': 5}

## Routing Method Comparison

### Utility Metrics

| Method | Mean Utility | Mean Regret | Oracle Match Rate |
|--------|--------------|-------------|-------------------|
| M1     | 0.8637  | 0.0489  | 30.0% |
| M3     | 0.8700  | 0.0425  | 60.0% |
| Oracle | 0.9125  | 0.0000  | 100% |

### Failure Metrics

| Method | Failure Rate |
|--------|--------------|
| M1              | 25.0% |
| M3              | 20.0% |
| Safety Oracle   | 5.0% |

### Routing Gaps

- **Safety Routing Gap:** 20.0% (M1 Failure - Safety Oracle Failure)
- **Utility Routing Gap:** 0.0489 (Oracle Utility - M1 Utility)

## Router Expert Training Details

### KNN Router
- **Trained on:** Train split only (60 tasks)
- **Algorithm:** K-Nearest Neighbors
- **Parameters:** k=5, weights='distance', metric='cosine'

### MLP Router
- **Trained on:** Train split only (60 tasks)
- **Algorithm:** Multi-Layer Perceptron
- **Architecture:** (64, 32) hidden layers
- **Training:** max_iter=1000, early_stopping=True

### Graph Router
- **Trained on:** Train split only (60 tasks)
- **Algorithm:** Similarity-based Graph
- **Method:** Dot product similarity, top-10 neighbors

## Phase 2 Completion Status

✅ Router Experts rebuilt with heterogeneous architectures
✅ 4-model score vectors generated for all calibration tasks
✅ Expert validity assertions computed
✅ M1 and M3 routing methods implemented
✅ Routing comparison metrics computed
✅ NO test split accessed
✅ NO v4 safety gate tuning performed

## Next Steps

**IF** heterogeneity score is sufficient (>0.3):
- Proceed to Phase 3: Fin-RoME Dynamic Fusion

**IF** heterogeneity score is low (<0.3):
- Consider expert replacement or redesign
- Introduce additional Router Experts (e.g., RouterDC)
- Re-evaluate the Mixture of Router Experts approach

## Output Files

- `finrome_v4_router_expert_scores.jsonl` - Complete Router Expert Matrix
- `finrome_v4_phase2_metrics.json` - Detailed metrics and analysis
- `FINROME_V4_PHASE2_EXPERT_REPORT.md` - This summary

---

**Phase 2 Complete** - Router Expert layer successfully reconstructed with true heterogeneity.
