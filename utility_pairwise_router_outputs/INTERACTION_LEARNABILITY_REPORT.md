# Five-Model Routability and Interaction Learnability Audit

## Decision

The five-model environment is routable, but the current utility-pairwise predictor does not generalize to the frozen v2 test distribution. The interaction learnability gate fails. FRAR-v2 training and weight tuning must not proceed on these results.

## Frozen data integrity

- Training tasks: 400
- Models: 5
- Repeats per task-model: 3
- Repeat rows: 6,000
- Aggregated task-model rows: 2,000
- Missing or duplicate keys: 0
- Training/v2 task overlap: 0
- Repeat aggregation: arithmetic mean; no best-repeat selection
- Quality: objective score; compliance tasks use `0.55*objective + 0.45*dual-judge mean`

## Routability audit

- Best Single utility: 0.8192 (Qwen Plus)
- Utility Oracle: 0.8852
- Utility Oracle gap: 0.0660
- Best Single quality: 0.8368 (Qwen Plus)
- Quality Oracle: 0.9156
- Quality Oracle gap: 0.0789
- Normalized utility-winner entropy: 0.8438
- Largest winner share: 43.75%
- Gemini wins against DeepSeek: 31.75%
- DeepSeek wins against Gemini: 65.50%

Utility Oracle winners: Qwen Turbo 175, Gemini 86, Qwen Plus 86, DeepSeek 42, GLM 11. The environment is not Best-Single dominated.

## Utility-pairwise router

- Target: pairwise utility preference
- Tie margin: 0.01; ties excluded from the binary loss
- Pairs: 10
- Cross-validation: five task-level folds
- Pairwise accuracy: 73.16%
- Fold-local global-prior accuracy: 69.48%
- Accuracy lift: 3.68 percentage points

OOF diagnostics:

- Oracle match: 47.50% (Best Single: 21.50%)
- Normalized selection entropy: 0.8309
- Gap recovery: 17.34% (required: 20%)

Independent frozen-v2 diagnostics:

- Router utility: 0.7503
- Training-selected Best Single utility: 0.7715
- Utility Oracle: 0.8227
- Gap recovery: -41.32%
- Oracle match: 32.86% (Best Single: 19.29%)

## Failure diagnosis

The model ranking by average utility is stable, but conditional winner patterns shift. In training, Gemini's utility wins are strongly associated with KG/long-context tasks. Frozen v2 contains no KG tasks; its Gemini Oracle wins move to TAT-QA (41) and ObliQA (12). The router selects Gemini only twice on v2, so it does not transfer the interaction learned from the training pool.

## Required next action

Do not tune FRAR weights, add model capacity, or alter v2. Establish a new outcome-blind development/validation split whose task-type and risk support matches the intended test domain, then rerun the same frozen utility-pairwise protocol. Keep v2 untouched as the final independent test.
