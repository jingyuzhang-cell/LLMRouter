import hashlib
import unittest
from terminal_quality import evaluate_terminal_quality

PAGE = "公司于2026年9月18日收到中国证监会立案告知书，编号0142026049号。"
RAW_SHA = "a" * 64
PAGE_SHA = hashlib.sha256(PAGE.encode()).hexdigest()


def contract(status="GOLD_CONFIRMED", provenance="human_adjudicated"):
    fact = {
        "fact_id": "F1", "status": status, "gold_provenance": provenance,
        "gold_source_sha256": RAW_SHA,
        "review": {"status": "ADJUDICATED", "independent_reviewers": 2, "reviewer_ids": ["R1", "R2"], "blind_to_strategy": True, "blind_to_model": True},
        "weight": 1.0, "critical": True, "value_kind": "date",
        "subject": "某公司", "predicate": "收到立案告知书日期",
        "value": "2026-09-18", "unit": "date", "date_type": "receipt",
        "source_evidence": [{"doc_id": "D1", "page": 1, "quote": "公司于2026年9月18日收到中国证监会立案告知书", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA}],
    }
    return {
        "task_id": "T1", "question": "公司何时收到立案告知书？",
        "required_facts": [fact], "unknown_items": [], "conflict_groups": [],
        "min_gold_coverage": 1.0,
    }


def output(claim, **kwargs):
    base = {
        "delivery_valid": True, "claims_complete": True,
        "claims": [claim], "abstentions": [], "abstentions_complete": True,
        "conflict_acknowledgements": [],
        "question_relevance": {"score": 1.0, "assessor_type": "human_adjudicator", "review_status": "ADJUDICATED", "reviewer_ids": ["R1", "R2"], "blind_to_strategy": True, "blind_to_model": True},
    }
    base.update(kwargs)
    return base


def good_claim(**overrides):
    claim = {
        "claim_id": "C1", "fact_id": "F1", "material": True,
        "subject": "某公司", "predicate": "收到立案告知书日期",
        "value": "2026年9月18日", "unit": "date", "date_type": "receipt",
        "citations": [{"doc_id": "D1", "page": 1, "quote": "公司于2026年9月18日收到中国证监会立案告知书", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA}],
    }
    claim.update(overrides)
    return claim


class TerminalQualityTests(unittest.TestCase):
    def setUp(self):
        self.sources = {"D1": {"raw_sha256": RAW_SHA, "pages": {"1": {"text": PAGE, "page_sha256": PAGE_SHA}}}}

    def test_correct_claim_with_adjudicated_source_span_scores(self):
        result = evaluate_terminal_quality(contract(), output(good_claim()), self.sources)
        self.assertEqual(result["status"], "SCORABLE_GOLD")
        self.assertEqual(result["Q_final"], 1.0)
        self.assertEqual(result["Q_delivered"], 1.0)

    def test_wrong_date_type_does_not_match_same_date(self):
        result = evaluate_terminal_quality(contract(), output(good_claim(date_type="publication")), self.sources)
        self.assertEqual(result["Q_final"], 0.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 1.0)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 0.0)

    def test_keyword_or_quote_hit_without_correct_predicate_is_not_pass(self):
        claim = good_claim(predicate="行政处罚决定作出日期", value="处罚")
        result = evaluate_terminal_quality(contract(), output(claim), self.sources)
        self.assertEqual(result["Q_final"], 0.0)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 0.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 1.0)

    def test_wrong_unit_does_not_match(self):
        result = evaluate_terminal_quality(contract(), output(good_claim(unit="publication_date")), self.sources)
        self.assertEqual(result["Q_final"], 0.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 1.0)

    def test_missing_required_fact_reduces_completeness(self):
        relevance = {"score": 0.0, "assessor_type": "human_adjudicator", "review_status": "ADJUDICATED", "reviewer_ids": ["R1", "R2"], "blind_to_strategy": True, "blind_to_model": True}
        result = evaluate_terminal_quality(contract(), output(good_claim(), claims=[], question_relevance=relevance), self.sources)
        self.assertEqual(result["Q_final"], 0.0)
        self.assertEqual(result["fact_metrics"]["weighted_fn"], 1.0)

    def test_silver_reference_never_becomes_formal_q(self):
        result = evaluate_terminal_quality(contract(status="SILVER_SOURCE_ANCHORED"), output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertIn("REFERENCE_GOLD_COVERAGE_BELOW_GATE", result["blocking_reasons"])

    def test_literal_quote_without_verified_source_hash_is_rejected(self):
        source_pages = {"D1": {"raw_sha256": "b" * 64, "pages": {"1": {"text": PAGE, "page_sha256": PAGE_SHA}}}}
        result = evaluate_terminal_quality(contract(), output(good_claim()), source_pages)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any(reason.startswith("REFERENCE_EVIDENCE_INVALID") for reason in result["blocking_reasons"]))

    def test_uncalibrated_judge_cannot_authorize_semantic_equivalence(self):
        claim = good_claim(value="2026年9月18日", predicate="公司收件日")
        claim["assessment"] = {"verdict": "SUPPORTED", "assessor_type": "calibrated_judge", "calibration_status": "PENDING"}
        result = evaluate_terminal_quality(contract(), output(claim), self.sources)
        self.assertIsNotNone(result["Q_final"])
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 0.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 1.0)

    def test_delivery_failure_keeps_semantic_q_unavailable(self):
        result = evaluate_terminal_quality(contract(), output(good_claim(), delivery_valid=False), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertEqual(result["Q_delivered"], 0.0)

    def test_correct_unknown_abstention_is_scored(self):
        task = contract()
        task["unknown_items"] = [{"item_id": "U1", "description": "最终处罚决定"}]
        final_output = output(good_claim(), abstentions=[{"item_id": "U1", "text": "材料未披露最终处罚决定，无法核验。"}])
        result = evaluate_terminal_quality(task, final_output, self.sources)
        self.assertEqual(result["status"], "SCORABLE_GOLD")
        self.assertEqual(result["dimensions"]["unverifiable_refusal"], 1.0)

    def test_unanswerable_assertion_is_not_hidden_by_keyword_match(self):
        task = contract()
        task["unknown_items"] = [{"item_id": "U1", "description": "最终处罚决定"}]
        bad_claim = good_claim(claim_id="C2")
        bad_claim["item_id"] = "U1"
        final_output = output(good_claim(), claims=[good_claim(), bad_claim], abstentions=[])
        result = evaluate_terminal_quality(task, final_output, self.sources)
        self.assertEqual(result["Q_final"], 0.6)
        self.assertEqual(result["dimensions"]["unverifiable_refusal"], 0.0)
        self.assertIn("UNVERIFIABLE_ITEM_ASSERTED", result["quality_warnings"])

    def test_conflict_requires_source_attribution(self):
        task = contract()
        task["conflict_groups"] = [{"conflict_id": "X1", "required_source_doc_ids": ["D1", "D2"]}]
        final_output = output(good_claim(), conflict_acknowledgements=[{"conflict_id": "X1", "acknowledged": True, "source_doc_ids": ["D1"]}])
        result = evaluate_terminal_quality(task, final_output, self.sources)
        self.assertEqual(result["dimensions"]["contradiction_handling"], 0.0)

    def test_claims_incomplete_blocks_formal_q(self):
        result = evaluate_terminal_quality(contract(), output(good_claim(), claims_complete=False), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertIn("CLAIM_EXTRACTION_INCOMPLETE", result["blocking_reasons"])

    def test_task_without_question_cannot_receive_relevance_score(self):
        task = contract()
        task["question"] = ""
        result = evaluate_terminal_quality(task, output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertIn("TASK_QUESTION_MISSING", result["blocking_reasons"])

    def test_short_keyword_quote_does_not_count_as_evidence_support(self):
        short_citation = {"doc_id": "D1", "page": 1, "quote": "立案告知书", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA}
        result = evaluate_terminal_quality(contract(), output(good_claim(citations=[short_citation])), self.sources)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 1.0)
        self.assertEqual(result["dimensions"]["evidence_support"], 0.0)
        self.assertLess(result["Q_final"], 1.0)

    def _derived_task(self):
        page2 = "公司上年度收入为50万元。"
        page2_sha = hashlib.sha256(page2.encode()).hexdigest()
        task = contract()
        derived = task["required_facts"][0]
        derived.update({
            "value_kind": "amount", "subject": "某公司", "predicate": "收入差额",
            "value": "100", "unit": "万元", "date_type": "UNKNOWN",
            "derivation": {"op": "subtract", "inputs": ["F2", "F3"]},
            "evidence_mode": "ALL",
            "source_evidence": [
                {"doc_id": "D1", "page": 1, "quote": "公司于2026年9月18日收到中国证监会立案告知书", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA},
                {"doc_id": "D2", "page": 1, "quote": "公司上年度收入为50万元。", "page_sha256": page2_sha, "raw_sha256": "b" * 64},
            ],
        })
        task["required_facts"].extend([
            {
                "fact_id": "F2", "status": "GOLD_CONFIRMED", "gold_provenance": "human_adjudicated",
                "gold_source_sha256": RAW_SHA,
                "review": {"status": "ADJUDICATED", "independent_reviewers": 2, "reviewer_ids": ["R1", "R2"], "blind_to_strategy": True, "blind_to_model": True},
                "value": "150", "value_kind": "amount", "weight": 1,
                "source_evidence": [{"doc_id": "D1", "page": 1, "quote": "公司于2026年9月18日收到中国证监会立案告知书", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA}],
            },
            {
                "fact_id": "F3", "status": "GOLD_CONFIRMED", "gold_provenance": "human_adjudicated",
                "gold_source_sha256": "b" * 64,
                "review": {"status": "ADJUDICATED", "independent_reviewers": 2, "reviewer_ids": ["R1", "R2"], "blind_to_strategy": True, "blind_to_model": True},
                "value": "50", "value_kind": "amount", "weight": 1,
                "source_evidence": [{"doc_id": "D2", "page": 1, "quote": "公司上年度收入为50万元。", "page_sha256": page2_sha, "raw_sha256": "b" * 64}],
            },
        ])
        source_pages = {
            **self.sources,
            "D2": {"raw_sha256": "b" * 64, "pages": {"1": {"text": page2, "page_sha256": page2_sha}}},
        }
        return task, source_pages

    def test_derived_cross_document_fact_requires_all_evidence_spans(self):
        task, source_pages = self._derived_task()
        claim = good_claim(
            fact_id="F1", value="100", unit="万元", predicate="收入差额",
            date_type="UNKNOWN",
            citations=[{"doc_id": "D1", "page": 1, "quote": "公司于2026年9月18日收到中国证监会立案告知书", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA}],
        )
        result = evaluate_terminal_quality(task, output(claim), source_pages)
        self.assertEqual(result["dimensions"]["evidence_support"], 0.0)
        self.assertLess(result["Q_final"], 1.0)

    def test_derived_fact_passes_only_when_both_source_spans_are_cited(self):
        task, source_pages = self._derived_task()
        page2_sha = source_pages["D2"]["pages"]["1"]["page_sha256"]
        claim = good_claim(
            fact_id="F1", value="100", unit="万元", predicate="收入差额",
            date_type="UNKNOWN",
            citations=[
                {"doc_id": "D1", "page": 1, "quote": "公司于2026年9月18日收到中国证监会立案告知书", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA},
                {"doc_id": "D2", "page": 1, "quote": "公司上年度收入为50万元。", "page_sha256": page2_sha, "raw_sha256": "b" * 64},
            ],
        )
        result = evaluate_terminal_quality(task, output(claim), source_pages)
        self.assertEqual(result["dimensions"]["evidence_support"], 1.0)

    def test_duplicate_claim_does_not_inflate_tp(self):
        claim = good_claim()
        result = evaluate_terminal_quality(contract(), output(claim, claims=[claim, dict(claim, claim_id="C2")]), self.sources)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 1.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 1.0)

    # --- Regression tests for operator-ruled fixes F1-F6 (ruling 2026-10-30) ---

    def _amount_fact(self, fact_id="F2", critical=False, evidence_required=False, value="1000", status="GOLD_CONFIRMED"):
        return {
            "fact_id": fact_id, "status": status, "gold_provenance": "human_adjudicated",
            "gold_source_sha256": RAW_SHA,
            "review": {"status": "ADJUDICATED", "independent_reviewers": 2, "reviewer_ids": ["R1", "R2"], "blind_to_strategy": True, "blind_to_model": True},
            "weight": 1.0, "critical": critical, "evidence_required": evidence_required,
            "value_kind": "amount", "subject": "某公司", "predicate": "处罚金额",
            "value": value, "unit": "万元",
            "source_evidence": [{"doc_id": "D1", "page": 1, "quote": "公司于2026年9月18日收到中国证监会立案告知书", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA}],
        }

    def test_critical_amount_wrong_vetoes_q_final_keeps_q_raw(self):
        task = contract()
        task["required_facts"].append(self._amount_fact(critical=True))
        wrong_amount = good_claim(claim_id="C2", fact_id="F2", subject="某公司", predicate="处罚金额", value="9999", unit="万元")
        result = evaluate_terminal_quality(task, output(good_claim(), claims=[good_claim(), wrong_amount]), self.sources)
        self.assertEqual(result["critical_gate"]["status"], "FAIL")
        self.assertEqual(result["Q_final"], 0.0)
        self.assertEqual(result["Q_raw"], 0.625)
        self.assertEqual(result["status"], "SCORABLE_GOLD")

    def test_critical_fact_omission_vetoes_q_final(self):
        task = contract()
        task["required_facts"][0]["critical"] = True
        result = evaluate_terminal_quality(task, output(good_claim(), claims=[]), self.sources)
        self.assertEqual(result["critical_gate"]["status"], "FAIL")
        self.assertEqual(result["Q_final"], 0.0)
        self.assertEqual(result["Q_raw"], 0.25)

    def test_critical_fact_without_formal_gold_withholds_q(self):
        task = contract()
        task["required_facts"][0]["critical"] = True
        task["required_facts"].append(self._amount_fact(fact_id="FS", status="SILVER_SOURCE_ANCHORED", critical=True))
        task["min_gold_coverage"] = 0.5
        result = evaluate_terminal_quality(task, output(good_claim()), self.sources)
        self.assertEqual(result["critical_gate"]["status"], "UNKNOWN")
        self.assertIsNone(result["Q_final"])
        self.assertIn("CRITICAL_GATE_UNKNOWN", result["blocking_reasons"])

    def test_critical_fact_evidence_requirement_enforced(self):
        task = contract()
        task["required_facts"].append(self._amount_fact(critical=True, evidence_required=True))
        short_citation = [{"doc_id": "D1", "page": 1, "quote": "处罚", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA}]
        amount_claim = good_claim(claim_id="C2", fact_id="F2", subject="某公司", predicate="处罚金额", value="1000", unit="万元", citations=short_citation)
        result = evaluate_terminal_quality(task, output(good_claim(), claims=[good_claim(), amount_claim]), self.sources)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 2.0)
        self.assertEqual(result["dimensions"]["evidence_support"], 0.5)
        self.assertEqual(result["critical_gate"]["status"], "FAIL")
        self.assertEqual(result["critical_gate"]["evidence_unsatisfied_fact_ids"], ["F2"])
        self.assertEqual(result["Q_final"], 0.0)

    def test_calibrated_judge_cannot_override_wrong_date_value(self):
        claim = good_claim(value="2026年9月19日", predicate="公司收件日")
        claim["assessment"] = {
            "verdict": "SUPPORTED", "assessor_type": "calibrated_judge",
            "calibration_status": "PASS", "judge_id": "J1",
            "calibration_artifact_sha256": "c" * 64,
            "blind_to_strategy": True, "blind_to_model": True,
            "binding_claim_id": "C1",
        }
        registry = {"J1": "c" * 64}
        result = evaluate_terminal_quality(contract(), output(claim), self.sources, registry)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 0.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 1.0)
        self.assertEqual(result["claim_results"][0]["status"], "WRONG_GOLD_FACT_VALUE_OR_RELATION")
        self.assertIsNotNone(result["Q_final"])

    def test_calibrated_judge_still_authorizes_paraphrase_with_correct_value(self):
        claim = good_claim(value="2026年9月18日", predicate="公司收件日")
        claim["assessment"] = {
            "verdict": "SUPPORTED", "assessor_type": "calibrated_judge",
            "calibration_status": "PASS", "judge_id": "J1",
            "calibration_artifact_sha256": "c" * 64,
            "blind_to_strategy": True, "blind_to_model": True,
            "binding_claim_id": "C1",
        }
        registry = {"J1": "c" * 64}
        result = evaluate_terminal_quality(contract(), output(claim), self.sources, registry)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 1.0)
        self.assertEqual(result["claim_results"][0]["status"], "SEMANTICALLY_CORRECT")
        self.assertEqual(result["Q_final"], 1.0)

    def test_nonfinite_claim_values_do_not_crash(self):
        task = contract()
        task["required_facts"].append(self._amount_fact(critical=False))
        nan_claim = good_claim(claim_id="C2", fact_id="F2", subject="某公司", predicate="处罚金额", value="NaN", unit="万元")
        inf_claim = good_claim(claim_id="C3", fact_id="F2", subject="某公司", predicate="处罚金额", value="Infinity", unit="万元")
        result = evaluate_terminal_quality(task, output(good_claim(), claims=[good_claim(), nan_claim, inf_claim]), self.sources)
        self.assertAlmostEqual(result["Q_final"], 0.541667, places=6)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 1.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 2.0)

    def test_gold_contract_nonfinite_value_blocks_q(self):
        task = contract()
        task["required_facts"].append(self._amount_fact(value="NaN"))
        result = evaluate_terminal_quality(task, output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any(reason.startswith("GOLD_CONTRACT_INVALID_VALUE") for reason in result["blocking_reasons"]))

    def test_gold_contract_illegal_date_blocks_q(self):
        task = contract()
        task["required_facts"][0]["value"] = "2026-02-31"
        result = evaluate_terminal_quality(task, output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any(reason.startswith("GOLD_CONTRACT_INVALID_VALUE") for reason in result["blocking_reasons"]))

    def test_calendar_validity_and_leap_year_boundaries(self):
        leap = contract()
        leap["required_facts"][0]["value"] = "2024-02-29"
        ok = evaluate_terminal_quality(leap, output(good_claim(value="2024年2月29日")), self.sources)
        self.assertEqual(ok["fact_metrics"]["weighted_tp"], 1.0)
        nonleap = contract()
        nonleap["required_facts"][0]["value"] = "2023-03-01"
        invalid = evaluate_terminal_quality(nonleap, output(good_claim(value="2023年2月29日")), self.sources)
        self.assertEqual(invalid["fact_metrics"]["weighted_tp"], 0.0)
        self.assertEqual(invalid["fact_metrics"]["weighted_fp"], 1.0)
        impossible = contract()
        impossible["required_facts"][0]["value"] = "2026-02-28"
        rejected = evaluate_terminal_quality(impossible, output(good_claim(value="2026年2月31日")), self.sources)
        self.assertEqual(rejected["fact_metrics"]["weighted_tp"], 0.0)

    def test_correct_duplicate_without_citations_labeled_duplicate(self):
        duplicate = good_claim(claim_id="C2")
        duplicate.pop("citations")
        result = evaluate_terminal_quality(contract(), output(good_claim(), claims=[good_claim(), duplicate]), self.sources)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 1.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 1.0)
        self.assertEqual(result["claim_results"][1]["status"], "DUPLICATE_CLAIM")
        self.assertIn("DUPLICATE_CLAIM:C2", result["quality_warnings"])
        self.assertEqual(result["blocking_reasons"], [])

    def test_silver_derivation_input_cannot_formalize_gold(self):
        page2 = "公司上年度收入为50万元。"
        page2_sha = hashlib.sha256(page2.encode()).hexdigest()
        task = contract()
        derived = task["required_facts"][0]
        derived.update({
            "value_kind": "amount", "subject": "某公司", "predicate": "收入差额",
            "value": "100", "unit": "万元", "date_type": "UNKNOWN",
            "derivation": {"op": "subtract", "inputs": ["F2", "F3"]},
            "source_evidence": [
                {"doc_id": "D1", "page": 1, "quote": "公司于2026年9月18日收到中国证监会立案告知书", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA},
                {"doc_id": "D2", "page": 1, "quote": page2, "page_sha256": page2_sha, "raw_sha256": "b" * 64},
            ],
        })
        silver_input = {
            "fact_id": "F2", "status": "SILVER_SOURCE_ANCHORED", "weight": 1.0,
            "value_kind": "amount", "subject": "某公司", "predicate": "本年度收入", "value": "150", "unit": "万元",
            "source_evidence": [{"doc_id": "D1", "page": 1, "quote": "公司于2026年9月18日收到中国证监会立案告知书", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA}],
        }
        gold_input = {
            "fact_id": "F3", "status": "GOLD_CONFIRMED", "gold_provenance": "human_adjudicated",
            "gold_source_sha256": "b" * 64,
            "review": {"status": "ADJUDICATED", "independent_reviewers": 2, "reviewer_ids": ["R1", "R2"], "blind_to_strategy": True, "blind_to_model": True},
            "weight": 1.0, "value_kind": "amount", "subject": "某公司", "predicate": "上年度收入", "value": "50", "unit": "万元",
            "source_evidence": [{"doc_id": "D2", "page": 1, "quote": page2, "page_sha256": page2_sha, "raw_sha256": "b" * 64}],
        }
        task["required_facts"].extend([silver_input, gold_input])
        sources = {**self.sources, "D2": {"raw_sha256": "b" * 64, "pages": {"1": {"text": page2, "page_sha256": page2_sha}}}}
        f3_claim = good_claim(claim_id="C3", fact_id="F3", subject="某公司", predicate="上年度收入", value="50", unit="万元", date_type="UNKNOWN",
                              citations=[{"doc_id": "D2", "page": 1, "quote": page2, "page_sha256": page2_sha, "raw_sha256": "b" * 64}])
        # F1 non-critical: excluded from formal Gold, F3 still scores, F1 never counts.
        derived["critical"] = False
        task["min_gold_coverage"] = 0.3
        result = evaluate_terminal_quality(task, output(f3_claim, claims=[f3_claim]), sources)
        self.assertEqual(result["critical_gate"]["status"], "PASS")
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 1.0)
        self.assertEqual(result["fact_metrics"]["weighted_fn"], 0.0)
        self.assertIn("REFERENCE_DERIVATION_INPUT_NOT_GOLD:F1", result["quality_warnings"])
        # F1 critical (fixture default): silver input makes the critical fact unevaluable -> gate UNKNOWN -> NULL.
        derived["critical"] = True
        result_critical = evaluate_terminal_quality(task, output(f3_claim, claims=[f3_claim]), sources)
        self.assertEqual(result_critical["critical_gate"]["status"], "UNKNOWN")
        self.assertIsNone(result_critical["Q_final"])
        self.assertIn("CRITICAL_GATE_UNKNOWN", result_critical["blocking_reasons"])
        # Full-coverage gate also blocks formal Q when a required fact cannot be formal Gold.
        full_gate = contract()
        full_gate["required_facts"] = task["required_facts"]
        full_gate["min_gold_coverage"] = 1.0
        result_full = evaluate_terminal_quality(full_gate, output(f3_claim, claims=[f3_claim]), sources)
        self.assertIsNone(result_full["Q_final"])
        self.assertIn("REFERENCE_GOLD_COVERAGE_BELOW_GATE", result_full["blocking_reasons"])


    # --- Regression tests for independent re-review findings F7-F10 (2026-10-30) ---

    def test_duplicate_fact_id_blocks_contract(self):
        task = contract()
        task["required_facts"].append(dict(self._amount_fact(fact_id="F1", critical=True)))  # duplicate of F1
        result = evaluate_terminal_quality(task, output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any("CONTRACT_STRUCTURE_INVALID:FACT_ID_DUPLICATE:F1" in r for r in result["blocking_reasons"]))

    def test_empty_fact_id_blocks_contract(self):
        task = contract()
        task["required_facts"][0]["fact_id"] = "  "
        result = evaluate_terminal_quality(task, output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any("FACT_ID_EMPTY" in r for r in result["blocking_reasons"]))

    def test_derivation_input_structure_problems_block(self):
        duplicated = self._derived_task()[0]
        duplicated["required_facts"][0]["derivation"]["inputs"] = ["F2", "F2"]
        _, sources = self._derived_task()
        result = evaluate_terminal_quality(duplicated, output(good_claim()), sources)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any("DERIVATION_INPUTS_DUPLICATE" in r for r in result["blocking_reasons"]))
        unresolved = self._derived_task()[0]
        unresolved["required_facts"][0]["derivation"]["inputs"] = ["F2", "FX"]
        result2 = evaluate_terminal_quality(unresolved, output(good_claim()), sources)
        self.assertIsNone(result2["Q_final"])
        self.assertTrue(any("DERIVATION_INPUT_UNRESOLVED" in r for r in result2["blocking_reasons"]))

    def test_invalid_min_gold_coverage_blocks(self):
        for bad in ("NaN", "Infinity", 1.5, -0.1):
            task = contract()
            task["min_gold_coverage"] = bad
            result = evaluate_terminal_quality(task, output(good_claim()), self.sources)
            self.assertIsNone(result["Q_final"], bad)
            self.assertTrue(any("MIN_GOLD_COVERAGE_INVALID" in r for r in result["blocking_reasons"]), bad)

    def test_invalid_fact_weight_blocks(self):
        for bad in ("NaN", -1, 0):
            task = contract()
            task["required_facts"].append(self._amount_fact(value="1000"))
            task["required_facts"][-1]["weight"] = bad
            result = evaluate_terminal_quality(task, output(good_claim()), self.sources)
            self.assertIsNone(result["Q_final"], bad)
            self.assertTrue(any("FACT_WEIGHT_INVALID" in r for r in result["blocking_reasons"]), bad)

    def test_invalid_dimension_weights_block(self):
        infinite = contract()
        infinite["dimension_weights"] = {"fact_correctness": "Infinity", "evidence_support": 1}
        result = evaluate_terminal_quality(infinite, output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any("DIMENSION_WEIGHT_INVALID:fact_correctness" in r for r in result["blocking_reasons"]))
        all_zero = contract()
        all_zero["dimension_weights"] = {name: 0 for name in (
            "fact_correctness", "evidence_support", "necessary_completeness",
            "contradiction_handling", "unverifiable_refusal", "question_relevance")}
        result2 = evaluate_terminal_quality(all_zero, output(good_claim()), self.sources)
        self.assertIsNone(result2["Q_final"])
        self.assertTrue(any("DIMENSION_WEIGHTS_ALL_ZERO" in r for r in result2["blocking_reasons"]))

    def test_invalid_claim_weight_blocks(self):
        claim = good_claim()
        claim["weight"] = "NaN"
        result = evaluate_terminal_quality(contract(), output(claim), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any("CLAIM_WEIGHT_INVALID:C1" in r for r in result["blocking_reasons"]))
        self.assertEqual(result["claim_results"][0]["status"], "INVALID_CLAIM_WEIGHT")

    def test_judge_credential_requires_registry_and_binding(self):
        claim = good_claim(value="2026年9月18日", predicate="公司收件日")
        claim["assessment"] = {
            "verdict": "SUPPORTED", "assessor_type": "calibrated_judge",
            "calibration_status": "PASS", "judge_id": "J1",
            "calibration_artifact_sha256": "c" * 64,
            "blind_to_strategy": True, "blind_to_model": True,
            "binding_claim_id": "C1",
        }
        # No registry supplied at all: a PASS string alone is not a credential.
        no_registry = evaluate_terminal_quality(contract(), output(claim), self.sources)
        self.assertEqual(no_registry["fact_metrics"]["weighted_tp"], 0.0)
        # Registry that does not contain this judge's registered artifact.
        wrong_registry = evaluate_terminal_quality(contract(), output(claim), self.sources, {"J1": "d" * 64})
        self.assertEqual(wrong_registry["fact_metrics"]["weighted_tp"], 0.0)
        # Registered credential but verdict bound to a different claim: no replay.
        bound_elsewhere = dict(claim)
        bound_elsewhere["assessment"] = dict(claim["assessment"], binding_claim_id="C9")
        replay = evaluate_terminal_quality(
            contract(), output(good_claim(), claims=[bound_elsewhere]), self.sources, {"J1": "c" * 64})
        self.assertEqual(replay["fact_metrics"]["weighted_tp"], 0.0)
        # Malformed artifact hash (not 64-hex) is rejected even when registered.
        malformed = dict(claim)
        malformed["assessment"] = dict(claim["assessment"], calibration_artifact_sha256="not-a-sha")
        bad_hash = evaluate_terminal_quality(contract(), output(malformed), self.sources, {"J1": "not-a-sha"})
        self.assertEqual(bad_hash["fact_metrics"]["weighted_tp"], 0.0)

    def test_abstention_without_explicit_text_not_scored(self):
        task = contract()
        task["unknown_items"] = [{"item_id": "U1", "description": "最终处罚决定"}]
        bare = output(good_claim(), abstentions=[{"item_id": "U1"}])
        result = evaluate_terminal_quality(task, bare, self.sources)
        self.assertEqual(result["dimensions"]["unverifiable_refusal"], 0.0)
        self.assertTrue(any(w.startswith("ABSTENTION_WITHOUT_EXPLICIT_TEXT") for w in result["quality_warnings"]))

    def test_conflict_acknowledgement_requires_per_source_versions(self):
        task = contract()
        task["conflict_groups"] = [{"conflict_id": "X1", "required_source_doc_ids": ["D1", "D2"]}]
        listed_only = output(
            good_claim(),
            conflict_acknowledgements=[{"conflict_id": "X1", "acknowledged": True, "source_doc_ids": ["D1", "D2"]}])
        result = evaluate_terminal_quality(task, listed_only, self.sources)
        self.assertEqual(result["dimensions"]["contradiction_handling"], 0.0)
        with_versions = output(
            good_claim(),
            conflict_acknowledgements=[{
                "conflict_id": "X1", "acknowledged": True,
                "source_versions": {
                    "D1": "公告载明公司于2026年9月18日收到立案告知书。",
                    "D2": "另一来源对同一事项的表述与此不同。",
                }}])
        result2 = evaluate_terminal_quality(task, with_versions, self.sources)
        self.assertEqual(result2["dimensions"]["contradiction_handling"], 1.0)

    def test_tampered_page_text_fails_hash_recomputation(self):
        tampered = {"D1": {"raw_sha256": RAW_SHA, "pages": {"1": {
            "text": PAGE + "篡改后的附加文本", "page_sha256": self.sources["D1"]["pages"]["1"]["page_sha256"]}}}}
        result = evaluate_terminal_quality(contract(), output(good_claim()), tampered)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any(reason.startswith("REFERENCE_EVIDENCE_INVALID") for reason in result["blocking_reasons"]))

    def test_derivation_with_incompatible_units_fails(self):
        task, sources = self._derived_task()
        task["required_facts"][2]["unit"] = "股"  # F3 input now in a different unit than F2
        claim = good_claim(
            fact_id="F1", value="100", unit="万元", predicate="收入差额", date_type="UNKNOWN",
            citations=[
                {"doc_id": "D1", "page": 1, "quote": "公司于2026年9月18日收到中国证监会立案告知书", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA},
                {"doc_id": "D2", "page": 1, "quote": "公司上年度收入为50万元。", "page_sha256": sources["D2"]["pages"]["1"]["page_sha256"], "raw_sha256": "b" * 64},
            ])
        result = evaluate_terminal_quality(task, output(claim), sources)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 0.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 1.0)

    # --- Regression tests for independent adversarial re-review of v1.2 (H1/M1-M7/L) ---

    def test_malformed_citation_offsets_do_not_crash(self):
        bad_offset = {"doc_id": "D1", "page": 1, "quote": "公司于2026年9月18日收到中国证监会立案告知书",
                      "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA, "start": "x", "end": 5}
        result = evaluate_terminal_quality(contract(), output(good_claim(citations=[bad_offset])), self.sources)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 1.0)
        self.assertEqual(result["dimensions"]["evidence_support"], 0.0)
        self.assertIsNotNone(result["Q_final"])

    def test_non_mapping_citations_and_claims_do_not_crash(self):
        claim = good_claim(citations="not-a-list")
        result = evaluate_terminal_quality(contract(), output(claim), self.sources)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 1.0)
        self.assertEqual(result["dimensions"]["evidence_support"], 0.0)
        self.assertIsNotNone(result["Q_final"])
        junk = output(good_claim(), claims=[good_claim(), "not-a-claim"])
        result2 = evaluate_terminal_quality(contract(), junk, self.sources)
        self.assertIsNone(result2["Q_final"])
        self.assertIn("CLAIM_STRUCTURE_INVALID_NON_MAPPING", result2["blocking_reasons"])

    def test_huge_weights_cannot_emit_nonfinite_q(self):
        task = contract()
        task["required_facts"].append(self._amount_fact())
        task["required_facts"][0]["weight"] = 1e308
        task["required_facts"][1]["weight"] = 1e308
        result = evaluate_terminal_quality(task, output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any("WEIGHT_SUM_NOT_FINITE" in r for r in result["blocking_reasons"]))

    def test_unknown_item_without_id_blocks_instead_of_poisoning(self):
        task = contract()
        task["unknown_items"] = [
            {"item_id": "U1", "description": "最终处罚决定"},
            {"description": "missing id"},
        ]
        result = evaluate_terminal_quality(task, output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])  # blocked, NOT scored 0.0
        self.assertTrue(any("UNKNOWN_ITEM_ID_INVALID" in r for r in result["blocking_reasons"]))

    def test_unparseable_coverage_and_weight_do_not_crash(self):
        unparseable = contract()
        unparseable["min_gold_coverage"] = "abc"
        result = evaluate_terminal_quality(unparseable, output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])
        bad_weight = contract()
        bad_weight["required_facts"].append(self._amount_fact())
        bad_weight["required_facts"][-1]["weight"] = "abc"
        result2 = evaluate_terminal_quality(bad_weight, output(good_claim()), self.sources)
        self.assertIsNone(result2["Q_final"])

    def test_verdict_on_idless_claim_is_invalid(self):
        claim = good_claim(value="2026年9月18日", predicate="公司收件日")
        claim.pop("claim_id")
        claim["assessment"] = {
            "verdict": "SUPPORTED", "assessor_type": "calibrated_judge",
            "calibration_status": "PASS", "judge_id": "J1",
            "calibration_artifact_sha256": "c" * 64,
            "blind_to_strategy": True, "blind_to_model": True,
            "binding_claim_id": "ANYTHING",
        }
        result = evaluate_terminal_quality(contract(), output(claim), self.sources, {"J1": "c" * 64})
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 0.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 1.0)

    def test_duplicate_claim_ids_block_evaluation(self):
        verdict = {
            "verdict": "SUPPORTED", "assessor_type": "calibrated_judge",
            "calibration_status": "PASS", "judge_id": "J1",
            "calibration_artifact_sha256": "c" * 64,
            "blind_to_strategy": True, "blind_to_model": True,
            "binding_claim_id": "C1",
        }
        claim = good_claim(value="2026年9月18日", predicate="公司收件日", assessment=verdict)
        twin = good_claim(claim_id="C1", value="2026年9月18日", predicate="公司收件日", assessment=verdict)
        result = evaluate_terminal_quality(contract(), output(claim, claims=[claim, twin]), self.sources, {"J1": "c" * 64})
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any("CLAIM_ID_DUPLICATE" in r for r in result["blocking_reasons"]))

    def test_conflict_unresolved_reference_blocks_formal_q(self):
        task = contract()
        task["required_facts"].append(self._amount_fact(status="CONFLICT_UNRESOLVED"))
        task["min_gold_coverage"] = 0.5
        result = evaluate_terminal_quality(task, output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any("REFERENCE_CONFLICT_UNRESOLVED" in r for r in result["blocking_reasons"]))

    def test_tolerance_bounds_enforced(self):
        unbounded = contract()
        unbounded["required_facts"].append(self._amount_fact())
        unbounded["required_facts"][-1]["tolerance"] = "1e999"
        result = evaluate_terminal_quality(unbounded, output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any(r.startswith("GOLD_CONTRACT_INVALID_VALUE:F2") for r in result["blocking_reasons"]))
        negative = contract()
        negative["required_facts"].append(self._amount_fact())
        negative["required_facts"][-1]["tolerance"] = "-1"
        result2 = evaluate_terminal_quality(negative, output(good_claim()), self.sources)
        self.assertIsNone(result2["Q_final"])

    def test_zero_gold_contract_never_formal(self):
        task = contract(status="SILVER_SOURCE_ANCHORED")
        task["min_gold_coverage"] = 0.0
        result = evaluate_terminal_quality(task, output(good_claim(), claims=[]), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertIn("NO_FORMAL_GOLD", result["blocking_reasons"])

    def test_unhashable_fact_id_blocks_without_crash(self):
        task = contract()
        task["required_facts"][0]["fact_id"] = ["F1"]
        result = evaluate_terminal_quality(task, output(good_claim()), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any("FACT_ID_NOT_SCALAR" in r for r in result["blocking_reasons"]))

    def test_bool_relevance_score_rejected(self):
        relevance = {"score": True, "assessor_type": "human_adjudicator", "review_status": "ADJUDICATED",
                     "reviewer_ids": ["R1", "R2"], "blind_to_strategy": True, "blind_to_model": True}
        result = evaluate_terminal_quality(contract(), output(good_claim(), question_relevance=relevance), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertIn("QUESTION_RELEVANCE_NOT_VALIDLY_ASSESSED", result["blocking_reasons"])

    # --- Operator ruling L5 (2026-10-30): beyond-contract supported claims ---

    def _credentialed_verdict(self, claim_id):
        return {
            "verdict": "SUPPORTED", "assessor_type": "calibrated_judge",
            "calibration_status": "PASS", "judge_id": "J1",
            "calibration_artifact_sha256": "c" * 64,
            "blind_to_strategy": True, "blind_to_model": True,
            "binding_claim_id": claim_id,
        }

    def _beyond_contract_claim(self, claim_id="C9", with_verdict=True):
        claim = {
            "claim_id": claim_id, "fact_id": "FX", "material": True,
            "subject": "某公司", "predicate": "告知书编号", "value": "0142026049号",
        }
        if with_verdict:
            claim["assessment"] = self._credentialed_verdict(claim_id)
        return claim

    def test_unmapped_credentialed_supported_claim_withholds_q(self):
        registry = {"J1": "c" * 64}
        claims = [good_claim(), self._beyond_contract_claim()]
        result = evaluate_terminal_quality(contract(), output(good_claim(), claims=claims), self.sources, registry)
        self.assertIsNone(result["Q_final"])
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertIn("UNMAPPED_MATERIAL_CLAIM", result["blocking_reasons"])
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 1.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 0.0)
        self.assertEqual(result["unmapped_supported_claims"]["claim_ids"], ["C9"])
        self.assertEqual(result["unmapped_supported_claims"]["weight"], 1.0)
        self.assertEqual(result["claim_results"][1]["status"], "UNMAPPED_SUPPORTED_CLAIM")

    def test_unmapped_claim_without_credential_never_counts_tp(self):
        claims = [good_claim(), self._beyond_contract_claim(with_verdict=False)]
        result = evaluate_terminal_quality(contract(), output(good_claim(), claims=claims), self.sources)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 1.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 1.0)
        self.assertIsNone(result["Q_final"])
        self.assertIn("CLAIM_ASSESSMENT_INCOMPLETE", result["blocking_reasons"])

    def test_claim_fully_matching_gold_uses_normal_rules_alongside_unmapped(self):
        registry = {"J1": "c" * 64}
        matching = dict(good_claim())
        matching.pop("fact_id")  # tuple-matches F1 through the normal matching path
        claims = [matching, self._beyond_contract_claim()]
        result = evaluate_terminal_quality(contract(), output(good_claim(), claims=claims), self.sources, registry)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 1.0)
        self.assertEqual(result["claim_results"][0]["status"], "CORRECT_GOLD")
        self.assertIsNone(result["Q_final"])  # the unmapped claim still withholds

    def test_unmapped_claim_evaluated_normally_after_contract_promotion(self):
        v2 = contract()
        v2["task_id"] = "T1_v2"
        v2["required_facts"].append({
            "fact_id": "FX", "status": "GOLD_CONFIRMED", "gold_provenance": "human_adjudicated",
            "gold_source_sha256": RAW_SHA,
            "review": {"status": "ADJUDICATED", "independent_reviewers": 2, "reviewer_ids": ["R1", "R2"], "blind_to_strategy": True, "blind_to_model": True},
            "weight": 1.0, "value_kind": "text", "subject": "某公司", "predicate": "告知书编号",
            "value": "0142026049号",
            "source_evidence": [{"doc_id": "D1", "page": 1, "quote": "编号0142026049号", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA}],
        })
        promoted = {
            "claim_id": "C9", "fact_id": "FX", "material": True,
            "subject": "某公司", "predicate": "告知书编号", "value": "0142026049号",
            "citations": [{"doc_id": "D1", "page": 1, "quote": "编号0142026049号", "page_sha256": PAGE_SHA, "raw_sha256": RAW_SHA}],
        }
        claims = [good_claim(), promoted]
        result = evaluate_terminal_quality(v2, output(good_claim(), claims=claims), self.sources)
        self.assertIsNotNone(result["Q_final"])
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 2.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 0.0)
        self.assertEqual(result["unmapped_supported_claims"]["count"], 0)

    def test_unmapped_rule_applies_identically_across_strategies(self):
        registry = {"J1": "c" * 64}
        strategy_a = output(good_claim(), claims=[good_claim(), self._beyond_contract_claim("C9")])
        strategy_b = output(good_claim(), claims=[good_claim(), self._beyond_contract_claim("Z7")])
        result_a = evaluate_terminal_quality(contract(), strategy_a, self.sources, registry)
        result_b = evaluate_terminal_quality(contract(), strategy_b, self.sources, registry)
        self.assertIsNone(result_a["Q_final"])
        self.assertIsNone(result_b["Q_final"])
        self.assertEqual(result_a["blocking_reasons"], result_b["blocking_reasons"])
        self.assertEqual(result_a["fact_metrics"], result_b["fact_metrics"])

    def test_nonmaterial_claims_recorded_not_dropped(self):
        side = good_claim(claim_id="C8", material=False)
        claims = [good_claim(), side]
        result = evaluate_terminal_quality(contract(), output(good_claim(), claims=claims), self.sources)
        self.assertEqual(result["nonmaterial_claims"]["claim_ids"], ["C8"])
        self.assertEqual(result["nonmaterial_claims"]["count"], 1)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 1.0)
        self.assertEqual(result["Q_final"], 1.0)

    # --- v1.2.3: mechanical guards from the v1.2.2 focused review ---

    def test_unmapped_ledger_weight_finite_or_null(self):
        import json as _json
        registry = {"J1": "c" * 64}
        heavy_a = self._beyond_contract_claim("C9")
        heavy_a["weight"] = 1e308
        heavy_b = self._beyond_contract_claim("C8")
        heavy_b["weight"] = 1e308
        claims = [good_claim(), heavy_a, heavy_b]
        result = evaluate_terminal_quality(contract(), output(good_claim(), claims=claims), self.sources, registry)
        self.assertIsNone(result["Q_final"])
        self.assertIn("CLAIM_WEIGHT_SUM_NOT_FINITE", result["blocking_reasons"])
        self.assertIsNone(result["unmapped_supported_claims"]["weight"])
        for metric in result["fact_metrics"].values():
            self.assertNotEqual(metric, float("inf"))
        _json.dumps(result, allow_nan=False)  # must not raise

    def test_unmapped_ledger_does_not_double_count_duplicate_ids(self):
        registry = {"J1": "c" * 64}
        claims = [good_claim(), self._beyond_contract_claim("C9"), self._beyond_contract_claim("C9")]
        result = evaluate_terminal_quality(contract(), output(good_claim(), claims=claims), self.sources, registry)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any("CLAIM_ID_DUPLICATE" in r for r in result["blocking_reasons"]))
        self.assertEqual(result["unmapped_supported_claims"]["count"], 1)
        self.assertEqual(result["unmapped_supported_claims"]["weight"], 1.0)
        self.assertTrue(any(w.startswith("UNMAPPED_LEDGER_DUPLICATE_SKIPPED") for w in result["quality_warnings"]))

    def test_nonmaterial_unknown_assertion_still_detected(self):
        task = contract()
        task["unknown_items"] = [{"item_id": "U1", "description": "最终处罚决定"}]
        sneaky = good_claim(claim_id="C8", material=False)
        sneaky["item_id"] = "U1"
        abstention = [{"item_id": "U1", "text": "材料未披露最终处罚决定，无法核验。"}]
        result = evaluate_terminal_quality(task, output(good_claim(), claims=[good_claim(), sneaky], abstentions=abstention), self.sources)
        self.assertEqual(result["dimensions"]["unverifiable_refusal"], 0.0)
        self.assertIn("UNVERIFIABLE_ITEM_ASSERTED", result["quality_warnings"])

    def test_structure_gates_cover_nonmaterial_claims(self):
        shadow = good_claim(claim_id="C1", material=False)  # duplicates the material claim's id
        claims = [good_claim(), shadow]
        result = evaluate_terminal_quality(contract(), output(good_claim(), claims=claims), self.sources)
        self.assertIsNone(result["Q_final"])
        self.assertTrue(any("CLAIM_ID_DUPLICATE:C1" in r for r in result["blocking_reasons"]))


if __name__ == "__main__":
    unittest.main()
