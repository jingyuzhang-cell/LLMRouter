#!/usr/bin/env python3
"""Promote the E08 SILVER draft to GOLD after dual independent human confirmation.

One-pass consolidation tool (operator directive 2026-10-30): when the two
reviewer confirmation files (and, where needed, the adjudication file) come
back, this script either produces the frozen GOLD contract in a single pass or
refuses with a precise reason. Zero model calls; the evaluator (v1.2.3) is
imported read-only for post-promotion self-checks.

Refuses (non-zero exit) unless EVERY gate passes:
  - two distinct reviewers, both blind flags true;
  - every fact carries a verdict; CONFIRMED requires evidence_span_ok=true;
  - a fact becomes GOLD only when BOTH reviewers CONFIRM (or adjudication
    confirms a disagreement, by an adjudicator distinct from both reviewers);
  - both-REJECTED facts become EXCLUDED (documented, outside the denominator);
  - both-DOWNGRADE facts move to unknown_items (never asserted as Gold);
  - CORRECTED or mixed verdicts without adjudication -> promotion refused
    (corrections must be re-confirmed; no sick fact ever turns GOLD);
  - criticality (F4/F6/F7/F8) frozen only on agreement (or adjudication).

--selftest exercises the machinery with SYNTHETIC self-confirmations derived
from the draft itself: output goes to /tmp only, task ids are marked
SYNTHETIC_TEST_ONLY, and nothing is written into the evidence package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EVIDENCE = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/E08_zhongtie")
DRAFT = EVIDENCE / "TASK_CONTRACT_E08_SILVER_DRAFT.json"
CRITICAL_IDS = ["F4", "F6", "F7", "F8"]
VERDICTS = {"CONFIRMED", "CORRECTED", "REJECTED", "DOWNGRADE_UNKNOWN"}

for _p in (
    "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4",
    "/root/r3_own_pool/deadline_reward_v1/quality_v4",
):
    if Path(_p).is_dir():
        sys.path.insert(0, _p)
        break

GOLD_PROVENANCE = "human_adjudicated"
ADJUDICATED_REVIEW = {
    "status": "ADJUDICATED", "independent_reviewers": 2, "reviewer_ids": None,
    "blind_to_strategy": True, "blind_to_model": True,
}


def die(code: int, message: str) -> None:
    print(f"PROMOTION REFUSED ({code}): {message}")
    sys.exit(code)


def load_confirmation(path: Path, reviewer_expectation: str) -> dict:
    if not path.exists():
        die(2, f"missing confirmation file: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    records = doc if isinstance(doc, list) else [doc]
    record = records[0]
    rid = record.get("reviewer_id")
    if record.get("blind_to_model") is not True or record.get("blind_to_strategy") is not True:
        die(3, f"{path.name}: reviewer must be blind to model and strategy")
    if rid not in {"A", "B"}:
        die(3, f"{path.name}: reviewer_id must be 'A' or 'B', got {rid!r}")
    return record


def check_filled(record: dict, name: str) -> None:
    problems = []
    for entry in record["facts"]:
        fid, verdict = entry["fact_id"], entry.get("verdict")
        if verdict not in VERDICTS:
            problems.append(f"{fid}: verdict missing/invalid ({verdict!r})")
        elif verdict == "CONFIRMED" and entry.get("evidence_span_ok") is not True:
            problems.append(f"{fid}: CONFIRMED requires evidence_span_ok=true")
        if entry.get("evidence_span_ok") is None:
            problems.append(f"{fid}: evidence_span_ok not filled")
    if record.get("unknown_items", [{}])[0].get("verdict") not in {"CONFIRMED", "REJECTED"}:
        problems.append("U1: unknown-item verdict missing")
    for fid in CRITICAL_IDS:
        if not str(record.get("criticality_review", {}).get(fid, "")).strip():
            problems.append(f"{fid}: criticality_review missing")
    if record.get("overall_confidence") not in {"low", "medium", "high"}:
        problems.append("overall_confidence missing")
    if problems:
        die(4, f"{name}: " + "; ".join(problems))


def agrees_adjudication(adjudication: dict, fid: str) -> dict | None:
    return (adjudication or {}).get("decisions", {}).get(fid)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", type=Path, default=EVIDENCE / "REVIEW_CONFIRMATION_A.json")
    parser.add_argument("--b", type=Path, default=EVIDENCE / "REVIEW_CONFIRMATION_B.json")
    parser.add_argument("--adjudication", type=Path, default=EVIDENCE / "ADJUDICATION_E08.json")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if not DRAFT.exists():
        die(1, f"SILVER draft missing: {DRAFT}")
    contract = json.loads(DRAFT.read_text(encoding="utf-8"))
    source_pages = contract.pop("source_pages")
    adjudication = None

    if args.selftest:
        print("SELFTEST MODE: synthetic self-confirmations; output to /tmp only, nothing enters the evidence package.")
        out_dir = Path("/tmp/e08_selftest")
        out_dir.mkdir(exist_ok=True)
        confirm = {
            "reviewer_id": "X", "review_date": "SYNTHETIC", "blind_to_model": True, "blind_to_strategy": True,
            "facts": [{"fact_id": f"F{i}", "verdict": "CONFIRMED", "evidence_span_ok": True} for i in range(1, 11)],
            "unknown_items": [{"item_id": "U1", "verdict": "CONFIRMED"}],
            "criticality_review": {fid: "agree" for fid in CRITICAL_IDS},
            "overall_confidence": "high",
        }
        record_a = {**confirm, "reviewer_id": "A"}
        record_b = {**confirm, "reviewer_id": "B"}
        target = out_dir / "TASK_CONTRACT_E08_GOLD_SELFTEST.json"
        task_id_override = "CM_E08_001_SYNTHETIC_TEST_ONLY"
    else:
        record_a = load_confirmation(args.a, "A")
        record_b = load_confirmation(args.b, "B")
        check_filled(record_a, args.a.name)
        check_filled(record_b, args.b.name)
        if record_a["reviewer_id"] == record_b["reviewer_id"]:
            die(5, "the two confirmations must come from two distinct reviewers")
        adjudication = None
        if args.adjudication.exists():
            adjudication = json.loads(args.adjudication.read_text(encoding="utf-8"))
            adj_id = adjudication.get("adjudicator_id")
            if adj_id in {record_a["reviewer_id"], record_b["reviewer_id"]} or not adj_id:
                die(6, "adjudicator must be a distinct third person")
            if adjudication.get("blind_to_model") is not True or adjudication.get("blind_to_strategy") is not True:
                die(6, "adjudicator must be blind to model and strategy")
        target = EVIDENCE / "TASK_CONTRACT_E08_GOLD_v1.json"
        task_id_override = None

    verdicts_a = {e["fact_id"]: e for e in record_a["facts"]}
    verdicts_b = {e["fact_id"]: e for e in record_b["facts"]}

    refusals, corrections, review_notes = [], [], []
    unknown_items = list(contract.get("unknown_items", []))
    for fact in contract["required_facts"]:
        fid = fact["fact_id"]
        va, vb = verdicts_a.get(fid, {}).get("verdict"), verdicts_b.get(fid, {}).get("verdict")
        adj = agrees_adjudication(adjudication or {}, fid)
        adj_verdict = adj.get("verdict") if adj else None
        pair = {va, vb}
        if va == vb == "CONFIRMED" or adj_verdict == "CONFIRMED":
            fact["status"] = "GOLD_CONFIRMED"
            fact["gold_provenance"] = GOLD_PROVENANCE
            fact["review"] = {
                **ADJUDICATED_REVIEW,
                "reviewer_ids": [record_a["reviewer_id"], record_b["reviewer_id"]],
                "dual_confirmed": va == vb == "CONFIRMED",
                "adjudicated": adj_verdict == "CONFIRMED",
            }
            if fid in CRITICAL_IDS:
                fact["critical"] = True
            review_notes.append(f"{fid}: GOLD (dual={va == vb == 'CONFIRMED'}, adjudicated={adj_verdict == 'CONFIRMED'})")
        elif va == vb == "REJECTED" or adj_verdict == "REJECTED":
            fact["status"] = "EXCLUDED"
            fact["exclusion_reason"] = (adj or verdicts_a.get(fid, {})).get("note") or "dual rejection"
            fact.pop("critical", None)
            review_notes.append(f"{fid}: EXCLUDED (dual rejection)")
        elif va == vb == "DOWNGRADE_UNKNOWN" or adj_verdict == "DOWNGRADE_UNKNOWN":
            unknown_items.append({
                "item_id": f"U_{fid}", "description": f"downgraded by dual review: {fact['predicate']}",
                "expected_status": "UNKNOWN",
            })
            fact["status"] = "NOT_APPLICABLE"
            fact.pop("critical", None)
            review_notes.append(f"{fid}: downgraded to UNKNOWN")
        else:
            if "CORRECTED" in pair:
                corrections.append(fid)
            refusals.append(f"{fid}: {va}/{vb}" + (f" adj={adj_verdict}" if adj else ""))

    if refusals:
        die(7, "facts without dual confirmation or adjudication: " + "; ".join(refusals)
            + (" — CORRECTED values must be fixed in the draft and re-confirmed" if corrections else ""))

    # Criticality must be agreed (or adjudicated) for every fact kept critical.
    for fid in CRITICAL_IDS:
        fact = next(f for f in contract["required_facts"] if f["fact_id"] == fid)
        if fact.get("status") != "GOLD_CONFIRMED":
            continue
        opinions = [
            str(record_a.get("criticality_review", {}).get(fid, "")).strip().lower(),
            str(record_b.get("criticality_review", {}).get(fid, "")).strip().lower(),
        ]
        adj_crit = (adjudication or {}).get("criticality", {}).get(fid)
        if not (opinions[0] == opinions[1] == "agree" or adj_crit == "agree"):
            die(8, f"criticality of {fid} not agreed ({opinions}, adj={adj_crit}) — resolve before promotion")

    contract["status"] = "GOLD_FROZEN"
    if task_id_override:
        contract["task_id"] = task_id_override
    contract["freeze"] = {
        "version": "E08_GOLD_v1",
        "promoted_from_sha256": hashlib.sha256(DRAFT.read_bytes()).hexdigest(),
        "reviewers": [record_a["reviewer_id"], record_b["reviewer_id"]],
        "adjudicator": None if args.selftest else (adjudication or {}).get("adjudicator_id"),
        "critical_frozen": [fid for fid in CRITICAL_IDS
                            if any(f["fact_id"] == fid and f.get("critical") for f in contract["required_facts"])],
        "model_calls": 0,
    }
    contract["source_pages"] = source_pages

    # Post-promotion self-checks with the frozen evaluator (v1.2.3, read-only):
    # a perfect answer must score 1.0 with gate PASS; corrupting the critical
    # notice number must veto Q_final to 0 while keeping Q_raw.
    from terminal_quality import evaluate_terminal_quality
    import copy
    gold_eval = copy.deepcopy(contract)
    gold_eval.pop("source_pages")
    claims = []
    relevance = {
        "score": 1.0, "assessor_type": "human_adjudicator", "review_status": "ADJUDICATED",
        "reviewer_ids": ["R1", "R2"], "blind_to_strategy": True, "blind_to_model": True,
    }
    for f in gold_eval["required_facts"]:
        if f["status"] != "GOLD_CONFIRMED":
            continue
        claim = {"claim_id": f"SIM_{f['fact_id']}", "fact_id": f["fact_id"], "material": True,
                 "subject": f["subject"], "predicate": f["predicate"], "value": f["value"],
                 "citations": [dict(ev) for ev in f["source_evidence"]]}
        for field in ("unit", "date_type", "value_kind"):
            if field in f:
                claim[field] = f[field]
        claims.append(claim)
    perfect = {"delivery_valid": True, "claims_complete": True, "claims": claims,
               "abstentions": [{"item_id": i["item_id"], "text": "证据未披露，无法核验。"} for i in unknown_items],
               "abstentions_complete": True, "conflict_acknowledgements": [], "question_relevance": relevance}
    r1 = evaluate_terminal_quality(gold_eval, perfect, source_pages)
    if r1["Q_final"] != 1.0 or r1["critical_gate"]["status"] != "PASS":
        die(9, f"post-promotion self-check failed (perfect answer: Q={r1['Q_final']}, gate={r1['critical_gate']['status']})")
    bad = json.loads(json.dumps(perfect))
    for c in bad["claims"]:
        if c["fact_id"] == "F6":
            c["value"] = "证监立案字9999999999号"
    r2 = evaluate_terminal_quality(gold_eval, bad, source_pages)
    if r2["Q_final"] != 0.0 or r2["critical_gate"]["status"] != "FAIL":
        die(9, "post-promotion veto self-check failed")

    target.write_text(json.dumps(contract, ensure_ascii=False, indent=1), encoding="utf-8")
    print("PROMOTED ->", target)
    print("  gold facts:", sum(1 for f in contract["required_facts"] if f["status"] == "GOLD_CONFIRMED"),
          "| excluded:", sum(1 for f in contract["required_facts"] if f["status"] == "EXCLUDED"),
          "| unknown additions:", len(unknown_items) - len(contract.get("unknown_items", [])))
    for note in review_notes:
        print("   ", note)
    print("  self-checks: perfect=1.0/PASS, critical-corruption veto=0/FAIL  OK")
    print("  sha256:", hashlib.sha256(target.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
