# Target-Support Utility-Pairwise Validation

## Protocol

- v2 was not used for splitting, training, validation, threshold selection, or weight selection.
- Eligible support was restricted to TAT-QA table reasoning (medium/low risk) and ObliQA compliance (high risk).
- The metadata-only split was frozen before outcomes were read.
- Training tasks: 139; frozen validation tasks: 70; overlap: 0.
- Pairwise target: utility preference with a 0.01 tie margin.

## Results

- Pairwise CV accuracy: 72.41%
- Fold-local global-prior accuracy: 72.33%
- Accuracy lift: 0.08 percentage points (required: 3 points)
- OOF gap recovery: -32.14% (required: at least 20%)
- Frozen-validation gap recovery: 20.25%
- Frozen-validation recovery bootstrap 95% CI: [-10.74%, 45.45%]
- Probability of positive validation recovery: 90.93% (required: 95%)
- Validation Oracle-match lift over Best Single: 18.57 percentage points
- Validation normalized selection entropy: 0.7952

## Gate decision

The target-support interaction gate fails. The validation point estimate is positive, but the effect is not stable enough and training OOF performance is negative. FRAR component ablation is not authorized under the frozen protocol.

## Interpretation

Restricting development to the target task/risk support improves independent validation substantially, changing gap recovery from negative on v2 to +20.25% on the new frozen validation set. However, 139 training tasks are insufficient to demonstrate interaction learning beyond the global model prior with acceptable uncertainty.

The next admissible action is to expand the outcome-blind target-support development pool or obtain an additional independently frozen target-support validation set. Do not tune FRAR weights or use v2 to select the router.
