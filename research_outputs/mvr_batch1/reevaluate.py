#!/usr/bin/env python3
"""Uniform deterministic re-adaptation + final evaluation for MVR-BATCH-1.

The runner's stored claims carry fact_id/value/quote/doc-hint. The adapter in
the runner omitted slot scaffolding (subject/predicate/unit/date_type) and the
sink often echoed node ids as doc ids — both are recoverable deterministically
from stored data: slots by fact_id; true doc/page by normalized quote
containment over the contract's hash-bound pages. Model outputs, prompts and
dispatches are untouched. Applied uniformly to all 16 runs.
"""
import json
import re
import sys
from pathlib import Path

OUT = Path("/root/research_outputs/mvr_batch1")
EVAL_PATH = "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4"
EVID = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence")
F1_UP, F1_DOWN, CL_TOL = 0.02, -0.02, 0.05
PRICE = {"glm": {"in": 0.80, "out": 2.80}, "ds": {"in": 0.30 * 7.5, "out": 1.20 * 7.5}}
sys.path.insert(0, EVAL_PATH)
from terminal_quality import evaluate_terminal_quality  # noqa: E402


def norm(s):
    return re.sub(r"\s+", "", str(s or ""))


CONTRACTS = {}
for tid, p in (("MVR1", "MVR1_shuntian/TASK_CONTRACT_MVR1_v1.json"),
               ("MVR2", "MVR2_yuandao/TASK_CONTRACT_MVR2_v1.json")):
    c = json.loads((EVID / p).read_text(encoding="utf-8"))
    c["_src"] = c.pop("source_pages")
    CONTRACTS[tid] = c

SLOTS = {}
for tid, c in CONTRACTS.items():
    SLOTS[tid] = {f["fact_id"]: f for f in c["required_facts"]}


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


def rebuild_terminal(tid, stored):
    claims = []
    for c in stored["claims"]:
        slot = SLOTS[tid].get(c.get("fact_id"))
        if slot is None:
            continue
        cit = locate_quote(tid, c["citations"][0].get("quote", "")) if c.get("citations") else None
        claim = {"claim_id": c["fact_id"], "fact_id": c["fact_id"], "material": True,
                 "subject": slot["subject"], "predicate": slot["predicate"], "value": c.get("value")}
        for k in ("unit", "date_type"):
            if slot.get(k):
                claim[k] = slot[k]
        claim["citations"] = [cit] if cit else []
        claims.append(claim)
    return {"delivery_valid": stored["delivery_valid"], "claims_complete": stored["claims_complete"],
            "claims": claims, "abstentions": stored["abstentions"], "abstentions_complete": True,
            "conflict_acknowledgements": []}


def eval_arm(tid, stored):
    terminal = rebuild_terminal(tid, stored)
    contract_view = {k: v for k, v in CONTRACTS[tid].items() if k != "_src"}
    ev = evaluate_terminal_quality(contract_view, terminal, CONTRACTS[tid]["_src"])
    return {"dimensions": ev["dimensions"], "critical_gate": ev["critical_gate"],
            "fact_metrics": ev["fact_metrics"], "Q_final": ev["Q_final"], "status": ev["status"],
            "blocking": ev["blocking_reasons"][:6]}


def main():
    plan = json.loads((OUT / "plan.json").read_text())
    calib = json.loads((OUT / "calibration.json").read_text())
    pairs = [json.loads(l) for l in (OUT / "pairs.jsonl").read_text().splitlines() if l.strip()]
    rows, switch_check = [], []
    for p in pairs:
        evA, evB = eval_arm(p["task"], p["arms"]["A"]["terminal"]), eval_arm(p["task"], p["arms"]["B"]["terminal"])
        fA, fB = evA["fact_metrics"]["f1"], evB["fact_metrics"]["f1"]

        def arm_cost_lat(arm):
            ds = [d for d in arm["dispatch"] if d["tag"] in ("A", "B")]
            return (sum(d["cost"] for d in ds), sum(d["lat"] for d in ds), len(ds))

        (ca, la, na) = arm_cost_lat(p["arms"]["A"])
        (cb, lb, nb) = arm_cost_lat(p["arms"]["B"])
        # dynamic dispatch evidence: post-fault T* nodes per arm
        tA = {d["node"]: d["model"] for d in p["arms"]["A"]["dispatch"] if d["type"] == plan["tstar"] and d["tag"] == "A"}
        tB = {d["node"]: d["model"] for d in p["arms"]["B"]["dispatch"] if d["type"] == plan["tstar"] and d["tag"] == "B"}
        switch_check.append({"task": p["task"], "pair": p["pair"], "tstar_models_A": tA, "tstar_models_B": tB,
                             "allocation_changed": tA != tB})
        rows.append({"task": p["task"], "pair": p["pair"],
                     "f1_A": fA, "f1_B": fB,
                     "d_f1": round(fB - fA, 4) if (fA is not None and fB is not None) else None,
                     "null": fA is None or fB is None,
                     "gate_A": evA["critical_gate"]["status"], "gate_B": evB["critical_gate"]["status"],
                     "tp_A": evA["fact_metrics"]["weighted_tp"], "tp_B": evB["fact_metrics"]["weighted_tp"],
                     "fp_A": evA["fact_metrics"]["weighted_fp"], "fp_B": evB["fact_metrics"]["weighted_fp"],
                     "fn_A": evA["fact_metrics"]["weighted_fn"], "fn_B": evB["fact_metrics"]["weighted_fn"],
                     "ev_A": evA, "ev_B": evB,
                     "cost_A": round(ca, 5), "cost_B": round(cb, 5), "d_cost": round(cb - ca, 5),
                     "lat_A": round(la, 2), "lat_B": round(lb, 2), "d_lat": round(lb - la, 2),
                     "calls_A": na, "calls_B": nb})
    valid = [r for r in rows if not r["null"]]
    mean_d = sum(r["d_f1"] for r in valid) / len(valid) if valid else None
    per_event = {t: round(sum(r["d_f1"] for r in valid if r["task"] == t) / max(1, sum(1 for r in valid if r["task"] == t)), 4)
                 for t in ("MVR1", "MVR2")}
    mean_dc = sum(r["d_cost"] for r in valid) / len(valid) if valid else None
    mean_dl = sum(r["d_lat"] for r in valid) / len(valid) if valid else None
    base_c = sum(r["cost_A"] for r in valid) / len(valid) if valid else 0
    base_l = sum(r["lat_A"] for r in valid) / len(valid) if valid else 0
    classification, q_class, cl_class = "无有效配对", "", ""
    if mean_d is not None:
        q_class = "up" if mean_d >= F1_UP else ("down" if mean_d <= F1_DOWN else "flat")
        improve = (mean_dc < 0 or mean_dl < 0) and mean_dc <= CL_TOL * base_c and mean_dl <= CL_TOL * base_l
        worsen = mean_dc > CL_TOL * base_c or mean_dl > CL_TOL * base_l
        cl_class = "improve" if improve else ("worsen" if worsen else "flat")
        classification = {"up": {"improve": "强正向", "flat": "质量收益", "worsen": "质量—成本权衡"},
                          "flat": {"improve": "效率收益", "flat": "无明显变化", "worsen": "效率退化"},
                          "down": {"improve": "质量退化但效率改善", "flat": "质量退化", "worsen": "综合退化"}}[q_class][cl_class]
    ledger = [json.loads(l) for l in (OUT / "ledger.jsonl").read_text().splitlines() if l.strip()]
    totals = {"calls": len(ledger),
              "tokens": sum(r["in"] + r["out"] for r in ledger),
              "cny": round(sum(r["cny"] for r in ledger), 4),
              "lat_sum": round(sum(r["lat"] for r in ledger), 1)}
    report = {"tstar": plan["tstar"], "allocation": plan["allocation"],
              "calibration_matrix": calib["matrix"],
              "pairs": [{k: v for k, v in r.items() if not k.startswith("ev_")} for r in rows],
              "n_valid": len(valid), "mean_d_f1": round(mean_d, 4) if mean_d is not None else None,
              "per_event_mean_d_f1": per_event,
              "mean_d_cost_cny": round(mean_dc, 5) if mean_dc is not None else None,
              "mean_d_lat_s": round(mean_dl, 2) if mean_dl is not None else None,
              "classification": classification, "q_class": q_class, "cl_class": cl_class,
              "dynamic_gate_fail_or_unknown": any(r["gate_B"] in ("FAIL", "UNKNOWN") for r in rows),
              "allocation_actually_changed": all(s["allocation_changed"] for s in switch_check),
              "switch_check": switch_check, "ledger_totals": totals}
    (OUT / "final_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    with open(OUT / "final_evals_detail.json", "w") as f:
        json.dump([{ "task": r["task"], "pair": r["pair"], "ev_A": r["ev_A"], "ev_B": r["ev_B"]} for r in rows], f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in report.items() if k not in ("pairs", "switch_check", "calibration_matrix")}, ensure_ascii=False, indent=1))
    print("\nper-pair:")
    for r in rows:
        print(f"{r['task']} p{r['pair']}: F1 {r['f1_A']} -> {r['f1_B']} (d={r['d_f1']})  gate {r['gate_A']}/{r['gate_B']}  "
              f"tp {r['tp_A']}->{r['tp_B']} fp {r['fp_A']}->{r['fp_B']}  C¥ {r['cost_A']}->{r['cost_B']}  L {r['lat_A']}->{r['lat_B']}s")


if __name__ == "__main__":
    main()
