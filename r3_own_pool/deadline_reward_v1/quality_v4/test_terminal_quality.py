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
        self.assertIsNotNone(result["Q_final"])
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 1.0)
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 0.0)

    def test_keyword_or_quote_hit_without_correct_predicate_is_not_pass(self):
        claim = good_claim(predicate="行政处罚决定作出日期", value="处罚")
        result = evaluate_terminal_quality(contract(), output(claim), self.sources)
        self.assertIsNotNone(result["Q_final"])
        self.assertEqual(result["fact_metrics"]["weighted_tp"], 0.0)
        self.assertEqual(result["fact_metrics"]["weighted_fp"], 1.0)

    def test_wrong_unit_does_not_match(self):
        result = evaluate_terminal_quality(contract(), output(good_claim(unit="publication_date")), self.sources)
        self.assertIsNotNone(result["Q_final"])
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
        bad_claim = good_claim()
        bad_claim["item_id"] = "U1"
        final_output = output(good_claim(), claims=[good_claim(), bad_claim], abstentions=[])
        result = evaluate_terminal_quality(task, final_output, self.sources)
        self.assertIsNotNone(result["Q_final"])
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


if __name__ == "__main__":
    unittest.main()
