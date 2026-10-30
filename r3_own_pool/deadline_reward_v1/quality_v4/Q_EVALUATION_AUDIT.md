# Q Evaluation Audit — Existing Project State

Scope: artifacts in the connected LLMRouter default branch. This is a repository-artifact audit, not a claim that the AutoDL runtime filesystem was inspected.

## Findings

### C9 judge calibration
`phase_c9_0/C9_2_MACHINE_CALIBRATION_CLOSURE.json` records MACHINE_CALIBRATION_FAIL:

| Judge | Successful / expected groups | Parse success |
|---|---:|---:|
| Qwen-Max | 15/15 | 1.000 |
| GLM-4-Flash | 9/15 | 0.600 |
| Doubao | 13/15 | 0.867 |

Stability calibration was NOT_RUN_THIS_CLOSURE; the C9 final semantic scorer was not frozen in this closure.

### Human calibration
`C9_HUMAN_REVIEW_STATUS.json` records UNAVAILABLE, requires two independent reviewers, 30 groups and 123 candidate answers per reviewer, forbids LLM substitution, and does not allow a human-Gold claim. Reviewer A/B each contain 30 template rows, zero scored rows, and have identical SHA-256. They are templates, not labels.

### E4.1 operational scorer
`E4_SCORER_FROZEN.json` freezes deterministic unit-contract scoring for 17 task types and Qwen-Max as the sole semantic judge for 23 open task types. GLM and Doubao are engineering-unavailable. The artifact explicitly states that the semantic layer is machine-judged without human validation.

The 160-row `E4_PHASE_A_FINAL_LABELS.jsonl` contains 83 workflow-valid and 77 delivery-failure outcomes. Semantic layer: 56 rows, mean Q_final 0.5848. Deterministic layer: 27 rows, mean 0.3333. Delivery-failure layer: 77 rows, Q_delivered 0. These are frozen E4.1 operational scores, not proof of human calibration or a domain-general capital-market DAG evaluator.

### Capital-market terminal evaluator
`deadline_reward_v1/terminal_eval.py` correctly restricts terminal scoring to sink nodes, but still checks keyword/date/amount/entity strings. For compound keys separated by |, any one component can satisfy a key. It does not verify full subject-predicate-value relation, date type, unit, source entailment or cross-document derivation. Its six tests concern sink-vs-intermediate placement and synthesis loss, not semantic correctness.

### Reference status
`SCORING_REFERENCE_COMPLETE_v2` is PARTIAL: 33 candidate items include 25 CONFIRMED, 7 UNCERTAIN and 1 REJECTED. CT02 and CT07 are single-model-only; CT03 retains seven uncertain items; CT09 has one rejected item. It is machine-assisted partial reference, not complete independently adjudicated Gold.

`SOURCE_CONSTRAINED_REFERENCE.json` explicitly says independent_gold=false and human_blind_review_performed=false. It leaves necessary completeness/question relevance unknown when the original question is missing and retains unresolved conflict items.

## Verdict
The project has useful components but no single domain-general, human-calibrated terminal Q evaluator. It has task-specific deterministic scorers, a Qwen-only operational semantic scorer, source-traceable Silver references and a keyword-based sink evaluator.

The new quality_v4 evaluator is an isolated offline implementation of the six-dimensional rubric with Gold gates, hash-bound source spans, typed fact matching, cross-document evidence requirements, UNKNOWN handling and judge-calibration checks. Its synthetic tests pass. It is not production-integrated or human-calibrated.
