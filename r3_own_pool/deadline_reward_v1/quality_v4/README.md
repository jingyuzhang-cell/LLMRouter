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
- Cross-document derivations can require all source spans; GOLD derivations only accept GOLD inputs.
- Uncalibrated judges cannot authorize semantic equivalence; deterministic checks (typed values, units, date types, subjects, derivations) take precedence over any judge verdict.
- Critical-fact hard gate (operator ruling 2026-10-30): PASS → Q_final=Q_raw; any critical fact confirmed wrong/omitted (or evidence-unsatisfied when required) → Q_final=0; critical fact unevaluable → Q_final=NULL. Q_raw is always retained for diagnostics.
- Non-finite numerics (NaN/±Infinity) are invalid claims, never crashes; illegal Gold values block Q. Dates are calendar-validated (leap years).
- Missing question, incomplete claim extraction, inadequate Gold coverage, invalid hashes or unassessed material claims withhold formal Q.
- Contract integrity gate: duplicate/empty fact ids, dead or duplicated derivation inputs, non-finite or out-of-range weights (fact/dimension/coverage/claim) all block formal Q before matching; page-text SHA-256 is recomputed, not merely compared.
- Judge credentials: a calibrated judge needs a registry-bound judge_id + 64-hex artifact hash, model/strategy blindness, and a per-claim binding; UNKNOWN abstentions and conflict acknowledgements require explicit substance (refusal text, per-source version text), not field presence.
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
