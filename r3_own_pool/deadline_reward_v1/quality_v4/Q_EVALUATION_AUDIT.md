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

## F1–F6 fix record (2026-10-30, operator rulings implemented; evaluator version bumped to terminal_quality_v1.1)

Operator rulings received and implemented the same day:

- **F1 → three-state critical-fact hard gate** (PASS → Q_final=Q_raw; FAIL → Q_final=0 when any critical fact is confirmed wrong, omitted, or evidence-unsatisfied under a frozen `evidence_required`; UNKNOWN → NULL when a critical fact lacks formal Gold and none is confirmed wrong; FAIL dominates UNKNOWN). `critical` is a contract-freeze-time property; SILVER can never ground the gate; Q_raw is always reported for diagnostics.
- **F2 → deterministic precedence**: `_semantic_core_matches` now enforces unit, date_type, subject binding (with optional `subject_aliases`), typed values and derivations before any SUPPORTED verdict can count; the explicit `fact_id` path is equally subject to it. Judge authorization survives only for predicate wording and text-kind paraphrase.
- **F3 → non-finite numerics rejected**: `_decimal` returns None for NaN/±Infinity (invalid claim → fp, no crash); a formal-Gold fact with a non-finite numeric (or unparseable tolerance, or non-calendar date) raises `GOLD_CONTRACT_INVALID_VALUE:{fact_id}` and withholds Q; all Decimal arithmetic is exception-guarded.
- **F4 → duplicate relabel**: value-correct duplicates are always labeled `DUPLICATE_CLAIM` (with or without citations); wrong-value repeats stay `WRONG_GOLD_FACT_VALUE_OR_RELATION`. fp accounting unchanged.
- **F5 → calendar validation**: dates validated via real calendar construction (2024-02-29 valid; 2023-02-29 and 2026-02-31 invalid).
- **F6 → GOLD-only derivations**: `_formal_gold` now requires every derivation input to be a non-excluded formal-GOLD fact (recursively, cycle-safe); a GOLD-flagged derived fact with a SILVER input is excluded from formal Gold (warning `REFERENCE_DERIVATION_INPUT_NOT_GOLD`), drops out of formal scoring, and — if critical — drives the gate to UNKNOWN.

Regression tests added (12) covering the operator's six required scenarios plus positive/interaction cases: critical amount wrong 10× (Q_final=0, Q_raw=0.625 preserved), critical omission, critical-without-formal-Gold (UNKNOWN→NULL), evidence-required critical with keyword citation (FAIL), judge-SUPPORTED wrong date (fp, not TP), judge-SUPPORTED paraphrase with correct value (still TP), NaN/Infinity claims (no crash), NaN in Gold contract (blocking), illegal Gold date (blocking), leap-year boundaries, correct-duplicate relabel, and SILVER-derivation exclusion (non-critical → excluded from scoring; critical → gate UNKNOWN; min-coverage=1 → coverage blocking).

**Real execution: `python -m unittest -v test_terminal_quality` → Ran 30 tests in 0.007s — OK (exit 0)** (18 original + 12 regression; py_compile OK; zero model calls; historical artifacts untouched). Checklist status: fixes ✔, regression tests ✔, full re-run ✔; remaining before merge: independent code re-review and final merge approval. PR stays DRAFT; human-calibration status unchanged.

## Independent re-review findings F7–F10 fixed (2026-10-30, evaluator bumped to terminal_quality_v1.2)

Operator's independent code re-review of 30ce7b6a (read directly from the PR, not from delivery summaries) found four further issues plus two boundary gaps; all fixed in one hardening pass:

- **F7 (HIGH) duplicate fact_id could bypass the critical gate** — `facts_by_id` silently collapsed duplicates and `matched_ids` is keyed by fact_id, so two critical facts sharing an id could both read as matched from one answer. Fixed with a contract-structure gate that blocks (no Q) on empty/duplicate fact ids and on duplicated/unresolvable derivation inputs — before any matching, never by patching the matcher.
- **F8 (HIGH) unvalidated numeric config** — fact weights, dimension weights and `min_gold_coverage` were `float()`-ed without finiteness/range checks (NaN coverage never triggers the gate; Infinity weights NaN the mean). Now: fact weights finite positive; dimension weights finite non-negative with ≥1 positive; coverage finite in [0,1]; claim weights (extraction-stage property) finite positive or `CLAIM_WEIGHT_INVALID` blocking.
- **F9 (HIGH) judge credential too weak** — a bare `calibration_status: PASS` + non-empty hash string sufficed. Now a calibrated-judge verdict requires: registry-bound judge_id whose registered artifact SHA equals a well-formed 64-hex hash, blindness to model and strategy, and a `binding_claim_id` equal to the assessed claim (no cross-claim replay). Registry is passed as `judge_calibration_registry` by the caller.
- **F10 (MED-HIGH) substance-free UNKNOWN/conflict scoring** — abstention counted on item_id presence; conflict on acknowledged + doc-id list. Now abstentions require explicit non-empty refusal text (bare ticks warn `ABSTENTION_WITHOUT_EXPLICIT_TEXT` and score 0), and conflict acknowledgement requires per-source `source_versions` with non-empty text for every required document.
- **Boundary 1**: `_span_is_valid` now recomputes sha256(page text) and rejects internally inconsistent page records.
- **Boundary 2**: derivation arithmetic requires identical input units (and target unit for add/subtract); mixed units cannot form a valid derivation until a conversion rule is frozen.

Regression tests added (12): duplicate/empty fact_id blocking, derivation input duplication/unresolvability, NaN/Infinity/out-of-range coverage, invalid fact/dimension/claim weights, judge-credential matrix (no registry / unregistered / cross-claim binding replay / malformed hash — all rejected), bare abstention, per-source conflict versions both ways, tampered page text vs stale hash, mixed-unit derivation.

**Real execution after hardening: `python -m unittest -v test_terminal_quality` → Ran 42 tests in 0.011s — OK (exit 0)** (30 prior + 12 new). Two prior judge tests updated to carry full credentials so their outcomes test the deterministic mismatch itself. Checklist: contract/credential hardening ✔, regression ✔, full re-run ✔; next: fresh independent code re-review of v1.2, then final merge approval. PR stays DRAFT; NOT_HUMAN_CALIBRATED unchanged.

## Fresh adversarial re-review of v1.2 → v1.2.1 (2026-10-30)

A fresh independent adversarial review (subagent, no authorship context; every finding reproduced by execution) returned **ISSUES_FOUND**: 1 HIGH, 7 MEDIUM, 9 LOW. The core matching/gate logic resisted every inflation attempt; defects clustered in input-validation robustness, credential-binding edges and numeric extremes. All HIGH/MEDIUM items plus L1/L2/L3/L7/L8 were fixed the same day (evaluator bumped to `terminal_quality_v1.2.1`):

- **H1 malformed citations crashed the scorer from the answer side** (`start="x"` → ValueError; non-mapping citations → AttributeError). Fixed: integer-coercible offsets via `_safe_int`, non-mapping citations/evidence/claims/abstentions/acknowledgements filtered or blocked.
- **M1 huge-but-finite weights (1e308) overflowed the sums to inf → NaN coverage silently bypassed the gate and emitted a green non-finite formal Q.** Fixed: `WEIGHT_SUM_NOT_FINITE` blocking + terminal `Q_NOT_FINITE` guard (formal Q is finite or NULL, always).
- **M2 an unknown_items entry without item_id poisoned every id-less claim (perfect answer scored 0.0).** Fixed: `UNKNOWN_ITEM_ID_INVALID` contract blocking — malformed contracts block, they do not convert correct answers into confirmed-wrong.
- **M3 the validator flagged unparseable weights/coverage but the scorer crashed before returning the flags** (`"abc"`). Fixed: `_finite_float`/`_fact_weight` at every use site with safe defaults.
- **M4 judge binding bypassed for id-less claims and duplicate claim_ids let one verdict authorize multiple facts.** Fixed: verdicts require a non-empty hashable claim_id; duplicate claim_ids block (`CLAIM_ID_DUPLICATE`).
- **M5 `CONFLICT_UNRESOLVED` facts never blocked by themselves at min_gold_coverage<1 (formal Q=1.0 over an unresolved conflict).** Fixed: explicit `REFERENCE_CONFLICT_UNRESOLVED` blocking, per protocol §4.
- **M6 unbounded tolerance voided the critical gate (tolerance 1e999 let a 10×-wrong amount pass; tolerance -1 made a correct answer unmatchable).** Frozen rule: tolerance finite, ≥0, and ≤ |gold value| (≤1 for zero-valued facts), else `GOLD_CONTRACT_INVALID_VALUE`.
- **M7 zero-Gold contracts could emit formal SCORABLE_GOLD at min_gold_coverage=0.** Fixed: `NO_FORMAL_GOLD` blocking whenever gold weight is 0.
- **L1** Decimal overflow at the derived-comparison line guarded; **L2** unhashable ids (fact/claim/unknown/conflict) blocked or filtered everywhere (four crash sites fixed); **L3** non-integer reviewer counts safely rejected; **L7** boolean relevance scores rejected; **L8** empty judge_id rejected, registry-vs-artifact comparison case-normalized.

**Recorded, not changed (open ruling questions):** L4 native-annotation evidence semantics, L5 credentialed-SUPPORTED-on-unmatched-claim currently withholds Q (beyond-contract true assertions make the answer unscorable — whether they should be a distinct fp class is an operator decision), L6 evidence satisfaction assessed on the first matching claim only, L9 blocking-vs-veto precedence (now documented explicitly in §9: withholding outranks the zero veto).

Test suite: +12 regression tests for the above (54 total); five tautological `assertIsNotNone` gate assertions strengthened to exact values; one fixture bug (duplicate claim_id "C1" in the unanswerable-assertion test) surfaced by the new validator and fixed. **Real execution: `Ran 54 tests in 0.013s — OK (exit 0)`; double-run byte-identical.** PR remains DRAFT pending operator's final review; NOT_HUMAN_CALIBRATED unchanged.
