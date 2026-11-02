#!/usr/bin/env python3
"""MVR-2 self-check through terminal_quality_v1.2.3 (read-only, zero model calls).

Behaviors asserted:
 1. perfect answer -> dims 1.0, gate PASS, tp=27, Q_final NULL (MVR boundary);
 2. wrong final fine for 曹亚蕾 (FB4) -> FAIL exactly [FB4]; the proposed-vs-final
    difference fact FC2 still scores (its derivation runs on CONTRACT facts,
    not on the claim's own numbers);
 3. document-number swap (FE2 -> 告知书文号) -> FAIL exactly [FE2];
 4. claiming 拟==终 (difference 0, wrongly applying the Shuntian pattern) ->
    FAIL exactly [FC2];
 5. omitting the critical combined company fine (FA3) -> FAIL [FA3],
    completeness < 1. Q_final NULL and Q_raw finite in every case.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4")
from terminal_quality import evaluate_terminal_quality  # noqa: E402

BASE = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/MVR2_yuandao")
contract = json.loads((BASE / "TASK_CONTRACT_MVR2_v1.json").read_text(encoding="utf-8"))
source_pages = contract.pop("source_pages")


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
        "abstentions": [{"item_id": "U1", "text": "决定书仅结论性表述采纳范围，无法核验内部权衡。"},
                        {"item_id": "U2", "text": "已故当事人程序细节未披露，不作断言。"}],
        "abstentions_complete": True, "conflict_acknowledgements": [],
        "question_relevance": {"score": None, "assessor_type": "none",
                               "note": "MVR mode: relevance unassessed by design"},
    }


def run(name, out, task):
    r = evaluate_terminal_quality(task, out, source_pages)
    print(f"[{name}] Q_final:", r["Q_final"],
          "| dims:", r["dimensions"]["fact_correctness"], r["dimensions"]["evidence_support"],
          r["dimensions"]["necessary_completeness"],
          "| gate:", r["critical_gate"]["status"],
          "| tp/fp/fn:", r["fact_metrics"]["weighted_tp"], r["fact_metrics"]["weighted_fp"],
          r["fact_metrics"]["weighted_fn"],
          "| failed:", r["critical_gate"]["failed_fact_ids"])
    return r


def main() -> int:
    ok = True
    r1 = run("PERFECT", perfect_output(contract), contract)
    ok &= (r1["Q_final"] is None and r1["dimensions"]["fact_correctness"] == 1.0
           and r1["dimensions"]["evidence_support"] == 1.0
           and r1["dimensions"]["necessary_completeness"] == 1.0
           and r1["critical_gate"]["status"] == "PASS"
           and r1["fact_metrics"]["weighted_tp"] == 27.0
           and r1["fact_metrics"]["weighted_fp"] == 0.0 and r1["fact_metrics"]["weighted_fn"] == 0.0)

    wrong_fine = copy.deepcopy(perfect_output(contract))
    for c in wrong_fine["claims"]:
        if c["fact_id"] == "FB4":
            c["value"] = "9000000"  # 终罚金额错：宣称 900 万
    r2 = run("FB4-WRONG-FINE", wrong_fine, contract)
    ok &= r2["Q_final"] is None and r2["critical_gate"]["status"] == "FAIL" \
        and r2["critical_gate"]["failed_fact_ids"] == ["FB4"]

    swap_no = copy.deepcopy(perfect_output(contract))
    for c in swap_no["claims"]:
        if c["fact_id"] == "FE2":
            c["value"] = "处罚字【2026】14号"  # 把告知书文号安到决定书上
    r3 = run("FE2-NUMBER-SWAP", swap_no, contract)
    ok &= r3["Q_final"] is None and r3["critical_gate"]["status"] == "FAIL" \
        and r3["critical_gate"]["failed_fact_ids"] == ["FE2"]

    no_diff = copy.deepcopy(perfect_output(contract))
    for c in no_diff["claims"]:
        if c["fact_id"] == "FC2":
            c["value"] = "0"  # 错误宣称拟=终（套用舜天模式）
    r4 = run("FC2-CLAIM-NO-DIFF", no_diff, contract)
    ok &= r4["Q_final"] is None and r4["critical_gate"]["status"] == "FAIL" \
        and r4["critical_gate"]["failed_fact_ids"] == ["FC2"]

    omit = perfect_output(contract)
    omit["claims"] = [c for c in omit["claims"] if c["fact_id"] != "FA3"]
    r5 = run("FA3-OMITTED", omit, contract)
    ok &= r5["Q_final"] is None and r5["critical_gate"]["status"] == "FAIL" \
        and r5["critical_gate"]["failed_fact_ids"] == ["FA3"] \
        and r5["dimensions"]["necessary_completeness"] < 1.0

    for r in (r1, r2, r3, r4, r5):
        ok &= r["Q_final"] is None and (r["Q_raw"] is None or r["Q_raw"] == r["Q_raw"])

    print("\nMVR-2 SELF-CHECK:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
