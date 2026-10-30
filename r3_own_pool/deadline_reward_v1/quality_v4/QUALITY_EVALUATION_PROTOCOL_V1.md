# Quality Evaluation Protocol v1 — Terminal Q

## 1. Research scope
This evaluator supplies the measurement layer shared by heterogeneous model capability profiling, static allocation, dynamic feedback, reward updates, and Q/C/L optimization. It does not replace or narrow the original research mainline.

## 2. Separate evaluation units
1. Node quality (Q_node): one node output against its frozen node contract; used for node/model capability profiles.
2. Terminal quality (Q_terminal): only the final sink answer against the task-level reference; primary scheduler outcome.
3. Delivery reliability (R_delivery): provider delivery, timeout, truncation, schema and execution-contract success.
4. Cost and latency (C,L): measured independently, not folded into Q.

Intermediate outputs may diagnose where facts were lost but must not be concatenated and counted as terminal correctness.

## 3. Frozen six-dimensional rubric
| Dimension | Operational definition |
|---|---|
| Fact correctness | Weighted precision of material claims against adjudicated facts, including subject, predicate, value, unit, date type and relation. |
| Evidence support | Fraction of claims whose citations resolve to hash-bound source spans supporting the fact. A short keyword is insufficient. |
| Necessary completeness | Weighted recall of pre-registered necessary facts. |
| Contradiction handling | Whether known source conflicts are represented with source-specific attribution. N/A if none applies. |
| Unverifiable refusal | Whether pre-registered UNKNOWN items remain unknown rather than asserted. N/A if none applies. |
| Question relevance | Blind assessment that the final answer addresses the frozen question. Cannot be scored if the question is missing. |

Q_final is the weighted mean of applicable dimensions. Weighted fact precision/recall/F1 are diagnostics, not silent replacements for the six-dimensional Q.

## 4. Reference status and Gold gate
- GOLD_CONFIRMED: formal scoring only with authoritative provenance and bound source/annotation hash.
- SILVER_SOURCE_ANCHORED: machine-located candidate, diagnostic only.
- UNKNOWN: evidence does not establish the fact.
- CONFLICT_UNRESOLVED: competing claims remain unadjudicated; blocks affected formal Q.
- EXCLUDED / NOT_APPLICABLE: explicitly outside denominator with a reason.

Human-adjudicated Gold requires two distinct independent reviewers, blind to model and strategy, with adjudication recorded. Native benchmark annotations require exact dataset and annotation hash. Official structured records require the original record and source evidence.

A quote appearing in a document is only a location check, not proof of semantic entailment. Semantic equivalence requires human adjudication or a judge that passed human calibration.

Formal Q is withheld when Gold coverage is below the frozen threshold (default 100%), required source spans/hashes fail, the task question is missing, or material claims are not exhaustively extracted and assessed.

## 5. Atomic fact and citation contract
Each fact records fact_id, subject, predicate, value, value_kind, unit, date_type, criticality weight, source document/page/quote, raw and page SHA-256, offsets, Gold provenance, and reviewer record. Derived facts additionally record a frozen derivation and input fact IDs.

Claims carry fact_id (or unambiguous tuple), subject, predicate, value, unit/date_type and citations. Multi-source derivations use evidence_mode=ALL. When offsets exist, at least 80% overlap with each adjudicated span is required; without offsets, the complete adjudicated quote (or a wider quote containing it) is required. Four-character keyword matches cannot pass.

Supported deterministic operations are add, subtract, ratio and percent_change using decimal arithmetic. More complex temporal, logical and causal relations require human or calibrated-judge assessment.

## 6. UNKNOWN and conflict policy
An item pre-registered UNKNOWN is correctly handled only when explicitly abstained from. Asserting a value is a false assertion. A conflict group identifies source documents and competing fact identities; the answer must acknowledge the discrepancy and attribute each version to its source.

## 7. Judge calibration gates
Reuse the frozen C9 gates:
- parse success ≥0.95;
- human within-one agreement ≥0.80;
- human MAE ≤0.75;
- duplicate exact agreement ≥0.80;
- order-perturbation MAE ≤0.50;
- family-bias review required.

Calibration must use independent human labels on a held-out split. Judges must be blind to model, scheduler arm and candidate ranking. Parse failure, timeout and missing labels remain missing, never semantic Q=0. The C9 packet requires two independent reviewers and adjudication of disagreements; current reviewer templates are unscored.

## 8. Mainline integration
- Capability profiling uses Q_node only with valid node contracts and references.
- Static scheduling optimizes calibrated node-level Q/C/L distributions.
- Dynamic scheduling uses terminal Q for task outcomes and valid node observations for diagnosis.
- Reward keeps semantic Q, reliability, cost and latency separate; scalar utility is separately frozen.
- DAG forest/Pareto comparisons use the same frozen terminal contract and reference version.

Historical Q is immutable. New scorer versions create new score versions; do not silently mix or rewrite old values.

## 9. Critical-fact hard gate (operator ruling 2026-10-30)

A three-state fact-level veto applies to facts marked `critical: true` in the frozen task contract:

| Critical-fact state | Q_final | Handling |
|---|---|---|
| All correct | Q_raw | normal computation |
| ≥1 confirmed wrong or omitted | 0 | critical-fact veto |
| ≥1 unevaluable, no confirmed critical error | NULL | no formal score |
| Answer not fully parseable | NULL | evaluation blocked |
| Final answer not delivered | NULL | Q_delivered=0, R_delivery=0 |

Q_raw (the weighted six-dimension mean) is retained for diagnostics; Q_final is the gated formal terminal quality. Boundaries, frozen before any model answer is seen:

1. `critical` is fixed at task-contract freeze time; it must never be decided after seeing model answers.
2. Critical facts must be formal GOLD; SILVER can never ground a hard-gate decision (a critical fact without formal Gold yields UNKNOWN, not FAIL).
3. Omission, wrong value, wrong subject, wrong date type and wrong fact relation are all judged against the pre-frozen contract; FAIL dominates UNKNOWN.
4. If the contract sets `evidence_required: true` on a critical fact, a correct value without qualifying evidence support also fails the gate.

## 10. Deterministic verification precedence (operator ruling 2026-10-30)

Typed deterministic validation runs first; a semantic judge may only operate where determinism does not apply:

```
typed deterministic checks (value/unit/date_type/subject/derivation)
        ↓ PASS / FAIL / UNKNOWN
semantic judge (predicate wording, text-kind paraphrase, complex relations)
```

A calibrated judge's SUPPORTED verdict can never override a deterministic result for numeric kinds (`number/amount/ratio/percent`), dates, units, date types or subject binding — including on the explicit `fact_id` path. Non-finite numeric values (NaN, ±Infinity) are invalid claims when asserted by a candidate answer and contract-validation failures (blocking, no Q) when present in the Gold contract. Dates are validated against the real calendar (leap years included). Derivation inputs of a formal-GOLD derived fact must themselves be formal GOLD.

## 11. Contract integrity and evaluation credentials (operator re-review 2026-10-30)

**Contract structure gate (blocks formal Q before any matching):**
- Every required fact carries a non-empty, globally unique `fact_id` (duplicate ids could otherwise let one answered fact satisfy another and inflate completeness or pass the critical gate).
- Every derivation declares non-empty, duplicate-free inputs that all resolve within the contract.
- Fact weights are finite positive; dimension weights are finite non-negative with at least one positive; `min_gold_coverage` is a finite number in [0,1]; claim weights come from the frozen extraction stage and must be finite positive — the evaluated answer cannot control them.
- `_span_is_valid` recomputes the page-text SHA-256: a page record whose stored hash does not match its own text is rejected, beyond matching the citation's declared hashes.
- Derivation arithmetic requires identical units across inputs (and with the target for add/subtract); no conversion rule is frozen today, so mixed units simply cannot form a valid derivation.

**Judge credential binding (a bare `PASS` string is not a credential):**
- A `calibrated_judge` assessment is valid only when the evaluation is given a calibration registry mapping `judge_id → calibration_artifact_sha256`, the assessment carries that judge_id with a well-formed 64-hex artifact hash registered there, and it is blind to model and strategy.
- Verdicts are bound to the exact claim via `binding_claim_id`; an assessment cannot be replayed across claims. Human adjudications of claims are subject to the same binding.

**Substance over field presence (UNKNOWN and conflicts):**
- An UNKNOWN abstention counts only with an explicit non-empty refusal text; a bare item_id tick does not.
- A conflict acknowledgement counts only when each required source document carries its own non-empty `source_versions` text attributing that source's version of the competing fact.

## 12. Production acceptance
1. Freeze task questions and required fact lists.
2. Obtain two independent blind human reviews; adjudicate disagreements.
3. Audit source hashes, spans, units, date types and derivations.
4. Pass all frozen C9 judge gates on held-out human labels, else use human review/escalation.
5. Validate claim extraction precision/recall; incomplete extraction withholds Q.
6. Reserve a clean independent scheduler-confirmation panel; calibration tasks are not unseen confirmation tasks.

Until all gates pass, report NOT_CALIBRATED / INCOMPLETE and do not feed formal scheduler-training targets or confirmatory claims.
