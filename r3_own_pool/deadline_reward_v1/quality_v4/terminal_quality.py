"""Gold-gated terminal quality evaluator for heterogeneous multi-agent DAGs.

The evaluator is deliberately offline: it never calls a model and never
turns a missing/invalid judge response into a semantic score of zero.
Only the final sink answer is scored. Intermediate-node scores belong to a
separate node-capability evaluation and must not be mixed into terminal Q.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence

FORMAL_GOLD_PROVENANCE = {
    "human_adjudicated",
    "native_dataset_annotation",
    "official_structured_record",
}


def _norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value if value is not None else ""))
    return re.sub(r"\s+", "", text).casefold()


def _decimal(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _date(value: Any) -> Optional[str]:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    text = text.replace("/", "-").replace(".", "-")
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        return None
    year, month, day = map(int, match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _value_equal(claim: Mapping[str, Any], fact: Mapping[str, Any]) -> bool:
    kind = fact.get("value_kind", "text")
    left, right = claim.get("value"), fact.get("value")
    if kind == "date":
        return _date(left) is not None and _date(left) == _date(right)
    if kind in {"number", "amount", "ratio", "percent"}:
        a, b = _decimal(left), _decimal(right)
        if a is None or b is None:
            return False
        tolerance = _decimal(fact.get("tolerance", "0")) or Decimal("0")
        return abs(a - b) <= tolerance
    if isinstance(right, list):
        return isinstance(left, list) and sorted(_norm_text(x) for x in left) == sorted(_norm_text(x) for x in right)
    aliases = [_norm_text(x) for x in fact.get("accepted_values", [])]
    return _norm_text(left) == _norm_text(right) or _norm_text(left) in aliases


def _tuple_equal(claim: Mapping[str, Any], fact: Mapping[str, Any]) -> bool:
    for field in ("subject", "predicate"):
        if _norm_text(claim.get(field)) != _norm_text(fact.get(field)):
            return False
    for field in ("unit", "date_type"):
        expected = fact.get(field)
        if expected not in (None, "", "UNKNOWN") and _norm_text(claim.get(field)) != _norm_text(expected):
            return False
    return _value_equal(claim, fact)


def _formal_gold(fact: Mapping[str, Any]) -> bool:
    if fact.get("status") != "GOLD_CONFIRMED" or fact.get("gold_provenance") not in FORMAL_GOLD_PROVENANCE:
        return False
    if fact["gold_provenance"] == "human_adjudicated":
        review = fact.get("review", {})
        reviewer_ids = review.get("reviewer_ids", [])
        return (
            review.get("status") == "ADJUDICATED"
            and int(review.get("independent_reviewers", 0)) >= 2
            and len(set(reviewer_ids)) >= 2
            and review.get("blind_to_strategy") is True
            and review.get("blind_to_model") is True
        )
    return bool(fact.get("gold_source_sha256"))


def _page_record(source_pages: Mapping[str, Any], doc_id: str, page: Any) -> Optional[Mapping[str, Any]]:
    doc = source_pages.get(doc_id)
    if not isinstance(doc, Mapping):
        return None
    pages = doc.get("pages", {})
    return pages.get(str(page), pages.get(page)) if isinstance(pages, Mapping) else None


def _span_is_valid(
    source_pages: Mapping[str, Any], doc_id: str, page: Any, quote: str,
    expected_page_sha256: Optional[str] = None,
    expected_raw_sha256: Optional[str] = None,
    start: Optional[int] = None, end: Optional[int] = None,
) -> bool:
    record = _page_record(source_pages, doc_id, page)
    if not record or not isinstance(record.get("text"), str):
        return False
    text = record["text"]
    if expected_page_sha256 and record.get("page_sha256") != expected_page_sha256:
        return False
    doc = source_pages.get(doc_id, {})
    if expected_raw_sha256 and doc.get("raw_sha256") != expected_raw_sha256:
        return False
    if start is not None or end is not None:
        if start is None or end is None or not (0 <= int(start) <= int(end) <= len(text)):
            return False
        return _norm_text(text[int(start):int(end)]) == _norm_text(quote)
    return bool(_norm_text(quote) and _norm_text(quote) in _norm_text(text))


def _reference_evidence_valid(fact: Mapping[str, Any], source_pages: Mapping[str, Any]) -> bool:
    evidence = fact.get("source_evidence") or []
    if not evidence:
        return fact.get("gold_provenance") == "native_dataset_annotation" and bool(fact.get("gold_source_sha256"))
    if fact.get("gold_provenance") != "native_dataset_annotation":
        if any(not item.get("raw_sha256") or not item.get("page_sha256") for item in evidence):
            return False
    return all(_span_is_valid(
        source_pages, item.get("doc_id"), item.get("page"), item.get("quote", ""),
        item.get("page_sha256"), item.get("raw_sha256"), item.get("start"), item.get("end"),
    ) for item in evidence)


def _citation_matches_evidence(
    citation: Mapping[str, Any], evidence: Mapping[str, Any], source_pages: Mapping[str, Any]
) -> bool:
    if citation.get("doc_id") != evidence.get("doc_id") or str(citation.get("page")) != str(evidence.get("page")):
        return False
    if not _span_is_valid(
        source_pages, citation.get("doc_id"), citation.get("page"),
        citation.get("quote", ""), citation.get("page_sha256"),
        citation.get("raw_sha256"), citation.get("start"), citation.get("end"),
    ):
        return False
    c_start, c_end = citation.get("start"), citation.get("end")
    e_start, e_end = evidence.get("start"), evidence.get("end")
    if c_start is not None and c_end is not None and e_start is not None and e_end is not None:
        overlap = max(0, min(int(c_end), int(e_end)) - max(int(c_start), int(e_start)))
        return overlap / max(1, int(e_end) - int(e_start)) >= 0.80
    candidate_quote = _norm_text(citation.get("quote", ""))
    reference_quote = _norm_text(evidence.get("quote", ""))
    return bool(candidate_quote and reference_quote and (candidate_quote == reference_quote or reference_quote in candidate_quote))


def _citations_support_fact(
    citations: Sequence[Mapping[str, Any]], fact: Mapping[str, Any], source_pages: Mapping[str, Any]
) -> bool:
    references = fact.get("source_evidence") or []
    if not references:
        return fact.get("gold_provenance") == "native_dataset_annotation" and bool(fact.get("gold_source_sha256"))
    if not citations:
        return False
    mode = fact.get("evidence_mode", "ALL" if fact.get("derivation") else "ANY")
    if mode == "ALL":
        return all(any(_citation_matches_evidence(c, e, source_pages) for c in citations) for e in references)
    return any(_citation_matches_evidence(c, e, source_pages) for c in citations for e in references)


def _valid_assessment(assessment: Mapping[str, Any]) -> bool:
    if assessment.get("assessor_type") == "human_adjudicator":
        reviewer_ids = assessment.get("reviewer_ids", [])
        return (
            assessment.get("review_status") == "ADJUDICATED"
            and len(set(reviewer_ids)) >= 2
            and assessment.get("blind_to_strategy") is True
            and assessment.get("blind_to_model") is True
        )
    if assessment.get("assessor_type") == "calibrated_judge":
        return assessment.get("calibration_status") == "PASS" and bool(assessment.get("calibration_artifact_sha256"))
    return False


def _assessment_verdict(claim: Mapping[str, Any]) -> Optional[str]:
    assessment = claim.get("assessment")
    if not isinstance(assessment, Mapping) or not _valid_assessment(assessment):
        return None
    verdict = assessment.get("verdict")
    return verdict if verdict in {"SUPPORTED", "CONTRADICTED", "UNSUPPORTED", "UNKNOWN"} else None


def _derived_value_ok(claim: Mapping[str, Any], fact: Mapping[str, Any], facts_by_id: Mapping[str, Any]) -> bool:
    derivation = fact.get("derivation")
    if not derivation:
        return _value_equal(claim, fact)
    input_ids = derivation.get("inputs", [])
    if not input_ids or any(fid not in facts_by_id for fid in input_ids):
        return False
    values = [_decimal(facts_by_id[fid].get("value")) for fid in input_ids]
    if any(value is None for value in values):
        return False
    operation = derivation.get("op")
    try:
        if operation == "add":
            expected = sum(values, Decimal("0"))
        elif operation == "subtract" and len(values) == 2:
            expected = values[0] - values[1]
        elif operation == "ratio" and len(values) == 2 and values[1] != 0:
            expected = values[0] / values[1]
        elif operation == "percent_change" and len(values) == 2 and values[1] != 0:
            expected = (values[0] - values[1]) / values[1] * Decimal("100")
        else:
            return False
    except (InvalidOperation, ZeroDivisionError):
        return False
    target, candidate = _decimal(fact.get("value")), _decimal(claim.get("value"))
    tolerance = _decimal(fact.get("tolerance", "0")) or Decimal("0")
    return target is not None and candidate is not None and abs(expected - target) <= tolerance and abs(candidate - target) <= tolerance


def _find_fact(claim: Mapping[str, Any], facts: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    fact_id = claim.get("fact_id")
    if fact_id:
        return next((fact for fact in facts if fact.get("fact_id") == fact_id), None)
    matches = [fact for fact in facts if _tuple_equal(claim, fact)]
    return matches[0] if len(matches) == 1 else None


def evaluate_terminal_quality(
    task_contract: Mapping[str, Any],
    terminal_output: Mapping[str, Any],
    source_pages: Mapping[str, Any],
) -> Dict[str, Any]:
    """Score one final sink output against a frozen, adjudicated task contract.

    Formal Q is withheld when the reference/claim extraction/semantic assessment
    is incomplete. Measurable answer errors reduce Q; they do not make evaluation
    itself unscorable.
    """
    blocking: List[str] = []
    warnings: List[str] = []
    required = list(task_contract.get("required_facts", []))
    unknown_items = list(task_contract.get("unknown_items", []))
    conflicts = list(task_contract.get("conflict_groups", []))
    claims = list(terminal_output.get("claims", []))
    facts_by_id = {fact.get("fact_id"): fact for fact in required if fact.get("fact_id")}
    unknown_ids = {item.get("item_id") for item in unknown_items}

    if not task_contract.get("question"):
        blocking.append("TASK_QUESTION_MISSING")
    if not required:
        blocking.append("NO_REQUIRED_FACTS")
    if not terminal_output.get("claims_complete", False):
        blocking.append("CLAIM_EXTRACTION_INCOMPLETE")

    nonexcluded = [fact for fact in required if fact.get("status") not in {"EXCLUDED", "NOT_APPLICABLE"}]
    gold = [fact for fact in nonexcluded if _formal_gold(fact)]
    total_weight = sum(float(fact.get("weight", 1.0)) for fact in nonexcluded)
    gold_weight = sum(float(fact.get("weight", 1.0)) for fact in gold)
    gold_coverage = gold_weight / total_weight if total_weight else 0.0
    min_coverage = float(task_contract.get("min_gold_coverage", 1.0))
    if gold_coverage + 1e-12 < min_coverage:
        blocking.append("REFERENCE_GOLD_COVERAGE_BELOW_GATE")
    for fact in gold:
        if not _reference_evidence_valid(fact, source_pages):
            blocking.append(f"REFERENCE_EVIDENCE_INVALID:{fact.get('fact_id')}")

    tp_weight = fp_weight = supported_claim_weight = asserted_claim_weight = 0.0
    matched_ids = set()
    unassessed_claims: List[str] = []
    claim_results = []
    for claim in claims:
        if not claim.get("material", True):
            continue
        weight = float(claim.get("weight", 1.0))
        asserted_claim_weight += weight
        fact = None if claim.get("item_id") in unknown_ids else _find_fact(claim, gold)
        citations = claim.get("citations") or []
        citation_ok = bool(fact and _citations_support_fact(citations, fact, source_pages))
        exact = bool(fact and _tuple_equal(claim, fact) and _derived_value_ok(claim, fact, facts_by_id))
        verdict = _assessment_verdict(claim)

        if fact and exact and fact["fact_id"] not in matched_ids:
            tp_weight += min(weight, float(fact.get("weight", 1.0)))
            if citation_ok:
                supported_claim_weight += weight
            else:
                warnings.append(f"CITATION_NOT_FULLY_SUPPORTING:{claim.get('claim_id')}")
            matched_ids.add(fact["fact_id"])
            claim_results.append({"claim_id": claim.get("claim_id"), "status": "CORRECT_GOLD" if citation_ok else "CORRECT_BUT_UNSUPPORTED_CITATION", "fact_id": fact["fact_id"]})
        elif verdict == "SUPPORTED" and fact and fact["fact_id"] not in matched_ids:
            tp_weight += min(weight, float(fact.get("weight", 1.0)))
            if citation_ok:
                supported_claim_weight += weight
            else:
                warnings.append(f"CITATION_NOT_FULLY_SUPPORTING:{claim.get('claim_id')}")
            matched_ids.add(fact["fact_id"])
            claim_results.append({"claim_id": claim.get("claim_id"), "status": "SEMANTICALLY_CORRECT" if citation_ok else "SEMANTICALLY_CORRECT_BUT_UNSUPPORTED_CITATION", "fact_id": fact["fact_id"]})
        elif fact and fact["fact_id"] in matched_ids and citation_ok:
            fp_weight += weight
            warnings.append(f"DUPLICATE_CLAIM:{claim.get('claim_id')}")
            claim_results.append({"claim_id": claim.get("claim_id"), "status": "DUPLICATE_CLAIM", "fact_id": fact["fact_id"]})
        elif fact and claim.get("fact_id") == fact["fact_id"]:
            fp_weight += weight
            claim_results.append({"claim_id": claim.get("claim_id"), "status": "WRONG_GOLD_FACT_VALUE_OR_RELATION", "fact_id": fact["fact_id"]})
        elif claim.get("item_id") in unknown_ids:
            fp_weight += weight
            warnings.append("UNVERIFIABLE_ITEM_ASSERTED")
            claim_results.append({"claim_id": claim.get("claim_id"), "status": "ASSERTED_UNVERIFIABLE"})
        elif verdict in {"CONTRADICTED", "UNSUPPORTED"}:
            fp_weight += weight
            claim_results.append({"claim_id": claim.get("claim_id"), "status": verdict})
        else:
            fp_weight += weight
            unassessed_claims.append(claim.get("claim_id"))
            claim_results.append({"claim_id": claim.get("claim_id"), "status": "UNASSESSED_OR_UNSUPPORTED"})

    if unassessed_claims:
        blocking.append("CLAIM_ASSESSMENT_INCOMPLETE")

    fn_weight = sum(float(fact.get("weight", 1.0)) for fact in gold if fact.get("fact_id") not in matched_ids)
    precision = tp_weight / (tp_weight + fp_weight) if tp_weight + fp_weight else 0.0
    recall = tp_weight / (tp_weight + fn_weight) if tp_weight + fn_weight else 0.0
    fact_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    support_rate = supported_claim_weight / asserted_claim_weight if asserted_claim_weight else 0.0
    completeness = (
        sum(float(fact.get("weight", 1.0)) for fact in gold if fact.get("fact_id") in matched_ids) / gold_weight
        if gold_weight else 0.0
    )

    abstained_ids = {item.get("item_id") for item in terminal_output.get("abstentions", [])}
    correct_abstentions = abstained_ids & unknown_ids
    asserted_unknown = {
        claim.get("item_id") for claim in claims
        if claim.get("item_id") in unknown_ids and claim.get("material", True)
    }
    unknown_score = len(correct_abstentions - asserted_unknown) / len(unknown_ids) if unknown_ids else None
    if unknown_ids and not terminal_output.get("abstentions_complete", False):
        blocking.append("UNKNOWN_HANDLING_INCOMPLETE")
    if asserted_unknown:
        warnings.append("UNVERIFIABLE_ITEM_ASSERTED")

    acknowledgements = {
        item.get("conflict_id"): item for item in terminal_output.get("conflict_acknowledgements", [])
    }
    conflict_scores = []
    for conflict in conflicts:
        acknowledgement = acknowledgements.get(conflict.get("conflict_id"), {})
        required_docs = set(conflict.get("required_source_doc_ids", []))
        supplied_docs = set(acknowledgement.get("source_doc_ids", []))
        conflict_scores.append(
            1.0 if acknowledgement.get("acknowledged") is True and required_docs.issubset(supplied_docs) else 0.0
        )
    conflict_score = sum(conflict_scores) / len(conflict_scores) if conflict_scores else None
    if conflict_scores and conflict_score < 1.0:
        warnings.append("CONFLICT_NOT_FULLY_ACKNOWLEDGED")

    relevance = terminal_output.get("question_relevance")
    relevance_score = None
    if isinstance(relevance, Mapping) and _valid_assessment(relevance):
        score = relevance.get("score")
        if isinstance(score, (int, float)) and 0.0 <= float(score) <= 1.0:
            relevance_score = float(score)
    if relevance_score is None:
        blocking.append("QUESTION_RELEVANCE_NOT_VALIDLY_ASSESSED")

    dimensions = {
        "fact_correctness": precision,
        "evidence_support": support_rate,
        "necessary_completeness": completeness,
        "contradiction_handling": conflict_score,
        "unverifiable_refusal": unknown_score,
        "question_relevance": relevance_score,
    }
    dimension_weights = task_contract.get("dimension_weights", {})
    weighted_dimensions = []
    for name, value in dimensions.items():
        if value is not None:
            dimension_weight = float(dimension_weights.get(name, 1.0))
            if dimension_weight > 0:
                weighted_dimensions.append((dimension_weight, value))
    q_partial = (
        sum(weight * value for weight, value in weighted_dimensions)
        / sum(weight for weight, _ in weighted_dimensions)
        if weighted_dimensions else None
    )

    delivery_valid = terminal_output.get("delivery_valid") is True
    if not delivery_valid:
        semantic_q = None
        delivered_q = 0.0
        blocking.append("DELIVERY_INVALID_SEMANTIC_QUALITY_UNAVAILABLE")
    else:
        semantic_q = q_partial if not blocking else None
        delivered_q = semantic_q if semantic_q is not None else None

    return {
        "task_id": task_contract.get("task_id"),
        "evaluation_version": "terminal_quality_v1",
        "status": "SCORABLE_GOLD" if semantic_q is not None else "INCOMPLETE",
        "Q_final": round(semantic_q, 6) if semantic_q is not None else None,
        "Q_partial_diagnostic": round(q_partial, 6) if q_partial is not None else None,
        "Q_delivered": round(delivered_q, 6) if delivered_q is not None else None,
        "delivery_valid": delivery_valid,
        "R_delivery": 1.0 if delivery_valid else 0.0,
        "gold_coverage": round(gold_coverage, 6),
        "min_gold_coverage": min_coverage,
        "dimensions": {key: round(value, 6) if value is not None else None for key, value in dimensions.items()},
        "fact_metrics": {
            "weighted_tp": round(tp_weight, 6), "weighted_fp": round(fp_weight, 6),
            "weighted_fn": round(fn_weight, 6), "precision": round(precision, 6),
            "recall": round(recall, 6), "f1": round(fact_f1, 6),
        },
        "claim_results": claim_results,
        "unassessed_claim_ids": unassessed_claims,
        "blocking_reasons": sorted(set(blocking)),
        "quality_warnings": sorted(set(warnings)),
        "scoring_scope": "final_sink_only",
        "model_calls": 0,
    }
