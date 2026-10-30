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

## 9. Production acceptance
1. Freeze task questions and required fact lists.
2. Obtain two independent blind human reviews; adjudicate disagreements.
3. Audit source hashes, spans, units, date types and derivations.
4. Pass all frozen C9 judge gates on held-out human labels, else use human review/escalation.
5. Validate claim extraction precision/recall; incomplete extraction withholds Q.
6. Reserve a clean independent scheduler-confirmation panel; calibration tasks are not unseen confirmation tasks.

Until all gates pass, report NOT_CALIBRATED / INCOMPLETE and do not feed formal scheduler-training targets or confirmatory claims.
