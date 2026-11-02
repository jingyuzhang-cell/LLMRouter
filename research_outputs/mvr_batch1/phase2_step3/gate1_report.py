#!/usr/bin/env python3
"""Gate step-3 report: error classification, stability, dependency, observability."""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path("/root/research_outputs/mvr_batch1/phase2_step3")
EVID = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2")
sys.path.insert(0, "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4")
from terminal_quality import _value_equal, _derived_value_ok, evaluate_terminal_quality  # noqa: E402

DAG_DOCNODES = {"E04": {"D1": "E1", "D2": "E2", "D3": "E3"}, "E06": {"D1": "E1", "D2": "E2"}}


def norm(s):
    return re.sub(r"\s+", "", str(s or ""))


def nums(s):
    return re.sub(r"[^0-9.+\-]", "", str(s or ""))


CONTRACTS = {}
for tid in ("E04", "E06"):
    c = json.loads((EVID / f"TASK_CONTRACT_PHASE2_{tid}_v1.json").read_text(encoding="utf-8"))
    c["_src"] = c.pop("source_pages")
    CONTRACTS[tid] = c


def locate_quote(tid, quote):
    q = norm(quote)
    if len(q) < 6:
        return None
    for doc_id, d in CONTRACTS[tid]["_src"].items():
        for page, rec in d["pages"].items():
            if q[: min(len(q), 24)] in norm(rec["text"]):
                return {"doc_id": doc_id, "page": int(page), "quote": quote,
                        "raw_sha256": d["raw_sha256"], "page_sha256": rec["page_sha256"]}
    return None


def parse_sink(run):
    m = re.search(r"\{.*\}", run["sink_raw"], re.S)
    return json.loads(m.group(0)) if m else None


def classify(tid, fact, value):
    """correct / format / expression / value (+None if unanswered)."""
    if value is None or str(value).strip() in ("", "null"):
        return "missing"
    if fact.get("derivation"):
        if _derived_value_ok({"value": value}, fact, {f["fact_id"]: f for f in CONTRACTS[tid]["required_facts"]}):
            return "correct"
    elif _value_equal({"value": value}, fact):
        return "correct"
    gold, ans = fact.get("value"), str(value)
    if fact.get("value_kind") in ("amount", "number", "percent") and nums(gold) and nums(ans):
        if nums(gold) == nums(ans):
            return "format"
        # 符号相反且绝对值相等记 value（符号即口径），千分位/单位后缀已归一
        if nums(gold).lstrip("-") == nums(ans).lstrip("-") and ("-" in nums(gold)) != ("-" in nums(ans)):
            return "value"
    if norm(gold) and (norm(gold) in norm(ans) or norm(ans) in norm(gold)) and len(norm(ans)) > len(norm(gold)):
        return "expression"
    return "value"


def main():
    sys.path.insert(0, "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4")
    rows = []
    for tid in ("E04", "E06"):
        facts = {f["fact_id"]: f for f in CONTRACTS[tid]["required_facts"]}
        for r in (1, 2, 3):
            run = json.loads((OUT / f"run_{tid}_r{r}.json").read_text())
            sink = parse_sink(run)
            claims = []
            for a in (sink or {}).get("answers", []) or []:
                if not isinstance(a, dict) or not a.get("fact_id"):
                    continue
                slot = facts.get(a["fact_id"])
                if not slot:
                    continue
                cit = locate_quote(tid, str(a.get("quote", "")))
                claim = {"claim_id": a["fact_id"], "fact_id": a["fact_id"], "material": True,
                         "subject": slot["subject"], "predicate": slot["predicate"], "value": a.get("value")}
                for k in ("unit", "date_type"):
                    if slot.get(k):
                        claim[k] = slot[k]
                claim["citations"] = [cit] if cit else []
                claims.append(claim)
            terminal = {"delivery_valid": True, "claims_complete": (sink or {}).get("complete") is True,
                        "claims": claims, "abstentions": (sink or {}).get("abstentions", []),
                        "abstentions_complete": True, "conflict_acknowledgements": []}
            view = {k: v for k, v in CONTRACTS[tid].items() if k != "_src"}
            ev = evaluate_terminal_quality(view, terminal, CONTRACTS[tid]["_src"])
            per_fact = {}
            got = {c["fact_id"]: c.get("value") for c in claims}
            for fid, f in facts.items():
                per_fact[fid] = {"class": classify(tid, f, got.get(fid)), "value": got.get(fid)}
            jout = next((t["output"][:300] for t in run["trace"] if t["node"] == "J1"), "")
            rows.append({"task": tid, "repeat": r, "f1": ev["fact_metrics"]["f1"],
                         "gate": ev["critical_gate"]["status"], "evidence_support": ev["dimensions"]["evidence_support"],
                         "per_fact": per_fact, "got": got, "j1_head": jout,
                         "sink_complete": (sink or {}).get("complete")})
    # aggregate stability
    stability = {}
    for tid in ("E04", "E06"):
        facts = {f["fact_id"]: f for f in CONTRACTS[tid]["required_facts"]}
        for fid, f in facts.items():
            classes = [next(row["per_fact"][fid]["class"] for row in rows if row["task"] == tid and row["repeat"] == r)
                       for r in (1, 2, 3)]
            values = [next(row["got"].get(fid) for row in rows if row["task"] == tid and row["repeat"] == r)
                      for r in (1, 2, 3)]
            errs = sum(1 for c in classes if c not in ("correct",))
            stability[f"{tid}:{fid}"] = {
                "classes": classes, "err_count": errs,
                "stable_value_error": sum(1 for c in classes if c == "value") >= 2,
                "gold": f.get("value"), "answers": [str(v)[:40] for v in values],
                "kind": f.get("value_kind"), "evidence_docs": sorted({e.get("doc_id") for e in f.get("source_evidence", [])}),
            }
    report = {"runs": [{k: v for k, v in r.items() if k not in ("per_fact", "got")} for r in rows],
              "stability": stability,
              "value_errors_stable": [k for k, v in stability.items() if v["stable_value_error"]],
              "value_errors_any": [k for k, v in stability.items() if "value" in v["classes"]],
              "format_errors": [k for k, v in stability.items() if "format" in v["classes"]],
              "expression_errors": [k for k, v in stability.items() if "expression" in v["classes"]],
              "missing": [k for k, v in stability.items() if "missing" in v["classes"]]}
    (OUT / "gate1_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report["runs"], ensure_ascii=False, indent=1))
    print("\nSTABLE VALUE ERRORS (>=2/3):", report["value_errors_stable"])
    print("ANY VALUE ERRORS:", report["value_errors_any"])
    print("FORMAT:", report["format_errors"])
    print("EXPRESSION:", report["expression_errors"])
    print("MISSING:", report["missing"])
    for k in report["value_errors_any"] + report["value_errors_stable"]:
        print(" ", k, json.dumps(stability[k], ensure_ascii=False)[:220])


if __name__ == "__main__":
    main()
