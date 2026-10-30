# Terminal Quality Evaluator v1 (Q)

This isolated offline implementation evaluates **only the final DAG sink answer** against a frozen task contract. It does not call models, change schedulers, replay historical runs, or overwrite historical scores.

## Dimensions
- Fact correctness: typed subject–predicate–value matching; weighted precision.
- Evidence support: citations must resolve to hash-bound source spans and cover the adjudicated evidence.
- Necessary completeness: weighted recall of required Gold facts.
- Contradiction handling: source-attributed acknowledgement of frozen conflict groups.
- Unverifiable refusal: correct abstention on frozen UNKNOWN items.
- Question relevance: blind, independently adjudicated assessment.

Default weights are equal across applicable dimensions, matching the project's existing six-dimensional terminal scoring specification. Task-specific weights must be frozen before evaluation.

## Guardrails
- SILVER and machine-generated references cannot produce formal Q.
- Short keyword hits do not prove claim entailment.
- Subject, predicate, value, unit and date type must match.
- Cross-document derivations can require all source spans.
- Uncalibrated judges cannot authorize semantic equivalence.
- Missing question, incomplete claim extraction, inadequate Gold coverage, invalid hashes or unassessed material claims withhold formal Q.
- Delivery failure is separate from semantic correctness: Q_final is null, R_delivery is 0, and Q_delivered is 0.

## Use
```python
from terminal_quality import evaluate_terminal_quality
result = evaluate_terminal_quality(frozen_task_contract, final_sink_output, hash_bound_source_pages)
```

The output claim extractor must be separately validated. If it cannot guarantee complete extraction of material claims, set `claims_complete=false`; formal Q is withheld.

## Validation
Run `python -m unittest -v`. Tests use synthetic fixtures only. Passing tests validates code invariants, not human calibration, domain validity, or scheduler benefit.

Status: IMPLEMENTED_OFFLINE / NOT_HUMAN_CALIBRATED / NOT_PRODUCTION_INTEGRATED.
