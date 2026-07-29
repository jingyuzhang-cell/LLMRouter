# Offline Experiment Validation

Overall: **PASS**

## Data audit
- Status: PASS
- Formal sample signature match: True
- Dataset distribution: {'FinReflectKG-EvalBench-derived': 17, 'ObliQA': 17, 'TAT-QA': 31, 'FinQA': 31, 'FinQA-seed': 1, 'TAT-QA-seed': 1, 'FinKG-seed': 1, 'AuditCompliance-seed': 1}
- Risk distribution: {'high': 36, 'medium': 64}
- Capability coverage: {'requires_calculation': 49, 'requires_table_reasoning': 55, 'requires_kg_reasoning': 18, 'requires_verification': 100}
- Exact duplicate groups: 0
- Near-duplicate pairs: 10
- Question/answer leakage flags: 0
- Missing evidence: 4

Warnings:
- 10 near-duplicate pairs require review
- 4 rows have no separate evidence field (all retain non-empty context/table)
- 11 long reference answers exceed 2000 characters

## Scoring properties
- Status: PASS
- PASS: quality monotonic
- PASS: cost monotonic decreasing
- PASS: latency monotonic decreasing
- PASS: reliability monotonic
- PASS: all-best boundary
- PASS: all-worst boundary
- PASS: cost clamp low/high
- PASS: token clamp
- PASS: latency clamp
- PASS: weights sum one
- PASS: 2000 randomized monotonic cases
- PASS: risk weighting preserves utility direction

## Checkpoint fault injection
- Status: PASS
- PASS: 30 percent interruption resumes 30 successes
- PASS: failed result remains retryable
- PASS: successful calls are not scheduled again
- PASS: latest successful duplicate wins
- PASS: corrupt line is ignored
- PASS: signature isolation
- PASS: atomic progress write
