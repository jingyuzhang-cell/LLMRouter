#!/usr/bin/env python3
"""MVR-1 self-check through terminal_quality_v1.2.3 (read-only, zero model calls).

MVR mode assertions:
 - a perfect answer yields fact/evidence/completeness dimensions = 1.0,
   critical gate PASS, tp=16/fp=0/fn=0 — while Q_final stays NULL
   (question relevance deliberately unassessed: the honest Route-B boundary);
 - corrupting the critical derived profit (F10) fails the critical gate;
 - swapping the decision notice number (F11 -> 〔2023〕37号) fails the gate;
 - omitting the critical company fine (F1) fails the gate by omission;
 - in every case Q_final is NULL and Q_raw stays a finite diagnostic.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4")
from terminal_quality import evaluate_terminal_quality  # noqa: E402

BASE = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/MVR1_shuntian")
contract = json.loads((BASE / "TASK_CONTRACT_MVR1_v1.json").read_text(encoding="utf-8"))
source_pages = contract.pop("source_pages")

UNSPECIFIED_RELEVANCE = {
    # MVR mode: no valid relevance assessment exists (no human, no calibrated
    # judge) — the evaluator must withhold Q_final and we report dimensions.
    "score": None, "assessor_type": "none", "note": "MVR mode: relevance unassessed by design",
}


def perfect_output(task):
    claims = []
    for f in task["required_facts"]:
        claim = {
            "claim_id": f"SIM_{f['fact_id']}", "fact_id": f["fact_id"], "material": True,
            "subject": f["subject"], "predicate": f["predicate"], "value": f["value"],
            "citations": [dict(ev) for ev in f["source_evidence"]],
        }
        for field in ("unit", "date_type", "value_kind"):
            if field in f:
                claim[field] = f[field]
        claims.append(claim)
    return {
        "delivery_valid": True, "claims_complete": True, "claims": claims,
        "abstentions": [{"item_id": "U1", "text": "决定书未载明当事人陈述申辩意见的具体内容，无法核验。"},
                        {"item_id": "U2", "text": "逐年度明细超出本合同要求，不作断言。"}],
        "abstentions_complete": True, "conflict_acknowledgements": [],
        "question_relevance": UNSPECIFIED_RELEVANCE,
    }


def run(name, out, task):
    result = evaluate_terminal_quality(task, out, source_pages)
    print(f"[{name}] Q_final:", result["Q_final"],
          "| dims(fact/evid/comp):", result["dimensions"]["fact_correctness"],
          result["dimensions"]["evidence_support"], result["dimensions"]["necessary_completeness"],
          "| gate:", result["critical_gate"]["status"],
          "| tp/fp/fn:", result["fact_metrics"]["weighted_tp"],
          result["fact_metrics"]["weighted_fp"], result["fact_metrics"]["weighted_fn"],
          "| failed:", result["critical_gate"]["failed_fact_ids"])
    return result


def main() -> int:
    ok = True

    r = run("PERFECT", perfect_output(contract), contract)
    ok &= (
        r["Q_final"] is None
        and r["dimensions"]["fact_correctness"] == 1.0
        and r["dimensions"]["evidence_support"] == 1.0
        and r["dimensions"]["necessary_completeness"] == 1.0
        and r["critical_gate"]["status"] == "PASS"
        and r["fact_metrics"]["weighted_tp"] == 16.0
        and r["fact_metrics"]["weighted_fp"] == 0.0
        and r["fact_metrics"]["weighted_fn"] == 0.0
    )

    corrupt = copy.deepcopy(perfect_output(contract))
    for c in corrupt["claims"]:
        if c["fact_id"] == "F10":
            c["value"] = "900000000"  # 虚增利润总额错约 3400 万
    r2 = run("F10-WRONG", corrupt, contract)
    ok &= r2["Q_final"] is None and r2["critical_gate"]["status"] == "FAIL" \
        and r2["critical_gate"]["failed_fact_ids"] == ["F10"] and r2["Q_raw"] is not None

    swap = copy.deepcopy(perfect_output(contract))
    for c in swap["claims"]:
        if c["fact_id"] == "F11":
            c["value"] = "〔2023〕37号"  # 文号混淆：把告知书文号安到决定书上
    r3 = run("F11-NUMBER-SWAP", swap, contract)
    ok &= r3["Q_final"] is None and r3["critical_gate"]["status"] == "FAIL" \
        and r3["critical_gate"]["failed_fact_ids"] == ["F11"]

    omit = perfect_output(contract)
    omit["claims"] = [c for c in omit["claims"] if c["fact_id"] != "F1"]
    r4 = run("F1-OMITTED", omit, contract)
    ok &= r4["Q_final"] is None and r4["critical_gate"]["status"] == "FAIL" \
        and r4["critical_gate"]["failed_fact_ids"] == ["F1"] \
        and r4["dimensions"]["necessary_completeness"] < 1.0

    print("\nMVR-1 SELF-CHECK:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
