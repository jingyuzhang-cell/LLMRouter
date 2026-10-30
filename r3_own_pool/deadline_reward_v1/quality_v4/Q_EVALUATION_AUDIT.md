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

## P0 real-execution audit record (2026-10-30, operator directive)

Correction of delivery status: the earlier claim "18 tests passed locally" had no execution record behind it. The suite has now been executed for real.

- Environment: Python 3.12.3, Linux; `python -m py_compile terminal_quality.py test_terminal_quality.py` → OK (exit 0).
- `python -m unittest -v test_terminal_quality` → **Ran 18 tests in 0.004s, OK (exit 0)**; two consecutive runs byte-identical (deterministic; the evaluator is a pure function with stdlib-only imports, zero model calls).
- Isolation re-verified: PR adds 6 new files (+850/−0), imports no existing scorer, writes nothing; historical scores untouched.
- PR remains DRAFT. Passing synthetic tests still validates code invariants only — not human calibration, domain validity, or scheduler benefit (unchanged status: IMPLEMENTED_OFFLINE / NOT_HUMAN_CALIBRATED / NOT_PRODUCTION_INTEGRATED).

### Code-review findings (all reproduced with minimal fixtures; code intentionally left unchanged pending operator decision)

- **F1 (HIGH, spec gap): the critical-fact hard gate is not implemented.** The `critical` field appears in the example contract and tests but is never read by `terminal_quality.py`. Repro: two GOLD facts, the critical amount wrong by ~10×, everything else perfect → `Q_final = 0.625` (fact 0.5 / evidence 0.5 / completeness 0.5 / relevance 1.0 averaged). A wrong critical amount can be averaged away, which violates the frozen Q specification (关键事实硬门禁). Gate semantics (cap Q, force NULL, or fact-level veto) must be decided by the operator, then implemented with tests.
- **F2 (HIGH, correctness): a calibrated-judge SUPPORTED verdict can override deterministic typed-value verification.** With an explicit `fact_id`, a claim whose date value is wrong by one day (2026-09-19 vs gold 2026-09-18) and whose predicate is paraphrased counts as TP (`SEMANTICALLY_CORRECT`) when `assessment = {verdict: SUPPORTED, assessor_type: calibrated_judge, calibration_status: PASS, ...}`. The SUPPORTED branch does not re-run `_derived_value_ok`/`_value_equal` for typed kinds. Deterministic checks for `date/number/amount/ratio/percent` should not be overridable; the judge should only authorize equivalence for text/relation claims.
- **F3 (MEDIUM, robustness): a numeric-typed claim value of `NaN` crashes the evaluator** with `decimal.InvalidOperation` (`_decimal` accepts `Decimal("NaN")`; the ordered comparison raises). A single malformed claim aborts the whole evaluation instead of yielding fp or NULL.
- **F4 (LOW, labeling): a correct duplicate claim without citations is counted fp (correct) but labeled `WRONG_GOLD_FACT_VALUE_OR_RELATION`** — misleading for downstream diagnosis; only citation-carrying duplicates get the `DUPLICATE_CLAIM` label.
- **F5 (LOW): no calendar validity check** — `2026-02-31` normalizes and matches (month/day range check only).
- **F6 (LOW–MEDIUM, gate scope): derivation inputs may reference non-GOLD facts.** `facts_by_id` is built from all required facts, so with `min_gold_coverage < 1` a SILVER input participates in the arithmetic consistency check of a GOLD derived fact and formal Q is issued (repro: gold coverage 0.667, Q_final 0.875 with a SILVER input). Derivation inputs of formal-gold facts should themselves be required to be formal gold.

Recommended order before this PR leaves DRAFT: decide F1 gate semantics, fix F1–F3 with new regression tests, relabel F4; F5/F6 can follow. Separately, the human-calibration prerequisites (C9 dual review, adjudication, fact-level Gold for the capital-market scenario) remain open — see the P1 package inventory in the main workspace.
