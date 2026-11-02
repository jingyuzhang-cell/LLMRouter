#!/usr/bin/env python3
"""Deterministic self-check: run the fixed terminal_quality v1.1 evaluator over the
E08 SILVER draft contract (a REAL document, not synthetic fixtures).

Checks, with zero model calls:
 1. Contract integrity: every fact's evidence span validates (hashes, offsets, quote).
 2. Honest-SILVER: gold coverage 0/1 blocks formal Q (REFERENCE_GOLD_COVERAGE_BELOW_GATE).
 3. A simulated all-correct answer (claims constructed deterministically FROM the
    contract itself — a plumbing test, not a model evaluation) still yields
    Q_final=None while SILVER, and turns scorable only if facts were GOLD — proven
    by flipping status in-memory to GOLD_CONFIRMED with a mock adjudicated review,
    which must then produce Q_final=1.0 with critical gate PASS.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4")
from terminal_quality import evaluate_terminal_quality  # noqa: E402

BASE = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/E08_zhongtie")
contract = json.loads((BASE / "TASK_CONTRACT_E08_SILVER_DRAFT.json").read_text())
source_pages = contract["source_pages"]
del contract["source_pages"]  # evaluator takes it separately

ADJUDICATED = {
    "status": "ADJUDICATED", "independent_reviewers": 2,
    "reviewer_ids": ["HUMAN_A", "HUMAN_B"],
    "blind_to_strategy": True, "blind_to_model": True,
}
RELEVANCE = {
    "score": 1.0, "assessor_type": "human_adjudicator", "review_status": "ADJUDICATED",
    "reviewer_ids": ["HUMAN_A", "HUMAN_B"], "blind_to_strategy": True, "blind_to_model": True,
}


def simulated_perfect_output(task):
    claims = []
    for f in task["required_facts"]:
        claim = {
            "claim_id": f"SIM_{f['fact_id']}", "fact_id": f["fact_id"], "material": True,
            "subject": f["subject"], "predicate": f["predicate"],
            "value": f["value"], "citations": [dict(ev) for ev in f["source_evidence"]],
        }
        for field in ("unit", "date_type", "value_kind"):
            if field in f:
                claim[field] = f[field]
        claims.append(claim)
    return {
        "delivery_valid": True, "claims_complete": True, "claims": claims,
        "abstentions": [{"item_id": "U1", "text": "公告未披露最终调查结论，截至截止日无法核验。"}],
        "abstentions_complete": True, "conflict_acknowledgements": [],
        "question_relevance": RELEVANCE,
    }


def main():
    ok = True

    # 1+2: SILVER contract, simulated perfect answer -> formal Q must be withheld.
    silver = json.loads(json.dumps(contract))  # deep copy
    out = simulated_perfect_output(silver)
    r_silver = evaluate_terminal_quality(silver, out, source_pages)
    print("[SILVER] status:", r_silver["status"],
          "| Q_final:", r_silver["Q_final"],
          "| gold_coverage:", r_silver["gold_coverage"],
          "| blocking:", r_silver["blocking_reasons"])
    passed = (
        r_silver["Q_final"] is None
        and "REFERENCE_GOLD_COVERAGE_BELOW_GATE" in r_silver["blocking_reasons"]
        and not any(b.startswith("REFERENCE_EVIDENCE_INVALID") for b in r_silver["blocking_reasons"])
        and not any(b.startswith("GOLD_CONTRACT_INVALID_VALUE") for b in r_silver["blocking_reasons"])
    )
    print("[SILVER] evidence spans & contract values all validate:",
          not any((b.startswith("REFERENCE_EVIDENCE_INVALID") or b.startswith("GOLD_CONTRACT_INVALID_VALUE"))
                  for b in r_silver["blocking_reasons"]))
    print("[SILVER] formal Q correctly withheld while unconfirmed:", r_silver["Q_final"] is None)
    ok &= passed

    # 3: same contract flipped to GOLD_CONFIRMED with mock adjudicated review ->
    #    perfect answer must score Q_final=1.0, critical gate PASS.
    gold = json.loads(json.dumps(contract))
    for f in gold["required_facts"]:
        f["status"] = "GOLD_CONFIRMED"
        f["critical"] = f.pop("critical_proposed", False)
        f["review"] = dict(ADJUDICATED)
    out_gold = simulated_perfect_output(gold)
    r_gold = evaluate_terminal_quality(gold, out_gold, source_pages)
    print("[GOLD-mock] status:", r_gold["status"],
          "| Q_final:", r_gold["Q_final"],
          "| Q_raw:", r_gold["Q_raw"],
          "| gate:", r_gold["critical_gate"]["status"],
          "| tp:", r_gold["fact_metrics"]["weighted_tp"],
          "| warnings:", r_gold["quality_warnings"])
    gate_pass = (
        r_gold["Q_final"] == 1.0
        and r_gold["critical_gate"]["status"] == "PASS"
        and r_gold["fact_metrics"]["weighted_tp"] == 10.0
        and r_gold["fact_metrics"]["weighted_fp"] == 0.0
    )
    print("[GOLD-mock] perfect answer scores 1.0 with gate PASS:", gate_pass)
    ok &= gate_pass

    # 4: one critical fact corrupted (F6 编号) in the GOLD-mock -> veto to 0 with Q_raw kept.
    corrupted = json.loads(json.dumps(gold))
    out_bad = json.loads(json.dumps(out_gold))
    for c in out_bad["claims"]:
        if c["fact_id"] == "F6":
            c["value"] = "证监立案字9999999999号"
    r_bad = evaluate_terminal_quality(corrupted, out_bad, source_pages)
    print("[GOLD-mock+wrong critical F6] Q_final:", r_bad["Q_final"],
          "| Q_raw:", r_bad["Q_raw"],
          "| gate:", r_bad["critical_gate"]["status"],
          "| failed:", r_bad["critical_gate"]["failed_fact_ids"])
    veto = r_bad["Q_final"] == 0.0 and r_bad["Q_raw"] is not None and r_bad["Q_raw"] > 0.9 \
        and r_bad["critical_gate"]["status"] == "FAIL" and r_bad["critical_gate"]["failed_fact_ids"] == ["F6"]
    print("[GOLD-mock+wrong critical F6] three-state veto works on a REAL document:", veto)
    ok &= veto

    print("\nSELF-CHECK:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
